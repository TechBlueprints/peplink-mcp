"""Peplink device MCP server entrypoint."""

from __future__ import annotations

import argparse
import json
import sys

from peplink_core import PeplinkConfigError, run_doctor
from peplink_core.bootstrap import load_runtime_fleet
from peplink_core.config import load_fleet_config
from peplink_core.fleet_summary import fleet_device_summaries


def _keys_command(args) -> int:
    if args.keys_command == "generate":
        import uuid

        secret = str(uuid.uuid4())
        ref_name = args.id.replace("-", "_")
        desc = args.description or f"{args.tier} key"
        print(f"# New MCP key '{args.id}' (tier={args.tier})")
        print("#")
        print("# 1) Add to config.yaml under mcp_keys:")
        print(f"  - id: {args.id}")
        print(f"    key_ref: mcp_keys.{ref_name}")
        print(f"    tier: {args.tier}")
        print(f'    description: "{desc}"')
        print("#")
        print("# 2) Add the secret to secrets.yaml under mcp_keys (NEVER commit):")
        print(f'  {ref_name}: "{secret}"')
        print("#")
        print("# 3) Callers authenticate with:  Authorization: Bearer " + secret)
        return 0

    if args.keys_command == "list":
        try:
            fleet = load_fleet_config(args.config, args.secrets)
        except PeplinkConfigError as exc:
            print(f"keys list: FAIL — {exc}", file=sys.stderr)
            return 1
        from peplink_mcp_shared.mcp_keys import McpKeyStore, resolve_key_ref

        try:
            McpKeyStore.from_fleet(fleet)  # validates refs/secrets
        except PeplinkConfigError as exc:
            print(f"keys list: FAIL — {exc}", file=sys.stderr)
            return 1
        if not fleet.mcp_keys:
            print("keys list: no mcp_keys configured")
            return 0
        print(f"keys list: {len(fleet.mcp_keys)} key(s)")
        for key in fleet.mcp_keys:
            secret = fleet.mcp_key_secrets.get(resolve_key_ref(key.key_ref), "")
            masked = f"{secret[:4]}…{secret[-4:]}" if len(secret) >= 8 else "(set)"
            print(f"  - {key.id} [{key.tier}] {masked} — {key.description or ''}".rstrip())
        return 0

    print("keys: specify a subcommand (generate|list)", file=sys.stderr)
    return 1


