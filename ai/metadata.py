import os
import json
import re
from typing import Dict, Any, List
from utils.logger import logger

class MetadataGenerator:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.uploader_cfg = config.get("uploader", {})
        self.clipping_cfg = config.get("clipping", {})
        self.provider = self.clipping_cfg.get("llm_provider", "gemini").lower()
        self.gemini_model = self.clipping_cfg.get("gemini_model", "gemini-3.6-flash")
        self.openai_model = self.clipping_cfg.get("openai_model", "gpt-4o-mini")
        self.default_tags = self.uploader_cfg.get("default_tags", ["Shorts", "viral", "trending"])
        self.credit_original = self.uploader_cfg.get("credit_original_creator", True)

    def _call_llm(self, prompt: str) -> str:
        if self.provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                res = client.models.generate_content(model=self.gemini_model, contents=prompt)
                return res.text
            except ImportError:
                import google.generativeai as genai_legacy
                genai_legacy.configure(api_key=api_key)
                m = genai_legacy.GenerativeModel(self.gemini_model)
                return m.generate_content(prompt).text
        else:
            api_key = os.getenv("OPENAI_API_KEY")
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            res = client.chat.completions.create(
                model=self.openai_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            return res.choices[0].message.content

    def generate_metadata(self, clip_info: Dict[str, Any], source_metadata: Dict[str, Any], clip_transcript: str) -> Dict[str, Any]:
        """
        Generates algorithmically optimized YouTube Shorts metadata:
        - Catchy Title (< 60 chars) with high curiosity gap
        - Description with #shorts and viral tags
        - Relevant keyword tags array
        """
        prompt = f"""
You are an expert YouTube Shorts algorithm strategist.
Create the perfect viral metadata for this YouTube Short clip.

Source Video Title: "{source_metadata.get('title', 'Unknown')}"
Original Channel: "{source_metadata.get('channel', 'Unknown')}"
Clip Hook: "{clip_info.get('hook', '')}"
Clip Transcript Snippet:
\"\"\"{clip_transcript[:500]}\"\"\"

REQUIREMENTS:
1. Title: Under 60 characters total. Must trigger intense curiosity or emotion. Include 1 relevant emoji. Do NOT use generic titles like 'Interesting Moment'. Make it feel urgent or shocking.
2. Description: 2-3 engaging sentences summarizing the clip, a question to drive comments, and 4-6 hashtags (MUST include #shorts, #viral, #trending).
3. Tags: 8-12 concise, highly searched keyword tags.

Respond ONLY with valid JSON:
{{
  "title": "Viral Hook Title 🤯 #shorts",
  "description": "Engaging description text... \\n\\n#shorts #viral #trending #podcast",
  "tags": ["shorts", "viral", "keyword1", "keyword2"]
}}
"""
        logger.info("Generating SEO-optimized viral metadata via LLM...")
        try:
            raw_text = self._call_llm(prompt)
            # Parse JSON
            cleaned = raw_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
            else:
                data = json.loads(cleaned)

            title = data.get("title", clip_info.get("working_title", "Unbelievable Moment 🤯 #shorts"))
            # Ensure #shorts in title or description
            if "#shorts" not in title.lower() and len(title) <= 50:
                title = f"{title} #shorts"

            description = data.get("description", "Watch till the end! #shorts #viral")
            if self.credit_original:
                orig_channel = source_metadata.get("channel", "")
                orig_url = source_metadata.get("url", "")
                credit_text = f"\n\nOriginal Content by: {orig_channel}\nFull video: {orig_url}"
                description += credit_text

            tags = list(set(data.get("tags", []) + self.default_tags))[:15]

            return {
                "title": title[:100],
                "description": description,
                "tags": tags
            }

        except Exception as e:
            logger.error(f"Error generating metadata: {e}")
            # Fallback metadata
            fallback_title = f"{clip_info.get('working_title', 'Viral Moment')} 🤯 #shorts"[:60]
            fallback_desc = f"Did you know this? Watch till the end!\n\n#shorts #viral #trending"
            if self.credit_original:
                fallback_desc += f"\n\nSource: {source_metadata.get('channel', 'Creator')}"
            return {
                "title": fallback_title,
                "description": fallback_desc,
                "tags": self.default_tags
            }
