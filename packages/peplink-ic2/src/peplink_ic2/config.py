"""InControl 2 config models.

These live in ``peplink_core.config`` (so the fleet ``FleetConfig`` can reference them
without a dependency on this package) and are re-exported here for ergonomic imports
from IC2 code: ``from peplink_ic2.config import IC2Config``.
"""

from peplink_core.config import (
    DeviceIC2Mapping,
    IC2ClientCredentials,
    IC2Config,
)

__all__ = ["DeviceIC2Mapping", "IC2ClientCredentials", "IC2Config"]
