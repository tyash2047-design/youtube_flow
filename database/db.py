import sqlite3
import os
import json
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from utils.logger import logger

class Database:
    def __init__(self, db_path: str = "./data/pipeline.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initializes tables and indexes if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Sources table (Original long-form videos)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT UNIQUE NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT,
                    channel TEXT,
                    duration INTEGER,
                    status TEXT DEFAULT 'DISCOVERED',
                    local_path TEXT,
                    audio_path TEXT,
                    discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    processed_at TIMESTAMP
                );
            """)

            # Highlight Clips table (9:16 Shorts)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clips (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_video_id TEXT NOT NULL,
                    start_time REAL NOT NULL,
                    end_time REAL NOT NULL,
                    duration REAL NOT NULL,
                    title TEXT,
                    description TEXT,
                    tags TEXT,
                    viral_score REAL,
                    reason TEXT,
                    rendered_path TEXT,
                    status TEXT DEFAULT 'PENDING',
                    youtube_video_id TEXT,
                    youtube_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    uploaded_at TIMESTAMP,
                    error_message TEXT,
                    FOREIGN KEY(source_video_id) REFERENCES sources(video_id)
                );
            """)

            # Daily Quota table (tracks YouTube API quota usage per day)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_quotas (
                    date TEXT PRIMARY KEY,
                    upload_count INTEGER DEFAULT 0,
                    quota_units_used INTEGER DEFAULT 0,
                    last_upload_at TIMESTAMP
                );
            """)

            # Indexes for fast lookup
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sources_vid ON sources(video_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_clips_status ON clips(status);")
            conn.commit()

    # --- Sources API ---
    def is_source_processed(self, video_id: str) -> bool:
        """Checks if a long-form video has already been recorded in the database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM sources WHERE video_id = ?", (video_id,))
            return cursor.fetchone() is not None

    def add_source(self, video_id: str, url: str, title: str, channel: str, duration: int) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO sources (video_id, url, title, channel, duration, status)
                VALUES (?, ?, ?, ?, ?, 'DISCOVERED')
            """, (video_id, url, title, channel, duration))
            conn.commit()
            return cursor.lastrowid

    def update_source_downloaded(self, video_id: str, local_path: str, audio_path: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sources 
                SET status = 'DOWNLOADED', local_path = ?, audio_path = ?
                WHERE video_id = ?
            """, (local_path, audio_path, video_id))
            conn.commit()

    def update_source_status(self, video_id: str, status: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE sources 
                SET status = ?, processed_at = CURRENT_TIMESTAMP
                WHERE video_id = ?
            """, (status, video_id))
            conn.commit()

    # --- Clips API ---
    def add_clip(self, source_video_id: str, start_time: float, end_time: float, 
                 title: str, description: str, tags: List[str], viral_score: float, reason: str) -> int:
        duration = round(end_time - start_time, 2)
        tags_json = json.dumps(tags)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO clips (
                    source_video_id, start_time, end_time, duration,
                    title, description, tags, viral_score, reason, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """, (source_video_id, start_time, end_time, duration, title, description, tags_json, viral_score, reason))
            conn.commit()
            return cursor.lastrowid

    def update_clip_rendered(self, clip_id: int, rendered_path: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE clips
                SET status = 'RENDERED', rendered_path = ?
                WHERE id = ?
            """, (rendered_path, clip_id))
            conn.commit()

    def update_clip_uploaded(self, clip_id: int, youtube_video_id: str, youtube_url: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE clips
                SET status = 'UPLOADED', youtube_video_id = ?, youtube_url = ?, uploaded_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (youtube_video_id, youtube_url, clip_id))
            conn.commit()
        # Increment daily quota counter
        self.record_upload_success()

    def update_clip_failed(self, clip_id: int, error_message: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE clips
                SET status = 'FAILED', error_message = ?
                WHERE id = ?
            """, (error_message, clip_id))
            conn.commit()

    def get_pending_renders(self, limit: int = 5) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT c.*, s.local_path as source_path, s.audio_path
                FROM clips c
                JOIN sources s ON c.source_video_id = s.video_id
                WHERE c.status = 'PENDING'
                ORDER BY c.viral_score DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_ready_to_upload_clips(self, limit: int = 1) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM clips
                WHERE status = 'RENDERED' AND rendered_path IS NOT NULL
                ORDER BY viral_score DESC, id ASC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    # --- Quota & Daily Limit API ---
    def get_today_str(self) -> str:
        return date.today().isoformat()

    def can_upload_today(self, max_daily_uploads: int = 0) -> bool:
        """Returns True if today's upload count is below the limit, or if limit is 0 (unlimited)."""
        if max_daily_uploads <= 0:
            return True
        today = self.get_today_str()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT upload_count FROM daily_quotas WHERE date = ?", (today,))
            row = cursor.fetchone()
            if not row:
                return True
            return row["upload_count"] < max_daily_uploads

    def get_today_upload_count(self) -> int:
        today = self.get_today_str()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT upload_count FROM daily_quotas WHERE date = ?", (today,))
            row = cursor.fetchone()
            return row["upload_count"] if row else 0

    def record_upload_success(self, quota_cost: int = 1600):
        today = self.get_today_str()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO daily_quotas (date, upload_count, quota_units_used, last_upload_at)
                VALUES (?, 1, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(date) DO UPDATE SET
                    upload_count = upload_count + 1,
                    quota_units_used = quota_units_used + ?,
                    last_upload_at = CURRENT_TIMESTAMP
            """, (today, quota_cost, quota_cost))
            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        """Returns overall pipeline statistics for CLI display."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sources")
            total_sources = cursor.fetchone()[0]

            cursor.execute("SELECT status, COUNT(*) FROM clips GROUP BY status")
            clips_by_status = dict(cursor.fetchall())

            today = self.get_today_str()
            cursor.execute("SELECT upload_count, quota_units_used FROM daily_quotas WHERE date = ?", (today,))
            today_row = cursor.fetchone()
            today_uploads = today_row["upload_count"] if today_row else 0
            today_quota = today_row["quota_units_used"] if today_row else 0

            return {
                "total_sources": total_sources,
                "clips_by_status": clips_by_status,
                "today_uploads": today_uploads,
                "today_quota_used": today_quota
            }

    def get_recent_uploads(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Returns the most recent uploaded clips."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, title, viral_score, youtube_url, uploaded_at
                FROM clips
                WHERE status = 'UPLOADED' AND youtube_url IS NOT NULL
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

