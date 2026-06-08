"""FastAPI application exposing the Piped-compatible resolver endpoints."""

from __future__ import annotations

import asyncio
import time

from cachetools import TTLCache
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import Config
from .extractor import (
    ExtractionError,
    extract_search,
    extract_streams,
    is_valid_video_id,
)

config = Config.from_env()

app = FastAPI(title="piped-resolver", version=__version__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.allowed_origins),
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Per-process result cache. Keyed by video id; entries expire before the
# googlevideo URLs they contain do (see Config.cache_ttl).
_streams_cache: TTLCache[str, dict] = TTLCache(
    maxsize=config.cache_maxsize, ttl=config.cache_ttl
)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Gate every non-health endpoint when API_KEY is configured."""
    if config.api_key and x_api_key != config.api_key:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


@app.get("/healthcheck")
async def healthcheck() -> dict[str, object]:
    return {"ok": True, "version": __version__, "ts": int(time.time())}


@app.get("/streams/{video_id}", dependencies=[Depends(require_api_key)])
async def streams(video_id: str) -> dict:
    if not is_valid_video_id(video_id):
        raise HTTPException(status_code=422, detail="invalid YouTube video id")

    cached = _streams_cache.get(video_id)
    if cached is not None:
        return cached

    try:
        data = await asyncio.to_thread(extract_streams, config, video_id)
    except ExtractionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface extractor faults as 502
        raise HTTPException(status_code=502, detail=f"extraction failed: {exc}") from exc

    # Don't cache an incomplete result (some adaptive streams failed range
    # probing); let the next request retry so playback isn't degraded for the
    # whole TTL.
    partial = data.pop("_partial", False)
    if not partial:
        _streams_cache[video_id] = data
    return data


@app.get("/search", dependencies=[Depends(require_api_key)])
async def search(
    q: str = Query(min_length=1),
    filter: str = Query(default="videos"),  # noqa: A002 — Piped wire name
) -> dict:
    try:
        return await asyncio.to_thread(extract_search, config, q)
    except Exception as exc:  # noqa: BLE001 — surface extractor faults as 502
        raise HTTPException(status_code=502, detail=f"search failed: {exc}") from exc
