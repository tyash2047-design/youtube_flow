from typing import Dict, Any

class VideoCropper:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.video_cfg = config.get("video", {})
        self.out_w = self.video_cfg.get("output_width", 1080)
        self.out_h = self.video_cfg.get("output_height", 1920)
        self.framing_mode = self.video_cfg.get("framing_mode", "cinematic_blur")
        self.blur_intensity = self.video_cfg.get("blur_intensity", 25)

    def get_filter_complex(self) -> str:
        """
        Generates the FFmpeg filtergraph string for converting landscape 16:9 to portrait 9:16.
        """
        w = self.out_w
        h = self.out_h

        if self.framing_mode == "center_crop":
            # Scale height to 1920, then crop the center 1080px
            return f"[0:v]scale=-2:{h},crop={w}:{h}:(in_w-{w})/2:0[v_cropped]"

        # Default: Cinematic Blurred Backdrop Stack
        # 1. Background: scale to fill 1080x1920, crop, apply heavy blur
        # 2. Foreground: scale to width 1080 keeping original aspect ratio (height ~608)
        # 3. Overlay foreground centered on blurred background
        blur = self.blur_intensity
        filter_str = (
            f"[0:v]split=2[bg_in][fg_in];"
            f"[bg_in]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur={blur}:5[bg_blurred];"
            f"[fg_in]scale={w}:-2[fg_scaled];"
            f"[bg_blurred][fg_scaled]overlay=(W-w)/2:(H-h)/2[v_cropped]"
        )
        return filter_str
