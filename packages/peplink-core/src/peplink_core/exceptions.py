"""Peplink core exceptions."""


class PeplinkError(Exception):
    """Base error."""


class PeplinkConfigError(PeplinkError):
    """Invalid or missing configuration."""


class PeplinkAuthError(PeplinkError):
    """Authentication failed."""


class PeplinkConnectionError(PeplinkError):
    """Network or TLS failure."""


class PeplinkAPIError(PeplinkError):
    """Device returned stat=fail or unexpected response."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
