"""Load Peplink credentials from secrets.conf-style INI files."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path

from peplink_core.config import (
    ClientCredentialsAuth,
    DeviceAuth,
    IC2ClientCredentials,
    IC2Config,
    UserpassAuth,
)


@dataclass(frozen=True)
class PeplinkSecretsIni:
    host: str
    read_only: DeviceAuth
    config_read: DeviceAuth | None = None
    admin: DeviceAuth | None = None


def _get(section: configparser.SectionProxy, key: str) -> str:
    return section.get(key, fallback="").strip()


def _client_auth(section: configparser.SectionProxy, prefix: str, *, scope: str) -> ClientCredentialsAuth | None:
    client_id = _get(section, f"{prefix}_client_id")
    client_secret = _get(section, f"{prefix}_client_secret")
    if client_id and client_secret:
        configured_scope = _get(section, f"{prefix}_scope") or scope
        return ClientCredentialsAuth(
            client_id=client_id,
            client_secret=client_secret,
            scope=configured_scope,
        )
    return None


def _load_peplink_secrets_from_section(
    section: configparser.SectionProxy,
    *,
    host_key: str,
    prefix: str,
    path: Path,
) -> PeplinkSecretsIni | None:
    host = _get(section, host_key)
    if not host:
        return None

    read_only = _client_auth(section, f"{prefix}readonly_api", scope="api.read-only")
    if read_only is None:
        username = _get(section, f"{prefix}username")
        password = _get(section, f"{prefix}password")
        if not username or not password:
            raise ValueError(f"{prefix}username/password not found in {path}")
        read_only = UserpassAuth(username=username, password=password)

    config_read = _client_auth(section, f"{prefix}config_read_api", scope="api")
    admin = _client_auth(section, f"{prefix}admin_api", scope="api")
    if admin is None:
        admin_username = _get(section, f"{prefix}admin_username")
        admin_password = _get(section, f"{prefix}admin_password")
        if admin_username and admin_password:
            admin = UserpassAuth(username=admin_username, password=admin_password)

    return PeplinkSecretsIni(
        host=host,
        read_only=read_only,
        config_read=config_read,
        admin=admin,
    )


def load_peplink_secrets(path: Path) -> PeplinkSecretsIni:
    """Return host plus status/config/admin auth from a secrets.conf [secrets] block."""
    parser = configparser.ConfigParser()
    parser.read(path)
    for section_name in parser.sections():
        section = parser[section_name]
        secrets = _load_peplink_secrets_from_section(
            section,
            host_key="peplink.host",
            prefix="peplink.",
            path=path,
        )
        if secrets is not None:
            return secrets

    raise ValueError(f"peplink.host not found in {path}")


def load_peplink_fusionhub_secrets(path: Path) -> PeplinkSecretsIni | None:
    """Optional home FusionHub block: peplink.fusionhub.host (+ userpass or API clients)."""
    parser = configparser.ConfigParser()
    parser.read(path)
    for section_name in parser.sections():
        section = parser[section_name]
        secrets = _load_peplink_secrets_from_section(
            section,
            host_key="peplink.fusionhub.host",
            prefix="peplink.fusionhub.",
            path=path,
        )
        if secrets is not None:
            return secrets
    return None


def _ic2_pair(
    section: configparser.SectionProxy, *prefixes: str
) -> IC2ClientCredentials | None:
    """First credential matching any prefix. Accepts client_id/clientid spellings."""
    for prefix in prefixes:
        client_id = _get(section, f"{prefix}client_id") or _get(section, f"{prefix}clientid")
        client_secret = _get(section, f"{prefix}client_secret") or _get(
            section, f"{prefix}clientsecret"
        )
        if client_id and client_secret:
            return IC2ClientCredentials(client_id=client_id, client_secret=client_secret)
    return None


def _ic2_value(section: configparser.SectionProxy, *keys: str) -> str | None:
    for key in keys:
        value = _get(section, key)
        if value:
            return value
    return None


def load_ic2_secrets(path: Path) -> IC2Config | None:
    """Load InControl 2 cloud credentials from a secrets.conf section.

    Keys (under any section, alongside ``peplink.host``). Both the canonical
    ``incontrol2.*`` spelling and the shorter ``ic2*`` spelling are accepted:

      peplink.incontrol2.client_id / client_secret   (or peplink.ic2_clientid/clientsecret)
                                                      — single client (read + write)
      peplink.incontrol2.readonly_client_id / …      (or peplink.ic2readonly_/ic2read_ clientid/…)
                                                      — optional read tier
      peplink.incontrol2.admin_client_id / …         (or peplink.ic2admin_clientid/…)
                                                      — optional write tier
      peplink.incontrol2.default_org_id / default_group_id  (or peplink.ic2.default_org_id)
      peplink.incontrol2.base_url                    (or peplink.ic2.base_url)

    Returns an enabled ``IC2Config`` when any IC2 credential is found, else ``None``.
    """
    parser = configparser.ConfigParser()
    parser.read(path)
    for section_name in parser.sections():
        section = parser[section_name]
        shared = _ic2_pair(section, "peplink.incontrol2.", "peplink.ic2_", "peplink.ic2.")
        read_only = _ic2_pair(
            section,
            "peplink.incontrol2.readonly_",
            "peplink.ic2readonly_",
            "peplink.ic2read_",
        )
        admin = _ic2_pair(section, "peplink.incontrol2.admin_", "peplink.ic2admin_")
        if not (shared or read_only or admin):
            continue
        base_url = _ic2_value(section, "peplink.incontrol2.base_url", "peplink.ic2.base_url")
        return IC2Config(
            enabled=True,
            base_url=base_url or "https://api.ic.peplink.com",
            default_org_id=_ic2_value(
                section, "peplink.incontrol2.default_org_id", "peplink.ic2.default_org_id"
            ),
            default_group_id=_ic2_value(
                section,
                "peplink.incontrol2.default_group_id",
                "peplink.ic2.default_group_id",
            ),
            auth=shared,
            read_only=read_only,
            admin=admin,
        )
    return None


def load_peplink_credentials(path: Path) -> tuple[str, str, str]:
    """Return (host, username, password) for legacy read-only userpass callers."""
    secrets = load_peplink_secrets(path)
    if not isinstance(secrets.read_only, UserpassAuth):
        raise ValueError(
            f"peplink.username/password not found in {path} (read-only API client configured instead)"
        )
    return secrets.host, secrets.read_only.username, secrets.read_only.password
