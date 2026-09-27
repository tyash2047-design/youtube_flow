# 🎬 Autonomous 24/7 YouTube Shorts Creation & Auto-Upload Engine

A production-ready, fully autonomous pipeline built in Python to monitor long-form content, extract high-retention highlights (15–50 seconds), format them into 9:16 vertical video, burn animated Hormozi-style subtitles, and automatically upload them to YouTube Shorts via the official YouTube Data API v3 with **0% manual intervention post-setup**.

---

## 🌟 Key Features

- **Automated Source Scraping (`yt-dlp`)**: Continuously monitors target creator channels, podcast playlists, and viral search queries.
- **AI Retention Peak Detection**: Uses Google Gemini (or OpenAI) to analyze word-level transcripts and extract punchy 15–50s segments with a compelling 3-second hook.
- **Cinematic 9:16 Re-Framing**: Transforms 16:9 landscape video into 1080x1920 vertical video (cinematic blurred backdrop stack or center crop).
- **Alex Hormozi Animated Subtitles**: Dynamically generates `.ass` subtitles with active spoken word highlights (neon yellow / lime green with bounce scale animations).
- **SQLite Deduplication & Quota Guard**: Prevents reprocessing previously scraped videos and guards against YouTube Data API daily quota exhaustion (capped at 4–5 uploads/day).
- **Resilient 24/7 Daemon (`APScheduler`)**: Persistent background runner with auto-retry on network errors, scheduled daily uploads at peak engagement hours, and local disk space auto-cleanup.

---

## 📁 Project Architecture

```
youtube-shorts-pipeline/
├── config.yaml                # Master configuration (channels, clip bounds, subtitles, schedules)
├── .env.example               # Secrets template (GEMINI_API_KEY, YOUTUBE_CLIENT_SECRET, etc.)
├── requirements.txt           # Python dependencies
├── main.py                    # Master CLI entrypoint
├── database/
│   └── db.py                  # SQLite schema: sources, clips, daily upload quotas, deduplication
├── downloader/
│   └── scraper.py             # Channel monitor (RSS/yt-dlp flat-playlist) & long-form downloader
├── ai/
│   ├── transcriber.py         # Whisper / Faster-Whisper word-level audio transcriber
│   ├── highlighter.py         # LLM scoring: detects retention hooks, climaxes, 15-50s bounds
│   └── metadata.py            # LLM viral title, description, and hashtag generator
├── editor/
│   ├── cropper.py             # 9:16 smart vertical reframing (cinematic blur / center crop)
│   ├── subtitles.py           # Hormozi-style ASS subtitle generator with dynamic word pop
│   └── renderer.py            # FFmpeg video assembler with safe zones
├── uploader/
│   ├── youtube_auth.py        # Google OAuth2 client secrets & automatic token refresh
│   └── youtube_uploader.py    # YouTube Data API v3 resumable uploader with quota protection
└── scheduler/
    └── runner.py              # APScheduler 24/7 background runner, queue manager & crash recovery
```

---

## 🚀 Step-by-Step Setup Guide

### 1. Prerequisites (Windows)

#### A. Install FFmpeg
Rendering vertical video and animated subtitles requires FFmpeg. In Windows PowerShell:
```powershell
winget install Gyan.FFmpeg
```
*(Restart your terminal after installation so FFmpeg is loaded into your `PATH`.)*

#### B. Install Python Dependencies
In the project directory:
```powershell
pip install -r requirements.txt
```

---

### 2. Configure Credentials (`.env`)

Copy `.env.example` to `.env`:
```powershell
cp .env.example .env
```

Open `.env` and configure:
```ini
# Get a free Gemini API key from https://aistudio.google.com/app/apikey
GEMINI_API_KEY=AIzaSy...

# Path to your Google Cloud OAuth2 Client Secret JSON
YOUTUBE_CLIENT_SECRET_FILE=./client_secrets.json
```

---

### 3. Setup Google Cloud YouTube API Credentials

To allow autonomous uploads to your YouTube channel:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g., `YouTube-Shorts-Automator`).
3. Navigate to **APIs & Services > Library** and search for **YouTube Data API v3**. Click **Enable**.
4. Go to **APIs & Services > OAuth consent screen**:
   - Select **External** and fill in your app name and email.
   - Under **Scopes**, add `.../auth/youtube.upload` and `.../auth/youtube.readonly`.
   - Under **Test Users**, add your YouTube channel's Google account email.
5. Go to **APIs & Services > Credentials**:
   - Click **Create Credentials > OAuth client ID**.
   - Select Application type: **Desktop App**.
   - Name it `ShortsUploader` and click **Create**.
6. Download the generated JSON file, rename it to `client_secrets.json`, and place it in this project folder.

---

### 4. Verify System Health

Run the audit check command:
```powershell
python main.py check
```
This inspects FFmpeg, API keys, OAuth credentials, and the SQLite database.

---

### 5. Perform One-Time YouTube Authentication

Authenticate your YouTube channel once to generate the persistent refresh token:
```powershell
python main.py auth
```
- A browser window will open asking you to sign in with your YouTube Google account.
- Once accepted, `data/youtube_token.json` is generated.
- **From this point onward, the pipeline automatically refreshes tokens in the background 24/7 without prompting you.**

---

### 6. Test Clip Generation (Dry Run)

You can test processing any YouTube video URL without uploading:
```powershell
python main.py process-url "https://www.youtube.com/watch?v=YOUR_VIDEO_ID"
```
The script will:
1. Download the audio & video.
2. Transcribe using Whisper.
3. Detect the best 15–50s viral moment.
4. Re-frame into 9:16 portrait.
5. Burn Alex Hormozi animated subtitles.
6. Save the final `.mp4` into `./data/rendered/`.

To immediately upload this test clip to your channel:
```powershell
python main.py process-url "https://www.youtube.com/watch?v=YOUR_VIDEO_ID" --upload
```

---

### 7. Run the 24/7 Autonomous Daemon

To start the autonomous self-running loop:
```powershell
python main.py run
```

The daemon will:
1. Check configured channels/keywords every 4 hours.
2. Automatically download, trim, and render 9:16 Shorts with Hormozi captions.
3. Auto-publish at your scheduled peak times (`09:30`, `13:00`, `17:30`, `21:00`).
4. Automatically delete large raw source files after processing to save disk space.
5. Enforce API quota limits (maximum 4 uploads per day).

---

### 8. Inspect Live Pipeline Status

At any time, open another terminal and run:
```powershell
python main.py status
```
Displays:
- Number of long-form videos processed.
- Today's upload count and remaining API quota.
- Counts of pending, rendered, and uploaded clips.
- Direct links to recently published YouTube Shorts.

---

## ⚙️ Customization (`config.yaml`)

Edit `config.yaml` to tailor your niche and styling:
- **Channels & Keywords**: Add your favorite creators or niche search terms.
- **Duration**: By default set strictly to `15s - 50s` for maximum retention.
- **Framing Mode**: Choose between `cinematic_blur` (default) or `center_crop`.
- **Subtitles**: Change font (`Arial Black`, `Impact`, `Montserrat`), colors (`&H0000FFFF&` bright yellow), and size.
- **Privacy Status**: Set to `public` when you are ready to publish live to the world (defaults to `private` for safety).
