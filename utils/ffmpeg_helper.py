import os
import shutil
import subprocess
import json
from typing import List, Optional, Tuple
from .logger import logger

def get_ffmpeg_path() -> str:
    """Finds or retrieves the FFmpeg executable path."""
    # 1. Check if 'ffmpeg' is on system PATH
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    # 2. Try imageio_ffmpeg if installed
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except ImportError:
        pass

    # 3. Check common Windows installation paths
    common_paths = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-*\bin\ffmpeg.exe"),
    ]
    for p in common_paths:
        if "*" in p:
            import glob
            matches = glob.glob(p)
            if matches and os.path.exists(matches[0]):
                return matches[0]
        elif os.path.exists(p):
            return p

    raise RuntimeError(
        "FFmpeg not found! Please install it by running in PowerShell:\n"
        "  winget install Gyan.FFmpeg\n"
        "Or install imageio-ffmpeg via:\n"
        "  pip install imageio-ffmpeg"
    )

def get_ffprobe_path() -> Optional[str]:
    """Finds or retrieves the FFprobe executable path if available."""
    system_ffprobe = shutil.which("ffprobe")
    if system_ffprobe:
        return system_ffprobe

    # Often located next to ffmpeg
    try:
        ffmpeg = get_ffmpeg_path()
        bin_dir = os.path.dirname(ffmpeg)
        candidate = os.path.join(bin_dir, "ffprobe.exe" if os.name == "nt" else "ffprobe")
        if os.path.exists(candidate):
            return candidate
    except Exception:
        pass
    return None

def run_ffmpeg_cmd(cmd: List[str], timeout: int = 600) -> Tuple[bool, str]:
    """
    Executes an FFmpeg command list.
    Replaces 'ffmpeg' with the discovered executable path.
    """
    try:
        ffmpeg_exe = get_ffmpeg_path()
        if cmd[0] in ("ffmpeg", "ffmpeg.exe"):
            cmd[0] = ffmpeg_exe

        logger.debug(f"Executing FFmpeg: {' '.join(cmd)}")
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace"
        )
        if result.returncode != 0:
            logger.error(f"FFmpeg command failed with return code {result.returncode}:\n{result.stderr[-1000:]}")
            return False, result.stderr
        return True, result.stdout
    except subprocess.TimeoutExpired:
        logger.error(f"FFmpeg command timed out after {timeout} seconds")
        return False, "Timed out"
    except Exception as e:
        logger.error(f"Error running FFmpeg: {e}")
        return False, str(e)

def get_media_duration(file_path: str) -> float:
    """Returns the duration of an audio or video file in seconds."""
    ffprobe = get_ffprobe_path()
    if ffprobe:
        cmd = [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
            if res.returncode == 0:
                return float(res.stdout.strip())
        except Exception:
            pass

    # Fallback to ffmpeg parse
    try:
        ffmpeg_exe = get_ffmpeg_path()
        cmd = [ffmpeg_exe, "-i", file_path]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        # Parse Duration: 00:01:23.45 from stderr
        for line in res.stderr.splitlines():
            if "Duration:" in line:
                part = line.split("Duration:")[1].split(",")[0].strip()
                h, m, s = part.split(":")
                return float(h) * 3600 + float(m) * 60 + float(s)
    except Exception as e:
        logger.warning(f"Could not read duration for {file_path}: {e}")
    return 0.0
