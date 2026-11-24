"""Small synchronous client for a local Ollama chat server.

The UI calls this client from a worker thread so model loading/generation never
blocks the Qt event loop. No prompt is sent outside the configured Ollama host.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AIEngineError(RuntimeError):
    """An actionable local Ollama connection or response error."""


class AIEngine:
    def __init__(self, host: str | None = None, model: str | None = None,
                 timeout: float = 180.0) -> None:
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")).rstrip("/")
        self.model = model or os.environ.get("JARVIS_OLLAMA_MODEL", "qwen2.5:3b")
        self.timeout = timeout
        cpu_count = max(1, os.cpu_count() or 4)
        default_threads = max(1, min(4, cpu_count // 2))
        try:
            configured_threads = int(os.environ.get("JARVIS_OLLAMA_THREADS", default_threads))
        except ValueError:
            configured_threads = default_threads
        self.num_threads = max(1, min(cpu_count, configured_threads))
        self._start_lock = threading.Lock()
        self._managed_server: subprocess.Popen | None = None

    def _server_reachable(self, timeout: float = 1.0) -> bool:
        request = Request(f"{self.host}/api/tags", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.status == 200
        except (OSError, URLError, ValueError):
            return False

    @staticmethod
    def _find_ollama_executable() -> str | None:
        configured = os.environ.get("OLLAMA_EXECUTABLE")
        candidates = [configured, shutil.which("ollama")]
        if os.name == "nt":
            local_app_data = os.environ.get("LOCALAPPDATA")
            program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
            if local_app_data:
                candidates.append(str(Path(local_app_data) / "Programs" / "Ollama" / "ollama.exe"))
            candidates.append(str(Path(program_files) / "Ollama" / "ollama.exe"))
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return candidate
        return None

    def ensure_server(self, startup_timeout: float = 20.0) -> bool:
        """Start the local Ollama server in the background when it is not already running."""
        if self._server_reachable():
            return True
        if urlparse(self.host).hostname not in ("127.0.0.1", "localhost", "::1"):
            return False
        with self._start_lock:
            if self._server_reachable():
                return True
            if self._managed_server is not None and self._managed_server.poll() is not None:
                self._managed_server = None
            if self._managed_server is None:
                executable = self._find_ollama_executable()
                if not executable:
                    return False
                creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                try:
                    self._managed_server = subprocess.Popen(
                        [executable, "serve"], stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=creation_flags,
                    )
                except OSError:
                    self._managed_server = None
                    return False
            deadline = time.monotonic() + startup_timeout
            while time.monotonic() < deadline:
                if self._server_reachable(timeout=1.0):
                    return True
                if self._managed_server.poll() is not None:
                    self._managed_server = None
                    return False
                time.sleep(0.4)
            return False

    def stop_managed_server(self) -> None:
        """Stop only the Ollama process this JARVIS instance started."""
        with self._start_lock:
            process = self._managed_server
            self._managed_server = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=4)
        except OSError:
            return
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                return

    def is_available(self) -> bool:
        if not self.ensure_server():
            return False
        request = Request(f"{self.host}/api/tags", headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=3) as response:
                if response.status != 200:
                    return False
                tags = json.loads(response.read().decode("utf-8"))
                return any(
                    model.get("name") == self.model or model.get("model") == self.model
                    for model in tags.get("models", [])
                )
        except (OSError, URLError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return False

    def respond(self, prompt: str, history: list[dict[str, str]] | None = None,
                language: str = "ko") -> str:
        prompt = prompt.strip()
        if not prompt:
            raise AIEngineError("질문을 입력해 주세요.")
        if not self.ensure_server():
            raise AIEngineError(
                "Ollama 서버를 시작하지 못했습니다. Ollama 설치 경로와 로컬 연결 상태를 확인하세요."
            )
        language_instruction = (
            "Answer in natural Korean. Do not use Chinese or Japanese characters."
            if language == "ko" else "Answer in natural English."
        )
        messages = [{
            "role": "system",
            "content": (
                "You are J.A.R.V.I.S., a concise and helpful desktop assistant. "
                f"{language_instruction} "
                "You are running locally on the user's computer. Never claim you performed "
                "an action unless a connected tool explicitly did it. Do not ask for or "
                "reveal passwords, API keys, or other secrets."
            ),
        }]
        # Keep only a few recent exchanges to bound memory and prompt size.
        messages.extend((history or [])[-4:])
        messages.append({"role": "user", "content": prompt})
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "30s",
            "options": {
                "temperature": 0.4,
                "num_predict": 192,
                "num_ctx": 1536,
                "num_batch": 128,
                "num_thread": self.num_threads,
            },
        }).encode("utf-8")
        request = Request(
            f"{self.host}/api/chat", data=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                raise AIEngineError(
                    f"Ollama에서 모델 '{self.model}'을 찾지 못했습니다. `ollama list`로 모델명을 확인하세요."
                ) from error
            raise AIEngineError(f"Ollama 요청 오류 (HTTP {error.code})") from error
        except (URLError, TimeoutError, OSError) as error:
            raise AIEngineError(
                "JARVIS가 Ollama 로컬 서버에 연결하지 못했습니다. 자동 시작 여부와 "
                "Windows의 로컬 연결 제한을 확인하세요."
            ) from error
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as error:
            raise AIEngineError("Ollama 응답을 읽지 못했습니다.") from error

        answer = result.get("message", {}).get("content", "").strip()
        if not answer:
            raise AIEngineError("Ollama가 빈 응답을 반환했습니다.")
        return answer
