"""InControl 2 client exceptions."""


class IC2Error(Exception):
    """Base error for the InControl 2 client."""


class IC2ConfigError(IC2Error):
    """Invalid or missing InControl 2 configuration."""


class IC2AuthError(IC2Error):
    """OAuth2 authentication or token grant failed."""


class IC2ConnectionError(IC2Error):
    """Network or TLS failure talking to api.ic.peplink.com."""


class IC2RateLimitError(IC2Error):
    """InControl 2 returned HTTP 429 (rate limit exceeded, 20 req/s/org)."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class IC2APIError(IC2Error):
    """InControl 2 returned a non-success ``resp_code`` envelope."""

    def __init__(self, message: str, *, resp_code: str | None = None) -> None:
        super().__init__(message)
        self.resp_code = resp_code
