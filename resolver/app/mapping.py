"""Pure mapping from yt-dlp info dicts to the Piped API JSON schema.

These functions are deliberately side-effect-free and network-free so they can
be unit-tested against saved fixtures. Each returns new dicts (no mutation of
the yt-dlp input).

Field names mirror Piped exactly because two distinct consumers parse this
schema unchanged:

  * The Piped web frontend reads the full ``/streams`` ``StreamInfo`` object
    (uploader/relatedStreams/chapters/subtitles/etc.), so those keys are always
    present (real values where yt-dlp provides them, safe defaults otherwise).
  * Lightweight clients (native players / ffmpeg muxers) read only
    ``videoStreams`` + ``audioStreams``; the H.264-mp4 + M4A pair MUST be
    present for >360p muxing, and ``codec`` must carry the real vcodec/acodec
    so codec-ranking players (VP9/AV1) can choose.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlsplit, urlunsplit

# yt-dlp protocols that are not progressive HTTP ranges. Native players and
# ffmpeg both play the direct googlevideo ranges more reliably than these.
_SKIP_PROTOCOLS = ("m3u8", "m3u8_native", "http_dash_segments", "dash")


def _proxy_stream_url(url: str, proxy_url: str) -> str:
    """Rewrite a raw googlevideo URL through a Piped media proxy.

    Matches Piped-Backend's ``rewriteURL`` scheme so the Piped web frontend and
    piped-proxy can serve the stream without browser CORS errors:
    ``{proxy}{path}?{original_query}&host={original_host}``.

    When ``proxy_url`` is empty the raw URL is returned unchanged — native
    players (ExoPlayer/ffmpeg) can fetch googlevideo directly.
    """
    if not proxy_url or not url:
        return url
    src = urlsplit(url)
    if not src.netloc:
        return url
    sep = "&" if src.query else ""
    query = f"{src.query}{sep}host={src.netloc}"
    proxy = urlsplit(proxy_url)
    return urlunsplit((proxy.scheme, proxy.netloc, src.path, query, ""))


def _is_skippable(fmt: dict[str, Any]) -> bool:
    if not fmt.get("url"):
        return True
    proto = fmt.get("protocol", "") or ""
    if proto.startswith(_SKIP_PROTOCOLS):
        return True
    note = (fmt.get("format_note") or "").lower()
    return "storyboard" in note


def _video_format(ext: str) -> str:
    return "MPEG_4" if ext == "mp4" else "WEBM"


def _audio_format(ext: str) -> str:
    return "M4A" if ext in ("m4a", "mp4") else "WEBM"


def _itag(format_id: str) -> int | None:
    head = format_id.split("-", 1)[0]
    return int(head) if head.isdigit() else None


def _track_type(fmt: dict[str, Any]) -> str | None:
    """Best-effort YouTube audio-track classification.

    Mirrors Piped's ORIGINAL/DUBBED/DESCRIPTIVE values so original-track
    preference keeps working. Falls back to language_preference when yt-dlp does
    not annotate the note.
    """
    note = (fmt.get("format_note") or "").lower()
    if "original" in note:
        return "ORIGINAL"
    if "descri" in note:
        return "DESCRIPTIVE"
    if "dub" in note:
        return "DUBBED"
    pref = fmt.get("language_preference")
    if isinstance(pref, int) and pref > 0:
        return "ORIGINAL"
    return None


def _bitrate_bps(fmt: dict[str, Any], *keys: str) -> int:
    for key in keys:
        val = fmt.get(key)
        if val:
            return int(float(val) * 1000)
    return 0


def _largest_thumbnail(info: dict[str, Any]) -> str:
    thumbnails = info.get("thumbnails") or []
    if thumbnails:
        # yt-dlp orders thumbnails worst→best; the last is the largest.
        return thumbnails[-1].get("url", "") or (info.get("thumbnail") or "")
    return info.get("thumbnail") or ""


def _iso_date(yyyymmdd: str | None) -> str:
    if yyyymmdd and len(yyyymmdd) == 8 and yyyymmdd.isdigit():
        return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"
    return ""


def _uploaded_ms(info: dict[str, Any]) -> int:
    ts = info.get("timestamp")
    if isinstance(ts, (int, float)) and ts > 0:
        return int(ts) * 1000
    return 0


def _map_chapters(info: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ch in info.get("chapters") or []:
        if not ch:
            continue
        out.append(
            {
                "title": ch.get("title", "") or "",
                "image": "",
                "start": int(ch.get("start_time") or 0),
            }
        )
    return out


def _content_length(fmt: dict[str, Any]) -> int:
    val = fmt.get("filesize") or fmt.get("filesize_approx")
    if val:
        return int(val)
    # Fall back to the googlevideo `clen` query param.
    clen = parse_qs(urlsplit(fmt.get("url", "") or "").query).get("clen")
    return int(clen[0]) if clen and clen[0].isdigit() else 0


def _segment_ranges(fmt: dict[str, Any]) -> dict[str, int]:
    """DASH SegmentBase byte ranges (probed in ranges.py), or -1 sentinels.

    Piped uses -1 to mean "unknown"; the frontend only builds a SegmentBase
    when the values are present and non-negative.
    """
    rng = fmt.get("_segment_range")
    if rng:
        return rng
    return {"initStart": -1, "initEnd": -1, "indexStart": -1, "indexEnd": -1}


def map_video_stream(fmt: dict[str, Any], proxy_url: str = "") -> dict[str, Any]:
    ext = fmt.get("ext", "") or ""
    height = int(fmt.get("height") or 0)
    return {
        "url": _proxy_stream_url(fmt["url"], proxy_url),
        "mimeType": f"video/{'mp4' if ext == 'mp4' else 'webm'}",
        "format": _video_format(ext),
        "codec": fmt.get("vcodec"),
        "quality": f"{height}p" if height else "",
        "height": height,
        "width": int(fmt.get("width") or 0),
        "fps": int(fmt.get("fps") or 0),
        "bitrate": _bitrate_bps(fmt, "tbr", "vbr"),
        "videoOnly": True,
        "itag": _itag(fmt.get("format_id", "")),
        "contentLength": _content_length(fmt),
        **_segment_ranges(fmt),
    }


def map_audio_stream(fmt: dict[str, Any], proxy_url: str = "") -> dict[str, Any]:
    ext = fmt.get("ext", "") or ""
    abr = int(float(fmt.get("abr") or 0))
    return {
        "url": _proxy_stream_url(fmt["url"], proxy_url),
        "mimeType": f"audio/{'mp4' if ext in ('m4a', 'mp4') else 'webm'}",
        "format": _audio_format(ext),
        "codec": fmt.get("acodec"),
        "quality": f"{abr}kbps" if abr else "",
        "bitrate": _bitrate_bps(fmt, "abr", "tbr"),
        "videoOnly": False,
        "itag": _itag(fmt.get("format_id", "")),
        "audioTrackType": _track_type(fmt),
        "audioTrackLocale": fmt.get("language"),
        "contentLength": _content_length(fmt),
        **_segment_ranges(fmt),
    }


def map_streams_response(
    info: dict[str, Any], proxy_url: str = ""
) -> dict[str, Any]:
    """Map a yt-dlp video info dict to a full Piped ``/streams`` response.

    Returns the complete Piped ``StreamInfo`` shape so the Piped web frontend
    renders correctly; absent yt-dlp data is filled with safe empty defaults
    (e.g. ``relatedStreams``/``subtitles``/``previewFrames`` are empty lists —
    the frontend tolerates these). Lightweight clients ignore the extra fields.
    """
    videos: list[dict[str, Any]] = []
    audios: list[dict[str, Any]] = []
    dropped = 0

    for fmt in info.get("formats", []):
        if _is_skippable(fmt):
            continue
        vcodec = fmt.get("vcodec", "none")
        acodec = fmt.get("acodec", "none")
        video_only = vcodec != "none" and acodec == "none"
        audio_only = acodec != "none" and vcodec == "none"
        is_candidate = (video_only and fmt.get("height")) or audio_only
        if not is_candidate:
            # muxed (both codecs) and codec-less formats are intentionally
            # dropped: clients want adaptive video-only + audio-only pairs.
            continue
        # When serving a Piped frontend (proxy_url set) the client builds a DASH
        # SegmentBase per stream, so a stream whose byte ranges could not be
        # probed would produce an invalid manifest (shaka 4002). Drop those;
        # native clients (no proxy_url) keep every stream regardless.
        if proxy_url and "_segment_range" not in fmt:
            dropped += 1
            continue
        if video_only:
            videos.append(map_video_stream(fmt, proxy_url))
        else:
            audios.append(map_audio_stream(fmt, proxy_url))

    response = {
        "title": info.get("title", "") or "",
        "description": info.get("description", "") or "",
        "uploadDate": _iso_date(info.get("upload_date")),
        "uploaded": _uploaded_ms(info),
        "uploader": info.get("uploader") or info.get("channel") or "",
        "uploaderUrl": info.get("uploader_url") or info.get("channel_url") or "",
        "uploaderAvatar": "",
        "uploaderVerified": False,
        "uploaderSubscriberCount": int(info.get("channel_follower_count") or 0),
        "category": (info.get("categories") or [""])[0] or "",
        "license": "",
        "visibility": "public",
        "tags": list(info.get("tags") or []),
        "metaInfo": [],
        "thumbnailUrl": _largest_thumbnail(info),
        "duration": int(info.get("duration") or 0),
        "views": int(info.get("view_count") or 0),
        "likes": int(info.get("like_count") or 0),
        "dislikes": -1,
        "hls": None,
        "dash": None,
        "lbryId": None,
        "livestream": bool(info.get("is_live")),
        "proxyUrl": proxy_url,
        "videoStreams": videos,
        "audioStreams": audios,
        "relatedStreams": [],
        "subtitles": [],
        "chapters": _map_chapters(info),
        "previewFrames": [],
    }
    if dropped:
        # Internal marker (popped before serialization): some adaptive streams
        # failed range-probing, so this result is incomplete and must not be
        # cached — the next request retries and should recover them.
        response["_partial"] = True
    return response


def map_search_response(info: dict[str, Any]) -> dict[str, Any]:
    """Map a yt-dlp ``ytsearch`` result to a Piped ``/search`` response."""
    items = []
    for entry in info.get("entries", []) or []:
        if not entry or not entry.get("id"):
            continue
        thumbnails = entry.get("thumbnails") or []
        thumbnail = thumbnails[-1].get("url", "") if thumbnails else (
            entry.get("thumbnail") or ""
        )
        items.append(
            {
                "type": "stream",
                "url": f"/watch?v={entry['id']}",
                "title": entry.get("title", "") or "",
                "uploaderName": entry.get("uploader") or entry.get("channel") or "",
                "uploaderUrl": entry.get("uploader_url")
                or entry.get("channel_url")
                or "",
                "duration": int(entry.get("duration") or 0),
                "thumbnail": thumbnail,
            }
        )
    return {"items": items, "nextpage": None, "suggestion": None, "corrected": False}
