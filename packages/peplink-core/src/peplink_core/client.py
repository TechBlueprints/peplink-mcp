"""HTTP client for Peplink device REST API."""

from __future__ import annotations

import threading
import time
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

import httpx

from peplink_core.config import AuthTier, ClientCredentialsAuth, DeviceAuth, UserpassAuth
from peplink_core.exceptions import (
    PeplinkAPIError,
    PeplinkAuthError,
    PeplinkConnectionError,
)

DEFAULT_SCOPE: dict[AuthTier, str] = {
    "read_only": "api.read-only",
    "config_read": "api",
    "admin": "api",
}

TOKEN_REFRESH_BUFFER_SEC = 600
MAX_ATTEMPTS = 4
RETRY_BASE_DELAY_SEC = 0.25


def _is_transient_error(exc: BaseException) -> bool:
    if isinstance(exc, PeplinkConnectionError):
        return True
    if isinstance(exc, PeplinkAPIError):
        return "Internal Error" in str(exc)
    return False


def _retry_delay(attempt: int) -> None:
    if attempt:
        time.sleep(RETRY_BASE_DELAY_SEC * attempt)


class PeplinkDeviceClient:
    """Authenticated client for one device credential tier."""

    def __init__(
        self,
        base_url: str,
        auth: DeviceAuth,
        tier: AuthTier,
        *,
        verify_tls: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth = auth
        self.tier = tier
        self.verify_tls = verify_tls
        self.timeout = timeout
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0
        self._cookie_name: str | None = None
        self._cookie_value: str | None = None
        self._lock = threading.Lock()

    def _client(self) -> httpx.Client:
        return httpx.Client(
            verify=self.verify_tls,
            timeout=self.timeout,
            headers={"Accept": "application/json"},
        )

    def ensure_authenticated(self) -> None:
        with self._lock:
            if isinstance(self.auth, ClientCredentialsAuth):
                if self._access_token and time.monotonic() < self._token_expires_at:
                    return
                self._grant_token()
            else:
                if self._cookie_value:
                    return
                self._login()

    def _grant_token(self) -> None:
        assert isinstance(self.auth, ClientCredentialsAuth)
        payload = {
            "clientId": self.auth.client_id,
            "clientSecret": self.auth.client_secret,
        }
        last_error: PeplinkAPIError | None = None
        data: dict[str, Any] | None = None
        for attempt in range(MAX_ATTEMPTS):
            _retry_delay(attempt)
            try:
                data = self._raw_request(
                    "POST", "/api/auth.token.grant", json_body=payload, auth=False
                )
                last_error = None
                break
            except PeplinkAPIError as exc:
                last_error = exc
                if not _is_transient_error(exc) or attempt >= MAX_ATTEMPTS - 1:
                    raise
        if last_error is not None or data is None:
            raise last_error or PeplinkAuthError("token grant failed")
        response = data.get("response") if isinstance(data.get("response"), dict) else data
        token = response.get("accessToken") if isinstance(response, dict) else None
        if not token:
            raise PeplinkAuthError("token grant succeeded but accessToken missing")

        expires_raw = response.get("expiresIn", 172800) if isinstance(response, dict) else 172800
        expires_in = int(expires_raw)
        self._access_token = str(token)
        self._token_expires_at = time.monotonic() + max(60, expires_in - TOKEN_REFRESH_BUFFER_SEC)

    def _login(self) -> None:
        assert isinstance(self.auth, UserpassAuth)
        payload = {
            "username": self.auth.username,
            "password": self.auth.password,
            "challenge": "challenge",
        }
        with self._client() as client:
            try:
                resp = client.post(f"{self.base_url}/api/login", json=payload)
            except httpx.HTTPError as exc:
                raise PeplinkConnectionError(f"login failed: {exc}") from exc

        if resp.status_code == 401:
            raise PeplinkAuthError("invalid username or password")

        try:
            body = resp.json()
        except ValueError as exc:
            raise PeplinkConnectionError("login returned non-JSON") from exc

        if body.get("stat") != "ok":
            raise PeplinkAuthError(body.get("message") or "login failed")

        cookie_name, cookie_value = _extract_session_cookie(resp)
        if not cookie_value:
            raise PeplinkAuthError("login succeeded but no bauth/pauth cookie returned")
        self._cookie_name = cookie_name
        self._cookie_value = cookie_value

    def _auth_query(self) -> dict[str, str]:
        if isinstance(self.auth, ClientCredentialsAuth):
            if not self._access_token:
                raise PeplinkAuthError("not authenticated")
            return {"accessToken": self._access_token}
        return {}

    def _auth_headers(self) -> dict[str, str]:
        if isinstance(self.auth, UserpassAuth):
            if not self._cookie_name or not self._cookie_value:
                raise PeplinkAuthError("not authenticated")
            return {"Cookie": f"{self._cookie_name}={self._cookie_value}"}
        return {}

    def _build_url(self, path: str, query: dict[str, Any] | None) -> str:
        url = f"{self.base_url}{path}"
        merged: dict[str, Any] = {}
        if query:
            merged.update(query)
        merged.update(self._auth_query())
        if not merged:
            return url
        parsed = urlparse(url)
        return urlunparse(parsed._replace(query=urlencode(merged)))

    def _raw_request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        auth: bool = True,
    ) -> dict[str, Any]:
        if auth:
            self.ensure_authenticated()

        url = self._build_url(path, query) if auth else f"{self.base_url}{path}"
        headers = self._auth_headers() if auth else {"Content-Type": "application/json"}

        with self._client() as client:
            try:
                resp = client.request(method, url, json=json_body, headers=headers)
            except httpx.HTTPError as exc:
                raise PeplinkConnectionError(f"{method} {path} failed: {exc}") from exc

        if resp.status_code >= 500:
            raise PeplinkConnectionError(f"{method} {path} HTTP {resp.status_code}")

        if resp.status_code == 401 and auth:
            self._clear_auth()
            raise PeplinkAuthError("HTTP 401 — credentials rejected or expired")

        try:
            body = resp.json()
        except ValueError as exc:
            raise PeplinkConnectionError(f"{method} {path} returned non-JSON") from exc

        if not isinstance(body, dict):
            raise PeplinkAPIError(f"{method} {path} returned unexpected payload")

        if body.get("stat") == "fail":
            code = body.get("code")
            parsed_code = int(code) if code is not None else None
            if parsed_code == 401 and auth:
                self._clear_auth()
                raise PeplinkAuthError(body.get("message") or "API auth failure")
            raise PeplinkAPIError(
                body.get("message") or "API call failed",
                code=parsed_code,
            )

        return body

    def _clear_auth(self) -> None:
        self._access_token = None
        self._token_expires_at = 0.0
        self._cookie_name = None
        self._cookie_value = None

    def request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call API and return the `response` object (or full body if absent)."""
        data: dict[str, Any] | None = None
        for attempt in range(MAX_ATTEMPTS):
            _retry_delay(attempt)
            try:
                data = self._raw_request(method, path, query=query, json_body=json_body)
                break
            except PeplinkAuthError:
                self._clear_auth()
                if attempt >= MAX_ATTEMPTS - 1:
                    raise
                self.ensure_authenticated()
            except (PeplinkConnectionError, PeplinkAPIError) as exc:
                if _is_transient_error(exc) and attempt < MAX_ATTEMPTS - 1:
                    continue
                raise
        else:
            raise PeplinkConnectionError(f"{method} {path} failed after retries")

        assert data is not None
        response = data.get("response")
        return response if isinstance(response, dict) else data

    def request_unauthenticated(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call API without attaching session/token (e.g. POST /api/login)."""
        data = self._raw_request(method, path, query=query, json_body=json_body, auth=False)
        response = data.get("response")
        return response if isinstance(response, dict) else data

    def ping(self) -> dict[str, Any]:
        """Lightweight connectivity check using WAN status (lite)."""
        return self.request("GET", "/api/status.wan.connection", query={"lite": "yes"})


def _extract_session_cookie(resp: httpx.Response) -> tuple[str | None, str | None]:
    for header in resp.headers.get_list("set-cookie"):
        for part in header.split(";"):
            part = part.strip()
            if part.startswith("bauth="):
                return "bauth", part[6:]
            if part.startswith("pauth="):
                return "pauth", part[6:]
    return None, None
