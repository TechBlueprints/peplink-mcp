"""Setup wizard tests — never prompts in non-interactive; scaffolds + verifies otherwise."""

from __future__ import annotations

import os

from peplink_device_mcp.setup_wizard import run_setup


def test_non_interactive_runs_checks_without_prompting_or_writing(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # No secrets.conf fallback, no config files -> all checks degrade gracefully.
    monkeypatch.setenv("PEPLINK_SECRETS_CONF", str(tmp_path / "nope.conf"))

    def _boom(_prompt):  # prompting in non-interactive mode is a bug
        raise AssertionError("wizard prompted in non-interactive mode")

    rc = run_setup(config_path=None, secrets_path=None, non_interactive=True, prompt=_boom)
    out = capsys.readouterr().out
    assert rc == 0
    assert "Prerequisites" in out and "Verify" in out and "Next steps" in out
    # never scaffolds/writes in non-interactive
    assert not (tmp_path / "config.yaml").exists()
    assert not (tmp_path / "secrets.yaml").exists()


def test_interactive_scaffolds_and_verifies(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PEPLINK_SECRETS_CONF", str(tmp_path / "nope.conf"))
    # Pretend we're on a TTY so the wizard goes interactive.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    answers = iter(["2", "y", ""])  # mode=LAN, scaffold=yes, credential-pause Enter

    def fake_prompt(_msg):
        return next(answers, "")

    # Stub the verify step's device probe so the test never does real network.
    import types

    import peplink_core

    fake = types.SimpleNamespace(ok=True, tiers=[types.SimpleNamespace(tier="read_only", ok=True)])
    monkeypatch.setattr(peplink_core, "run_doctor", lambda *a, **k: fake)

    cfg = tmp_path / "config.yaml"
    sec = tmp_path / "secrets.yaml"
    rc = run_setup(
        config_path=str(cfg), secrets_path=str(sec), non_interactive=False, prompt=fake_prompt
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "Mode: lan" in out
    # scaffolded from examples (placeholders only)
    assert cfg.exists() and sec.exists()
    assert "REPLACE" in sec.read_text()  # placeholders, not real secrets
    assert os.path.basename(str(cfg)) == "config.yaml"
