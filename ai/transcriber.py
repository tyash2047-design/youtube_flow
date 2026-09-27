import os
from typing import List, Dict, Any, Optional
from utils.logger import logger

class Transcriber:
    def __init__(self, model_size: str = "small", device: str = "auto"):
        self.model_size = model_size
        self.device = device
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return

        # Attempt to load faster-whisper first (much faster on CPU and CUDA)
        try:
            from faster_whisper import WhisperModel
            import ctranslate2
            cuda_count = 0
            try:
                cuda_count = ctranslate2.get_cuda_device_count()
            except Exception:
                pass
            dev = "cuda" if (self.device == "cuda" or (self.device == "auto" and cuda_count > 0)) else "cpu"
            compute_type = "float16" if dev == "cuda" else "int8"
            logger.info(f"Loading faster-whisper ({self.model_size}) on [cyan]{dev}[/cyan] ({compute_type})...")
            self._model = WhisperModel(self.model_size, device=dev, compute_type=compute_type)
            self._backend = "faster-whisper"
            return
        except Exception as e:
            logger.warning(f"Could not initialize faster-whisper: {e}")
            pass

        # Fallback to standard openai-whisper
        try:
            import whisper
            dev = "cpu"
            try:
                import torch
                if self.device == "cuda" or (self.device == "auto" and torch.cuda.is_available()):
                    dev = "cuda"
            except Exception:
                pass
            logger.info(f"Loading openai-whisper ({self.model_size}) on [cyan]{dev}[/cyan]...")
            self._model = whisper.load_model(self.model_size, device=dev)
            self._backend = "openai-whisper"
            return
        except Exception as e:
            logger.warning(f"Could not initialize openai-whisper: {e}")
            pass

        raise RuntimeError(
            "Neither 'faster-whisper' nor 'openai-whisper' is functional.\n"
            "Please run: pip install faster-whisper"
        )

    def transcribe(self, audio_file: str) -> Dict[str, Any]:
        """
        Transcribes audio with word-level timestamps.
        Returns a standardized dictionary with segments and word timings.
        """
        self._load_model()
        logger.info(f"Starting word-level transcription for: {audio_file}")

        if not os.path.exists(audio_file):
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

        segments_data = []
        full_text_list = []

        if self._backend == "faster-whisper":
            segments, info = self._model.transcribe(
                audio_file,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            for seg in segments:
                words = []
                if seg.words:
                    for w in seg.words:
                        clean_word = w.word.strip()
                        if clean_word:
                            words.append({
                                "word": clean_word,
                                "start": round(w.start, 2),
                                "end": round(w.end, 2)
                            })
                segments_data.append({
                    "id": seg.id,
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": seg.text.strip(),
                    "words": words
                })
                full_text_list.append(seg.text.strip())

        elif self._backend == "openai-whisper":
            result = self._model.transcribe(audio_file, word_timestamps=True)
            for seg in result.get("segments", []):
                words = []
                for w in seg.get("words", []):
                    clean_word = w.get("word", "").strip()
                    if clean_word:
                        words.append({
                            "word": clean_word,
                            "start": round(w.get("start", 0.0), 2),
                            "end": round(w.get("end", 0.0), 2)
                        })
                segments_data.append({
                    "id": seg.get("id", 0),
                    "start": round(seg.get("start", 0.0), 2),
                    "end": round(seg.get("end", 0.0), 2),
                    "text": seg.get("text", "").strip(),
                    "words": words
                })
                full_text_list.append(seg.get("text", "").strip())

        logger.info(f"Transcription complete: extracted {len(segments_data)} segments.")
        return {
            "full_text": " ".join(full_text_list),
            "segments": segments_data
        }
