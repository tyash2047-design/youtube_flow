import os
import sys
import logging

try:
    from rich.logging import RichHandler
    HAS_RICH = True
except ImportError:
    HAS_RICH = False

def setup_logger(name: str = "yt_pipeline", log_file: str = "data/pipeline.log") -> logging.Logger:
    """Configures a colorized console logger using rich (or standard StreamHandler fallback) and file output."""
    log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Avoid duplicate handlers if re-initialized
    if logger.handlers:
        return logger

    # Console Handler
    if HAS_RICH:
        console_handler = RichHandler(
            rich_tracebacks=True,
            show_time=True,
            show_path=False,
            markup=True
        )
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    
    console_handler.setLevel(log_level)
    logger.addHandler(console_handler)

    # File Handler
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s]: %(message)s"
        )
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
    except Exception:
        pass

    return logger

logger = setup_logger()
