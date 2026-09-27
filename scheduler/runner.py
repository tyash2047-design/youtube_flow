import os
import time
import shutil
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from database.db import Database
from downloader.scraper import ContentScraper
from ai.transcriber import Transcriber
from ai.highlighter import HighlightDetector
from ai.metadata import MetadataGenerator
from editor.renderer import VideoRenderer
from uploader.youtube_uploader import YouTubeShortsUploader
from utils.logger import logger

class PipelineRunner:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.db = Database(config.get("paths", {}).get("database_file", "./data/pipeline.db"))
        self.scraper = ContentScraper(config, self.db)
        
        # AI components
        clip_cfg = config.get("clipping", {})
        self.transcriber = Transcriber(
            model_size=clip_cfg.get("whisper_model_size", "small"),
            device=clip_cfg.get("whisper_device", "auto")
        )
        self.highlighter = HighlightDetector(config)
        self.metadata_gen = MetadataGenerator(config)
        
        # Editor & Uploader
        self.renderer = VideoRenderer(config)
        self.uploader = YouTubeShortsUploader(config, self.db)
        
        # Settings
        self.scheduler_cfg = config.get("scheduler", {})
        self.delete_raw = self.scheduler_cfg.get("delete_raw_source_after_processing", True)
        self.retention_days = self.scheduler_cfg.get("rendered_retention_days", 7)

    def process_single_source(self, video_info: Dict[str, Any]) -> int:
        """
        Processes a single long-form video from download to rendered clips:
        1. Download video & extract audio
        2. Transcribe word-level timestamps
        3. Detect 15-50s highlights with LLM
        4. Generate metadata & render 9:16 vertical clips with Hormozi captions
        5. Clean up raw source video
        """
        vid_id = video_info["video_id"]
        logger.info(f"--- Processing Source: [bold yellow]{video_info.get('title')}[/bold yellow] ({vid_id}) ---")

        # 1. Download
        dl_result = self.scraper.download_video_and_audio(video_info)
        if not dl_result:
            return 0

        source_video = dl_result["video_path"]
        audio_path = dl_result["audio_path"]

        try:
            # 2. Transcribe
            transcript = self.transcriber.transcribe(audio_path)
            if not transcript or not transcript.get("segments"):
                logger.warning(f"No speech or transcript found for {vid_id}")
                self.db.update_source_status(vid_id, "NO_TRANSCRIPT")
                return 0

            # Collect all words across segments for accurate subtitle timing
            all_words = []
            for seg in transcript["segments"]:
                all_words.extend(seg.get("words", []))

            # 3. Detect Highlights (15 - 50 seconds)
            clips = self.highlighter.detect_highlights(transcript, video_info)
            if not clips:
                logger.warning(f"No high-retention highlights met score threshold for {vid_id}")
                self.db.update_source_status(vid_id, "NO_CLIPS")
                return 0

            rendered_count = 0
            for i, clip in enumerate(clips):
                start = clip["start_time"]
                end = clip["end_time"]
                
                # Extract clip transcript snippet
                clip_words = [w["word"] for w in all_words if w.get("start", 0) >= start and w.get("end", 0) <= end]
                clip_text = " ".join(clip_words)

                # 4. Generate Metadata
                meta = self.metadata_gen.generate_metadata(clip, video_info, clip_text)
                
                # Add to DB
                clip_id = self.db.add_clip(
                    source_video_id=vid_id,
                    start_time=start,
                    end_time=end,
                    title=meta["title"],
                    description=meta["description"],
                    tags=meta["tags"],
                    viral_score=clip["viral_score"],
                    reason=clip["reason"]
                )
                clip["id"] = clip_id

                # 5. Render 9:16 video with animated subtitles
                rendered_path = self.renderer.render_short(
                    source_video_path=source_video,
                    clip_info=clip,
                    words_list=all_words,
                    output_filename=f"short_{vid_id}_{clip_id}.mp4"
                )

                if rendered_path:
                    self.db.update_clip_rendered(clip_id, rendered_path)
                    rendered_count += 1
                    
                    # Auto-publish immediately as soon as ready
                    if self.scheduler_cfg.get("post_immediately", True):
                        logger.info(f"⚡ Instant Upload: Publishing Short #{clip_id} to YouTube right now...")
                        ready_clips = self.db.get_ready_to_upload_clips(limit=1)
                        if ready_clips:
                            self.uploader.upload_short(ready_clips[0])
                else:
                    self.db.update_clip_failed(clip_id, "Rendering failed")

            self.db.update_source_status(vid_id, "PROCESSED")
            logger.info(f"Successfully processed {vid_id}: generated [green]{rendered_count}[/green] shorts.")
            return rendered_count

        finally:
            # 6. Disk space cleanup: delete raw source video and audio
            if self.delete_raw:
                logger.info(f"Cleaning up raw source media for {vid_id}...")
                for path in [source_video, audio_path]:
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except Exception as e:
                            logger.warning(f"Could not remove temp file {path}: {e}")

    def execute_discovery_and_generation(self):
        """Monitors channels & keywords, then processes newly discovered content."""
        logger.info(">>> Starting scheduled content discovery & clip generation <<<")
        max_to_process = self.config.get("sources", {}).get("max_videos_per_scrape", 2)
        candidates = []

        # 1. Check Channels
        for channel in self.config.get("sources", {}).get("channels", []):
            try:
                new_vids = self.scraper.fetch_candidates_from_channel(channel)
                candidates.extend(new_vids)
                if len(candidates) >= max_to_process:
                    break
            except Exception as e:
                logger.error(f"Error checking channel {channel}: {e}")

        # 2. Check Keywords if need more candidates
        if len(candidates) < max_to_process:
            for kw in self.config.get("sources", {}).get("keywords", []):
                try:
                    new_vids = self.scraper.search_candidates_by_keywords(kw, max_results=3)
                    candidates.extend(new_vids)
                    if len(candidates) >= max_to_process:
                        break
                except Exception as e:
                    logger.error(f"Error searching keyword {kw}: {e}")

        if not candidates:
            logger.info("No new candidate videos found during this discovery cycle.")
            return

        # Process up to max_to_process videos
        to_process = candidates[:max_to_process]
        for vid in to_process:
            try:
                self.process_single_source(vid)
            except Exception as e:
                logger.error(f"Failed to process video {vid.get('video_id')}: {e}", exc_info=True)

    def execute_scheduled_upload(self):
        """Pulls pending rendered shorts and publishes to YouTube."""
        logger.info(">>> Checking for YouTube Shorts upload queue <<<")
        max_uploads = self.config.get("uploader", {}).get("max_daily_uploads", 0)

        while True:
            if not self.db.can_upload_today(max_uploads):
                logger.info("Daily upload limit reached. Skipping upload job.")
                break

            ready_clips = self.db.get_ready_to_upload_clips(limit=1)
            if not ready_clips:
                logger.info("No rendered clips currently waiting in queue to upload.")
                break

            clip = ready_clips[0]
            logger.info(f"Selected clip for upload: #{clip['id']} - '{clip['title']}' (Viral Score: {clip['viral_score']})")
            try:
                self.uploader.upload_short(clip)
            except Exception as e:
                logger.error(f"Error during upload of clip {clip['id']}: {e}", exc_info=True)
                break

            # If not in immediate upload mode, only upload 1 clip per scheduled trigger
            if not self.scheduler_cfg.get("post_immediately", True):
                break

    def cleanup_old_rendered_files(self):
        """Removes old rendered shorts older than configured retention period."""
        if self.retention_days <= 0:
            return
        cutoff = datetime.now() - timedelta(days=self.retention_days)
        render_dir = self.config.get("paths", {}).get("rendered_clips_dir", "./data/rendered")
        if not os.path.exists(render_dir):
            return

        for fname in os.listdir(render_dir):
            fpath = os.path.join(render_dir, fname)
            if os.path.isfile(fpath):
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                if mtime < cutoff:
                    try:
                        os.remove(fpath)
                        logger.info(f"Pruned old rendered file: {fname}")
                    except Exception:
                        pass

    def start_24_7(self):
        """Starts the persistent background runner using APScheduler."""
        logger.info("[bold green]Starting Autonomous 24/7 YouTube Shorts Daemon...[/bold green]")
        scheduler = BlockingScheduler()

        # 1. Content Discovery & Generation Job
        scrape_hours = self.scheduler_cfg.get("scrape_interval_hours", 4)
        scheduler.add_job(
            self.execute_discovery_and_generation,
            trigger=IntervalTrigger(hours=scrape_hours),
            id="discovery_job",
            name="Scrape & Generate Highlights",
            replace_existing=True
        )

        # 2. Upload Poller (Checks every 2 minutes for instant publishing)
        if self.scheduler_cfg.get("post_immediately", True):
            scheduler.add_job(
                self.execute_scheduled_upload,
                trigger=IntervalTrigger(minutes=2),
                id="instant_upload_poller",
                name="Instant Upload Poller (2 min)",
                replace_existing=True
            )
        else:
            # Fixed times throughout the day
            upload_times = self.scheduler_cfg.get("upload_times", ["09:30", "13:00", "17:30", "21:00"])
            for idx, t_str in enumerate(upload_times):
                parts = t_str.split(":")
                if len(parts) == 2:
                    hr, mn = int(parts[0]), int(parts[1])
                    scheduler.add_job(
                        self.execute_scheduled_upload,
                        trigger=CronTrigger(hour=hr, minute=mn),
                        id=f"upload_job_{idx}",
                        name=f"Upload Short at {t_str}",
                        replace_existing=True
                    )

        # 3. Daily Housekeeping (Pruning old clips)
        scheduler.add_job(
            self.cleanup_old_rendered_files,
            trigger=CronTrigger(hour=3, minute=0),
            id="cleanup_job",
            name="Daily Storage Pruning",
            replace_existing=True
        )

        # Run an initial discovery pass on startup
        logger.info("Executing initial discovery & queue check on launch...")
        try:
            self.execute_discovery_and_generation()
            self.execute_scheduled_upload()
        except Exception as e:
            logger.error(f"Error during initial startup pass: {e}")

        logger.info(f"Daemon active: Scraping every {scrape_hours}h | Upload schedule: {', '.join(upload_times)}")
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Daemon received termination signal. Shutting down cleanly.")
