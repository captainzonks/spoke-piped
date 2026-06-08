"""Unit tests for the yt-dlp -> Piped schema mapping (network-free)."""

from __future__ import annotations

from app.mapping import map_search_response, map_streams_response


def _video_info() -> dict:
    """Minimal yt-dlp info dict covering the format kinds we care about."""
    return {
        "title": "Example 4K Video",
        "duration": 213,
        "upload_date": "20231231",
        "timestamp": 1703980800,
        "uploader": "Example Channel",
        "channel_url": "https://www.youtube.com/channel/abc",
        "view_count": 12345,
        "like_count": 678,
        "channel_follower_count": 90000,
        "categories": ["Music"],
        "tags": ["a", "b"],
        "chapters": [{"start_time": 0, "title": "Intro"}],
        "thumbnails": [{"url": "https://t/lo"}, {"url": "https://t/hi"}],
        "formats": [
            # H.264 mp4 video-only (itag 137) — required for ffmpeg mux pairs
            {
                "format_id": "137",
                "url": "https://gv/137",
                "ext": "mp4",
                "vcodec": "avc1.640028",
                "acodec": "none",
                "height": 1080,
                "width": 1920,
                "fps": 30,
                "tbr": 4000,
                "protocol": "https",
            },
            # AV1 webm video-only (itag 401) — preferred by codec-ranking players
            {
                "format_id": "401",
                "url": "https://gv/401",
                "ext": "webm",
                "vcodec": "av01.0.12M.08",
                "acodec": "none",
                "height": 2160,
                "width": 3840,
                "fps": 30,
                "tbr": 18000,
                "protocol": "https",
            },
            # M4A audio-only (itag 140) — required for ffmpeg mux pairs
            {
                "format_id": "140",
                "url": "https://gv/140",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "abr": 128,
                "language": "en",
                "language_preference": 10,
                "protocol": "https",
            },
            # Opus audio-only (itag 251)
            {
                "format_id": "251",
                "url": "https://gv/251",
                "ext": "webm",
                "vcodec": "none",
                "acodec": "opus",
                "abr": 160,
                "language": "en",
                "protocol": "https",
            },
            # Muxed 360p (itag 18) — should be dropped
            {
                "format_id": "18",
                "url": "https://gv/18",
                "ext": "mp4",
                "vcodec": "avc1.42001E",
                "acodec": "mp4a.40.2",
                "height": 360,
                "protocol": "https",
            },
            # HLS variant — should be skipped
            {
                "format_id": "hls-1080",
                "url": "https://gv/hls",
                "ext": "mp4",
                "vcodec": "avc1.640028",
                "acodec": "none",
                "height": 1080,
                "protocol": "m3u8_native",
            },
            # Storyboard — should be skipped
            {
                "format_id": "sb0",
                "url": "https://gv/sb",
                "ext": "mhtml",
                "vcodec": "none",
                "acodec": "none",
                "format_note": "storyboard",
                "protocol": "mhtml",
            },
        ],
    }


def test_streams_partitions_adaptive_only() -> None:
    resp = map_streams_response(_video_info())
    assert resp["title"] == "Example 4K Video"
    assert resp["duration"] == 213
    # muxed/hls/storyboard dropped: 2 video-only + 2 audio-only remain
    assert len(resp["videoStreams"]) == 2
    assert len(resp["audioStreams"]) == 2
    assert all(v["videoOnly"] for v in resp["videoStreams"])
    assert all(not a["videoOnly"] for a in resp["audioStreams"])


def test_mux_requires_mp4_h264_and_m4a_present() -> None:
    resp = map_streams_response(_video_info())
    mp4 = [v for v in resp["videoStreams"] if v["format"] == "MPEG_4"]
    m4a = [a for a in resp["audioStreams"] if a["format"] == "M4A"]
    assert mp4 and mp4[0]["mimeType"] == "video/mp4"
    assert mp4[0]["height"] == 1080
    assert mp4[0]["itag"] == 137
    assert m4a and m4a[0]["mimeType"] == "audio/mp4"
    assert m4a[0]["bitrate"] == 128_000


def test_codec_ranking_gets_av1_codec_and_height() -> None:
    resp = map_streams_response(_video_info())
    av1 = [v for v in resp["videoStreams"] if v["codec"].startswith("av01")]
    assert av1 and av1[0]["height"] == 2160
    assert av1[0]["format"] == "WEBM"
    assert av1[0]["quality"] == "2160p"


def test_audio_track_type_original_from_language_preference() -> None:
    resp = map_streams_response(_video_info())
    m4a = next(a for a in resp["audioStreams"] if a["format"] == "M4A")
    assert m4a["audioTrackType"] == "ORIGINAL"
    assert m4a["audioTrackLocale"] == "en"


def test_empty_formats_yields_empty_lists() -> None:
    resp = map_streams_response({"title": "x", "duration": 0, "formats": []})
    assert resp["videoStreams"] == []
    assert resp["audioStreams"] == []


def test_full_piped_shape_present_for_frontend() -> None:
    """The Piped web frontend reads the full StreamInfo object; ensure every
    key it expects is present with the right type."""
    resp = map_streams_response(_video_info(), proxy_url="https://proxy.example")
    for key in (
        "uploader",
        "uploaderUrl",
        "uploaderAvatar",
        "uploaderVerified",
        "uploaderSubscriberCount",
        "uploadDate",
        "uploaded",
        "category",
        "description",
        "views",
        "likes",
        "dislikes",
        "thumbnailUrl",
        "livestream",
        "proxyUrl",
        "relatedStreams",
        "subtitles",
        "chapters",
        "previewFrames",
        "tags",
        "metaInfo",
        "visibility",
    ):
        assert key in resp, f"missing frontend key: {key}"
    assert resp["uploadDate"] == "2023-12-31"
    assert resp["uploaded"] == 1703980800 * 1000
    assert resp["uploader"] == "Example Channel"
    assert resp["uploaderUrl"].endswith("/channel/abc")
    assert resp["views"] == 12345
    assert resp["likes"] == 678
    assert resp["category"] == "Music"
    assert resp["thumbnailUrl"] == "https://t/hi"
    assert resp["proxyUrl"] == "https://proxy.example"
    assert resp["chapters"] == [{"title": "Intro", "image": "", "start": 0}]
    assert resp["relatedStreams"] == []
    assert resp["livestream"] is False


def test_search_maps_entries_to_piped_items() -> None:
    info = {
        "entries": [
            {
                "id": "dQw4w9WgXcQ",
                "title": "Rick",
                "uploader": "Rick Astley",
                "duration": 213,
                "thumbnails": [{"url": "https://t/lo"}, {"url": "https://t/hi"}],
            },
            {"id": None},  # dropped
            None,  # dropped
        ]
    }
    resp = map_search_response(info)
    assert len(resp["items"]) == 1
    item = resp["items"][0]
    assert item["type"] == "stream"
    assert item["url"] == "/watch?v=dQw4w9WgXcQ"
    assert item["uploaderName"] == "Rick Astley"
    assert item["thumbnail"] == "https://t/hi"
    assert "nextpage" in resp
