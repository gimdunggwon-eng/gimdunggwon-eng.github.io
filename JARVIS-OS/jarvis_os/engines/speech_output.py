"""Local Korean/English text-to-speech using Supertonic ONNX."""

import gc
import os
import re
import threading
from pathlib import Path


class SpeechOutputError(RuntimeError):
    """Local speech generation or playback failed."""


class SpeechOutputEngine:
    SAMPLE_RATE = 44_100
    _stop_requested = threading.Event()
    _jarvis_name = re.compile(
        r"(?i)\bJ\s*\.?\s*A\s*\.?\s*R\s*\.?\s*V\s*\.?\s*I\s*\.?\s*S\.?(?!\w)"
    )

    @staticmethod
    def stop() -> None:
        SpeechOutputEngine._stop_requested.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    @classmethod
    def speak(cls, text: str) -> None:
        text = cls._normalize_pronunciation(text.strip())
        if not text:
            return
        if len(text) > 1200:
            text = text[:1200].rsplit(" ", 1)[0] + "…"

        model_dir = Path(__file__).resolve().parents[2] / ".models" / "supertonic3"
        os.environ["HF_HOME"] = str(model_dir / "hf-home")
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        try:
            import numpy as np
            import psutil
            import sounddevice as sd
            from supertonic import TTS
        except ImportError as error:
            raise SpeechOutputError(
                "음성 출력 패키지를 찾지 못했습니다. 프로젝트 requirements.txt를 설치하세요."
            ) from error

        if psutil.virtual_memory().available < 512 * 1024 * 1024:
            raise SpeechOutputError(
                "음성 출력에 사용할 메모리가 부족합니다. 다른 앱을 닫고 다시 시도해 주세요."
            )

        tts = None
        cls._stop_requested.clear()
        try:
            tts = TTS(
                model="supertonic-3",
                model_dir=model_dir,
                auto_download=True,
                intra_op_num_threads=2,
                inter_op_num_threads=1,
            )
            voice_name = os.environ.get("JARVIS_TTS_VOICE", "M1")
            try:
                speed = float(os.environ.get("JARVIS_TTS_SPEED", "1.5"))
            except ValueError:
                speed = 1.5
            speed = max(0.7, min(2.0, speed))
            style = tts.get_voice_style(voice_name=voice_name)
            language = "ko" if re.search(r"[\uac00-\ud7a3]", text) else "en"
            for chunk in cls._split_text(text):
                if cls._stop_requested.is_set():
                    break
                wav, _duration = tts.synthesize(
                    text=chunk, lang=language, voice_style=style,
                    total_steps=8, speed=speed,
                )
                if cls._stop_requested.is_set():
                    break
                audio = np.asarray(wav, dtype=np.float32).reshape(-1)
                sd.play(audio, samplerate=cls.SAMPLE_RATE)
                sd.wait()
        except SpeechOutputError:
            raise
        except Exception as error:
            raise SpeechOutputError(
                "음성 응답을 만들거나 재생하지 못했습니다. 스피커와 오디오 출력을 확인하세요."
            ) from error
        finally:
            del tts
            gc.collect()

    @classmethod
    def _normalize_pronunciation(cls, text: str) -> str:
        if not text:
            return text
        spoken_name = "자비스" if re.search(r"[\uac00-\ud7a3]", text) else "Jarvis"
        return cls._jarvis_name.sub(spoken_name, text)

    @staticmethod
    def _split_text(text: str, max_length: int = 280) -> list[str]:
        sentences = re.split(r"(?<=[.!?。！？])\s+", text)
        chunks: list[str] = []
        current = ""
        for sentence in sentences:
            sentence = sentence.strip()
            while len(sentence) > max_length:
                cut = sentence.rfind(" ", 0, max_length)
                if cut < 1:
                    cut = max_length
                part, sentence = sentence[:cut].strip(), sentence[cut:].strip()
                if current:
                    chunks.append(current)
                    current = ""
                chunks.append(part)
            if not sentence:
                continue
            if current and len(current) + len(sentence) + 1 > max_length:
                chunks.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            chunks.append(current)
        return chunks or [text]
