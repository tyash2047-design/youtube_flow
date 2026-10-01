import os
import json
import re
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from utils.logger import logger

load_dotenv()

class HighlightDetector:
    def __init__(self, config: Dict[str, Any], db=None):
        load_dotenv()
        self.config = config
        self.db = db
        self.clip_cfg = config.get("clipping", {})
        self.min_clip_sec = self.clip_cfg.get("min_clip_seconds", 15)
        self.max_clip_sec = self.clip_cfg.get("max_clip_seconds", 50)
        self.max_clips = self.clip_cfg.get("max_clips_per_source", 3)
        self.min_retention_score = self.clip_cfg.get("min_retention_score", 7.5)
        self.provider = self.clip_cfg.get("llm_provider", "gemini").lower()
        self.gemini_model = self.clip_cfg.get("gemini_model", "gemini-3.5-flash-lite")
        self.openai_model = self.clip_cfg.get("openai_model", "gpt-4o-mini")

    def _call_gemini(self, prompt: str) -> str:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables. Please add it to your .env file.")

        models_to_try = [self.gemini_model, "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash"]
        last_err = None
        for m in models_to_try:
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                response = client.models.generate_content(
                    model=m,
                    contents=prompt
                )
                if response and response.text:
                    return response.text
            except Exception as e:
                last_err = e
                continue

        try:
            import google.generativeai as genai_legacy
            genai_legacy.configure(api_key=api_key)
            model = genai_legacy.GenerativeModel("gemini-1.5-flash")
            response = model.generate_content(prompt)
            return response.text
        except Exception:
            raise last_err or RuntimeError("All Gemini models failed.")

    def _call_openai(self, prompt: str) -> str:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY not found in environment variables.")
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=self.openai_model,
            messages=[
                {"role": "system", "content": "You are an elite short-form content producer specializing in YouTube Shorts algorithms."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content

    def _parse_llm_json(self, raw_text: str) -> List[Dict[str, Any]]:
        """Cleans and extracts JSON array from LLM output."""
        cleaned = raw_text.strip()
        # Remove markdown code fences if present
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        
        # Match outermost bracket
        match = re.search(r"\[\s*\{.*\}\s*\]", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)

        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and "clips" in data:
                return data["clips"]
        except Exception as e:
            logger.error(f"Failed to parse LLM JSON: {e}\nRaw text was:\n{raw_text[:500]}")
        return []

    def detect_highlights(self, transcript_data: Dict[str, Any], video_metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Analyzes the transcript segments to identify peak engaging moments strictly between
        min_clip_seconds (15s) and max_clip_seconds (50s).
        """
        segments = transcript_data.get("segments", [])
        if not segments:
            logger.warning("No transcript segments provided to highlight detector.")
            return []

        # Create a timestamped transcript representation (support full video up to 2500 segments)
        transcript_lines = []
        is_hindi_detected = False
        for s in segments:
            text = s.get("text", "")
            transcript_lines.append(f"[{s['start']:.1f}s - {s['end']:.1f}s]: {text}")
            if not is_hindi_detected and any(0x0900 <= ord(c) <= 0x097F or 0x0600 <= ord(c) <= 0x06FF for c in text):
                is_hindi_detected = True

        channel_name = video_metadata.get("channel", "").lower()
        title_text = video_metadata.get("title", "").lower()
        if any(k in channel_name or k in title_text for k in ["shubh", "sshhuubb", "slayy", "ayush", "bhandari", "carry", "techno", "mythpat", "rawknee", "gaming", "hindi"]):
            is_hindi_detected = True

        formatted_transcript = "\n".join(transcript_lines[:2500])

        language_instruction = (
            "LANGUAGE REQUIREMENT (MANDATORY CONVERSATIONAL HINGLISH):\n"
            "This video is from an Indian channel / in Hindi. You MUST write all titles, hooks, and context in modern, trendy conversational HINGLISH "
            "(Latin alphabet / English letters, e.g. 'Bhai Wolverine Game Me Ye Kya Ho Gaya?! 🤯', 'Bhai ne ye kya bol diya?! 💀'). "
            "STRICTLY FORBIDDEN: NEVER use Devanagari script (हिंदी) or Urdu script under any circumstances! Do NOT use plain formal English for Hindi jokes."
            if is_hindi_detected else
            "LANGUAGE REQUIREMENT:\nUse the native language of the video (in Latin/English script)."
        )

        prompt = f"""
You are an elite Autonomous AI Video Director and viral YouTube Shorts master editor.
Instead of mechanically slicing random moments, you must THINK on your own like a multi-million-subscriber content creator and video editor.

Read this video transcript, understand the full story, creator, language, and comedy style.
Identify the TOP {self.max_clips} VIRAL SELF-CONTAINED SHORTS.

Video Title: "{video_metadata.get('title', 'Unknown')}"
Channel: "{video_metadata.get('channel', 'Unknown')}"

TRANSCRIPT WITH TIMESTAMPS:
\"\"\"
{formatted_transcript}
\"\"\"

CRITICAL DIRECTOR & VIRALITY RULES (DO NOT VIOLATE):
1. COMPLETE STANDALONE CONTEXT (MANDATORY):
   - A viewer scrolling YouTube Shorts has NEVER seen this 20-minute video.
   - The clip MUST make 100% complete sense on its own with ZERO outside knowledge.
   - SETUP: The clip MUST start right when the story, challenge, funny discussion, or event is INTRODUCED. Never start after the setup has already happened.
   - NO RANDOM TIMES: DO NOT pick random shouts, laughter, or ongoing fights where the viewer doesn't know who is being fought, why the creator is reacting, or what the goal is.
   - FORBIDDEN: Starting a clip with "Like I said earlier", "So guys next up", or right in the middle of a scream without the preceding cause.
   - PUNCHLINE / RESOLUTION: The clip MUST contain the full payoff, outcome, joke landing, or conclusion. Never cut off before the punchline or mid-sentence!

2. ZERO MID-SENTENCE CUTS:
   - "start_time" MUST be the exact start of a complete sentence or new thought.
   - "end_time" MUST be the exact end of a complete sentence or natural pause.
   - Never start or end in the middle of a spoken sentence or thought.

3. DURATION RULE:
   - Aim for 25 to 45 seconds so there is ample time for:
     [1] Hook/Premise Setup (5-8s) -> [2] Action/Conflict (15-25s) -> [3] Hilarious Resolution/Punchline (5-8s).
   - Reject any moment that cannot deliver a complete narrative within {self.min_clip_sec}-{self.max_clip_sec}s.

4. SOUND DESIGN & MEMES ("MEMES SOMETIMES"):
   - "bgm_track": Choose the background music track that elevates this moment:
     * "sneaky_comedy" (for funny, sarcastic, awkward, or goofy moments)
     * "gaming_upbeat" (for gaming, intense action, high energy, or epic moments)
     * "none" (if the speaker is already very loud and dramatic)
   - "meme_sfx": Use meme sound effects SOMETIMES (only when there is an actual punchline, joke landing, fail, or shock):
     * "vine_boom" (for sudden shock, revelation, or awkward silence)
     * "bruh" (for epic fails, dumb choices, or facepalms)
     * "huh" (for bizarre, confused, or unexpected moments)
     * "ding" (for a sudden realization or genius idea)
     * "wow" (for an impressive action or sarcastic praise)
     * null (if this specific clip is serious or does not need a meme sound)
   - "meme_offset_seconds": Exact relative timestamp from clip start (e.g. 18.5) where the meme SFX should hit!

5. {language_instruction}

Return ONLY a raw JSON array matching this exact schema:
[
  {{
    "director_thoughts": {{
      "story_arc": "Setup -> Escalation -> Punchline narrative breakdown",
      "cold_viewer_test": "Why a stranger who has never seen this channel will 100% understand this clip in 3 seconds",
      "pacing_and_audio": "Why dynamic cuts and this specific BGM/meme SFX elevate the retention"
    }},
    "start_time": 124.5,
    "end_time": 158.2,
    "hook": "Exact opening words that grab attention",
    "working_title": "Punchy Hinglish Title",
    "viral_score": 9.5,
    "setup_dialogue": "Exact first spoken line that gives the viewer the context",
    "punchline_dialogue": "Exact last spoken line that concludes the moment",
    "dynamic_cuts": true,
    "bgm_track": "sneaky_comedy",
    "meme_sfx": "vine_boom",
    "meme_offset_seconds": 21.4,
    "reason": "Why this 25-45s moment makes 100% sense to someone who has never seen the full video"
  }}
]
"""

        logger.info(f"Querying Autonomous AI Director ({self.provider.upper()}) for viral shorts (Hindi/Hinglish mode: {is_hindi_detected})...")
        try:
            if self.provider == "gemini":
                raw_response = self._call_gemini(prompt)
            else:
                raw_response = self._call_openai(prompt)
        except Exception as e:
            logger.error(f"Error calling {self.provider}: {e}")
            return []

        candidates = self._parse_llm_json(raw_response)
        valid_clips = []

        for c in candidates:
            try:
                start = float(c.get("start_time", 0))
                end = float(c.get("end_time", 0))

                # Smart sentence/segment boundary snapping to avoid cutting words in half
                snapped_start = start
                snapped_end = end
                closest_start_diff = 999
                closest_end_diff = 999

                for s in segments:
                    s_start = s.get("start", 0)
                    s_end = s.get("end", 0)
                    if abs(s_start - start) < closest_start_diff and abs(s_start - start) <= 2.5:
                        closest_start_diff = abs(s_start - start)
                        snapped_start = s_start
                    if abs(s_end - end) < closest_end_diff and abs(s_end - end) <= 2.5:
                        closest_end_diff = abs(s_end - end)
                        snapped_end = s_end

                duration = round(snapped_end - snapped_start, 2)
                score = float(c.get("viral_score", 0))

                # Strictly validate 15-50 second rule
                if duration < self.min_clip_sec or duration > self.max_clip_sec:
                    logger.debug(f"Rejecting candidate clip duration {duration}s outside bounds ({self.min_clip_sec}-{self.max_clip_sec}s)")
                    continue

                if score < self.min_retention_score:
                    continue

                # Parse AI director audio & editing choices
                bgm_choice = c.get("bgm_track", "gaming_upbeat")
                meme_choice = c.get("meme_sfx")
                if meme_choice in ("none", "null", ""):
                    meme_choice = None
                meme_offset = float(c.get("meme_offset_seconds", 0.0) or c.get("meme_offset", 0.0) or 0.0)

                director_thoughts = c.get("director_thoughts", {})
                thought_summary = (
                    f"Story: {director_thoughts.get('story_arc', '')}\n"
                    f"Cold Test: {director_thoughts.get('cold_viewer_test', '')}\n"
                    f"Pacing: {director_thoughts.get('pacing_and_audio', '')}"
                ) if director_thoughts else c.get("reason", "")

                # Record reasoning in Database for live web dashboard
                if self.db and hasattr(self.db, "log_ai_thought"):
                    self.db.log_ai_thought(
                        thought_type="DIRECTOR_DECISION",
                        title=f"Director Vision: {c.get('working_title', 'Viral Short')}",
                        reasoning_text=thought_summary,
                        metadata_json=json.dumps({
                            "start": snapped_start,
                            "end": snapped_end,
                            "score": score,
                            "bgm": bgm_choice,
                            "meme": meme_choice
                        })
                    )

                valid_clips.append({
                    "start_time": snapped_start,
                    "end_time": snapped_end,
                    "duration": duration,
                    "hook": c.get("hook", ""),
                    "working_title": c.get("working_title", "Viral Highlight"),
                    "viral_score": score,
                    "reason": c.get("reason", ""),
                    "director_thoughts": director_thoughts,
                    "dynamic_cuts": c.get("dynamic_cuts", True),
                    "bgm_track": bgm_choice,
                    "meme_sfx": meme_choice,
                    "meme_offset": meme_offset
                })
            except Exception as e:
                logger.warning(f"Error parsing candidate clip: {e}")

        # Sort by viral score descending and cap at max_clips
        valid_clips.sort(key=lambda x: x["viral_score"], reverse=True)
        final_clips = valid_clips[:self.max_clips]
        logger.info(f"Highlight detector selected {len(final_clips)} viral clips with verified narrative context (duration: 15-50s).")
        return final_clips
