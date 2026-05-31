# peplink-mcp — setup quickstart

> **Wildly experimental.** Review the code before pointing it at real hardware. Admin-tier
> tools can change device configuration or cause outages. See the [README](../README.md) warning.

The fastest path is the **guided setup**, which runs every check below for you and tells you
exactly what to create:

```bash
uv run peplink-device-mcp setup
```

It never creates credentials or writes secrets for you — it scaffolds config, prints the exact
steps for the parts only you can do, pauses, then verifies. The rest of this page is the same
flow written out.

---

## 1. Pick an access mode

peplink-mcp can talk to your fleet two ways — use either or **both**:

| Mode | What it does | You need |
|------|--------------|----------|
| **InControl 2 (cloud)** | Fleet inventory/status + InControl-managed config (SSID, VLAN, WAN priority, firewall, reboot…) via Peplink's cloud | An IC2 account + API client(s) |
| **LAN-direct** | Each device's native `/api/...` REST surface on your LAN/VPN | Network reach to the devices + per-device credentials |

## 2. Prerequisites

- **Python 3.12+** and **[`uv`](https://docs.astral.sh/uv/)**.
- Cloud creds (IC2) and/or LAN-reachable Peplink gear, per the mode you chose.

## 3. Install

```bash
uv sync --all-packages
uv run peplink-device-mcp --help
make test          # optional: run the suite
```

## 4. Choose a config model

| Model | When | Files |
|-------|------|-------|
| **Single-device (quick)** | One device / dev box | `secrets.conf` (INI), pointed to by `PEPLINK_SECRETS_CONF` |
| **Fleet (full)** | Many devices, IC2, sites | `config.yaml` (non-secret) + `secrets.yaml` (secret) |

Copy the templates:

```bash
cp examples/config/config.yaml config.yaml
cp examples/config/secrets.yaml.example secrets.yaml   # fill in — never commit
```

**Precedence:** when both `--config`/`--secrets` (or `PEPLINK_MCP_CONFIG`/`PEPLINK_MCP_SECRETS`)
are set, the YAML pair is used; otherwise it falls back to `secrets.conf`.

## 5. Create your credentials (you do this — the tool can't)

> peplink-mcp will **never** mint API clients, create accounts, or type passwords for you.

### LAN-direct devices
On each device's web admin create API clients (preferred) or use a userpass account, mapped to
tiers — `read_only` → `api.read-only`; `config_read`/`admin` → `api` scope. Put them in
`secrets.yaml` under `devices.<id>.auth`, or in `secrets.conf` under `peplink.*` keys. Switch/AP
(SNMP)/FusionHub specifics and 8.5.x gotchas are in [`device-types.md`](device-types.md).

### InControl 2 (cloud)
IC2 API clients **inherit the permissions of the user that creates them** — there's no read-only
toggle on the client. For least privilege:

1. Sign in to <https://incontrol2.peplink.com>.
2. **Organization Settings → Organization Users →** add an **Organization Viewer** (read-only)
   user; keep your admin user for writes.
3. As **each** user: click your email (top-right) → **Client Applications → New Client**
   (client-credentials grant, Token Type **Bearer**) → **Save** → copy the **Client ID + Secret**.
4. Put them in secrets:
   - `secrets.yaml`: `incontrol2.read_only` + `incontrol2.admin` (or a single `incontrol2.auth`
     used for both).
   - `secrets.conf`: `peplink.ic2read_clientid`/`_clientsecret` + `peplink.ic2admin_clientid`/`_clientsecret`.
5. Enable it in `config.yaml`: `incontrol2.enabled: true` and `default_org_id: "<your org id>"`.

## 6. Verify each layer

```bash
uv run peplink-device-mcp validate    --config config.yaml --secrets secrets.yaml
uv run peplink-device-mcp doctor       --device <id> --config config.yaml --secrets secrets.yaml
uv run peplink-device-mcp ic2-doctor   --config config.yaml --secrets secrets.yaml
```
`validate` checks config shape; `doctor` does a live per-tier auth probe of one device;
`ic2-doctor` does a live IC2 token grant + org list (and the admin token when read ≠ admin).

## 7. Map devices to InControl 2 + group them

```bash
uv run peplink-device-mcp ic2-sync                 # dry run: device -> IC2 serial + site
uv run peplink-device-mcp ic2-sync --write         # emit <config>.synced.yaml to review/merge
```
`ic2-sync` joins each fleet device to its IC2 record (by serial, else name/model) and reports the
**site** (= IC2 group name). Ambiguous matches are flagged, never guessed.

**Sites** (`main` / `branch` / `mobile` …) give the agent context and line up with IC2's
group-scoped config tools. Set `site:` per device in `config.yaml` (gateway-managed devices
inherit their gateway's site), or organize your devices into IC2 groups and let `ic2-sync`
derive `site` from the group name.

## 8. Connect an MCP client

```bash
uv run peplink-device-mcp keys generate --id cursor-readonly --tier read_only   # mint a key
uv run peplink-device-mcp serve --transport stdio    # local, trusted (no key needed)
```
- **stdio** — for a local agent (Cursor/Claude Desktop); the launching process is trusted.
- **http** — for network access; **requires** MCP API keys (`Authorization: Bearer <key>`).

Point your client at the `serve` command (see `examples/cursor-mcp.json`). Then **ask your agent**
to run `validate` / `ic2-doctor` / `ic2-sync` and interpret the results — that's the easiest way
to finish setup.

**Running as a server / in Docker?** Use `--transport http` (requires an MCP key) — see
[`docker.md`](docker.md).

## 9. Enable writes safely

Write/config/command tools are **triple-gated**: an admin-tier MCP key, an explicit
`confirm=true`, **and** a per-family policy env flag (default-deny). Enable only what you need:

```
PEPLINK_POLICY_ALLOW_IC2_CONFIG_WRITE=1     # IC2 SSID/VLAN/WAN-priority/firewall/…
PEPLINK_POLICY_ALLOW_IC2_REBOOT=1           # IC2 device reboot
PEPLINK_POLICY_ALLOW_IC2_FACTORY_RESET=1    # IC2 factory reset
PEPLINK_POLICY_ALLOW_IC2_CONFIG_RESTORE=1   # IC2 config-backup restore
# device-side: PEPLINK_POLICY_ALLOW_SYSTEM_REBOOT, _WAN_DISABLE, _SMS_SEND, _CONFIG_APPLY, …
```

## Reference

- [`device-types.md`](device-types.md) — per-kind auth, discovery, fleet config, gotchas.
- [`fusionhub-api.md`](fusionhub-api.md) — FusionHub REST matrix.
- `examples/config/` — annotated `config.yaml` + `secrets.yaml.example` templates.
