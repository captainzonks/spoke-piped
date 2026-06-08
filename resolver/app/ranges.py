"""Compute DASH ``SegmentBase`` byte ranges for adaptive streams.

The Piped web frontend builds a DASH manifest client-side and needs each
stream's ``initStart/initEnd/indexStart/indexEnd`` (the init segment and the
index box). YouTube reports these in its player response, but yt-dlp strips
them from its format dicts — only ``contentLength`` (the ``clen`` URL param /
``filesize``) survives.

We recover them by reading the container header over HTTP ``Range`` requests:

  * **mp4** (`ftyp`/`moov`/`sidx` boxes): the index is the ``sidx`` box; the
    init segment is everything before it.
  * **webm** (Matroska/EBML): the index is the ``Cues`` element; the init
    segment is everything before it.

YouTube front-loads the index for DASH-ready streams, so only a handful of
small range reads per stream are needed. Results are pure data; the network
I/O is confined here and to the caller's worker thread.
"""

from __future__ import annotations

import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

# A small read budget guards against a missing/relocated index (e.g. webm with
# Cues at the tail): we walk container headers, never whole boxes, and bail out
# rather than scanning a multi-GB file.
_MAX_WALK_BYTES = 4 * 1024 * 1024
_HEADER_READ = 32
_PROBE_TIMEOUT = 10
_MAX_WORKERS = 8

_MP4_SIDX = b"sidx"
_EBML_ID = 0x1A45DFA3
_SEGMENT_ID = 0x18538067
_CUES_ID = 0x1C53BB6B
_CLUSTER_ID = 0x1F43B675


class _RangeReader:
    """Lazily reads byte ranges of a remote URL via HTTP ``Range`` GETs."""

    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self._url = url
        self._headers = headers

    def read(self, start: int, length: int) -> bytes:
        end = start + length - 1
        req = urllib.request.Request(self._url, headers=self._headers)
        req.add_header("Range", f"bytes={start}-{end}")
        with urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT) as resp:
            return resp.read()


def _mp4_index(reader: _RangeReader) -> tuple[int, int] | None:
    """Return (indexStart, indexSize) for the ``sidx`` box, or None."""
    pos = 0
    while pos < _MAX_WALK_BYTES:
        hdr = reader.read(pos, _HEADER_READ)
        if len(hdr) < 8:
            return None
        size = int.from_bytes(hdr[0:4], "big")
        box_type = hdr[4:8]
        if size == 1:  # 64-bit largesize
            if len(hdr) < 16:
                return None
            size = int.from_bytes(hdr[8:16], "big")
        if size <= 0:
            return None
        if box_type == _MP4_SIDX:
            return pos, size
        pos += size
    return None


def _read_vint(buf: bytes, offset: int, keep_marker: bool) -> tuple[int, int]:
    """Parse an EBML variable-length integer. Returns (value, byte_length)."""
    first = buf[offset]
    mask = 0x80
    length = 1
    while length <= 8 and not (first & mask):
        mask >>= 1
        length += 1
    if length > 8:
        raise ValueError("invalid EBML vint")
    value = first if keep_marker else (first & (mask - 1))
    for i in range(1, length):
        value = (value << 8) | buf[offset + i]
    return value, length


def _ebml_index(reader: _RangeReader) -> tuple[int, int] | None:
    """Return (indexStart, indexSize) for the webm ``Cues`` element, or None."""
    # Skip the top-level EBML header, descend into Segment, then walk Segment's
    # children looking for Cues before the first Cluster.
    pos = 0
    seg_children_start: int | None = None
    while pos < _MAX_WALK_BYTES:
        buf = reader.read(pos, _HEADER_READ)
        if len(buf) < 4:
            return None
        try:
            elem_id, id_len = _read_vint(buf, 0, keep_marker=True)
            size, size_len = _read_vint(buf, id_len, keep_marker=False)
        except (ValueError, IndexError):
            return None
        header_len = id_len + size_len
        content_start = pos + header_len
        if elem_id == _SEGMENT_ID:
            # Descend: walk Segment's children, do not skip its body.
            seg_children_start = content_start
            pos = content_start
            continue
        if seg_children_start is not None:
            if elem_id == _CUES_ID:
                return pos, header_len + size
            if elem_id == _CLUSTER_ID:
                # Cues should precede Clusters in DASH webm; give up if not.
                return None
        pos = content_start + size
    return None


def _probe_one(fmt: dict[str, Any]) -> dict[str, int] | None:
    url = fmt.get("url")
    if not url:
        return None
    headers = {str(k): str(v) for k, v in (fmt.get("http_headers") or {}).items()}
    headers.setdefault("User-Agent", "Mozilla/5.0")
    reader = _RangeReader(url, headers)
    ext = (fmt.get("ext") or "").lower()
    container = (fmt.get("container") or "").lower()
    is_webm = "webm" in ext or "webm" in container
    # Retry: a transient range-read failure should not silently drop an
    # otherwise-good stream from the manifest (which would also poison the
    # cache for the whole TTL).
    for _ in range(3):
        try:
            found = _ebml_index(reader) if is_webm else _mp4_index(reader)
        except OSError:
            found = None
        if found:
            index_start, index_size = found
            if index_start > 0:
                return {
                    "initStart": 0,
                    "initEnd": index_start - 1,
                    "indexStart": index_start,
                    "indexEnd": index_start + index_size - 1,
                }
    return None


def attach_segment_ranges(formats: list[dict[str, Any]]) -> None:
    """Probe DASH byte ranges for each format, attaching ``_segment_range``.

    Mutates the yt-dlp format dicts in place (they are throwaway per request).
    Failures are silent: a format without ``_segment_range`` simply omits the
    range fields downstream.
    """
    targets = [f for f in formats if f.get("url")]
    if not targets:
        return
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        results = pool.map(_probe_one, targets)
        for fmt, rng in zip(targets, results):
            if rng:
                fmt["_segment_range"] = rng
