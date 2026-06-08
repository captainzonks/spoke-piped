"""yt-dlp extraction wrapper.

Builds yt-dlp options from `Config` (including the bgutil POT provider wiring)
and exposes blocking `extract_streams` / `extract_search` helpers. Callers run
these in a worker thread — `YoutubeDL` is synchronous and blocking.
"""

from __future__ import annotations

import re
from typing import Any

from yt_dlp import YoutubeDL

from .config import Config
from .mapping import _is_skippable, map_search_response, map_streams_response
from .ranges import attach_segment_ranges

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class ExtractionError(RuntimeError):
    """Raised when extraction yields no usable adaptive formats."""


def is_valid_video_id(video_id: str) -> bool:
    return bool(_VIDEO_ID_RE.match(video_id))


def _base_opts(config: Config) -> dict[str, Any]:
    extractor_args: dict[str, Any] = {
        # bgutil HTTP POT provider — the plugin reads this and fetches
        # po_tokens automatically.
        "youtubepot-bgutilhttp": {"base_url": [config.bgutil_base_url]},
    }
    # Only pin innertube clients when explicitly configured. Left unset (the
    # default), yt-dlp picks the client set that still returns direct stream
    # URLs. Forcing web/web_safari yields SABR-only formats with no URLs
    # (yt-dlp#12482) — i.e. nothing playable.
    if config.player_clients:
        extractor_args["youtube"] = {"player_client": list(config.player_clients)}

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        # YouTube signatures (sig/nsig) require yt-dlp's EJS challenge solver
        # script in addition to a JS runtime (deno). Without it, signed
        # adaptive formats are dropped ("Requested format is not available").
        # Downloaded from GitHub on first use and cached.
        "remote_components": ["ejs:github"],
        "extractor_args": extractor_args,
    }
    if config.proxy:
        opts["proxy"] = config.proxy
    return opts


def extract_streams(config: Config, video_id: str) -> dict[str, Any]:
    """Extract a single video and map it to the Piped ``/streams`` schema."""
    with YoutubeDL(_base_opts(config)) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
    # Probe DASH byte ranges for the adaptive formats we will emit, so the
    # Piped frontend can build a working SegmentBase (yt-dlp drops these).
    # Only needed when serving a frontend (PROXY_URL set); native clients
    # ignore the ranges, so skip the extra round-trips for generic deploys.
    if config.proxy_url:
        adaptive = [
            f
            for f in info.get("formats", [])
            if not _is_skippable(f)
            and (f.get("vcodec", "none") != "none")
            != (f.get("acodec", "none") != "none")
        ]
        attach_segment_ranges(adaptive)
    response = map_streams_response(
        info, proxy_url=config.proxy_url, secret=config.proxy_hash_secret
    )
    if not response["videoStreams"] and not response["audioStreams"]:
        raise ExtractionError(
            "no adaptive formats returned — po_token or extractor failure"
        )
    return response


def extract_search(config: Config, query: str) -> dict[str, Any]:
    """Run a flat ``ytsearch`` and map it to the Piped ``/search`` schema."""
    opts = {**_base_opts(config), "extract_flat": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(
            f"ytsearch{config.search_limit}:{query}", download=False
        )
    return map_search_response(info)
