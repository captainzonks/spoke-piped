"""Runtime configuration, loaded once from the environment.

All settings are generic (no deployment-specific defaults) so the image is
shareable. Override via environment variables — see the module `.env.example`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _split_csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Config:
    """Immutable application configuration."""

    host: str
    port: int
    # bgutil POT provider base URL (the HTTP server, default port 4416).
    bgutil_base_url: str
    # yt-dlp innertube clients to try, in order. Empty = let yt-dlp choose its
    # default set (recommended — it picks clients that return direct stream
    # URLs; forcing web/web_safari gives SABR-only formats with no URLs).
    player_clients: tuple[str, ...]
    # Optional outbound proxy for extraction (keep on a residential egress;
    # datacenter IPs get adaptive-stream blocked even with a po_token).
    proxy: str | None
    # Public Piped media-proxy base URL echoed back as `proxyUrl` so the Piped
    # web frontend can proxy thumbnails/streams. Empty = frontend uses direct
    # URLs. Set to the site's ytproxy host (e.g. https://tubeproxy.example.com).
    proxy_url: str
    # Shared secret for signing proxied stream URLs (piped-proxy `qhash`). When
    # the proxy enforces HASH_SECRET, unsigned URLs are rejected (403); this
    # must equal the proxy's secret. Empty = emit unsigned URLs (proxy must run
    # without HASH_SECRET).
    proxy_hash_secret: bytes
    # In-process result cache. googlevideo URLs carry an ~6h `expire`, so a
    # sub-expiry TTL keeps responses valid while cutting repeat extraction.
    cache_ttl: int
    cache_maxsize: int
    search_limit: int
    # Optional shared-secret gate. When set, every endpoint except
    # /healthcheck requires the `X-API-Key` header to match.
    api_key: str | None
    # CORS allow-list. "*" permits any origin (fine for a LAN-only deploy).
    allowed_origins: tuple[str, ...] = field(default=("*",))

    @staticmethod
    def _read_proxy_secret() -> bytes:
        path = os.getenv("PROXY_HASH_SECRET_FILE")
        if path and os.path.exists(path):
            with open(path, "rb") as fh:
                return fh.read().rstrip(b"\n")
        return (os.getenv("PROXY_HASH_SECRET", "") or "").encode()

    @staticmethod
    def from_env() -> "Config":
        return Config(
            host=os.getenv("RESOLVER_HOST", "0.0.0.0"),
            port=int(os.getenv("RESOLVER_PORT", "8000")),
            bgutil_base_url=os.getenv(
                "BGUTIL_BASE_URL", "http://piped-bgutil:4416"
            ).rstrip("/"),
            player_clients=_split_csv(os.getenv("YTDLP_PLAYER_CLIENTS", "")),
            proxy=os.getenv("RESOLVER_PROXY") or None,
            proxy_url=(os.getenv("PROXY_URL", "") or "").rstrip("/"),
            proxy_hash_secret=Config._read_proxy_secret(),
            cache_ttl=int(os.getenv("CACHE_TTL", "3600")),
            cache_maxsize=int(os.getenv("CACHE_MAXSIZE", "512")),
            search_limit=int(os.getenv("SEARCH_LIMIT", "20")),
            api_key=os.getenv("API_KEY") or None,
            allowed_origins=_split_csv(os.getenv("ALLOWED_ORIGINS", "*")) or ("*",),
        )