def _print_doctor_report(report) -> None:
    print(f"device: {report.device_id}")
    print(f"host:   {report.host} ({report.kind})")
    print(f"url:    {report.base_url}")
    for tier in report.tiers:
        status = "OK" if tier.ok else "FAIL"
        print(f"  [{status}] {tier.tier} ({tier.auth_type}): {tier.message}")
    print(f"overall: {'OK' if report.ok else 'FAIL'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="peplink-device-mcp",
        description="MCP server for Peplink devices (direct LAN API). Wildly experimental.",
    )
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run the MCP server")
    serve.add_argument("--config", default=None, help="Path to config.yaml")
    serve.add_argument("--secrets", default=None, help="Path to secrets.yaml")
    serve.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio (local, trusted) or http (network, requires mcp_keys)",
    )
    serve.add_argument("--host", default=None, help="HTTP bind host (default from config)")
    serve.add_argument("--port", type=int, default=None, help="HTTP bind port (default from config)")

    keys = sub.add_parser("keys", help="Manage MCP API keys")
    keys_sub = keys.add_subparsers(dest="keys_command")
    keys_gen = keys_sub.add_parser("generate", help="Mint a new MCP API key (GUID)")
    keys_gen.add_argument("--id", required=True, help="Key id (e.g. cursor-readonly)")
    keys_gen.add_argument(
        "--tier", choices=["read_only", "admin"], default="read_only", help="Caller tier"
    )
    keys_gen.add_argument("--description", default=None, help="Human description")
    keys_list = keys_sub.add_parser("list", help="List configured MCP keys (secrets masked)")
    keys_list.add_argument("--config", default=None)
    keys_list.add_argument("--secrets", default=None)

    doctor = sub.add_parser("doctor", help="Test config and device connectivity")
    doctor.add_argument("--device", required=True, help="device_id from config")
    doctor.add_argument("--config", default=None)
    doctor.add_argument("--secrets", default=None)
    doctor.add_argument("--json", action="store_true", help="Print JSON report")

    validate = sub.add_parser("validate", help="Validate config files only")
    validate.add_argument("--config", default=None)
    validate.add_argument("--secrets", default=None)

    ic2_doctor = sub.add_parser(
        "ic2-doctor", help="Test InControl 2 cloud credentials (OAuth + org list)"
    )
    ic2_doctor.add_argument("--config", default=None)
    ic2_doctor.add_argument("--secrets", default=None)

    ic2_sync = sub.add_parser(
        "ic2-sync", help="Propose fleet device → InControl 2 serial + site mappings"
    )
    ic2_sync.add_argument("--config", default=None)
    ic2_sync.add_argument("--secrets", default=None)
    ic2_sync.add_argument(
        "--write", action="store_true", help="Emit a synced config copy (<config>.synced.yaml)"
    )

    setup = sub.add_parser("setup", help="Guided first-time setup walkthrough")
    setup.add_argument("--config", default=None)
    setup.add_argument("--secrets", default=None)
    setup.add_argument(
        "--non-interactive", action="store_true", help="Run checks only; no prompts/writes"
    )

    sub.add_parser("version", help="Print version")

    args = parser.parse_args(argv)

    if args.command == "version":
        from peplink_device_mcp import __version__

        print(__version__)
        return 0

    if args.command == "validate":
        try:
            fleet = load_fleet_config(args.config, args.secrets)
        except PeplinkConfigError as exc:
            print(f"validate: FAIL — {exc}", file=sys.stderr)
            return 1
        default_id = fleet.defaults.device_id or "(none)"
        print(
            f"validate: OK — {len(fleet.devices)} device(s), "
            f"default={default_id}, access_mode={fleet.access_mode}"
        )
        for row in fleet_device_summaries(fleet):
            default = " [default]" if row["default"] else ""
            auth = f"ro={row.get('read_only_auth', '?')}"
            if row.get("admin_configured"):
                auth += f" admin={row['admin_auth']}"
            else:
                auth += " admin=(none)"
            host = row.get("host") or f"discover→{row.get('discover_via')}"
            print(
                f"  - {row['device_id']}{default}: {host} "
                f"({row['kind']}, {row.get('host_source')}) {auth}"
            )
        ic2 = fleet.incontrol2
        if ic2.enabled:
            org = ic2.default_org_id or "(none)"
            if ic2.read_only or ic2.admin:
                tiers = []
                if ic2.read_credentials():
                    tiers.append("read")
                if ic2.write_credentials():
                    tiers.append("write")
                auth_state = f"auth tiers: {'+'.join(tiers) or 'NONE'}"
            elif ic2.auth:
                auth_state = "auth set (shared read+write)"
            else:
                auth_state = "auth MISSING"
            print(f"  incontrol2: enabled, default_org={org}, {auth_state}, base_url={ic2.base_url}")
            mapped = [d for d, c in fleet.devices.items() if c.ic2]
            if mapped:
                print(f"  incontrol2 device mappings: {', '.join(sorted(mapped))}")
        else:
            print("  incontrol2: disabled")
        return 0

    if args.command == "ic2-doctor":
        from peplink_ic2 import run_ic2_doctor
        from peplink_ic2.exceptions import IC2Error

        try:
            # load_runtime_fleet picks up YAML (--config/--secrets or PEPLINK_MCP_*)
            # or the secrets.conf file (incl. peplink.incontrol2.* keys).
            fleet = load_runtime_fleet(args.config, args.secrets)
        except PeplinkConfigError as exc:
            print(f"ic2-doctor: config error — {exc}", file=sys.stderr)
            return 1
        if not fleet.ic2_enabled:
            print(
                "ic2-doctor: InControl 2 not configured — set peplink.incontrol2.client_id/"
                "client_secret in secrets.conf, or incontrol2 in config.yaml/secrets.yaml",
                file=sys.stderr,
            )
            return 1
        try:
            report = run_ic2_doctor(fleet.incontrol2)
        except IC2Error as exc:
            print(f"ic2-doctor: error — {exc}", file=sys.stderr)
            return 1
        print(f"incontrol2: {report.base_url}")
        for check in report.checks:
            status = "OK" if check.ok else "FAIL"
            print(f"  [{status}] {check.check}: {check.message}")
        print(f"overall: {'OK' if report.ok else 'FAIL'}")
        return 0 if report.ok else 2

    if args.command == "setup":
        from peplink_device_mcp.setup_wizard import run_setup

        return run_setup(
            config_path=args.config,
            secrets_path=args.secrets,
            non_interactive=args.non_interactive,
        )

    if args.command == "ic2-sync":
        from peplink_ic2.exceptions import IC2Error

        from peplink_device_mcp.ic2_sync import run_ic2_sync

        try:
            return run_ic2_sync(
                config_path=args.config, secrets_path=args.secrets, write=args.write
            )
        except PeplinkConfigError as exc:
            print(f"ic2-sync: config error — {exc}", file=sys.stderr)
            return 1
        except IC2Error as exc:
            print(f"ic2-sync: error — {exc}", file=sys.stderr)
            return 1

    if args.command == "keys":
        return _keys_command(args)

    if args.command == "serve":
        from peplink_device_mcp.runtime import run_server

        try:
            run_server(
                config_path=args.config,
                secrets_path=args.secrets,
                transport=args.transport,
                host=args.host,
                port=args.port,
            )
        except PeplinkConfigError as exc:
            print(f"serve: FAIL — {exc}", file=sys.stderr)
            return 1
        return 0

    if args.command == "doctor":
        try:
            fleet = load_runtime_fleet(args.config, args.secrets)
            report = run_doctor(args.device, fleet=fleet)
        except PeplinkConfigError as exc:
            print(f"doctor: config error — {exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"doctor: error — {exc}", file=sys.stderr)
            return 1

        if args.json:
            payload = {
                "device_id": report.device_id,
                "host": report.host,
                "kind": report.kind,
                "base_url": report.base_url,
                "ok": report.ok,
                "tiers": [
                    {
                        "tier": t.tier,
                        "ok": t.ok,
                        "auth_type": t.auth_type,
                        "message": t.message,
                        "detail": t.detail,
                    }
                    for t in report.tiers
                ],
            }
            print(json.dumps(payload, indent=2))
        else:
            _print_doctor_report(report)
        return 0 if report.ok else 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
