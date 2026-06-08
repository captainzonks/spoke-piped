# piped-resolver — Piped-compatible YouTube resolver (yt-dlp + bgutil POT)
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# yt-dlp requires a JavaScript runtime to decipher YouTube signatures (nsig).
# Without one, all signed adaptive formats are dropped and extraction fails
# with "Requested format is not available". Deno is yt-dlp's default EJS runtime.
COPY --from=denoland/deno:bin-2.8.2 /deno /usr/local/bin/deno

# Install deps first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

# Non-root.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin appuser
USER 1000

EXPOSE 8000

# Honors RESOLVER_HOST / RESOLVER_PORT via the env the app reads at import.
CMD ["sh", "-c", "uvicorn app.main:app --host ${RESOLVER_HOST:-0.0.0.0} --port ${RESOLVER_PORT:-8000}"]
