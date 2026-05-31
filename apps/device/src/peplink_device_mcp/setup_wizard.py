"""Guided ``peplink-device-mcp setup`` — sequences the existing verification commands
and walks the operator through the parts only they can do (creating credentials).

It NEVER creates credentials/accounts or writes real secrets: it scaffolds config from
the committed examples (with placeholders), prints the exact steps for the operator to
create their own clients, pauses, then verifies with validate / doctor / ic2-doctor.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from peplink_core.bootstrap import load_runtime_fleet

Prompt = Callable[[str], str]


def _find_examples() -> Path | None:
    for base in (Path.cwd(), Path(__file__).resolve().parents[4]):
        cand = base / "examples" / "config"
        if (cand / "config.yaml").exists():
            return cand
    return None


def _rule(title: str) -> None:
    print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


def _check(ok: bool, label: str, detail: str = "") -> None:
    mark = "OK  " if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))


def _prereqs() -> None:
    _rule("Prerequisites")
    py = sys.version_info
    _check(py >= (3, 12), f"Python {py.major}.{py.minor} (need >= 3.12)")
    _check(shutil.which("uv") is not None, "uv on PATH")
    print("  You also need: cloud (InControl 2) credentials and/or LAN-reachable Peplink gear.")


def _scaffold(config_path: Path, secrets_path: Path, *, interactive: bool, prompt: Prompt) -> None:
    _rule("Config files")
    examples = _find_examples()
    if config_path.exists() and secrets_path.exists():
        _check(True, f"config present: {config_path.name}, {secrets_path.name}")
        return
    if not interactive:
        print("  config not found — re-run interactively to scaffold, or copy examples/config/.")
        return
    if examples is None:
        print("  examples/config not found — create config.yaml + secrets.yaml by hand.")
        return
    ans = prompt(f"  Scaffold {config_path.name} + {secrets_path.name} from examples? [Y/n] ")
    if ans.strip().lower() in ("n", "no"):
        return
    if not config_path.exists():
        shutil.copy(examples / "config.yaml", config_path)
        print(f"  wrote {config_path} (edit device list to match your fleet)")
    if not secrets_path.exists():
        shutil.copy(examples / "secrets.yaml.example", secrets_path)
        print(f"  wrote {secrets_path} (PLACEHOLDERS only — paste real credentials yourself)")


_LAN_STEPS = """  LAN device credentials (per device you manage directly):
    - On each router's web admin, create API clients (or use a userpass account).
    - Map tiers: read_only -> api.read-only ; config_read/admin -> api scope.
    - Put them in secrets.yaml under devices.<id>.auth, or secrets.conf peplink.* keys.
    - See docs/device-types.md for switch/AP/FusionHub specifics and 8.5.x gotchas."""

_IC2_STEPS = """  InControl 2 credentials (cloud) — you create these; the tool cannot:
    1. Sign in to https://incontrol2.peplink.com.
    2. (Least privilege) Org Settings -> add an Organization VIEWER user (read-only),
       and keep your admin user for writes.
    3. As each user: profile (top-right email) -> Client Applications -> New Client
       (client-credentials, Bearer) -> Save -> copy Client ID + Secret.
    4. Put them in secrets:
         secrets.yaml:  incontrol2.read_only/admin (or a single incontrol2.auth)
         secrets.conf:  peplink.ic2read_clientid/secret + peplink.ic2admin_clientid/secret
    5. Enable IC2: config.yaml incontrol2.enabled: true + default_org_id."""


def _credentials(mode: str, *, interactive: bool, prompt: Prompt) -> None:
    _rule("Create your credentials")
    if mode in ("lan", "both"):
        print(_LAN_STEPS)
    if mode in ("ic2", "both"):
        print(_IC2_STEPS)
    if interactive:
        prompt("\n  Create the credentials above, paste them into secrets, then press Enter… ")


def _verify(config_path: Path, secrets_path: Path, mode: str) -> None:
    _rule("Verify")
    cfg = str(config_path) if config_path.exists() else None
    sec = str(secrets_path) if secrets_path.exists() else None
    try:
        fleet = load_runtime_fleet(cfg, sec)
        _check(True, "config loads", f"{len(fleet.devices)} device(s)")
    except Exception as exc:  # noqa: BLE001 - report, don't crash the wizard
        _check(False, "config loads", str(exc))
        return

    if mode in ("lan", "both") and fleet.defaults.device_id:
        from peplink_core import run_doctor

        try:
            report = run_doctor(fleet.defaults.device_id, fleet=fleet)
            _check(report.ok, f"device doctor ({fleet.defaults.device_id})",
                   ", ".join(f"{t.tier}:{'ok' if t.ok else 'fail'}" for t in report.tiers))
        except Exception as exc:  # noqa: BLE001
            _check(False, "device doctor", str(exc))

    if mode in ("ic2", "both"):
        from peplink_ic2 import run_ic2_doctor

        if not fleet.ic2_enabled:
            _check(False, "InControl 2", "not enabled (set incontrol2 + credentials)")
        else:
            try:
                rep = run_ic2_doctor(fleet.incontrol2)
                _check(rep.ok, "InControl 2 doctor",
                       ", ".join(f"{c.check}:{'ok' if c.ok else 'fail'}" for c in rep.checks))
            except Exception as exc:  # noqa: BLE001
                _check(False, "InControl 2 doctor", str(exc))


def _next_steps(mode: str) -> None:
    _rule("Next steps")
    if mode in ("ic2", "both"):
        print("  - Map fleet -> InControl 2:  uv run peplink-device-mcp ic2-sync [--write]")
    print("  - Mint an MCP key:           uv run peplink-device-mcp keys generate --id NAME --tier read_only")
    print("  - Run the server (stdio):    uv run peplink-device-mcp serve --transport stdio")
    print("  - Connect Cursor/Claude to that command, then ask your agent to run")
    print("    `validate` / `ic2-doctor` / `ic2-sync` and interpret the results.")
    print("  - Enable writes only when ready: PEPLINK_POLICY_ALLOW_* env flags + confirm=true.")
    print("\n  Full walkthrough: docs/quickstart.md")


def run_setup(
    *,
    config_path: str | None,
    secrets_path: str | None,
    non_interactive: bool = False,
    prompt: Prompt = input,
) -> int:
    interactive = not non_interactive and sys.stdin.isatty()
    cfg = Path(config_path or "config.yaml")
    sec = Path(secrets_path or "secrets.yaml")

    print("peplink-device-mcp setup — guided walkthrough (Wildly experimental)\n")
    _prereqs()

    mode = "both"
    if interactive:
        choice = prompt(
            "\nWhat do you want to manage? [1] InControl 2 cloud  [2] LAN devices  "
            "[3] both (default): "
        ).strip()
        mode = {"1": "ic2", "2": "lan", "3": "both", "": "both"}.get(choice, "both")
    print(f"\nMode: {mode}")

    _scaffold(cfg, sec, interactive=interactive, prompt=prompt)
    _credentials(mode, interactive=interactive, prompt=prompt)
    _verify(cfg, sec, mode)

    if mode in ("ic2", "both") and interactive:
        ans = prompt("\n  Run ic2-sync to preview device -> InControl 2 mapping now? [Y/n] ")
        if ans.strip().lower() not in ("n", "no"):
            from peplink_device_mcp.ic2_sync import run_ic2_sync

            try:
                run_ic2_sync(
                    config_path=str(cfg) if cfg.exists() else None,
                    secrets_path=str(sec) if sec.exists() else None,
                    write=False,
                )
            except Exception as exc:  # noqa: BLE001 - report, don't crash the wizard
                print(f"  ic2-sync skipped: {exc}")

    _next_steps(mode)
    return 0
