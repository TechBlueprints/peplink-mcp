"""Minimal SNMPv2c client (Pepwave AP status reads)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from peplink_core.exceptions import PeplinkConfigError


class SnmpConfig(BaseModel):
    community: str
    config_community: str | None = None
    port: int = Field(default=161, ge=1, le=65535)
    timeout_sec: float = Field(default=2.0, gt=0)
    retries: int = Field(default=1, ge=0)

    @property
    def config_read_community(self) -> str:
        return self.config_community or self.community


@dataclass(frozen=True)
class SnmpVarbind:
    oid: str
    value: Any


def _format_snmp_value(value: Any) -> Any:
    text = str(value)
    if text in ("noSuchObject", "noSuchInstance", "endOfMibView"):
        return None
    if type(value).__name__ == "IpAddress":
        octets = getattr(value, "asOctets", lambda: None)()
        if octets and len(octets) == 4:
            return ".".join(str(b) for b in octets)
    return value


class SnmpSession:
    """Sync facade over PySNMP asyncio API."""

    def __init__(self, host: str, config: SnmpConfig) -> None:
        if not host:
            raise PeplinkConfigError("SNMP host is required")
        self.host = host
        self.config = config

    def get(self, oid: str) -> Any | None:
        results = self.get_many([oid])
        return results.get(oid)

    def get_many(self, oids: list[str]) -> dict[str, Any | None]:
        if not oids:
            return {}
        return asyncio.run(self._get_many_async(oids))

    def walk(self, base_oid: str) -> list[SnmpVarbind]:
        return asyncio.run(self._walk_async(base_oid))

    async def _get_many_async(self, oids: list[str]) -> dict[str, Any | None]:
        from pysnmp.hlapi.v1arch.asyncio import (
            CommunityData,
            ObjectIdentity,
            ObjectType,
            SnmpDispatcher,
            UdpTransportTarget,
            get_cmd,
        )

        dispatcher = SnmpDispatcher()
        transport = await UdpTransportTarget.create(
            (self.host, self.config.port),
            timeout=self.config.timeout_sec,
            retries=self.config.retries,
        )
        auth = CommunityData(self.config.community, mpModel=1)
        var_binds = [ObjectType(ObjectIdentity(oid)) for oid in oids]
        error, status, _index, bindings = await get_cmd(
            dispatcher,
            auth,
            transport,
            *var_binds,
            lookupMib=False,
        )
        if error:
            raise PeplinkConfigError(f"SNMP GET failed for {self.host}: {error}")
        if status:
            raise PeplinkConfigError(f"SNMP GET agent error for {self.host}: {status}")

        out: dict[str, Any | None] = {}
        for index, (_resp_oid, value) in enumerate(bindings):
            out[oids[index]] = _format_snmp_value(value)
        return out

    async def _walk_async(self, base_oid: str) -> list[SnmpVarbind]:
        from pysnmp.hlapi.v1arch.asyncio import (
            CommunityData,
            ObjectIdentity,
            ObjectType,
            SnmpDispatcher,
            UdpTransportTarget,
            walk_cmd,
        )

        dispatcher = SnmpDispatcher()
        transport = await UdpTransportTarget.create(
            (self.host, self.config.port),
            timeout=self.config.timeout_sec,
            retries=self.config.retries,
        )
        auth = CommunityData(self.config.community, mpModel=1)
        prefix = base_oid.rstrip(".") + "."
        rows: list[SnmpVarbind] = []
        async for error, status, _index, bindings in walk_cmd(
            dispatcher,
            auth,
            transport,
            ObjectType(ObjectIdentity(base_oid)),
            lookupMib=False,
        ):
            if error:
                raise PeplinkConfigError(f"SNMP WALK failed for {self.host}: {error}")
            if status:
                raise PeplinkConfigError(f"SNMP WALK agent error for {self.host}: {status}")
            for oid, value in bindings:
                oid_str = str(oid)
                if not oid_str.startswith(prefix):
                    return rows
                formatted = _format_snmp_value(value)
                if formatted is None:
                    continue
                rows.append(SnmpVarbind(oid=oid_str, value=formatted))
        return rows
