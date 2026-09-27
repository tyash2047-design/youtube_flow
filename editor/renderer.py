import os
import sys
import tempfile
from typing import Dict, Any, List, Optional
from utils.logger import logger
from utils.ffmpeg_helper import run_ffmpeg_cmd, get_ffmpeg_path
from .cropper import VideoCropper
from .subtitles import SubtitleGenerator

def escape_ffmpeg_filter_path(path: str) -> str:
    """Escapes file paths for FFmpeg filter arguments on Windows and POSIX."""
    # Convert backslashes to forward slashes
    clean = path.replace("\\", "/")
    # Escape colon (e.g. C: -> C\:)
    clean = clean.replace(":", r"\:")
    # Escape single quotes
    clean = clean.replace("'", r"\'")
    return clean

class VideoRenderer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.cropper = VideoCropper(config)
        self.subtitle_gen = SubtitleGenerator(config)
        self.output_dir = config.get("paths", {}).get("rendered_clips_dir", "./data/rendered")
        os.makedirs(self.output_dir, exist_ok=True)
        self.fps = config.get("video", {}).get("fps", 30)
        self.normalize_audio = config.get("video", {}).get("normalize_audio", True)
        self.subtitles_enabled = config.get("subtitles", {}).get("enabled", True)

    def render_short(
        self,
        source_video_path: str,
        clip_info: Dict[str, Any],
        words_list: List[Dict[str, Any]],
        output_filename: Optional[str] = None
    ) -> Optional[str]:
        """
        Renders a 9:16 vertical YouTube Short from a source video with:
        - Exact start/end trimming (15-50s)
        - 9:16 vertical re-framing (cinematic blur or center crop)
        - Word-by-word animated subtitles burned in
        - Audio loudness normalization
        """
        start_time = clip_info["start_time"]
        end_time = clip_info["end_time"]
        duration = round(end_time - start_time, 2)
        clip_id = clip_info.get("id", "clip")

        if not output_filename:
            output_filename = f"short_{clip_id}_{int(start_time)}_{int(end_time)}.mp4"
        final_output_path = os.path.join(self.output_dir, output_filename)

        logger.info(f"Rendering 9:16 Short ({duration}s): [cyan]{final_output_path}[/cyan]")

        # 1. Generate ASS subtitles
        ass_path = os.path.join(self.output_dir, f"temp_{clip_id}_{int(start_time)}.ass")
        has_subtitles = False
        if self.subtitles_enabled and words_list:
            try:
                self.subtitle_gen.generate_ass(words_list, start_time, end_time, ass_path)
                has_subtitles = os.path.exists(ass_path) and os.path.getsize(ass_path) > 100
            except Exception as e:
                logger.warning(f"Failed to generate ASS subtitles: {e}")

        # 2. Build FFmpeg Filtergraph
        # First part: Cropping to 9:16
        crop_filter = self.cropper.get_filter_complex()
        
        # If subtitles enabled, chain the ASS filter
        if has_subtitles:
            escaped_ass = escape_ffmpeg_filter_path(ass_path)
            # Chain subtitle burn to [v_cropped] output
            full_filter = f"{crop_filter};[v_cropped]ass='{escaped_ass}'[v_out]"
            v_map = "[v_out]"
        else:
            full_filter = crop_filter
            v_map = "[v_cropped]"

        # Audio filter
        audio_filter = "loudnorm=I=-14:LRA=11:TP=-1.5" if self.normalize_audio else "anull"

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_time:.2f}",
            "-to", f"{end_time:.2f}",
            "-i", source_video_path,
            "-filter_complex", full_filter,
            "-map", v_map,
            "-map", "0:a?",
            "-af", audio_filter,
            "-r", str(self.fps),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-ar", "44100",
            "-b:a", "192k",
            "-movflags", "+faststart",
            final_output_path
        ]

        logger.info(f"Starting FFmpeg rendering pipeline for clip {clip_id}...")
        success, stderr = run_ffmpeg_cmd(cmd, timeout=400)

        # Cleanup temporary subtitle file
        if os.path.exists(ass_path):
            try:
                os.remove(ass_path)
            except Exception:
                pass

        if not success or not os.path.exists(final_output_path):
            logger.error(f"Failed to render short video: {stderr[-500:]}")
            return None

        file_size_mb = os.path.getsize(final_output_path) / (1024 * 1024)
        logger.info(f"Rendered Short successfully ({file_size_mb:.2f} MB): [green]{final_output_path}[/green]")
        return final_output_path
