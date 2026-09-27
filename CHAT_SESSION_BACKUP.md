# 💾 Autonomous YouTube Shorts Engine - Chat Session Backup

- **Date Saved**: 2026-09-23
- **Conversation ID**: `0a22d94b-6603-4c03-9e86-eeba2bc14b29`
- **Channel**: **Viral Chaos** (`@ViralChaos-786`)
- **Project Directory**: `C:\Users\Thakur\.gemini\antigravity-ide\scratch\youtube-shorts-pipeline\`

---

## 📌 Executive Summary

We designed, built, and launched a production-grade, 24/7 self-running YouTube Shorts content creation and auto-upload pipeline with **0% manual intervention required post-setup**.

### What Was Built:
1. **Scraping & Monitoring** (`downloader/scraper.py`):
   - Monitors comedy podcasts & viral creators (`@badfriends`, `@TheoVon`, `@MrBeast`, `@Flagrant2`, `@ColinAndSamir`).
   - Flat-playlist scanning via `yt-dlp` to discover candidate videos without downloading full media first.
2. **AI Transcription** (`ai/transcriber.py`):
   - Uses `faster-whisper` on GPU/CPU to extract word-level timestamps (`[{word, start, end}]`).
3. **Viral Highlight Detection** (`ai/highlighter.py`):
   - Uses Google Gemini 3.6 Flash to analyze transcript retention peaks.
   - Enforces a strict **15 to 50 second** clip limit and strong 3-second opening curiosity hooks.
4. **Trendy Animated Subtitles & 9:16 Video Reframing** (`editor/`):
   - Re-frames 16:9 landscape to 1080x1920 (cinematic blurred backdrop stack).
   - Generates Alex Hormozi–style animated ASS subtitles with karaoke-style bright yellow (`&H0000FFFF&`) word-by-word bounce pop (`\fscx115\fscy115`).
   - Normalizes audio loudness to standard YouTube -14 LUFS.
5. **Deduplication & Quota Guard** (`database/db.py`):
   - SQLite database tracks processed sources and clips.
   - Quota governor strictly caps uploads at 4/day to prevent exceeding YouTube Data API v3 daily limits.
6. **YouTube Data API v3 Uploader** (`uploader/`):
   - Google OAuth2 authenticated with persistent refresh token cached in `data/youtube_token.json`.
   - Automatic background token refresh without user intervention.
   - LLM-generated viral clickbait titles (<60 chars), descriptions with `#shorts #viral`, and tags.
7. **24/7 Autopilot Daemon** (`scheduler/runner.py`):
   - Continuous `APScheduler` runner handling periodic scraping every 4 hours, timed daily publishing, and automatic disk space cleanup.

---

## 🔑 Configured Credentials

- **Gemini API Key**: Saved in `.env` (`AQ.Ab8RN6...W8wQ`). Tested and verified with `gemini-3.6-flash`.
- **Google OAuth Client**: Saved in `client_secrets.json` (Project: `ogbg-lobby`).
- **YouTube Token**: Authenticated for account `myclipsbot@gmail.com` and saved in `data/youtube_token.json`.
- **Upload Privacy**: Configured to `public` in `config.yaml` so uploaded Shorts appear immediately on the channel.

---

## 💻 Daily Operations Cheat Sheet

### 1. Check Pipeline Status & Upload Counter
```powershell
cd C:\Users\Thakur\.gemini\antigravity-ide\scratch\youtube-shorts-pipeline
python main.py status
```

### 2. Audit System Health & Credentials
```powershell
python main.py check
```

### 3. Discover New Viral Videos
```powershell
python main.py discover
# Or search a custom keyword:
python main.py discover --query "MrBeast crazy podcast"
```

### 4. Manually Process & Upload a Specific Video
```powershell
python main.py process-url "https://www.youtube.com/watch?v=VIDEO_ID" --upload
```

### 5. Launch the 24/7 Autopilot (if restarted)
```powershell
python main.py run
```

---

## 📂 File Directory

```
youtube-shorts-pipeline/
├── config.yaml                # Master configuration (channels, clip bounds, subtitles, schedules)
├── .env                       # Environment variables (Gemini API key)
├── client_secrets.json        # Google Cloud OAuth 2.0 credentials
├── requirements.txt           # Python package dependencies
├── main.py                    # Master CLI entrypoint
├── database/db.py             # SQLite deduplication and quota manager
├── downloader/scraper.py      # yt-dlp channel monitor & video downloader
├── ai/transcriber.py          # Faster-Whisper word-level audio transcriber
├── ai/highlighter.py          # Gemini 3.6 Flash viral highlight extractor
├── ai/metadata.py             # Gemini SEO title, description, and tags generator
├── editor/cropper.py          # 9:16 vertical video reframing filter
├── editor/subtitles.py        # Alex Hormozi animated ASS subtitle generator
├── editor/renderer.py         # FFmpeg video slicing & subtitle burning
├── uploader/youtube_auth.py   # OAuth2 refresh token manager
├── uploader/youtube_uploader.py # YouTube Data API v3 uploader
├── scheduler/runner.py        # 24/7 APScheduler background loop
├── utils/logger.py            # Rich logger with file output
├── utils/ffmpeg_helper.py     # FFmpeg executable detector & command executor
├── README.md                  # Setup and usage guide
└── CHAT_SESSION_BACKUP.md     # This complete backup file
```
