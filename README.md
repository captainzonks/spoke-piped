# spoke-piped

<!--
==============================================================================
README.md - spoke-piped module documentation
==============================================================================
Description: Piped (privacy-friendly YouTube frontend) Spoke module
Author: Matt Barham
Created: 2026-04-25
Modified: 2026-04-26
Version: 1.2.0
==============================================================================
Document Type: Reference
Audience: Developer
Status: Final
==============================================================================
-->

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/E1E21U3S1R)

Spoke module for [Piped](https://github.com/TeamPiped/Piped-Backend) — a
privacy-friendly alternative to YouTube. Hosts an instance suitable for
[LibreTube](https://libretube.dev/), [Piped Web](https://github.com/TeamPiped/Piped),
and other compatible frontends.

## Services

| Service           | Description                                | Port  | Network |
|-------------------|--------------------------------------------|-------|---------|
| `piped-postgres`  | Module-local Postgres for Piped            | 5432  | troxy   |
| `piped-backend`   | Piped API (Java/Hibernate)                 | 8080  | troxy   |
| `piped-frontend`  | Piped web UI (static SPA)                  | 80    | troxy   |
| `piped-proxy`     | YouTube media segment proxy (Rust)         | 8080  | troxy   |
| `piped-bg-helper` | PoToken provider for backend               | 8080  | troxy   |
| `piped-resolver`  | yt-dlp adaptive resolver (serves /streams) | 8000  | troxy   |
| `piped-bgutil`    | bgutil POT provider for the resolver       | 4416  | troxy   |

This module ships its own Postgres so it remains standalone. It does not
depend on the hub Postgres.

### Adaptive resolver (`piped-resolver`)

YouTube's po_token/SABR gate causes the upstream Piped backend to return only a
360p muxed stream (no adaptive 1080p/4K, empty `audioStreams`). `piped-resolver`
is a small FastAPI service (yt-dlp + a bgutil POT provider) that re-implements
the Piped `/streams/{id}` and `/search` endpoints and returns the full adaptive
set. It is built locally from [`resolver/`](resolver/).

Only the **`/streams`** path on the API host is routed to the resolver (Traefik
router `piped-api-streams`, priority 200); every other API path stays on
`piped-backend`. The web frontend therefore keeps working (channels, playlists,
comments) *and* gains adaptive playback. Clients need no change — they keep
their existing Piped API URL.

`piped-bgutil` is internal-only and must never be exposed (it mints tokens with
no auth). `yt-dlp`, the bgutil plugin, and the provider image move fast — bump
`resolver/requirements.txt` and `PIPED_BGUTIL_IMAGE` together when extraction
breaks.

## Routing

Three Traefik subdomains are exposed on `${DOMAIN}`. The subdomain prefix
for each is templated and overridable per site (e.g. rebrand to
`tube/tubeapi/tubeproxy` from `modules.yml` env_overrides):

| Host                                          | Target          | Default prefix | Purpose             |
|-----------------------------------------------|-----------------|----------------|---------------------|
| `${PIPED_FRONTEND_SUBDOMAIN}.${DOMAIN}`       | piped-frontend  | `piped`        | Web UI              |
| `${PIPED_API_SUBDOMAIN}.${DOMAIN}`            | piped-backend   | `pipedapi`     | API for clients     |
| `${PIPED_API_SUBDOMAIN}.${DOMAIN}/streams`    | piped-resolver  | `pipedapi`     | Adaptive streams     |
| `${PIPED_PROXY_SUBDOMAIN}.${DOMAIN}`          | piped-proxy     | `pipedproxy`   | Video segment proxy |

`piped-bg-helper` and `piped-bgutil` are internal-only. The `/streams` path on
the API host is split off to `piped-resolver` (router priority 200); all other
API paths stay on `piped-backend`.

> **Note:** Subdomain templating requires Spoke's `deploy_traefik_rules.sh`
> at version 1.3.0 or later (envsubst on rule YAMLs at deploy time).

## Prerequisites

- Spoke hub deployed with `troxy` network
- Traefik available as a hub service
- Three DNS records (or one wildcard) pointing to the host:
  - `${PIPED_FRONTEND_SUBDOMAIN}.${DOMAIN}` (default `piped.${DOMAIN}`)
  - `${PIPED_API_SUBDOMAIN}.${DOMAIN}` (default `pipedapi.${DOMAIN}`)
  - `${PIPED_PROXY_SUBDOMAIN}.${DOMAIN}` (default `pipedproxy.${DOMAIN}`)

## Quick Start

```bash
# 1. Generate the postgres password and ytproxy hash secret
mkdir -p ${SECRETS_DIR}/piped
openssl rand -base64 32 > ${SECRETS_DIR}/piped/piped_postgres_password
openssl rand -hex 32      > ${SECRETS_DIR}/piped/piped_proxy_hash_secret
chmod 600 ${SECRETS_DIR}/piped/*

# 2. Stage the backend config
mkdir -p ${PIPED_DIR}/config ${PIPED_DIR}/postgres
cp config/config.properties.example ${PIPED_DIR}/config/config.properties
chmod 600 ${PIPED_DIR}/config/config.properties
# Edit ${PIPED_DIR}/config/config.properties:
#  - replace example.org with your DOMAIN
#  - set hibernate.connection.password to match piped_postgres_password

# 3. Deploy via Spoke
make deploy MODULE=piped
```

## Module Environment Variables

| Variable                  | Default                                  | Description                          |
|---------------------------|------------------------------------------|--------------------------------------|
| `PIPED_IMAGE`             | `1337kavin/piped:azul-zulu`              | Backend image                        |
| `PIPED_FRONTEND_IMAGE`    | `1337kavin/piped-frontend:latest`        | Frontend image                       |
| `PIPED_PROXY_IMAGE`       | `1337kavin/piped-proxy:latest`           | ytproxy image                        |
| `PIPED_BG_HELPER_IMAGE`   | `1337kavin/bg-helper-server:latest`      | bg-helper image                      |
| `PIPED_RESOLVER_IMAGE`    | `spoke-piped-resolver:local`             | Resolver image (built from resolver/)|
| `PIPED_BGUTIL_IMAGE`      | `brainicism/bgutil-ytdlp-pot-provider:1.3.1` | bgutil POT provider image        |
| `PIPED_POSTGRES_IMAGE`    | `pgautoupgrade/pgautoupgrade:18-alpine`  | Module-local Postgres image          |
| `PIPED_FRONTEND_IP`       | `192.168.35.26`                          | Frontend static IP on troxy          |
| `PIPED_BACKEND_IP`        | `192.168.35.27`                          | Backend static IP on troxy           |
| `PIPED_PROXY_IP`          | `192.168.35.28`                          | ytproxy static IP on troxy           |
| `PIPED_BG_HELPER_IP`      | `192.168.35.29`                          | bg-helper static IP on troxy         |
| `PIPED_POSTGRES_IP`       | `192.168.35.30`                          | Postgres static IP on troxy          |
| `PIPED_RESOLVER_IP`       | `192.168.35.31`                          | Resolver static IP on troxy          |
| `PIPED_BGUTIL_IP`         | `192.168.35.32`                          | bgutil static IP on troxy            |
| `PIPED_RESOLVER_PLAYER_CLIENTS` | _(empty)_                          | yt-dlp innertube clients to pin      |
| `PIPED_RESOLVER_PROXY_URL`| _(empty)_                                | Public ytproxy URL echoed as proxyUrl|
| `PIPED_RESOLVER_CACHE_TTL`| `3600`                                   | /streams cache TTL (seconds)         |
| `PIPED_RESOLVER_SEARCH_LIMIT` | `20`                                 | ytsearch result count                |
| `PIPED_RESOLVER_ALLOWED_ORIGINS` | `*`                               | CORS allow-list                      |
| `PIPED_FRONTEND_SUBDOMAIN`| `piped`                                  | Frontend subdomain prefix            |
| `PIPED_API_SUBDOMAIN`     | `pipedapi`                               | API subdomain prefix                 |
| `PIPED_PROXY_SUBDOMAIN`   | `pipedproxy`                             | ytproxy subdomain prefix             |
| `PIPED_POSTGRES_DB`       | `piped`                                  | Postgres database name               |
| `PIPED_POSTGRES_USER`     | `piped`                                  | Postgres role                        |
| `PIPED_DIR`               | `${APPDATA_DIR}/piped`                   | Persistent data root                 |

## Secrets

Mapped via `modules.yml` `secrets_map`:

| Secret name                | File path under `${SECRETS_DIR}` | Purpose                            |
|----------------------------|----------------------------------|------------------------------------|
| `piped_postgres_password`  | `piped/piped_postgres_password`  | Postgres password (DB + Hibernate) |
| `piped_proxy_hash_secret`  | `piped/piped_proxy_hash_secret`  | Shared URL-signing secret          |

## Notes

- Upstream tags `latest` for frontend, proxy, and bg-helper. Pin via image
  digest in `modules.yml` env_overrides for reproducible deploys.
- The hibernate password lives inside `config.properties` (read by the JVM at
  startup) and must be kept in sync with `${SECRETS_DIR}/piped/piped_postgres_password`.
- `BG_HELPER_URL` is commented out in the example config. Uncomment to wire
  the backend to the in-stack `piped-bg-helper`.
- The `BACKEND_HOSTNAME` env var on `piped-frontend` is read once at
  container creation by the upstream entrypoint script, which `sed`s the
  hostname into the static JS bundle. After changing
  `PIPED_API_SUBDOMAIN`, the frontend container must be **recreated**, not
  just restarted (`docker compose up -d --force-recreate piped-frontend`,
  or `make rebuild MODULE=piped SERVICE=piped-frontend`). A plain restart
  preserves the original creation-time env and serves a stale bundle.

## References

- [Piped-Backend](https://github.com/TeamPiped/Piped-Backend)
- [Piped (frontend)](https://github.com/TeamPiped/Piped)
- [piped-proxy](https://github.com/TeamPiped/piped-proxy)
- [Piped-Docker (upstream compose)](https://github.com/TeamPiped/Piped-Docker)
- [LibreTube](https://libretube.dev/)
