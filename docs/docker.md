# Running peplink-device-mcp in Docker

The container runs the **HTTP transport** (stdio is for a local agent; a container exposes
the MCP over the network). The HTTP server **fails closed** — it refuses to start without at
least one MCP API key — and serves a public `/health` endpoint for liveness checks.

## 1. Provide config + secrets (not baked into the image)

Create a host dir with your real files; it's mounted read-only at `/config`:

```bash
mkdir -p docker/config
cp examples/config/config.yaml   docker/config/config.yaml      # edit to your fleet
cp examples/config/secrets.yaml.example docker/config/secrets.yaml   # fill in — never commit
```

`docker/config/` is gitignored. `secrets.yaml` **must** include an `mcp_keys` entry plus its
secret (the HTTP transport requires it):

```bash
uv run peplink-device-mcp keys generate --id docker-ops --tier admin
# paste the printed mcp_keys block into config.yaml and the secret into secrets.yaml
```

## 2. Build & run

```bash
docker compose -f docker/docker-compose.yml up --build
# or, image only (build context = repo root):
docker build -f apps/device/Dockerfile -t peplink-device-mcp .
```

The default command is `serve --transport http --host 0.0.0.0 --port 8080`. Verify:

```bash
curl http://localhost:8080/health
# {"status":"ok","devices":N,"mcp_keys":M,"access_mode":"..."}
```

## 3. Connect an MCP client

Point your client at the streamable-HTTP endpoint with the bearer key:

```
URL:    http://<host>:8080/mcp
Header: Authorization: Bearer <your mcp key secret>
```

## 4. Networking — cloud vs LAN

- **InControl 2 (cloud) only:** the default **bridge** network is fine (outbound HTTPS to
  `api.ic.peplink.com`).
- **LAN-direct devices:** the container must reach your devices. On Linux use **host
  networking** (drop the `ports:` mapping):
  ```yaml
  network_mode: host
  ```
  On Docker Desktop (macOS/Windows) host networking is limited — reach devices by routable IP,
  or run LAN-direct mode outside Docker.

> **Startup dependency:** the server resolves `discover:`-based (gateway-managed) devices at
> boot, so the gateway must be reachable with valid credentials when the container starts —
> otherwise startup fails (and `restart: unless-stopped` will loop). Devices with a static
> `host:` or that are **InControl 2-only** have no such boot-time dependency.

## 5. Enabling writes

Write/config/command tools are triple-gated (admin key + `confirm=true` + a policy env flag,
default-deny). Allow only what you need via `environment:` in compose, e.g.:

```yaml
environment:
  PEPLINK_POLICY_ALLOW_IC2_CONFIG_WRITE: "1"
  PEPLINK_POLICY_ALLOW_IC2_REBOOT: "1"
```

## 6. TLS

The app serves plain HTTP. For network exposure, front it with a reverse proxy
(Caddy/nginx/Traefik) terminating TLS and forwarding to `:8080`.

## One-off commands

The entrypoint is the CLI, so any subcommand works against the mounted config:

```bash
docker run --rm -v "$PWD/docker/config:/config:ro" peplink-device-mcp ic2-doctor
docker run --rm -v "$PWD/docker/config:/config:ro" peplink-device-mcp ic2-sync
docker run --rm -v "$PWD/docker/config:/config:ro" peplink-device-mcp validate
```

## Image notes

- Multi-stage uv build; both stages use `python:3.12-slim-bookworm` so the resolved `.venv` is
  portable. Runs as a non-root user (`uid 10001`).
- `uv.lock` is honored (`--frozen`); rebuild after dependency changes.
- The manifest YAMLs the server reads are included in the image; secrets never are
  (see `.dockerignore`).

### podman

Works with podman (`podman build -f apps/device/Dockerfile -t peplink-device-mcp .`,
`podman run`/`podman compose`). podman builds **OCI** images, which ignore the `HEALTHCHECK`
directive — use `podman build --format docker …` to honor it, or rely on the compose
`healthcheck:` (which works either way). To use a `secrets.conf` instead of YAML, clear the
YAML env and point at the file:

```bash
podman run --rm -v /path/to/secrets.conf:/config/secrets.conf:ro \
  -e PEPLINK_MCP_CONFIG= -e PEPLINK_MCP_SECRETS= -e PEPLINK_SECRETS_CONF=/config/secrets.conf \
  peplink-device-mcp ic2-doctor
```
