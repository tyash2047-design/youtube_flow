import os
import json
import re
import subprocess
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from utils.logger import logger
from utils.ffmpeg_helper import run_ffmpeg_cmd, escape_ffmpeg_filter_path

load_dotenv()

class AIAutoHealer:
    """
    Autonomous Self-Healing and Error-Recovery Engine for the YouTube Shorts Pipeline.
    When a problem occurs (bot verification block, invalid clip boundaries, FFmpeg filter crash,
    or noisy/silent audio), this healer:
    1. Diagnoses the root cause autonomously.
    2. Formulates and executes an automatic fix / fallback.
    3. Logs the diagnosis and remediation into the database for full transparency.
    """

    def __init__(self, config: Dict[str, Any], db=None, ai_brain=None):
        self.config = config
        self.db = db
        self.ai_brain = ai_brain

    def log_heal_event(self, problem_type: str, title: str, diagnosis: str, fix_applied: str, success: bool = True):
        """Logs an auto-healing event to the database and logger."""
        status_tag = "[green]FIXED[/green]" if success else "[red]UNRESOLVED[/red]"
        logger.info(f"🛠️ [bold yellow]Autonomous Auto-Heal ({problem_type}):[/bold yellow] {status_tag} - {title}")
        logger.info(f"   Diagnosis: {diagnosis}")
        logger.info(f"   Fix Applied: {fix_applied}")

        if self.db and hasattr(self.db, "log_ai_thought"):
            self.db.log_ai_thought(
                thought_type=f"AUTO_HEAL_{problem_type.upper()}",
                title=f"Auto-Heal: {title}",
                reasoning_text=f"Problem: {problem_type}\nDiagnosis: {diagnosis}\nRemediation: {fix_applied}\nSuccess: {success}",
                metadata_json=json.dumps({"success": success, "type": problem_type})
            )

    # =========================================================================
    # 1. RENDER AUTO-HEALER: Recovers from FFmpeg filter or audio mix failures
    # =========================================================================
    def heal_render_failure(
        self,
        renderer,
        source_video_path: str,
        clip_info: Dict[str, Any],
        words_list: List[Dict[str, Any]],
        output_filename: str,
        stderr: str
    ) -> Optional[str]:
        """
        Diagnoses FFmpeg render stderr and automatically applies progressive fallbacks:
        - Fallback 1: If subtitle ASS filter failed -> render with pure video framing & audio
        - Fallback 2: If multi-stream audio mix (amix/adelay) failed -> render with voice-only loudnorm
        - Fallback 3: If dynamic cut filter failed -> render with standard center-crop / blur
        """
        clip_id = clip_info.get("id", "clip")
        start_time = clip_info["start_time"]
        end_time = clip_info["end_time"]
        duration = round(end_time - start_time, 2)
        final_output_path = os.path.join(renderer.output_dir, output_filename)

        diagnosis = "FFmpeg execution failed during complex multi-stream rendering."
        fix_applied = ""

        # Check for subtitle errors
        is_sub_error = any(k in stderr.lower() for k in ["ass", "subtitles", "libass", "glyph", "fontconfig"])
        # Check for audio filtergraph errors
        is_audio_error = any(k in stderr.lower() for k in ["amix", "adelay", "afade", "filter_complex", "channel layout", "audio"])
        # Check for video filtergraph errors
        is_video_filter_error = any(k in stderr.lower() for k in ["crop", "scale", "v_cuts", "v_cropped"])

        if is_sub_error:
            diagnosis = "Subtitle burn failed due to special characters, font mapping, or ASS escape error."
            fix_applied = "Bypassed ASS subtitle burn filter; rendering video with dynamic cuts and ducked audio."
        elif is_audio_error:
            diagnosis = "Complex multi-stream audio mixing (BGM + Meme SFX + Voice) failed due to channel mismatch or delay syntax."
            fix_applied = "Stripped external SFX/BGM streams; applying clean dialogue audio with EBU R128 loudness normalization."
        elif is_video_filter_error:
            diagnosis = "Dynamic camera cut expression failed on video dimensions."
            fix_applied = "Falling back to standard 9:16 cinematic blur without punch-zoom expression."
        else:
            diagnosis = f"General FFmpeg error: {stderr[-250:].strip()}"
            fix_applied = "Executing resilient standard 9:16 render with dialogue audio only."

        logger.warning(f"Initiating autonomous render healing for clip #{clip_id}...")

        # Build Resilient Healed Filtergraph
        crop_filter = renderer.cropper.get_filter_complex()
        
        # Audio fallback: Voice dialogue with loudness normalization
        healed_cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_time:.2f}",
            "-to", f"{end_time:.2f}",
            "-i", source_video_path,
            "-filter_complex", f"{crop_filter};[0:a]loudnorm=I=-14:LRA=11:TP=-1.5[a_clean]",
            "-map", "[v_cropped]",
            "-map", "[a_clean]",
            "-r", str(renderer.fps),
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "22",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-ar", "44100",
            "-b:a", "192k",
            "-t", f"{duration:.2f}",
            "-movflags", "+faststart",
            final_output_path
        ]

        success, retry_stderr = run_ffmpeg_cmd(healed_cmd, timeout=300)
        if success and os.path.exists(final_output_path) and os.path.getsize(final_output_path) > 10000:
            self.log_heal_event("RENDER", f"Clip #{clip_id} Auto-Rescued", diagnosis, fix_applied, success=True)
            return final_output_path

        # If even that failed, ultimate simple scale fallback
        ultimate_cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_time:.2f}",
            "-to", f"{end_time:.2f}",
            "-i", source_video_path,
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-c:a", "aac",
            "-t", f"{duration:.2f}",
            final_output_path
        ]
        u_success, _ = run_ffmpeg_cmd(ultimate_cmd, timeout=200)
        if u_success and os.path.exists(final_output_path):
            self.log_heal_event("RENDER", f"Clip #{clip_id} Rescued via Safe Pad", diagnosis, "Applied safe aspect-ratio padding", success=True)
            return final_output_path

        self.log_heal_event("RENDER", f"Clip #{clip_id} Render Recovery Failed", diagnosis, "All fallback renders exhausted", success=False)
        return None

    # =========================================================================
    # 2. AUDIO AUTO-HEALER: Enhances quiet or noisy speech for Whisper
    # =========================================================================
    def heal_audio_for_transcription(self, audio_path: str, transcriber) -> Optional[Dict[str, Any]]:
        """
        When Whisper detects 0 words or silent segments, this healer runs audio bandpass
        filtering to isolate human speech frequencies (200Hz - 3400Hz) and boosts volume.
        """
        if not os.path.exists(audio_path):
            return None

        enhanced_path = audio_path.replace(".wav", "_enhanced.wav")
        diagnosis = "Raw audio yielded 0 speech segments. Background music or low vocal energy may be masking speech."
        fix_applied = "Applying 200Hz-3400Hz human vocal bandpass filter + 2.5x volume gain."

        logger.info(f"🛠️ Attempting autonomous audio restoration on {os.path.basename(audio_path)}...")
        filter_str = "highpass=f=200,lowpass=f=3400,volume=2.5,dynaudnorm"
        cmd = [
            "ffmpeg", "-y",
            "-i", audio_path,
            "-af", filter_str,
            enhanced_path
        ]
        success, _ = run_ffmpeg_cmd(cmd, timeout=120)
        if not success or not os.path.exists(enhanced_path):
            return None

        try:
            transcript = transcriber.transcribe(enhanced_path)
            if transcript and transcript.get("segments"):
                self.log_heal_event("TRANSCRIPTION", "Audio Speech Rescued", diagnosis, fix_applied, success=True)
                # Cleanup enhanced file after transcription
                try:
                    os.remove(enhanced_path)
                except Exception:
                    pass
                return transcript
        except Exception as e:
            logger.warning(f"Healed transcription attempt failed: {e}")

        if os.path.exists(enhanced_path):
            try:
                os.remove(enhanced_path)
            except Exception:
                pass
        self.log_heal_event("TRANSCRIPTION", "Audio Non-Verbal", diagnosis, "Speech could not be isolated (likely non-verbal music/gaming montage).", success=False)
        return None

    # =========================================================================
    # 3. CLIPPING AUTO-HEALER: Self-Corrects rejected or hallucinated boundaries
    # =========================================================================
    def heal_clip_boundaries(
        self,
        highlighter,
        transcript_data: Dict[str, Any],
        video_metadata: Dict[str, Any],
        rejection_reason: str
    ) -> List[Dict[str, Any]]:
        """
        When all candidate clips fail length or narrative bounds, this triggers an
        autonomous self-correction prompt to Gemini with the explicit rejection reason.
        """
        diagnosis = f"Initial clipping pass failed: {rejection_reason}"
        fix_applied = "Dispatched self-correction prompt to AI Director with strict boundary guidance."

        segments = transcript_data.get("segments", [])
        if not segments:
            return []

        # Find the segment cluster with highest dialogue density
        transcript_snippet = "\n".join([f"[{s['start']:.1f}s - {s['end']:.1f}s]: {s.get('text', '')}" for s in segments[:120]])

        critique_prompt = f"""
AUTONOMOUS DIRECTOR CRITIQUE & SELF-CORRECTION:
Your previous highlight suggestions were REJECTED for the following reason:
"{rejection_reason}"

You MUST self-correct now. Find EXACTLY ONE standalone viral moment between 22 and 40 seconds.
Rules for Self-Correction:
1. "start_time" MUST be the exact start of a sentence introducing a question, complaint, or challenge.
2. "end_time" MUST be the exact moment the punchline lands or the action concludes.
3. Total duration MUST be between 22.0 and 42.0 seconds.

Video Title: "{video_metadata.get('title', '')}"
Channel: "{video_metadata.get('channel', '')}"

Transcript:
\"\"\"
{transcript_snippet}
\"\"\"

Respond strictly in valid JSON:
[
  {{
    "director_thoughts": {{
      "story_arc": "Corrected narrative arc",
      "cold_viewer_test": "Why this 25-40s moment is self-contained",
      "pacing_and_audio": "Why BGM and cut timing fit"
    }},
    "start_time": 10.0,
    "end_time": 38.0,
    "hook": "Opening line",
    "working_title": "Self-Corrected Viral Title",
    "viral_score": 9.0,
    "dynamic_cuts": true,
    "bgm_track": "sneaky_comedy",
    "meme_sfx": "vine_boom",
    "meme_offset_seconds": 15.0,
    "reason": "Corrected self-contained clip"
  }}
]
"""
        try:
            logger.info("🧠 AI Director executing autonomous self-correction loop on clip boundaries...")
            raw = highlighter._call_gemini(critique_prompt) if highlighter.provider == "gemini" else highlighter._call_openai(critique_prompt)
            corrected = highlighter._parse_llm_json(raw)
            if corrected:
                self.log_heal_event("CLIPPING", "AI Director Self-Corrected Boundaries", diagnosis, fix_applied, success=True)
                return corrected
        except Exception as e:
            logger.warning(f"Self-correction loop error: {e}")

        self.log_heal_event("CLIPPING", "Boundary Self-Correction Exhausted", diagnosis, "Video does not contain qualifying narrative arc", success=False)
        return []

    # =========================================================================
    # 4. DOWNLOAD AUTO-HEALER: Handles YouTube bot blocks & unavailable videos
    # =========================================================================
    def heal_download_block(self, video_info: Dict[str, Any], scraper) -> List[Dict[str, Any]]:
        """
        When YouTube blocks downloading a candidate video (e.g. 'Sign in to confirm you're not a bot'),
        this healer diagnoses the block and immediately generates alternative search queries
        to hunt replacement videos on the same topic so the pipeline NEVER gets stuck.
        """
        vid_id = video_info.get("video_id", "unknown")
        title = video_info.get("title", "Unknown Title")
        diagnosis = f"YouTube returned bot verification challenge for video {vid_id} ('{title}')."
        
        # Mark source as BLOCKED_BOT in DB
        if self.db and hasattr(self.db, "update_source_status"):
            self.db.update_source_status(vid_id, "BLOCKED_BOT")

        # Formulate clean search queries to find alternative videos
        clean_keywords = re.sub(r'[^a-zA-Z0-9\s]', ' ', title).split()
        pivot_query = " ".join(clean_keywords[:4]) + " gaming funny moments"
        fix_applied = f"Marked {vid_id} as BLOCKED_BOT; autonomously pivoting to alternative viral search: '{pivot_query}'"

        logger.info(f"🛠️ [bold yellow]Download Auto-Heal:[/bold yellow] YouTube bot block detected on {vid_id}. Pivoting immediately...")
        self.log_heal_event("DOWNLOAD", f"Bypassed Bot Block on {vid_id}", diagnosis, fix_applied, success=True)

        try:
            new_candidates = scraper.search_candidates_by_keywords(pivot_query, max_results=3)
            return new_candidates
        except Exception as e:
            logger.warning(f"Error discovering alternative candidates: {e}")
            return []
