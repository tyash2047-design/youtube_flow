import os
import json
import re
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from utils.logger import logger

load_dotenv()

class AIBrain:
    """
    The Autonomous Cognitive Engine for the YouTube Shorts Pipeline.
    Instead of following rigid scripts, this brain:
    1. Thinks on its own about viral content strategy and real-time search angles.
    2. Exercises creative director judgment with Chain-of-Thought reasoning.
    3. Conducts the 'Cold Stranger Test' to guarantee complete standalone context.
    4. Directs audio pacing, dynamic punch-zooms, and contextual meme sound effects.
    5. Crafts curiosity-gap titles, descriptions, and debate-provoking pinned comments.
    """

    def __init__(self, config: Dict[str, Any], db=None):
        self.config = config
        self.db = db
        clipping_cfg = config.get("clipping", {})
        self.provider = clipping_cfg.get("llm_provider", "gemini").lower()
        self.gemini_model = clipping_cfg.get("gemini_model", "gemini-3.5-flash-lite")
        self.openai_model = clipping_cfg.get("openai_model", "gpt-4o-mini")

    def _call_llm(self, prompt: str) -> str:
        """Calls LLM with fallback support across Gemini models."""
        if self.provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                raise ValueError("GEMINI_API_KEY environment variable is missing.")

            # Try primary model then fallback models
            models_to_try = [self.gemini_model, "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.6-flash"]
            last_err = None
            for model_name in models_to_try:
                try:
                    from google import genai
                    client = genai.Client(api_key=api_key)
                    res = client.models.generate_content(model=model_name, contents=prompt)
                    if res and res.text:
                        return res.text
                except Exception as e:
                    last_err = e
                    continue

            # Legacy fallback
            try:
                import google.generativeai as genai_legacy
                genai_legacy.configure(api_key=api_key)
                m = genai_legacy.GenerativeModel("gemini-1.5-flash")
                return m.generate_content(prompt).text
            except Exception:
                raise last_err or RuntimeError("Gemini models failed.")
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

    def _parse_json(self, raw_text: str) -> Any:
        cleaned = raw_text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)
        return json.loads(cleaned)

    def think_content_strategy(self, recent_topics: Optional[List[str]] = None) -> List[Dict[str, str]]:
        """
        Autonomously brainstorms viral content discovery strategies and search queries.
        The AI thinks about what YouTube audiences are craving today in gaming, comedy,
        and high-engagement creator moments.
        """
        prompt = f"""
You are the Executive Content Strategist of an autonomous 24/7 YouTube Shorts channel.
You do NOT rely on static, boring search terms. You THINK on your own about what is blowing up on YouTube right now.

Target Audience & Niches:
- High-energy gaming chaos & funny streamer reactions (e.g. GTA 5 stunts, Minecraft trolling, horror game scares, insane clutches)
- Trending Indian/Hinglish gaming & comedy creators (e.g. Shub / sshhuubb, Slayy Point, CarryMinati, Mythpat, Techno Gamerz, Ayush Bhandari)
- Shocking viral real-world stunts & wild challenges (e.g. MrBeast gaming challenges, WhistlinDiesel destruction)

Already Covered Recently:
{json.dumps(recent_topics or [])}

TASK:
1. Reason about audience psychology: What title premise or thumbnail concept makes a viewer STOP scrolling instantly?
2. Generate 4 fresh, highly effective YouTube search queries designed to find long-form videos packed with viral highlight moments.

Respond STRICTLY in valid JSON:
{{
  "thought_process": "Your internal reasoning as an AI strategist about audience psychology, trending themes, and why these queries will find gold",
  "strategies": [
    {{
      "niche": "Hinglish Gaming Comedy",
      "search_query": "specific search string to run on YouTube",
      "creative_angle": "What kind of moments we are hunting for (e.g., unexpected fail, funny rage, price shock)"
    }},
    {{
      "niche": "High Stakes Stunt / Chaos",
      "search_query": "specific search string",
      "creative_angle": "reasoning"
    }},
    {{
      "niche": "Trending Streamer Banter",
      "search_query": "specific search string",
      "creative_angle": "reasoning"
    }},
    {{
      "niche": "Viral Challenge Moments",
      "search_query": "specific search string",
      "creative_angle": "reasoning"
    }}
  ]
}}
"""
        logger.info("🧠 AI Brain is autonomously thinking about current content strategy and viral angles...")
        try:
            raw = self._call_llm(prompt)
            data = self._parse_json(raw)
            thought = data.get("thought_process", "")
            strategies = data.get("strategies", [])
            logger.info(f"🧠 AI Content Strategist Thought: [italic cyan]{thought[:160]}...[/italic cyan]")
            
            # Log to DB if available
            if self.db and hasattr(self.db, "log_ai_thought"):
                self.db.log_ai_thought(
                    thought_type="CONTENT_STRATEGY",
                    title="Autonomous Viral Discovery Plan",
                    reasoning_text=thought,
                    metadata_json=json.dumps(strategies)
                )
            return strategies
        except Exception as e:
            logger.warning(f"AI content strategy thinking fallback: {e}")
            return [
                {"niche": "Hinglish Gaming", "search_query": "Shub funniest gaming highlights", "creative_angle": "Relatable gamer comedy"},
                {"niche": "Stunts", "search_query": "WhistlinDiesel insane stunts moments", "creative_angle": "Pure destruction and shock value"}
            ]

    def think_pinned_comment(self, short_title: str, short_hook: str, is_hindi: bool = True) -> str:
        """
        Autonomously crafts a high-engagement pinned comment designed to trigger passionate debate
        or laughs in the comments section, driving YouTube algorithm metrics.
        """
        lang_instruction = "Write in witty conversational Hinglish (Latin alphabet only; e.g. 'Aapke saath kabhi aisa hua hai? 😂 Batao comments me!')." if is_hindi else "Write in snappy English."
        prompt = f"""
You are a viral YouTube Shorts audience growth hacker.
Craft the single perfect pinned comment for this Short to maximize viewer comments and debate.

Short Title: "{short_title}"
Short Premise: "{short_hook}"
Language: {lang_instruction}

Guidelines:
- Ask an opinionated or funny question that makes people WANT to comment their opinion.
- Keep it under 2 sentences.
- Include 1 emoji.

Return ONLY the plain comment text without quotes.
"""
        try:
            res = self._call_llm(prompt).strip().strip('"')
            return res
        except Exception:
            return "Aapke saath kabhi aisa hua hai? 😂 Comments me batao!" if is_hindi else "Would you have done this? 😂 Drop your thoughts below!"
