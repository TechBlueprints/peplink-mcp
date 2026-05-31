"""Load MCP tool specs from device manifest YAML files."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

McpToolTier = Literal["read_only", "config_read", "admin"]


@dataclass(frozen=True)
class ManifestToolSpec:
    name: str
    method: str
    path: str
    tier: McpToolTier
    query: dict[str, str] = field(default_factory=dict)
    device_kinds: tuple[str, ...] = ()
    destructive: bool = False
    coverage_exempt: bool = False
    policy: str | None = None


def _parse_query(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for part in raw.split("&"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _normalize_tier(raw: str | None) -> McpToolTier:
    if raw in ("read_only", "config_read", "admin"):
        return raw  # type: ignore[return-value]
    return "read_only"


def load_manifest_tool_specs(
    *manifest_paths: Path | str,
) -> list[ManifestToolSpec]:
    specs: list[ManifestToolSpec] = []
    for manifest_path in manifest_paths:
        path = Path(manifest_path)
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            continue
        for entry in data.get("endpoints", []):
            if not isinstance(entry, dict):
                continue
            tool = entry.get("tool")
            if not tool or not isinstance(tool, str):
                continue
            method = str(entry.get("method", "GET")).upper()
            api_path = entry.get("path")
            if not api_path or not isinstance(api_path, str):
                continue
            kinds = entry.get("device_kinds") or []
            specs.append(
                ManifestToolSpec(
                    name=tool,
                    method=method,
                    path=api_path,
                    tier=_normalize_tier(entry.get("tier")),
                    query=_parse_query(entry.get("query")),
                    device_kinds=tuple(kinds) if isinstance(kinds, list) else (),
                    destructive=bool(entry.get("destructive")),
                    coverage_exempt=bool(entry.get("coverage_exempt")),
                    policy=(str(entry["policy"]) if entry.get("policy") else None),
                )
            )
    return specs


def default_device_manifest_paths(repo_root: Path | None = None) -> tuple[Path, Path]:
    root = repo_root or Path(__file__).resolve().parents[4]
    return (
        root / "apps/device/src/peplink_device_mcp/manifest/router-api-8.5.2.yaml",
        root / "apps/device/src/peplink_device_mcp/manifest/supplemental.yaml",
    )
