"""HTTP client for the InControl 2 cloud REST API (api.ic.peplink.com).

Differs from ``peplink_core.client.PeplinkDeviceClient`` in three ways that matter:

* **OAuth2** — token is granted at ``POST /api/oauth2/token`` with a
  ``application/x-www-form-urlencoded`` body (NOT JSON), and sent on every call as
  an ``Authorization: Bearer`` header.
* **Response envelope** — IC2 wraps payloads as
  ``{resp_code, caller_ref, server_ref, message, data}``; we unwrap ``data``.
* **Rate limiting** — IC2 enforces ~20 requests/second/organization and returns
  HTTP 429; we back off and retry, honoring ``Retry-After`` when present.
"""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx
from peplink_core.config import IC2ClientCredentials

from peplink_ic2.exceptions import (
    IC2APIError,
    IC2AuthError,
    IC2ConnectionError,
    IC2RateLimitError,
)

DEFAULT_BASE_URL = "https://api.ic.peplink.com"
TOKEN_PATH = "/api/oauth2/token"
TOKEN_REFRESH_BUFFER_SEC = 600
DEFAULT_EXPIRES_IN = 172799
MAX_ATTEMPTS = 4
RETRY_BASE_DELAY_SEC = 0.25

# resp_code values (case-insensitive) we accept as success.
_SUCCESS_CODES = {"success", "ok", "200", "0"}


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, (IC2ConnectionError, IC2RateLimitError))


class IC2Client:
    """Authenticated client for one InControl 2 OAuth2 credential set."""

    def __init__(
        self,
        auth: IC2ClientCredentials,
        *,
        base_url: str = DEFAULT_BASE_URL,
        verify_tls: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.verify_tls = verify_tls
        self.timeout = timeout
        self._access_token: str | None = None
        self._refresh_token: str | None = auth.refresh_token
        self._token_expires_at: float = 0.0
        self._lock = threading.Lock()

    # -- transport ---------------------------------------------------------

    def _client(self) -> httpx.Client:
        return httpx.Client(
            verify=self.verify_tls,
            timeout=self.timeout,
            headers={"Accept": "application/json"},
        )

    # -- auth --------------------------------------------------------------

    def ensure_authenticated(self) -> None:
        with self._lock:
            if self._access_token and time.monotonic() < self._token_expires_at:
                return
            self._grant_token()

    def _grant_token(self) -> None:
        # Prefer a refresh-token exchange; fall back to a fresh client_credentials grant.
        if self._refresh_token:
            try:
                self._post_token(
                    {
                        "grant_type": "refresh_token",
                        "client_id": self.auth.client_id,
                        "client_secret": self.auth.client_secret,
                        "refresh_token": self._refresh_token,
                    }
                )
                return
            except IC2AuthError:
                self._refresh_token = None  # refresh expired/invalid; fall through

        self._post_token(
            {
                "grant_type": "client_credentials",
                "client_id": self.auth.client_id,
                "client_secret": self.auth.client_secret,
            }
        )

    def _post_token(self, form: dict[str, str]) -> None:
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                time.sleep(RETRY_BASE_DELAY_SEC * attempt)
            try:
                with self._client() as client:
                    resp = client.post(
                        f"{self.base_url}{TOKEN_PATH}",
                        data=form,
                        headers={"Content-Type": "application/x-www-form-urlencoded"},
                    )
            except httpx.HTTPError as exc:
                last_error = IC2ConnectionError(f"token request failed: {exc}")
                continue

            if resp.status_code == 429:
                last_error = IC2RateLimitError("token request rate-limited")
                continue
            if resp.status_code in (400, 401, 403):
                raise IC2AuthError(f"token grant rejected (HTTP {resp.status_code})")
            if resp.status_code >= 500:
                last_error = IC2ConnectionError(f"token request HTTP {resp.status_code}")
                continue

            try:
                body = resp.json()
            except ValueError as exc:
                raise IC2AuthError("token response was not JSON") from exc

            token = body.get("access_token") if isinstance(body, dict) else None
            if not token:
                raise IC2AuthError("token grant succeeded but access_token missing")

            self._access_token = str(token)
            refresh = body.get("refresh_token")
            if refresh:
                self._refresh_token = str(refresh)
            expires_in = int(body.get("expires_in", DEFAULT_EXPIRES_IN))
            self._token_expires_at = time.monotonic() + max(
                60, expires_in - TOKEN_REFRESH_BUFFER_SEC
            )
            return

        raise last_error or IC2AuthError("token grant failed after retries")

    def _clear_auth(self) -> None:
        self._access_token = None
        self._token_expires_at = 0.0

    # -- requests ----------------------------------------------------------

    def _build_url(self, path: str, query: dict[str, Any] | None) -> str:
        url = f"{self.base_url}{path}"
        if not query:
            return url
        parsed = urlparse(url)
        return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    def _raw_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        self.ensure_authenticated()
        url = self._build_url(path, query)
        headers = {"Authorization": f"Bearer {self._access_token}"}

        with self._client() as client:
            try:
                resp = client.request(method, url, json=json_body, headers=headers)
            except httpx.HTTPError as exc:
                raise IC2ConnectionError(f"{method} {path} failed: {exc}") from exc

        if resp.status_code == 429:
            retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
            raise IC2RateLimitError(f"{method} {path} rate-limited", retry_after=retry_after)
        if resp.status_code == 401:
            self._clear_auth()
            raise IC2AuthError("HTTP 401 — token rejected or expired")
        if resp.status_code >= 500:
            raise IC2ConnectionError(f"{method} {path} HTTP {resp.status_code}")

        try:
            body = resp.json()
        except ValueError as exc:
            raise IC2ConnectionError(f"{method} {path} returned non-JSON") from exc

        return _unwrap_envelope(body, where=f"{method} {path}")

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> Any:
        """Call IC2 and return the unwrapped ``data`` payload."""
        last_error: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                delay = RETRY_BASE_DELAY_SEC * attempt
                if isinstance(last_error, IC2RateLimitError) and last_error.retry_after:
                    delay = max(delay, last_error.retry_after)
                time.sleep(delay)
            try:
                return self._raw_request(method, path, query=query, json_body=json_body)
            except IC2AuthError:
                self._clear_auth()
                if attempt >= MAX_ATTEMPTS - 1:
                    raise
                self.ensure_authenticated()
            except (IC2ConnectionError, IC2RateLimitError) as exc:
                last_error = exc
                if not _is_transient(exc) or attempt >= MAX_ATTEMPTS - 1:
                    raise
        raise last_error or IC2ConnectionError(f"{method} {path} failed after retries")

    def ping(self) -> Any:
        """Lightweight connectivity/auth check — lists accessible organizations."""
        return self.request("GET", "/rest/o")


def _parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _unwrap_envelope(body: Any, *, where: str) -> Any:
    """Validate the IC2 ``{resp_code, message, data}`` envelope and return ``data``."""
    if not isinstance(body, dict):
        raise IC2APIError(f"{where} returned unexpected payload (not an object)")

    resp_code = body.get("resp_code")
    code_str = str(resp_code).strip().lower() if resp_code is not None else ""
    ok = code_str in _SUCCESS_CODES or (not code_str and "data" in body)
    if not ok:
        message = body.get("message") or f"{where} failed"
        raise IC2APIError(str(message), resp_code=str(resp_code) if resp_code is not None else None)

    return body.get("data")
