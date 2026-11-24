from dataclasses import dataclass
from datetime import datetime
import re

from jarvis_os.engines.desktop import DesktopEngine
from jarvis_os.engines.security import SecurityEngine
from jarvis_os.engines.system_monitor import SystemMonitor


@dataclass(frozen=True)
class CommandResult:
    text: str
    success: bool


class CommandRouter:
    """Routes bilingual local commands and allowlisted desktop actions."""

    ALIASES = {
        "help": "help", "도움말": "help", "명령어": "help", "뭘 할 수 있어": "help",
        "무엇을 도와줄 수 있어": "help", "사용 방법": "help",
        "status": "status", "상태": "status", "현재 상태": "status",
        "시스템 상태": "status", "시스템 상태 알려줘": "status", "컴퓨터 상태": "status",
        "컴퓨터 상태 알려줘": "status", "cpu 사용량": "status", "cpu 사용률 알려줘": "status",
        "메모리 사용량": "status", "메모리 사용량 알려줘": "status", "램 사용량": "status",
        "램 얼마나 남았어": "status",
        "time": "time", "시간": "time", "현재 시간": "time", "현재 시각": "time",
        "현재 시간 알려줘": "time", "시간 알려줘": "time", "몇 시야": "time", "지금 몇 시": "time",
        "uptime": "uptime", "가동 시간": "uptime", "가동시간": "uptime",
        "가동 시간 알려줘": "uptime", "얼마나 켜져 있어": "uptime", "컴퓨터 켜진 시간": "uptime",
        "open notepad": "notepad", "메모장 열기": "notepad", "메모장": "notepad",
        "메모장 켜": "notepad", "메모장 켜줘": "notepad", "메모장 열어줘": "notepad",
        "메모장 실행": "notepad", "메모장 실행해": "notepad",
        "open calculator": "calculator", "계산기 열기": "calculator", "계산기": "calculator",
        "계산기 켜": "calculator", "계산기 켜줘": "calculator", "계산기 열어줘": "calculator",
        "계산기 실행": "calculator", "계산기 실행해": "calculator",
    }

    def __init__(self, monitor: SystemMonitor | None = None,
                 desktop: DesktopEngine | None = None,
                 security: SecurityEngine | None = None) -> None:
        self.monitor = monitor or SystemMonitor()
        self.desktop = desktop or DesktopEngine()
        self.security = security or SecurityEngine()
        self.language = "ko"

    def set_language(self, language: str) -> None:
        self.language = "ko" if language.lower().startswith("ko") else "en"

    def handle(self, raw_command: str) -> CommandResult:
        text = re.sub(r"\s+", " ", raw_command.strip().lower())
        text = re.sub(r"[?!.,。！？]+$", "", text)
        korean = self.language == "ko" or any("\uac00" <= char <= "\ud7a3" for char in text)
        command = self.ALIASES.get(text)
        if command is None and korean:
            if any(phrase in text for phrase in ("몇 시", "몇시", "시간 알려", "현재 시각", "지금 시각")):
                command = "time"
            elif any(phrase in text for phrase in ("가동 시간", "가동시간", "얼마나 켜져", "켜진 시간")):
                command = "uptime"
            elif any(phrase in text for phrase in (
                "상태", "사용량", "사용률", "얼마나 썼", "얼마나 써", "얼마 남았"
            )) and any(
                word in text for word in ("시스템", "컴퓨터", "cpu", "메모리", "램")
            ):
                command = "status"
            elif any(phrase in text for phrase in ("도움", "뭘 할 수", "무엇을 할 수", "사용 방법")):
                command = "help"
        if text in ("안녕", "안녕하세요", "반가워", "자비스 안녕"):
            return CommandResult("안녕하세요. 무엇을 도와드릴까요?", True)
        if text in ("고마워", "고맙습니다", "감사", "감사합니다"):
            return CommandResult("천만에요. 더 필요한 게 있으면 말씀해 주세요.", True)
        if text in ("너는 누구야", "네 이름은 뭐야", "자비스"):
            return CommandResult("저는 J.A.R.V.I.S. 데스크톱 프로토타입입니다.", True)
        if command == "help":
            if korean:
                return CommandResult(
                    "사용 가능: 도움말 · 상태 · 시간 · 가동시간 · 메모장 열기 · 계산기 열기", True
                )
            return CommandResult(
                "Available: HELP · STATUS · TIME · UPTIME · OPEN NOTEPAD · OPEN CALCULATOR", True
            )
        if command == "time":
            now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            return CommandResult(f"현재 시각: {now}" if korean else f"Local time: {now}", True)
        if command == "uptime":
            seconds = self.monitor.sample().uptime_seconds
            days, remainder = divmod(seconds, 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, _ = divmod(remainder, 60)
            value = f"{days}일 {hours}시간 {minutes}분" if korean else f"{days}d {hours}h {minutes}m"
            return CommandResult(f"시스템 가동 시간: {value}" if korean else f"System uptime: {value}", True)
        if command == "status":
            snapshot = self.monitor.sample()
            if korean:
                result = (f"시스템 정상 · CPU {snapshot.cpu_percent:.0f}% · 메모리 "
                          f"{snapshot.memory_percent:.0f}% "
                          f"({snapshot.memory_used_gb:.1f}/{snapshot.memory_total_gb:.1f} GiB) · "
                          f"JARVIS {snapshot.process_memory_mb:.0f} MiB")
            else:
                result = (f"System online · CPU {snapshot.cpu_percent:.0f}% · Memory "
                          f"{snapshot.memory_percent:.0f}% "
                          f"({snapshot.memory_used_gb:.1f}/{snapshot.memory_total_gb:.1f} GiB) · "
                          f"JARVIS {snapshot.process_memory_mb:.0f} MiB")
            return CommandResult(result, True)
        if command in ("notepad", "calculator"):
            action = f"open:{command}"
            if not self.security.authorize(action):
                return CommandResult("보안 정책에서 차단했습니다." if korean else "Blocked by security policy.", False)
            try:
                self.desktop.open_application(command)
            except (OSError, ValueError) as error:
                prefix = "실행하지 못했습니다" if korean else "Could not open"
                return CommandResult(f"{prefix} ({command}): {error}", False)
            name = {"notepad": "메모장", "calculator": "계산기"}[command] if korean else command
            return CommandResult(f"{name}을(를) 열었습니다." if korean else f"Opened {name}.", True)
        unknown = text or ("(빈 명령)" if korean else "(empty)")
        return CommandResult(
            ("아직 자유 대화형 AI는 연결되지 않았어요. 현재는 도움말, 상태, 시간, 가동시간, "
             "메모장 열기, 계산기 열기를 지원합니다.")
            if korean else
            "Free-form AI chat is not connected yet. Try HELP, STATUS, TIME, UPTIME, "
            "OPEN NOTEPAD, or OPEN CALCULATOR.",
            False,
        )
