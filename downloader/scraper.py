import os
import re
from typing import List, Dict, Any, Optional
import yt_dlp
from database.db import Database
from utils.logger import logger
from utils.ffmpeg_helper import get_ffmpeg_path

class ContentScraper:
    def __init__(self, config: Dict[str, Any], db: Database):
        self.config = config
        self.db = db
        self.sources_cfg = config.get("sources", {})
        self.min_duration = self.sources_cfg.get("min_duration_seconds", 180)
        self.max_duration = self.sources_cfg.get("max_duration_seconds", 7200)
        self.min_views = self.sources_cfg.get("min_views", 10000)
        self.download_dir = config.get("paths", {}).get("temp_download_dir", "./data/downloads")
        os.makedirs(self.download_dir, exist_ok=True)

    def _get_cookie_file(self) -> Optional[str]:
        """
        Locates or restores YouTube cookies from environment variables or local files.
        Essential for cloud deployments (Render, AWS, GCP) to bypass bot verification.
        """
        cookie_path = os.path.join(self.download_dir, "cookies.txt")

        # 1. Base64 encoded cookies from environment variable
        cookie_b64 = os.getenv("YOUTUBE_COOKIES_BASE64")
        if cookie_b64:
            try:
                import base64
                decoded = base64.b64decode(cookie_b64.strip()).decode("utf-8", errors="ignore")
                with open(cookie_path, "w", encoding="utf-8") as f:
                    f.write(decoded)
                logger.info(f"Restored YouTube cookies from YOUTUBE_COOKIES_BASE64 -> {cookie_path}")
                return cookie_path
            except Exception as e:
                logger.warning(f"Could not decode YOUTUBE_COOKIES_BASE64: {e}")

        # 2. Raw text cookies from environment variable
        cookie_txt = os.getenv("YOUTUBE_COOKIES_TXT")
        if cookie_txt:
            try:
                with open(cookie_path, "w", encoding="utf-8") as f:
                    f.write(cookie_txt.strip())
                logger.info(f"Restored YouTube cookies from YOUTUBE_COOKIES_TXT -> {cookie_path}")
                return cookie_path
            except Exception as e:
                logger.warning(f"Could not write YOUTUBE_COOKIES_TXT: {e}")

        # 3. Existing cookie files in repo / workspace
        candidates = [
            "./data/cookies.txt",
            "./cookies.txt",
            cookie_path
        ]
        for c in candidates:
            if os.path.exists(c) and os.path.getsize(c) > 10:
                return c

        return None

    def _get_flat_ydl_opts(self) -> Dict[str, Any]:
        cookie_file = self._get_cookie_file()
        opts: Dict[str, Any] = {
            "extract_flat": True,
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "playlist_items": "1-10",  # Check top 10 most recent videos per channel
            "ignoreerrors": True,
            "js_runtimes": {"node": {}},
            "extractor_args": {
                "youtube": {
                    "player_client": ["visionos"]
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
        }
        if cookie_file:
            opts["cookiefile"] = cookie_file
        return opts

    def fetch_candidates_from_channel(self, channel_url: str) -> List[Dict[str, Any]]:
        """Scrapes recent video metadata from a channel URL without downloading."""
        logger.info(f"Scanning channel: [cyan]{channel_url}[/cyan]")
        candidates = []
        ydl_opts = self._get_flat_ydl_opts()
        
        # Ensure we look at the /videos tab for uploads
        if not channel_url.endswith("/videos") and not channel_url.endswith("/streams"):
            scan_url = f"{channel_url.rstrip('/')}/videos"
        else:
            scan_url = channel_url

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(scan_url, download=False)
                if not info or "entries" not in info:
                    return candidates

                for entry in info["entries"]:
                    if not entry:
                        continue
                    
                    vid_id = entry.get("id")
                    title = entry.get("title", "Unknown Title")
                    duration = entry.get("duration") or 0
                    view_count = entry.get("view_count") or 0
                    url = entry.get("url") or f"https://www.youtube.com/watch?v={vid_id}"

                    # Skip previously processed sources
                    if self.db.is_source_processed(vid_id):
                        logger.debug(f"Skipping already processed video: {vid_id} ({title})")
                        continue

                    # Filter by duration (must be long enough to have great highlights)
                    if duration and (duration < self.min_duration or duration > self.max_duration):
                        logger.debug(f"Skipping video duration {duration}s outside range ({self.min_duration}-{self.max_duration}): {title}")
                        continue

                    candidates.append({
                        "video_id": vid_id,
                        "title": title,
                        "url": url,
                        "channel": entry.get("channel") or entry.get("uploader") or "Unknown",
                        "duration": int(duration),
                        "view_count": int(view_count)
                    })
        except Exception as e:
            logger.warning(f"Error scraping channel {channel_url}: {e}")

        logger.info(f"Found {len(candidates)} new candidate videos from {channel_url}")
        return candidates

    def search_candidates_by_keywords(self, keyword: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Searches YouTube by keyword for viral long-form videos."""
        logger.info(f"Searching keyword: [cyan]{keyword}[/cyan]")
        candidates = []
        query = f"ytsearch{max_results}:{keyword}"
        ydl_opts = self._get_flat_ydl_opts()

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(query, download=False)
                if not info or "entries" not in info:
                    return candidates

                for entry in info["entries"]:
                    if not entry:
                        continue
                    vid_id = entry.get("id")
                    if self.db.is_source_processed(vid_id):
                        continue

                    duration = entry.get("duration") or 0
                    if duration and (duration < self.min_duration or duration > self.max_duration):
                        continue

                    candidates.append({
                        "video_id": vid_id,
                        "title": entry.get("title", "Unknown"),
                        "url": entry.get("url") or f"https://www.youtube.com/watch?v={vid_id}",
                        "channel": entry.get("channel") or entry.get("uploader") or "Unknown",
                        "duration": int(duration),
                        "view_count": int(entry.get("view_count") or 0)
                    })
        except Exception as e:
            logger.warning(f"Error searching keyword '{keyword}': {e}")
        return candidates

    def download_video_and_audio(self, video_info: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Downloads high-resolution 1080p/720p video and extracts a 16kHz mono audio file.
        Records progress in SQLite database.
        """
        vid_id = video_info["video_id"]
        url = video_info["url"]
        title = video_info.get("title", vid_id)
        channel = video_info.get("channel", "Unknown")
        duration = video_info.get("duration", 0)

        # Sanitize filename
        safe_title = re.sub(r'[^a-zA-Z0-9_-]', '_', title)[:40]
        video_out_tmpl = os.path.join(self.download_dir, f"{vid_id}_{safe_title}.%(ext)s")
        audio_out_file = os.path.join(self.download_dir, f"{vid_id}_{safe_title}.wav")

        # Record in DB
        self.db.add_source(vid_id, url, title, channel, duration)

        # Clean up any partial/stale files for this video ID before starting to avoid HTTP 416 range errors
        import glob
        for stale in glob.glob(os.path.join(self.download_dir, f"{vid_id}_*")):
            try:
                os.remove(stale)
            except Exception:
                pass

        max_res = self.sources_cfg.get("download_resolution", "1080")
        format_selector = (
            f"bestvideo[height<={max_res}][ext=mp4]+bestaudio[ext=m4a]/"
            f"bestvideo[height<={max_res}]+bestaudio/"
            f"best[height<={max_res}][ext=mp4]/"
            f"best[height<={max_res}]/"
            f"best"
        )

        # Attempt to get ffmpeg path
        ffmpeg_location = None
        try:
            ffmpeg_location = get_ffmpeg_path()
        except Exception:
            pass

        cookie_file = self._get_cookie_file()
        if cookie_file:
            logger.info(f"Using authenticated cookie file: {cookie_file}")
        else:
            logger.info("No cookie file detected. Using visionos / mobile client API to bypass datacenter bot checks.")

        ydl_opts = {
            "format": format_selector,
            "outtmpl": video_out_tmpl,
            "merge_output_format": "mp4",
            "nopart": True,
            "overwrites": True,
            "windowsfilenames": True,
            "quiet": False,
            "no_warnings": True,
            "ignoreerrors": False,
            "js_runtimes": {"node": {}},
            "extractor_args": {
                "youtube": {
                    "player_client": ["visionos"]
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
        }
        if cookie_file:
            ydl_opts["cookiefile"] = cookie_file
        if ffmpeg_location:
            ydl_opts["ffmpeg_location"] = ffmpeg_location

        logger.info(f"Downloading source: [green]{title}[/green] ({vid_id})")
        downloaded_video_path = None

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                downloaded_video_path = ydl.prepare_filename(info)
                # Ensure .mp4 extension if merged
                base, _ = os.path.splitext(downloaded_video_path)
                if os.path.exists(f"{base}.mp4"):
                    downloaded_video_path = f"{base}.mp4"
        except Exception as e:
            err_str = str(e)
            logger.warning(f"Download with visionos reported: {e}. Retrying with web_embedded client...")
            ydl_opts_fallback = dict(ydl_opts)
            ydl_opts_fallback.pop("cookiefile", None)
            ydl_opts_fallback["extractor_args"] = {
                "youtube": {
                    "player_client": ["web_embedded"]
                }
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts_fallback) as ydl_fb:
                    info = ydl_fb.extract_info(url, download=True)
                    downloaded_video_path = ydl_fb.prepare_filename(info)
                    base, _ = os.path.splitext(downloaded_video_path)
                    if os.path.exists(f"{base}.mp4"):
                        downloaded_video_path = f"{base}.mp4"
            except Exception as e2:
                logger.warning(f"Fallback download also reported: {e2}. Resolving stream files on Windows...")
                e = e2
            import time, shutil
            from utils.ffmpeg_helper import run_ffmpeg_cmd

            expected_base = os.path.join(self.download_dir, f"{vid_id}_{safe_title}")
            target_mp4 = f"{expected_base}.mp4"

            # 1. Check for .temp.mp4 lock recovery
            temp_candidates = glob.glob(os.path.join(self.download_dir, f"{vid_id}_*.temp.mp4"))
            if temp_candidates:
                t_cand = temp_candidates[0]
                for _ in range(6):
                    time.sleep(2.0)
                    try:
                        if os.path.exists(target_mp4):
                            os.remove(target_mp4)
                        shutil.move(t_cand, target_mp4)
                        downloaded_video_path = target_mp4
                        break
                    except Exception:
                        pass

            # 2. Check if yt-dlp downloaded separate video and audio streams but failed during merger
            if not downloaded_video_path or not os.path.exists(downloaded_video_path):
                vid_files = [f for f in glob.glob(os.path.join(self.download_dir, f"{vid_id}_*.mp4")) if ".temp." not in f]
                aud_files = glob.glob(os.path.join(self.download_dir, f"{vid_id}_*.m4a"))
                if vid_files and aud_files:
                    logger.info("Found separate video and audio tracks, merging with direct FFmpeg copy...")
                    cmd_merge = [
                        "ffmpeg", "-y", "-i", vid_files[0], "-i", aud_files[0],
                        "-c", "copy", target_mp4
                    ]
                    success_merge, merge_err = run_ffmpeg_cmd(cmd_merge, timeout=120)
                    if success_merge and os.path.exists(target_mp4) and os.path.getsize(target_mp4) > 1000000:
                        downloaded_video_path = target_mp4

            if not downloaded_video_path or not os.path.exists(downloaded_video_path):
                logger.error(f"Download failed for {url}: {e}")
                self.db.update_source_status(vid_id, "FAILED")
                return None

        # Extract 16kHz mono audio for Whisper transcription using ffmpeg
        logger.info(f"Extracting mono audio for Whisper transcription: {audio_out_file}")
        try:
            from utils.ffmpeg_helper import run_ffmpeg_cmd
            # If an m4a audio file exists from the download, extract directly from it for speed
            aud_files = glob.glob(os.path.join(self.download_dir, f"{vid_id}_*.m4a"))
            audio_source = aud_files[0] if (aud_files and os.path.exists(aud_files[0])) else downloaded_video_path

            cmd = [
                "ffmpeg", "-y", "-i", audio_source,
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                audio_out_file
            ]
            success, err = run_ffmpeg_cmd(cmd, timeout=300)
            if not success or not os.path.exists(audio_out_file) or os.path.getsize(audio_out_file) < 1000:
                logger.error(f"FFmpeg audio extraction failed: {err}")
                self.db.update_source_status(vid_id, "FAILED")
                return None
        except Exception as ex:
            logger.error(f"Audio extraction exception: {ex}")
            self.db.update_source_status(vid_id, "FAILED")
            return None

        # Update SQLite database
        self.db.update_source_downloaded(vid_id, downloaded_video_path, audio_out_file)
        logger.info(f"Source video and audio ready: {downloaded_video_path}")

        return {
            "video_id": vid_id,
            "video_path": downloaded_video_path,
            "audio_path": audio_out_file,
            "title": title,
            "channel": channel,
            "duration": duration,
            "url": url
        }
