# FusionHub REST surface

FusionHub is a SpeedFusion/PepVPN **hub** (VM, cloud image, or appliance), not an edge router.
It uses the same `https://<host>/api/<endpoint>` transport as routers, but its live REST surface
is a subset — model it as `kind: fusionhub` in fleet config so tool gating matches.

## Authentication

FusionHub VMs often have no OAuth API clients. Userpass tiers work:

| MCP tier | Typical login | Use |
|----------|---------------|-----|
| `read_only` | read-only account | `status.pepvpn`, `status.wan.connection`, … |
| `config_read` | admin account | `config.pepvpn`, `config.pepvpn.profile`, … |
| `admin` | admin account | PepVPN config writes |

TLS is usually self-signed — set `verify_tls: false`.

## What FusionHub is for

- Central PepVPN/SpeedFusion point; remote routers connect as peers.
- Advertises remote LAN subnets to the core network.
- Not a gateway — it does not replace your LAN default router.

## REST surface

- **Hub-specific reads:** `GET /api/config.pepvpn`, `GET /api/config.pepvpn.profile`, plus
  `status.wan` / `status.lan`, `config.firewall`, `config.natMapping`, …
- **Shared reads:** `GET /api/status.pepvpn` (live peers + routes), `status.wan.connection`,
  `status.traffic`, `config.lan`, …
- **Absent vs a router:** `config.mesh`, `config.speedfusionConnectProtect`, `info.location`,
  and cellular/Wi-Fi `cmd.*` are missing or return `Unsupported request`.

For peplink-mcp tools and tiers, see [`device-types.md`](device-types.md) and
[`quickstart.md`](quickstart.md).
