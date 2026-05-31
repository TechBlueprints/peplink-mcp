# peplink-mcp

> **Wildly experimental — use at your own risk.** This project is early, incomplete, and untested in production. **Review the code yourself** before running it against real hardware or networks. Admin-tier tools can change device configuration, disrupt connectivity, or cause outages. **Any damage, data loss, downtime, or misconfiguration resulting from use of this software is entirely your responsibility.** The authors and contributors accept no liability.

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io) server for interacting with Peplink devices and the Peplink InControl2 cloud management platform.

## Disclaimer

**Peplink** is a registered trademark of **Peplink International Ltd.** This project is an independent, community-driven effort and is **not affiliated with, endorsed by, sponsored by, or in any way officially connected with Peplink International Ltd.** or any of its subsidiaries or affiliates.

Use of the Peplink name is solely for descriptive purposes — to identify the devices and platform this software is designed to work with. All product names, trademarks, and registered trademarks are the property of their respective owners.

## Experimental status

- **No production guarantees.** APIs, tools, defaults, and behavior may change without notice.
- **Verify before you trust.** Do not point agents or automation at production gear until you have read the source and understand what each tool does.
- **Assume admin tools are dangerous.** Treat write/config/command endpoints like direct router admin access.
- **No warranty.** Software is provided **AS IS** under the Apache 2.0 license (see [LICENSE](LICENSE)); liability is disclaimed to the fullest extent permitted by law.

## Overview

`peplink-mcp` exposes Peplink device management and telemetry to AI assistants and other
MCP-compatible clients, two ways:

- **LAN-direct** — each device's native `/api/...` REST surface (routers, FusionHub, switches; APs via SNMP).
- **InControl 2 (cloud)** — fleet inventory/status and InControl-managed config (SSID, VLAN, WAN priority, firewall, reboot, …) via Peplink's cloud.

It's wildly experimental — see the warning at the top.

## Setup

**→ [`docs/quickstart.md`](docs/quickstart.md)** is the full walkthrough. The fastest path is the
guided wizard, which checks prerequisites, scaffolds config, tells you exactly which credentials
to create, and verifies each layer:

```bash
uv sync --all-packages
uv run peplink-device-mcp setup          # guided first-time setup
```

Useful commands (all also runnable by your connected agent):

```bash
uv run peplink-device-mcp validate                 # check config shape
uv run peplink-device-mcp doctor --device <id>     # live per-tier device auth probe
uv run peplink-device-mcp ic2-doctor               # live InControl 2 token grant + org list
uv run peplink-device-mcp ic2-sync                 # map fleet devices -> InControl 2 (serial + site)
uv run peplink-device-mcp serve --transport stdio  # run the MCP server
make test
```

### Fleet notes

Peplink **device types** — four kinds in fleet config:

| `kind` | Section |
|--------|---------|
| `router` | [`docs/device-types.md`](docs/device-types.md#routers-kind-router) |
| **`fusionhub`** | [`docs/device-types.md`](docs/device-types.md#fusionhub-kind-fusionhub) · [`docs/fusionhub-api.md`](docs/fusionhub-api.md) |
| `switch` | [`docs/device-types.md`](docs/device-types.md#switches-kind-switch) |
| `ap` | [`docs/device-types.md`](docs/device-types.md#ap-one-kind-ap) |

Example FusionHub entries: a static-host hub and a mesh-discovered hub in [`examples/config/config.yaml`](examples/config/config.yaml).

## License

This project is licensed under the [Apache License, Version 2.0](LICENSE).

```
Copyright 2026 TechBlueprints

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
```
