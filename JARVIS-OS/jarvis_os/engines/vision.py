"""Local-only Ollama vision client used for opt-in screen descriptions."""

import base64
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psutil

MIN_SCREEN_FREE_GIB = 2.5


class VisionEngineError(RuntimeError):
    """Actionable local vision-model errors."""


class VisionEngine:
    def __init__(self, host: str | None = None, model: str | None = None,
                 timeout: float = 90.0) -> None:
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("JARVIS_VISION_MODEL", "moondream:latest")
        self.timeout = timeout
        cpu_count = max(1, os.cpu_count() or 4)
        self.num_threads = max(1, min(cpu_count, max(1, cpu_count // 2)))

    @staticmethod
    def available_memory_gib() -> float:
        return psutil.virtual_memory().available / (1024 ** 3)

    def check_model(self) -> bool:
        request = Request(f"{self.host}/api/tags", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=3) as response:
                tags = json.loads(response.read().decode("utf-8"))
            return any(item.get("name") == self.model or item.get("model") == self.model
                       for item in tags.get("models", []))
        except (OSError, URLError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return False

    def is_model_loaded(self) -> bool:
        request = Request(f"{self.host}/api/ps", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=3) as response:
                loaded = json.loads(response.read().decode("utf-8"))
            return any(item.get("name") == self.model or item.get("model") == self.model
                       for item in loaded.get("models", []))
        except (OSError, URLError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return False

    def unload(self) -> None:
        """Ask the local Ollama server to release the vision model from RAM."""
        if not self.is_model_loaded():
            return
        payload = json.dumps({
            "model": self.model, "prompt": "", "stream": False, "keep_alive": 0,
        }).encode("utf-8")
        request = Request(
            f"{self.host}/api/generate", data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                response.read()
        except (HTTPError, URLError, TimeoutError, OSError):
            # Ollama's normal keep-alive timeout is the fallback if explicit unload fails.
            return

    def describe(self, image: bytes, language: str = "ko") -> str:
        if (self.available_memory_gib() < MIN_SCREEN_FREE_GIB
                and not self.is_model_loaded()):
            raise VisionEngineError(
                f"여유 메모리가 {MIN_SCREEN_FREE_GIB:.1f}GiB보다 적어 화면 분석을 잠시 중단했습니다."
            )
        instruction = (
            "Describe the visible screen in concise natural Korean. Focus on the active app, "
            "visible content, and any obvious issue. Ignore the JARVIS HUD overlay. "
            "Do not infer hidden content or take actions."
            if language == "ko" else
            "Describe the visible screen concisely in English. Focus on the active app, "
            "visible content, and obvious issues. Ignore the JARVIS HUD overlay. "
            "Do not infer hidden content or take actions."
        )
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": instruction,
                          "images": [base64.b64encode(image).decode("ascii")]}],
            "stream": False,
            "keep_alive": "30s",
            "options": {
                "temperature": 0.2,
                "num_predict": 96,
                "num_ctx": 1024,
                "num_batch": 96,
                "num_thread": self.num_threads,
            },
        }).encode("utf-8")
        request = Request(f"{self.host}/api/chat", data=payload,
                          headers={"Content-Type": "application/json", "Accept": "application/json"},
                          method="POST")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                raise VisionEngineError(
                    f"Ollama 비전 모델 '{self.model}'을 찾지 못했습니다. "
                    "모델을 준비한 뒤 다시 켜 주세요."
                ) from error
            raise VisionEngineError(f"Ollama 화면 분석 오류 (HTTP {error.code})") from error
        except (URLError, TimeoutError, OSError) as error:
            raise VisionEngineError("Ollama에 연결할 수 없습니다. Ollama 실행 상태를 확인하세요.") from error
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
            raise VisionEngineError("화면 분석 응답을 읽지 못했습니다.") from error
        answer = result.get("message", {}).get("content", "").strip()
        if not answer:
            raise VisionEngineError("비전 모델이 빈 설명을 반환했습니다.")
        return answer
