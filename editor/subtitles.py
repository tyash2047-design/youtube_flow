import os
from typing import List, Dict, Any
from utils.logger import logger

def format_ass_time(seconds: float) -> str:
    """Converts seconds into ASS time format: H:MM:SS.cs"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

class SubtitleGenerator:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.sub_cfg = config.get("subtitles", {})
        self.enabled = self.sub_cfg.get("enabled", True)
        self.font_name = self.sub_cfg.get("font_name", "Arial Black")
        self.font_size = self.sub_cfg.get("font_size", 46)
        self.words_per_burst = self.sub_cfg.get("words_per_burst", 3)
        self.highlight_color = self.sub_cfg.get("highlight_color", "&H0000FFFF&") # Bright Yellow
        self.primary_color = self.sub_cfg.get("primary_color", "&H00FFFFFF&")     # White
        self.outline_color = self.sub_cfg.get("outline_color", "&H00000000&")     # Black
        self.outline_width = self.sub_cfg.get("outline_width", 4.5)
        self.shadow_depth = self.sub_cfg.get("shadow_depth", 2.0)
        self.enable_pop = self.sub_cfg.get("enable_scale_pop", True)
        
        # Vertical placement: safe from bottom 25% UI (margin calculated for 1920 height)
        # MarginV = 560 places text at ~70% from top (30% from bottom)
        v_pct = self.sub_cfg.get("vertical_position", 0.68)
        self.margin_v = int(1920 * (1.0 - v_pct))

    def generate_ass(self, words_list: List[Dict[str, Any]], clip_start: float, clip_end: float, output_ass_path: str) -> str:
        """
        Creates an Alex Hormozi style ASS subtitle file with animated active word highlights.
        Timestamps are normalized relative to clip_start (0.0s).
        """
        os.makedirs(os.path.dirname(os.path.abspath(output_ass_path)), exist_ok=True)

        # Filter words strictly belonging to this clip window and normalize timestamps
        clip_words = []
        for w in words_list:
            w_start = w.get("start", 0.0)
            w_end = w.get("end", 0.0)
            if w_end > clip_start and w_start < clip_end:
                norm_start = max(0.0, w_start - clip_start)
                norm_end = min(clip_end - clip_start, w_end - clip_start)
                clean_text = w.get("word", "").strip().upper()
                if clean_text and norm_end > norm_start:
                    clip_words.append({
                        "word": clean_text,
                        "start": norm_start,
                        "end": norm_end
                    })

        if not clip_words:
            logger.warning("No words found for subtitle generation in clip window.")
            # Return empty or dummy ASS file
            with open(output_ass_path, "w", encoding="utf-8") as f:
                f.write("[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n[Events]\n")
            return output_ass_path

        # Group words into bursts of 2-4 words
        bursts = []
        current_burst = []
        for w in clip_words:
            current_burst.append(w)
            if len(current_burst) >= self.words_per_burst:
                bursts.append(current_burst)
                current_burst = []
        if current_burst:
            bursts.append(current_burst)

        # Build ASS dialogues
        dialogue_lines = []
        scale_tag = r"\fscx115\fscy115" if self.enable_pop else ""

        for burst in bursts:
            burst_start = burst[0]["start"]
            burst_end = burst[-1]["end"]

            for i, target_word in enumerate(burst):
                w_start = target_word["start"]
                w_end = target_word["end"]
                
                # Active window for this specific word
                line_start = format_ass_time(w_start)
                line_end = format_ass_time(w_end)

                # Assemble burst text with current word highlighted
                styled_parts = []
                for j, word_item in enumerate(burst):
                    word_str = word_item["word"]
                    if i == j:
                        # Highlight active word with scale pop and highlight color
                        styled_parts.append(f"{{\\c{self.highlight_color}{scale_tag}}}{word_str}{{\\rDefault}}")
                    else:
                        styled_parts.append(word_str)

                text_content = " ".join(styled_parts)
                dialogue_lines.append(
                    f"Dialogue: 0,{line_start},{line_end},Default,,0,0,0,,{text_content}"
                )

        ass_content = f"""[Script Info]
Title: Hormozi Style Viral Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{self.font_name},{self.font_size},{self.primary_color},&H000000FF&,{self.outline_color},&H80000000&,-1,0,0,0,100,100,1.5,0,1,{self.outline_width},{self.shadow_depth},2,40,40,{self.margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(dialogue_lines) + "\n"

        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)

        logger.debug(f"Generated animated ASS subtitles: {output_ass_path}")
        return output_ass_path
