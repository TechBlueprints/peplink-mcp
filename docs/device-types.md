# Peplink device types — management and APIs

How **peplink-mcp** talks to each class of Peplink hardware on a fleet LAN, and how to
configure each in `config.yaml` / `secrets.yaml`. Keep your specific deployment inventory
(IPs, hostnames, serials, secrets) in your own environment, not here.

---

## Device kinds

| `kind` | Examples | Primary read | Primary write |
|--------|----------|--------------|---------------|
| `router` | Balance, MAX, B One, Transit | HTTPS REST | HTTPS REST |
| `fusionhub` | FusionHub VM / appliance (SpeedFusion hub) | HTTPS REST (hub subset) | HTTPS REST (PepVPN config) |
| `switch` | SD Switch | HTTPS REST (partial) | HTTPS REST via **gateway** (Switch Controller) |
| `ap` | AP One | **SNMP** | Gateway AP Controller when adopted; otherwise out of band |

`management: direct | gateway` controls **write** routing for controller-managed devices
(switches, adopted APs). Gateway-managed writes are sent to the gateway, not the device IP.

### Management patterns

| Pattern | `kind` | `management` | Read | Write |
|---------|--------|--------------|------|-------|
| Standalone router / gateway | `router` | `direct` | REST → device | REST → device |
| Mesh / VPN peer router | `router` | `direct` | REST → discovered IP | REST → discovered IP |
| FusionHub | `fusionhub` | `direct` | REST → hub | REST → hub (PepVPN config) |
| Controller-managed switch | `switch` | `gateway` | REST → switch IP | REST → gateway |
| Standalone switch | `switch` | `direct` | REST → switch | REST → switch |
| Adopted AP | `ap` | `gateway` | SNMP → AP | Gateway AP APIs |
| Standalone AP | `ap` | `direct` | SNMP → AP | Out of band / InControl 2 |

---

## Routers (`kind: router`)

- **Base URL:** `https://<host>/api/<endpoint>`
- **Docs:** [Peplink Router API](https://www.peplink.com/support/downloads/supplementary-materials/)
  (versioned PDFs; e.g. an 8.5.2 baseline for 8.5.x firmware).
- **Methods:** GET for reads; POST with JSON body for writes/commands.

### Authentication

| Pattern | Login | Notes |
|---------|-------|-------|
| **OAuth-like API clients** | `POST /api/auth.client` + `/api/auth.token.grant` | Preferred for automation; scoped |
| **Session cookie** | `POST /api/login` (JSON body) | Legacy; cookie on later requests |

Recommended three-tier mapping for MCP / automation:

| Tier | Peplink scope | Typical use |
|------|---------------|-------------|
| `read_only` | `api.read-only` | `GET /api/status.*`, `GET /api/info.*` |
| `config_read` | `api` | `GET /api/config.*` |
| `admin` | `api` | `POST /api/config.*`, `POST /api/cmd.*` |

Common gotchas on modern 8.x firmware:

- **Writes over a login session need `X-Requested-With: XMLHttpRequest`.** A router (MAX BR1/BR2,
  FusionHub on 8.6.1) answers every POST made with the `/api/login` cookie with
  `{"stat": "fail", "code": 401}` unless the request carries that header, as the web admin's do,
  even when the login reports `"permission": {"GET": 1, "POST": 1}` (a read-only login reports
  `"POST": 0`). The client adds it to every non-GET request. SD switches accept POSTs either way.

- `api.read-only` clients may get `401` on `GET /api/config.*` — provision a separate
  `config_read` client with the `api` scope.
- Sending an explicit `scope` on `/api/auth.token.grant` can fail; rely on the client's
  baked-in scope.
- Devices commonly use **self-signed** TLS — set `verify_tls: false` on the LAN.

### Built-in Wi-Fi and external APs

Routers with integrated Wi-Fi expose `GET /api/status.ap` and `GET /api/config.ssid.profile`
(needs `config_read`). When an AP Controller is enabled, `GET /api/status.extap.mesh*` lists
adopted external APs and link topology.

---

## FusionHub (`kind: fusionhub`)

A SpeedFusion/PepVPN hub (VM, cloud image, or appliance) terminating VPN tunnels — **not** an
edge router (no cellular, no client Wi-Fi). Its live REST surface differs from a router; see
[`fusionhub-api.md`](fusionhub-api.md). FusionHub VMs often have no OAuth clients — userpass
tiers work (`read_only` via a read-only account; `config_read`/`admin` via the admin login).

---

## Switches (`kind: switch`)

SD switches expose a partial REST API: `status.port` (link, VLAN mode, name and per-port PoE
`{"enable", "power"}`, power only while PoE is on), the public `status.system.info` (model, CPU
load, uptime, temperature; the CGI form is not answered) and `config.port`. Reads use the switch IP
with a userpass account; a switch managed by a router's Switch Controller takes that router's
logins, and its read-only login can still read `config.port` and `config.admin`.

Writes on a controller-managed switch (`management: gateway`) are blocked on the switch IP, and for
good reason: tested 2026-10-31 on SD Switch Rugged 1.3.2 under a MAX BR2 Pro 8.6.1, a PoE command
sent to the switch answers `ok` (after ~10 s) but the controller keeps its own PoE setting. No API
route through the gateway was found either: the gateway's `config.port` lists only its own front
panel, and the `moduleType`/`moduleId` addressing in the 8.5.2 docs is for modular devices such as
the EPX. Change a managed switch's ports in the gateway's Switch Controller web UI.

PoE commands (`cmd.port.poe.enable` / `disable`) take port objects, `{"port": [{"id": 1}]}`: an SD
switch rejects bare numbers (`Mandatory - id in port[0]`) and answers `ok` to a list of numbers
without changing anything.

---

## AP One (`kind: ap`)

Standalone AP One firmware does not expose the router-style `/api/...` REST surface, so
peplink-mcp reads APs over **SNMP** (Pepwave enterprise MIB):

- Firmware, serial, uptime, hostname; per-AP Wi-Fi client list with signal; radio channels/SSID;
  SSID profile config (passphrase masked by the device).
- Config: `devices.<id>.snmp.community` (and optional `snmp.config_community`). HTTP auth is
  optional and unused by the SNMP tools.

AP write/config is done through the gateway's AP Controller (when adopted) or InControl 2.

---

## InControl 2 routing (config authority)

When InControl 2 is configured and manages a device's config, peplink-mcp prefers the cloud
path. Config-write precedence is **ic2 → gateway → device**: a write to an InControl-managed
domain (SSID, VLAN, WAN priority, firewall, …) is routed to the `peplink_ic2_*` tools by
default. A device write tool can break the glass with `override="gateway"` or
`override="device"`. Per-device `config_authority: device | ic2 | auto` pins the default plane.

See [`quickstart.md`](quickstart.md) for setup and the policy/confirm gates on writes.
