"""Offline, multilingual microphone capture and speech recognition."""

import os
import time
from pathlib import Path


class VoiceInputUnavailable(RuntimeError):
    """Microphone or offline speech recognition is unavailable."""


class VoiceEngine:
    """Record until silence and transcribe locally with multilingual Whisper tiny."""

    SAMPLE_RATE = 16_000
    MAX_RECORD_SECONDS = 15
    NO_SPEECH_TIMEOUT_SECONDS = 8
    END_SILENCE_SECONDS = 1.0
    _model = None

    @classmethod
    def _load_model(cls):
        model_name = os.environ.get("JARVIS_WHISPER_MODEL", "tiny")
        model_dir = Path(os.environ.get(
            "JARVIS_VOICE_MODEL_DIR",
            str(Path(__file__).resolve().parents[2] / ".models" / f"whisper-{model_name}"),
        ))
        os.environ["HF_HOME"] = str(model_dir / "hf-home")
        os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise VoiceInputUnavailable(
                "음성 인식 패키지가 없습니다. 프로젝트 폴더에서 `pip install -r requirements.txt`를 실행하세요."
            ) from error

        try:
            model_dir.mkdir(parents=True, exist_ok=True)
            cls._model = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=2,
                num_workers=1,
                download_root=str(model_dir),
            )
        except Exception as error:
            raise VoiceInputUnavailable(
                "오프라인 음성 모델을 준비하지 못했습니다. 인터넷 연결과 프로젝트 폴더의 여유 공간을 확인하세요."
            ) from error
        return cls._model

    @classmethod
    def listen_once(cls) -> str:
        try:
            import sounddevice as sd
        except ImportError as error:
            raise VoiceInputUnavailable(
                "마이크 입력 패키지가 없습니다. 프로젝트의 requirements.txt를 설치하세요."
            ) from error
        try:
            import numpy as np
        except ImportError as error:
            raise VoiceInputUnavailable("numpy 패키지를 찾지 못했습니다.") from error

        try:
            import psutil
            minimum_free_memory = 512 * 1024 * 1024
            if psutil.virtual_memory().available < minimum_free_memory:
                raise VoiceInputUnavailable(
                    "사용 가능한 메모리가 부족합니다. 다른 앱을 닫은 뒤 다시 시도해 주세요."
                )
            devices = sd.query_devices()
            if not any(device.get("max_input_channels", 0) > 0 for device in devices):
                raise VoiceInputUnavailable(
                    "사용 가능한 마이크가 없습니다. Windows에서 마이크를 연결하고 앱 권한을 확인하세요."
                )
            audio = cls._record_until_silence(sd, np)
        except VoiceInputUnavailable:
            raise
        except Exception as error:
            raise VoiceInputUnavailable(
                "마이크를 열지 못했습니다. Windows 마이크 권한과 기본 입력 장치를 확인하세요."
            ) from error

        signal = np.asarray(audio, dtype=np.float32).reshape(-1)
        if signal.size == 0 or float(np.max(np.abs(signal))) < 0.003:
            raise VoiceInputUnavailable("음성이 감지되지 않았습니다. 마이크 입력을 확인하고 다시 말씀해 주세요.")

        if psutil.virtual_memory().available < 512 * 1024 * 1024:
            raise VoiceInputUnavailable(
                "사용 가능한 메모리가 부족합니다. 다른 앱을 닫은 뒤 다시 시도해 주세요."
            )
        model = cls._model or cls._load_model()
        try:
            segments, _info = model.transcribe(
                signal,
                language=None,
                task="transcribe",
                beam_size=5,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as error:
            raise VoiceInputUnavailable("음성을 변환하지 못했습니다. 다시 또렷하게 말씀해 주세요.") from error
        finally:
            # Keep RAM available for the local chat model on low-memory laptops.
            cls._model = None
            if "segments" in locals():
                del segments
            del model
            import gc
            gc.collect()
        if not text:
            raise VoiceInputUnavailable("음성을 인식하지 못했습니다. 마이크 가까이에서 다시 말씀해 주세요.")
        return text

    @classmethod
    def _record_until_silence(cls, sounddevice, numpy):
        frame_seconds = 0.1
        frame_size = int(cls.SAMPLE_RATE * frame_seconds)
        max_frames = int(cls.MAX_RECORD_SECONDS / frame_seconds)
        no_speech_frames = int(cls.NO_SPEECH_TIMEOUT_SECONDS / frame_seconds)
        silence_frames_needed = int(cls.END_SILENCE_SECONDS / frame_seconds)
        frames = []
        noise_levels = []
        speech_started = False
        silent_frames = 0
        started_at = time.monotonic()

        with sounddevice.InputStream(
            samplerate=cls.SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=frame_size,
        ) as stream:
            for index in range(max_frames):
                block, _overflowed = stream.read(frame_size)
                audio_frame = numpy.asarray(block, dtype=numpy.float32).reshape(-1)
                frames.append(audio_frame.copy())
                rms = float(numpy.sqrt(numpy.mean(numpy.square(audio_frame))))

                if not speech_started and index < 5:
                    noise_levels.append(rms)
                noise_floor = float(numpy.median(noise_levels)) if noise_levels else 0.0
                threshold = max(0.004, min(0.025, noise_floor * 2.5))

                if rms >= threshold or (index < 5 and rms >= 0.018):
                    speech_started = True
                    silent_frames = 0
                elif speech_started:
                    silent_frames += 1
                    if silent_frames >= silence_frames_needed:
                        break
                elif index >= no_speech_frames:
                    break

                if time.monotonic() - started_at >= cls.MAX_RECORD_SECONDS:
                    break

        if not speech_started:
            raise VoiceInputUnavailable("음성이 감지되지 않았어요. 마이크 가까이에서 다시 말해 주세요.")
        return numpy.concatenate(frames)
