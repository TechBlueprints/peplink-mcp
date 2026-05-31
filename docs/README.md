# peplink-mcp documentation

| Document | Purpose |
|----------|---------|
| [`quickstart.md`](quickstart.md) | **Start here** — install, config model, credentials, InControl 2, verify, connect a client |
| [`docker.md`](docker.md) | **Run in Docker** — image build, HTTP transport, config/secrets mount, networking, TLS |
| [`device-types.md`](device-types.md) | **Device type reference** — `router`, **`fusionhub`**, `switch`, `ap`: auth, discovery, fleet config, MCP behavior |
| [`fusionhub-api.md`](fusionhub-api.md) | **FusionHub-only** live REST endpoint matrix (supplement to `kind: fusionhub` in device-types) |

New here? Run `uv run peplink-device-mcp setup` or follow **quickstart.md**. Then use
**device-types.md** for per-kind details and **fusionhub-api.md** for SpeedFusion hub automation.
