FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ffmpeg — reels ovozi va kadrlarini ajratish uchun (video_brief.py, 2026-11-28).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Dependencies before source, so an edit to a handler does not re-resolve pip.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin ketoshop \
    && chown -R ketoshop:ketoshop /app
USER ketoshop

# bot.py reads PORT for the aiohttp Mini App server; the bot itself polls, so
# nothing is served on this port unless create_webapp() succeeds.
ENV PORT=8080
EXPOSE 8080

CMD ["python", "bot.py"]
