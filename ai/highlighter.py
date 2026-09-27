import os
import json
import re
from typing import List, Dict, Any, Optional
from utils.logger import logger

class HighlightDetector:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.clip_cfg = config.get("clipping", {})
        self.min_clip_sec = self.clip_cfg.get("min_clip_seconds", 15)
        self.max_clip_sec = self.clip_cfg.get("max_clip_seconds", 50)
        self.max_clips = self.clip_cfg.get("max_clips_per_source", 3)
        self.min_retention_score = self.clip_cfg.get("min_retention_score", 7.5)
        self.provider = self.clip_cfg.get("llm_provider", "gemini").lower()
        self.gemini_model = self.clip_cfg.get("gemini_model", "gemini-3.6-flash")
        self.openai_model = self.clip_cfg.get("openai_model", "gpt-4o-mini")

    def _call_gemini(self, prompt: str) -> str:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in environment variables. Please add it to your .env file.")

        # Try official modern google-genai SDK first
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=self.gemini_model,
                contents=prompt
            )
            return response.text
        except ImportError:
            pass

        # Try google.generativeai legacy package
        try:
            import google.generativeai as genai_legacy
            genai_legacy.configure(api_key=api_key)
            model = genai_legacy.GenerativeModel(self.gemini_model)
            response = model.generate_content(prompt)
            return response.text
        except ImportError:
            raise RuntimeError("Please install google-genai by running: pip install google-genai")

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

        # Create a compressed timestamped transcript representation
        transcript_lines = []
        for s in segments:
            transcript_lines.append(f"[{s['start']:.1f}s - {s['end']:.1f}s]: {s['text']}")
        formatted_transcript = "\n".join(transcript_lines[:400]) # Cap input if massive

        prompt = f"""
You are a world-class YouTube Shorts producer and algorithm retention specialist.
Analyze this video transcript and identify the TOP {self.max_clips} most viral, high-retention clip moments.

Video Title: "{video_metadata.get('title', 'Unknown')}"
Channel: "{video_metadata.get('channel', 'Unknown')}"

TRANSCRIPT WITH TIMESTAMPS:
\"\"\"
{formatted_transcript}
\"\"\"

CRITICAL REQUIREMENTS:
1. STRICT DURATION RULE: Every clip's duration (end_time - start_time) MUST be between {self.min_clip_sec} and {self.max_clip_sec} seconds. Never exceed {self.max_clip_sec}s. Never go below {self.min_clip_sec}s.
2. HOOK RULE: The first 3 seconds of the clip MUST contain a curiosity gap, shocking statement, high-stakes question, or captivating hook that stops viewers from swiping away.
3. COHESION RULE: The segment must be a self-contained story, idea, or funny interaction with a clear punchline, conclusion, or cliffhanger.
4. Retention Score: Score each candidate clip from 1.0 to 10.0 based on viral potential.
5. Only return clips with a score of {self.min_retention_score} or higher.

Return ONLY a raw JSON array matching this exact schema:
[
  {{
    "start_time": 124.5,
    "end_time": 158.2,
    "hook": "Exact opening words that grab attention",
    "working_title": "Short punchy internal title",
    "viral_score": 9.4,
    "reason": "Why this specific 15-50s moment will achieve 100%+ retention on YouTube Shorts"
  }}
]
"""

        logger.info(f"Querying {self.provider.upper()} for viral highlight detection...")
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
                duration = round(end - start, 2)
                score = float(c.get("viral_score", 0))

                # Strictly validate 15-50 second rule
                if duration < self.min_clip_sec or duration > self.max_clip_sec:
                    logger.debug(f"Rejecting candidate clip duration {duration}s outside bounds ({self.min_clip_sec}-{self.max_clip_sec}s)")
                    continue

                if score < self.min_retention_score:
                    continue

                valid_clips.append({
                    "start_time": start,
                    "end_time": end,
                    "duration": duration,
                    "hook": c.get("hook", ""),
                    "working_title": c.get("working_title", "Viral Highlight"),
                    "viral_score": score,
                    "reason": c.get("reason", "")
                })
            except Exception as e:
                logger.warning(f"Error parsing candidate clip: {e}")

        # Sort by viral score descending and cap at max_clips
        valid_clips.sort(key=lambda x: x["viral_score"], reverse=True)
        final_clips = valid_clips[:self.max_clips]
        logger.info(f"Highlight detector selected {len(final_clips)} viral clips (duration: 15-50s).")
        return final_clips
