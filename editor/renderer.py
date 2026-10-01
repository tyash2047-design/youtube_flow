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
        self.dynamic_cuts = config.get("video", {}).get("dynamic_cuts", True)
        self.normalize_audio = config.get("video", {}).get("normalize_audio", True)
        self.subtitles_enabled = config.get("subtitles", {}).get("enabled", True)
        
        # Audio design config
        self.audio_cfg = config.get("audio_design", {})
        self.bgm_enabled = self.audio_cfg.get("bgm_enabled", True)
        self.bgm_volume = self.audio_cfg.get("bgm_volume", 0.14)
        self.memes_enabled = self.audio_cfg.get("memes_enabled", True)
        self.meme_volume = self.audio_cfg.get("meme_volume", 0.85)

    def _resolve_bgm_path(self, track_name: Optional[str]) -> Optional[str]:
        """Resolves background music file path from assets/music/."""
        if not track_name or track_name == "none":
            return None
        music_dir = "assets/music"
        # Try direct match
        for ext in [".mp3", ".wav", ".ogg"]:
            candidate = os.path.join(music_dir, f"{track_name}{ext}")
            if os.path.exists(candidate) and os.path.getsize(candidate) > 1000:
                return candidate
        # Try any available track in music_dir
        if os.path.exists(music_dir):
            files = [os.path.join(music_dir, f) for f in os.listdir(music_dir) if f.endswith(".mp3") and os.path.getsize(os.path.join(music_dir, f)) > 1000]
            if files:
                return files[0]
        return None

    def _resolve_sfx_path(self, sfx_name: Optional[str]) -> Optional[str]:
        """Resolves meme sound effect file path from assets/sfx/."""
        if not sfx_name or sfx_name in ("none", "null"):
            return None
        sfx_dir = "assets/sfx"
        clean = sfx_name.lower().replace("-", "_").replace(" ", "_")
        for ext in [".mp3", ".wav"]:
            candidate = os.path.join(sfx_dir, f"{clean}{ext}")
            if os.path.exists(candidate) and os.path.getsize(candidate) > 1000:
                return candidate
        return None

    def render_short(
        self,
        source_video_path: str,
        clip_info: Dict[str, Any],
        words_list: List[Dict[str, Any]],
        output_filename: Optional[str] = None
    ) -> Optional[str]:
        """
        Renders an Autonomous Director 9:16 vertical YouTube Short with:
        - Exact start/end trimming (15-50s)
        - 9:16 vertical re-framing (cinematic blur)
        - Dynamic camera cuts / punch zooms (alternating 1.0x and 1.18x every 4s)
        - Word-by-word animated subtitles burned in (Hinglish/English)
        - AI-selected background music ducked at -22dB with outro fade
        - AI-timed meme sound effects (vine boom, bruh, etc.) on punchlines
        - EBU R128 loudness normalization
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

        # 2. Build Video Filtergraph
        crop_filter = self.cropper.get_filter_complex()
        
        # Determine dynamic camera cuts
        use_cuts = clip_info.get("dynamic_cuts", self.dynamic_cuts)
        if use_cuts:
            # Alternates between 1.0x wide (1080x1920) and 1.18x punch zoom (915x1627) every 4 seconds
            v_chain = f"{crop_filter};[v_cropped]crop=w='if(mod(floor(t/4),2), 915, 1080)':h='if(mod(floor(t/4),2), 1627, 1920)':x='(1080-out_w)/2':y='(1920-out_h)/2',scale=1080:1920[v_cuts]"
            v_target = "[v_cuts]"
        else:
            v_chain = crop_filter
            v_target = "[v_cropped]"

        if has_subtitles:
            escaped_ass = escape_ffmpeg_filter_path(ass_path)
            full_v_filter = f"{v_chain};{v_target}ass='{escaped_ass}'[v_out]"
            v_map = "[v_out]"
        else:
            full_v_filter = v_chain
            v_map = v_target

        # 3. Build Audio Filtergraph with BGM and Meme SFX
        cmd_inputs = [
            "-ss", f"{start_time:.2f}",
            "-to", f"{end_time:.2f}",
            "-i", source_video_path
        ]
        
        next_input_idx = 1
        a_mix_labels = ["[0:a]"]
        a_filter_parts = []

        # Background Music (BGM)
        bgm_track = clip_info.get("bgm_track") or ("sneaky_comedy" if "laugh" in str(clip_info).lower() or "joke" in str(clip_info).lower() else "gaming_upbeat")
        bgm_path = self._resolve_bgm_path(bgm_track) if self.bgm_enabled else None
        if bgm_path:
            cmd_inputs.extend(["-stream_loop", "-1", "-i", bgm_path])
            a_filter_parts.append(f"[{next_input_idx}:a]volume={self.bgm_volume},afade=t=out:st={max(0.0, duration-1.5):.2f}:d=1.5[a_bgm]")
            a_mix_labels.append("[a_bgm]")
            next_input_idx += 1
            logger.info(f"Adding Background Music: [cyan]{os.path.basename(bgm_path)}[/cyan] (vol: {self.bgm_volume})")

        # Meme SFX
        meme_sfx = clip_info.get("meme_sfx")
        meme_offset = float(clip_info.get("meme_offset", 0.0) or clip_info.get("meme_offset_seconds", 0.0) or 0.0)
        meme_path = self._resolve_sfx_path(meme_sfx) if (self.memes_enabled and meme_sfx) else None
        if meme_path and meme_offset > 0.0 and meme_offset < duration:
            cmd_inputs.extend(["-i", meme_path])
            delay_ms = int(meme_offset * 1000)
            a_filter_parts.append(f"[{next_input_idx}:a]adelay={delay_ms}|{delay_ms},volume={self.meme_volume}[a_meme]")
            a_mix_labels.append("[a_meme]")
            next_input_idx += 1
            logger.info(f"Adding Meme SFX: [yellow]{os.path.basename(meme_path)}[/yellow] at {meme_offset:.2f}s")

        # Assemble audio mix
        if len(a_mix_labels) > 1:
            mix_inputs_str = "".join(a_mix_labels)
            amix_filter = f"{mix_inputs_str}amix=inputs={len(a_mix_labels)}:duration=first:dropout_transition=2"
            if self.normalize_audio:
                amix_filter += ",loudnorm=I=-14:LRA=11:TP=-1.5"
            a_filter_parts.append(f"{amix_filter}[a_out]")
            audio_graph = ";".join(a_filter_parts)
            a_map = "[a_out]"
        else:
            audio_graph = "[0:a]loudnorm=I=-14:LRA=11:TP=-1.5[a_out]" if self.normalize_audio else "[0:a]anull[a_out]"
            a_map = "[a_out]"

        full_filter_complex = f"{full_v_filter};{audio_graph}"

        cmd = [
            "ffmpeg", "-y",
            *cmd_inputs,
            "-filter_complex", full_filter_complex,
            "-map", v_map,
            "-map", a_map,
            "-r", str(self.fps),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-ar", "44100",
            "-b:a", "192k",
            "-t", f"{duration:.2f}",
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
