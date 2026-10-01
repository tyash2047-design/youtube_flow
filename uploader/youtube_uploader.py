import os
import time
import json
from typing import Dict, Any, Optional
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError
from database.db import Database
from utils.logger import logger
from .youtube_auth import YouTubeAuth

class YouTubeShortsUploader:
    def __init__(self, config: Dict[str, Any], db: Database):
        self.config = config
        self.db = db
        self.uploader_cfg = config.get("uploader", {})
        self.paths_cfg = config.get("paths", {})
        
        self.privacy_status = self.uploader_cfg.get("privacy_status", "private")
        self.category_id = str(self.uploader_cfg.get("category_id", "24"))
        self.max_daily_uploads = self.uploader_cfg.get("max_daily_uploads", 4)
        
        secrets_file = os.getenv("YOUTUBE_CLIENT_SECRET_FILE", self.paths_cfg.get("client_secrets_file", "./client_secrets.json"))
        token_file = self.paths_cfg.get("token_file", "./data/youtube_token.json")
        self.auth = YouTubeAuth(client_secrets_file=secrets_file, token_file=token_file)

    def upload_short(self, clip_record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Uploads a rendered 9:16 video to YouTube Shorts using YouTube Data API v3.
        Performs quota checks and logs the resulting video ID.
        """
        clip_id = clip_record["id"]
        video_path = clip_record.get("rendered_path")

        if not video_path or not os.path.exists(video_path):
            err_msg = f"Cannot upload: rendered file not found at '{video_path}'"
            logger.error(err_msg)
            self.db.update_clip_failed(clip_id, err_msg)
            return None

        # 1. Quota check
        if self.max_daily_uploads > 0 and not self.db.can_upload_today(self.max_daily_uploads):
            today_count = self.db.get_today_upload_count()
            logger.warning(f"Daily upload quota reached ({today_count}/{self.max_daily_uploads}). Postponing upload for clip {clip_id}.")
            return None

        # 2. Authenticate
        service = self.auth.get_service(allow_browser=False)
        if not service:
            err_msg = "YouTube authentication service unavailable. Run 'python main.py auth' to set up tokens."
            logger.error(err_msg)
            self.db.update_clip_failed(clip_id, err_msg)
            return None

        # 3. Parse Metadata
        title = clip_record.get("title", "Viral Moment #shorts")
        if "#shorts" not in title.lower():
            title = f"{title} #shorts"

        description = clip_record.get("description", "Watch till the end! #shorts #viral")
        tags_raw = clip_record.get("tags")
        if isinstance(tags_raw, str):
            try:
                tags = json.loads(tags_raw)
            except Exception:
                tags = ["Shorts", "viral"]
        elif isinstance(tags_raw, list):
            tags = tags_raw
        else:
            tags = ["Shorts", "viral"]

        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": tags,
                "categoryId": self.category_id,
            },
            "status": {
                "privacyStatus": self.privacy_status,
                "selfDeclaredMadeForKids": False,
            }
        }

        media = MediaFileUpload(
            video_path,
            chunksize=1024 * 1024 * 2,  # 2MB chunks
            resumable=True,
            mimetype="video/mp4"
        )

        logger.info(f"Uploading to YouTube Shorts: [bold cyan]{title}[/bold cyan] ({self.privacy_status})")
        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        response = None
        retry_count = 0
        max_retries = 5

        while response is None:
            try:
                status, response = request.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"Upload progress: {progress}%")
            except HttpError as e:
                if e.resp.status in [500, 502, 503, 504]:
                    retry_count += 1
                    if retry_count > max_retries:
                        logger.error(f"HTTP error during upload: {e}")
                        self.db.update_clip_failed(clip_id, str(e))
                        return None
                    sleep_time = 2 ** retry_count
                    logger.warning(f"Server error {e.resp.status}. Retrying in {sleep_time}s...")
                    time.sleep(sleep_time)
                elif e.resp.status == 403 and "quotaExceeded" in str(e):
                    err_msg = "YouTube API quota exceeded for today (10,000 units)."
                    logger.error(err_msg)
                    self.db.update_clip_failed(clip_id, err_msg)
                    return None
                else:
                    logger.error(f"Fatal YouTube API error: {e}")
                    self.db.update_clip_failed(clip_id, str(e))
                    return None
            except Exception as ex:
                logger.error(f"Unexpected upload error: {ex}")
                self.db.update_clip_failed(clip_id, str(ex))
                return None

        video_id = response.get("id")
        shorts_url = f"https://youtube.com/shorts/{video_id}"
        logger.info(f"Upload completed successfully! [bold green]Shorts URL: {shorts_url}[/bold green]")

        # Record in database
        self.db.update_clip_uploaded(clip_id, video_id, shorts_url)

        # Post AI engagement comment if available
        pinned_comment = clip.get("pinned_comment")
        if pinned_comment:
            self._post_pinned_comment(service, video_id, pinned_comment)

        return {
            "clip_id": clip_id,
            "youtube_id": video_id,
            "url": shorts_url,
            "title": title
        }

    def _post_pinned_comment(self, service, video_id: str, text: str):
        """Attempts to post an engagement-driving comment to the uploaded Short."""
        try:
            body = {
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {
                            "textOriginal": text
                        }
                    }
                }
            }
            service.commentThreads().insert(part="snippet", body=body).execute()
            logger.info(f"Posted AI engagement comment to Short {video_id}: [italic yellow]'{text}'[/italic yellow]")
        except Exception as e:
            logger.debug(f"Could not post comment to Short (non-critical): {e}")
