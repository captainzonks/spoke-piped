"""piped-resolver — a Piped-API-compatible YouTube stream resolver.

Re-implements the Piped endpoints (`/streams/{id}`, `/search`) that Piped
clients consume, backed by yt-dlp + a bgutil proof-of-origin token provider so
adaptive (1080p/4K) formats are returned where Piped's own extractor no longer
does. Drop-in for the `tubeapi`/`pipedapi` host's `/streams` path.
"""

__version__ = "0.1.0"
