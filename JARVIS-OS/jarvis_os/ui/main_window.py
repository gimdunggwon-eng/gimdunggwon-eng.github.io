from datetime import datetime
from collections import deque
from pathlib import Path

from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, QByteArray, QBuffer, QIODevice,
)
from PySide6.QtGui import (
    QColor, QKeyEvent, QPainter, QPainterPath, QPen,
)
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from jarvis_os.engines.system_monitor import SystemMonitor
from jarvis_os.engines.command_router import CommandRouter
from jarvis_os.engines.ai import AIEngine, AIEngineError
from jarvis_os.engines.voice import VoiceEngine, VoiceInputUnavailable
from jarvis_os.engines.speech_output import SpeechOutputEngine, SpeechOutputError
from jarvis_os.engines.vision import (
    MIN_SCREEN_FREE_GIB, VisionEngine, VisionEngineError,
)
from jarvis_os.engines.gesture import GestureWorker
from jarvis_os.ui.suit3d import HologramSuitDisplay
from jarvis_os.ui.keyboard_layout import activate_input_language, set_ime_mode
from jarvis_os.ui.hangul import compose_dubeolsik, is_dubeolsik_key


class CommandInput(QLineEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setInputMethodHints(Qt.InputMethodHint.ImhNone)
        self.history: list[str] = []
        self.history_index = 0
        self.korean_input = True
        self._hangul_buffer = ""
        self._hangul_start: int | None = None
        self._hangul_rendered_length = 0
        self._updating_hangul = False
        self.cursorPositionChanged.connect(self._handle_cursor_move)

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if self.korean_input:
            QTimer.singleShot(0, self._activate_hangul_ime)

    def _activate_hangul_ime(self) -> None:
        try:
            # Windows IME context belongs to the top-level native window, not the child edit HWND.
            set_ime_mode(int(self.window().winId()), self.korean_input)
        except (OSError, TypeError, ValueError):
            pass

    def set_korean_input(self, enabled: bool) -> None:
        self.korean_input = enabled
        self._reset_hangul_buffer()
        activate_input_language("ko" if enabled else "en")
        if self.hasFocus():
            QTimer.singleShot(0, self._activate_hangul_ime)

    def _reset_hangul_buffer(self) -> None:
        self._hangul_buffer = ""
        self._hangul_start = None
        self._hangul_rendered_length = 0

    def _handle_cursor_move(self, _old: int, new: int) -> None:
        if self._updating_hangul or not self._hangul_buffer:
            return
        if new != self._hangul_start + self._hangul_rendered_length:
            self._reset_hangul_buffer()

    def _replace_hangul_buffer(self) -> None:
        if self._hangul_start is None:
            selected = self.selectionStart()
            self._hangul_start = selected if selected >= 0 else self.cursorPosition()
            if selected >= 0:
                self._updating_hangul = True
                self.insert("")
                self._updating_hangul = False
        rendered = compose_dubeolsik(self._hangul_buffer)
        self._updating_hangul = True
        try:
            if self._hangul_rendered_length:
                self.setSelection(self._hangul_start, self._hangul_rendered_length)
                self.insert("")
            self.setCursorPosition(self._hangul_start)
            if rendered:
                self.insert(rendered)
            self._hangul_rendered_length = len(rendered)
        finally:
            self._updating_hangul = False

    def setText(self, text: str) -> None:
        self._reset_hangul_buffer()
        super().setText(text)

    def clear(self) -> None:
        self._reset_hangul_buffer()
        super().clear()

    def remember(self, command: str) -> None:
        if command and (not self.history or self.history[-1] != command):
            self.history.append(command)
            self.history = self.history[-50:]
        self.history_index = len(self.history)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        history_shortcut = (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier
            and event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down)
        )
        if history_shortcut and self.history:
            self._reset_hangul_buffer()
            step = -1 if event.key() == Qt.Key.Key_Up else 1
            self.history_index = max(0, min(len(self.history), self.history_index + step))
            self.setText(self.history[self.history_index]
                         if self.history_index < len(self.history) else "")
            return
        modifiers = event.modifiers()
        if self.korean_input and not (modifiers & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )):
            if event.key() == Qt.Key.Key_Backspace and self._hangul_buffer:
                self._hangul_buffer = self._hangul_buffer[:-1]
                self._replace_hangul_buffer()
                event.accept()
                return
            typed = event.text()
            if len(typed) == 1 and is_dubeolsik_key(typed):
                self._hangul_buffer += typed
                self._replace_hangul_buffer()
                event.accept()
                return
        if event.key() not in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt):
            self._reset_hangul_buffer()
        super().keyPressEvent(event)


class VoiceCaptureWorker(QThread):
    recognized = Signal(str)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.recognized.emit(VoiceEngine.listen_once())
        except VoiceInputUnavailable as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(str(error))


class SpeechOutputWorker(QThread):
    failed = Signal(str)

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.text = text

    def run(self) -> None:
        try:
            SpeechOutputEngine.speak(self.text)
        except SpeechOutputError as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(f"음성 응답 오류: {error}")


class AIResponseWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, engine: AIEngine, prompt: str,
                 history: list[dict[str, str]], language: str, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.prompt = prompt
        self.history = history
        self.language = language

    def run(self) -> None:
        try:
            self.completed.emit(self.engine.respond(self.prompt, self.history, self.language))
        except AIEngineError as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(f"AI 처리 중 오류가 발생했습니다: {error}")


class AIAvailabilityWorker(QThread):
    checked = Signal(bool)

    def __init__(self, engine: AIEngine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine

    def run(self) -> None:
        self.checked.emit(self.engine.is_available())


class ScreenVisionWorker(QThread):
    checked = Signal(bool)
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, engine: VisionEngine, image: bytes | None = None, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.image = image
        self.language = "ko"

    def run(self) -> None:
        if self.image is None:
            self.checked.emit(self.engine.check_model())
            return
        try:
            self.completed.emit(self.engine.describe(self.image, self.language))
        except VisionEngineError as error:
            self.failed.emit(str(error))
        except Exception as error:
            self.failed.emit(f"화면 분석 오류: {error}")


class VisionUnloadWorker(QThread):
    def __init__(self, engine: VisionEngine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine

    def run(self) -> None:
        self.engine.unload()


class TelemetrySparkline(QWidget):
    def __init__(self, color: str) -> None:
        super().__init__()
        self.values: deque[float] = deque(maxlen=60)
        self.line_color = QColor(color)
        self.setMinimumHeight(34)
        self.setMaximumHeight(42)

    def add_value(self, value: float) -> None:
        self.values.append(max(0.0, min(100.0, value)))
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.rect().adjusted(2, 3, -2, -3)
        painter.setPen(QPen(QColor(36, 70, 88, 115), 1))
        for fraction in (0.25, 0.5, 0.75):
            y = area.top() + area.height() * fraction
            painter.drawLine(int(area.left()), int(y), int(area.right()), int(y))
        if not self.values:
            return
        points = [
            (area.left() + i * area.width() / max(1, len(self.values) - 1),
             area.bottom() - value / 100.0 * area.height())
            for i, value in enumerate(self.values)
        ]
        line = QPainterPath()
        line.moveTo(*points[0])
        for point in points[1:]:
            line.lineTo(*point)
        fill = QPainterPath(line)
        fill.lineTo(points[-1][0], area.bottom())
        fill.lineTo(points[0][0], area.bottom())
        fill.closeSubpath()
        tint = QColor(self.line_color)
        tint.setAlpha(28)
        painter.fillPath(fill, tint)
        painter.setPen(QPen(self.line_color, 1.8, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(line)


class MetricCard(QFrame):
    def __init__(self, title: str, chart_color: str) -> None:
        super().__init__()
        self.title_en = title
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        self.title = QLabel(title.upper())
        self.title.setObjectName("metricTitle")
        self.value = QLabel("--%")
        self.value.setObjectName("metricValue")
        self.detail = QLabel("Reading system telemetry")
        self.detail.setObjectName("muted")
        self.bar = QProgressBar()
        self.bar.setObjectName("metricBar")
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.sparkline = TelemetrySparkline(chart_color)
        layout.addWidget(self.title)
        layout.addWidget(self.value)
        layout.addWidget(self.bar)
        layout.addWidget(self.sparkline)
        layout.addWidget(self.detail)

    def set_metric(self, value: float, detail: str) -> None:
        self.value.setText(f"{value:.0f}%")
        self.bar.setValue(round(value))
        self.sparkline.add_value(value)
        self.detail.setText(detail)

    def set_language(self, language: str) -> None:
        titles = {"Processor": "프로세서", "Memory": "메모리"}
        self.title.setText(titles.get(self.title_en, self.title_en) if language == "ko"
                           else self.title_en.upper())


class EngineStatus(QFrame):
    def __init__(self, name: str, state: str, ready: bool = False) -> None:
        super().__init__()
        self.setObjectName("engineStatus")
        self.name_en = name
        self.state_en = state
        self.ready = ready
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self.label = QLabel(name.upper())
        self.label.setObjectName("engineName")
        self.value = QLabel(state.upper())
        self.value.setObjectName("engineReady" if ready else "enginePending")
        layout.addWidget(self.label)
        layout.addWidget(self.value)

    def set_language(self, language: str) -> None:
        if language == "ko":
            names = {"System monitor": "시스템 모니터", "Voice": "음성 입력",
                     "AI core": "AI 코어", "Desktop control": "데스크톱 제어"}
            states = {"Active": "작동 중", "Not configured": "설정 확인 필요",
                      "Not connected": "연결 안 됨",
                      "Allowlist only": "허용 목록만", "Configured": "로컬 모델 준비",
                      "Connected": "연결됨", "Unavailable": "확인 필요",
                      "Offline": "오프라인", "Listening": "듣는 중", "Ready": "준비됨"}
            self.label.setText(names.get(self.name_en, self.name_en).upper())
            self.value.setText(states.get(self.state_en, self.state_en).upper())
        else:
            self.label.setText(self.name_en.upper())
            self.value.setText(self.state_en.upper())


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.monitor = SystemMonitor()
        self.command_router = CommandRouter(self.monitor)
        self.ai_engine = AIEngine()
        self.vision_engine = VisionEngine()
        self.ai_history: list[dict[str, str]] = []
        self.transcript: list[tuple[str, str]] = []
        self.ai_worker: AIResponseWorker | None = None
        self._chat_ai_busy = False
        self._vision_ai_busy = False
        self._speech_ai_busy = False
        self.ai_status_worker: AIAvailabilityWorker | None = None
        self.speech_worker: SpeechOutputWorker | None = None
        self.speech_queue: list[str] = []
        self.voice_output_enabled = True
        self.language = "ko"
        self.voice_worker: VoiceCaptureWorker | None = None
        self.screen_analysis_enabled = False
        self.screen_model_ready = False
        self.screen_capture_pending = False
        self.screen_worker: ScreenVisionWorker | None = None
        self.vision_unload_worker: VisionUnloadWorker | None = None
        self.gesture_last_error = False
        self.suit_fullscreen_dialog: QDialog | None = None
        self.setWindowTitle("J.A.R.V.I.S. OS v0.1.0")
        self.setMinimumSize(900, 600)
        self._build_ui()
        self.set_language("ko")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_metrics)
        self.timer.start(1000)
        self.refresh_metrics()
        QTimer.singleShot(0, self._check_ai_availability)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(24, 12, 24, 12)
        outer.setSpacing(10)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        title = QLabel("J.A.R.V.I.S.")
        title.setObjectName("brand")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("muted")
        brand.addWidget(title)
        brand.addWidget(self.subtitle)
        self.clock = QLabel()
        self.clock.setObjectName("clock")
        self.clock.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addLayout(brand)
        header.addStretch(1)
        header.addWidget(self.clock)
        self.ram_badge = QLabel()
        self.ram_badge.setObjectName("ramReady")
        self.ram_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.ram_badge)
        self.language_button = QPushButton("EN")
        self.language_button.setObjectName("languageButton")
        self.language_button.clicked.connect(self.toggle_language)
        header.addWidget(self.language_button)
        outer.addLayout(header)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFixedHeight(1)
        outer.addWidget(divider)

        center_row = QHBoxLayout()
        self.center_row = center_row
        center_row.setSpacing(32)
        center_row.setContentsMargins(0, 6, 0, 6)
        self.core = HologramSuitDisplay()
        center_row.addStretch(1)
        center_row.addWidget(self.core, 1)
        center_info = QVBoxLayout()
        center_info.setSpacing(10)
        self.system_status = QLabel("SYSTEM STATUS  ·  ONLINE")
        self.system_status.setObjectName("status")
        self.headline = QLabel()
        self.headline.setObjectName("headline")
        self.headline.setWordWrap(True)
        self.headline.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.headline.setMinimumHeight(88)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        center_info.addStretch(1)
        center_info.addWidget(self.system_status)
        center_info.addWidget(self.headline)
        center_info.addWidget(self.hint)
        self.hologram_model_button = QPushButton()
        self.hologram_model_button.setObjectName("commandButton")
        self.hologram_model_button.clicked.connect(self._toggle_hologram_model)
        center_info.addWidget(self.hologram_model_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.suit_fullscreen_button = QPushButton()
        self.suit_fullscreen_button.setObjectName("commandButton")
        self.suit_fullscreen_button.clicked.connect(self._show_suit_fullscreen)
        center_info.addWidget(self.suit_fullscreen_button, 0, Qt.AlignmentFlag.AlignLeft)
        center_info.addStretch(1)
        center_row.addLayout(center_info, 1)
        center_row.addStretch(1)
        outer.addLayout(center_row, 2)

        engines = QHBoxLayout()
        engines.setSpacing(12)
        self.engine_cards = [
            EngineStatus("System monitor", "Active", ready=True),
            EngineStatus("Voice", "Offline", ready=True),
            EngineStatus("AI core", "Not connected"),
            EngineStatus("Desktop control", "Allowlist only", ready=True),
        ]
        for card in self.engine_cards:
            engines.addWidget(card)
        outer.addLayout(engines)

        command_row = QHBoxLayout()
        command_row.setSpacing(10)
        self.command_input = CommandInput()
        self.command_input.setObjectName("commandInput")
        self.command_input.returnPressed.connect(self.submit_command)
        self.voice_button = QPushButton()
        self.voice_button.setObjectName("commandButton")
        self.voice_button.setToolTip("7초 동안 말하면 오프라인 음성 인식 후 명령 또는 질문으로 보냅니다.")
        self.voice_button.clicked.connect(self.start_voice_input)
        command_row.addWidget(self.voice_button)
        self.speak_button = QPushButton()
        self.speak_button.setObjectName("commandButton")
        self.speak_button.setCheckable(True)
        self.speak_button.setChecked(True)
        self.speak_button.toggled.connect(self._set_voice_output_enabled)
        command_row.addWidget(self.speak_button)
        self.input_language_button = QPushButton()
        self.input_language_button.setObjectName("commandButton")
        self.input_language_button.setToolTip("한글/영문 키 입력 모드를 전환합니다.")
        self.input_language_button.clicked.connect(self.toggle_input_language)
        command_row.addWidget(self.input_language_button)
        self.command_button = QPushButton()
        self.command_button.setObjectName("commandButton")
        self.command_button.clicked.connect(self.submit_command)
        command_row.addWidget(self.command_input, 1)
        command_row.addWidget(self.command_button)
        outer.addLayout(command_row)

        screen_row = QHBoxLayout()
        self.screen_button = QPushButton()
        self.screen_button.setObjectName("commandButton")
        self.screen_button.setCheckable(True)
        self.screen_button.toggled.connect(self._toggle_screen_analysis)
        screen_row.addWidget(self.screen_button)
        self.screen_status = QLabel()
        self.screen_status.setObjectName("muted")
        self.screen_status.setWordWrap(True)
        screen_row.addWidget(self.screen_status, 1)
        self.gesture_worker: GestureWorker | None = None
        self.gesture_button = QPushButton()
        self.gesture_button.setObjectName("commandButton")
        self.gesture_button.setCheckable(True)
        self.gesture_button.toggled.connect(self._toggle_gesture_control)
        screen_row.addWidget(self.gesture_button)
        outer.addLayout(screen_row)
        self.gesture_status = QLabel()
        self.gesture_status.setObjectName("muted")
        self.gesture_status.setWordWrap(True)
        outer.addWidget(self.gesture_status)
        self.screen_timer = QTimer(self)
        self.screen_timer.setInterval(15000)
        self.screen_timer.timeout.connect(self._capture_screen_for_analysis)

        self.command_output = QPlainTextEdit()
        self.command_output.setObjectName("commandOutput")
        self.command_output.setReadOnly(True)
        self.command_output.setMaximumBlockCount(100)
        self.command_output.setFixedHeight(84)
        outer.addWidget(self.command_output)

        metrics = QHBoxLayout()
        metrics.setSpacing(16)
        self.cpu_card = MetricCard("Processor", "#30c9e8")
        self.memory_card = MetricCard("Memory", "#50e6c2")
        self.memory_card.bar.setObjectName("memoryBar")
        metrics.addWidget(self.cpu_card)
        metrics.addWidget(self.memory_card)
        outer.addLayout(metrics)

        self.footer = QLabel()
        self.footer.setObjectName("footer")
        self.footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.footer)

        self.setCentralWidget(root)
        self.setStyleSheet("""
            QWidget#root { background: #07111d; color: #d9f4ff; font-family: 'Segoe UI'; }
            QLabel#brand { color: #a9eaff; font-size: 30px; font-weight: 700; letter-spacing: 4px; }
            QLabel#muted { color: #87a6b7; font-size: 13px; }
            QLabel#clock { color: #8bdcff; font-size: 20px; font-family: Consolas; }
            QLabel#ramReady { color: #50e6c2; background: #0b292c; border: 1px solid #1c625b; border-radius: 12px; padding: 5px 12px; font-size: 11px; font-weight: 700; }
            QLabel#ramWarning { color: #ffd18f; background: #302417; border: 1px solid #8b6434; border-radius: 12px; padding: 5px 12px; font-size: 11px; font-weight: 700; }
            QFrame#divider { background: #17445c; border: none; }
            QLabel#status { color: #50e6c2; font-size: 12px; }
            QLabel#headline { color: #e5f8ff; font-size: 34px; font-weight: 300; padding: 2px 0; }
            QFrame#metricCard { background: #0b1b2a; border: 1px solid #17445c; border-radius: 8px; }
            QFrame#engineStatus { background: #091725; border: 1px solid #15394b; border-radius: 6px; }
            QLabel#engineName { color: #82a5b8; font-size: 10px; }
            QLabel#engineReady { color: #50e6c2; font-size: 12px; font-weight: 600; }
            QLabel#enginePending { color: #efbb74; font-size: 12px; font-weight: 600; }
            QLineEdit#commandInput { background: #091725; border: 1px solid #1b536b; border-radius: 5px; padding: 11px 14px; color: #c6efff; font-size: 13px; }
            QLineEdit#commandInput:focus { border: 1px solid #36c8e5; }
            QPushButton#commandButton { background: #12374a; border: 1px solid #24708b; border-radius: 5px; padding: 10px 24px; color: #aeeeff; font-weight: 700; }
            QPushButton#commandButton:hover { background: #18516a; }
            QPushButton#commandButton:checked { background: #124a49; border-color: #50e6c2; color: #baffef; }
            QPushButton#languageButton { background: transparent; border: 1px solid #24708b; border-radius: 5px; padding: 7px 12px; color: #8bdcff; }
            QPushButton#languageButton:hover { background: #12374a; }
            QPlainTextEdit#commandOutput { background: #091725; border: 1px solid #1c4b60; border-radius: 7px; color: #9bd8ee; font-size: 12px; padding: 7px; }
            QLabel#metricTitle { color: #8ccce1; font-size: 12px; }
            QLabel#metricValue { color: #b6edff; font-size: 32px; font-weight: 600; }
            QProgressBar { height: 5px; background: #142d3c; border: none; border-radius: 2px; }
            QProgressBar::chunk { background: #30c9e8; border-radius: 2px; }
            QProgressBar#memoryBar::chunk { background: #50e6c2; border-radius: 2px; }
            QProgressBar#memoryBar[pressure="true"]::chunk { background: #e9a85d; }
            QLabel#memoryWarning { color: #f1ba72; font-size: 11px; }
            QLabel#footer { color: #65889a; font-size: 11px; }
        """)

    def toggle_language(self) -> None:
        self.set_language("en" if self.language == "ko" else "ko")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self.command_input.setFocus)

    def closeEvent(self, event) -> None:
        self.screen_timer.stop()
        if self.gesture_worker is not None and self.gesture_worker.isRunning():
            self.gesture_worker.requestInterruption()
            self.gesture_worker.wait(2500)
        self.ai_engine.stop_managed_server()
        super().closeEvent(event)

    def set_language(self, language: str) -> None:
        self.language = "ko" if language == "ko" else "en"
        activate_input_language(self.language)
        korean = self.language == "ko"
        self.command_input.set_korean_input(korean)
        self.command_router.set_language(self.language)
        self.core.set_language(self.language)
        self.subtitle.setText("개인 시스템 인터페이스  /  프로토타입 0.1.0" if korean
                              else "PERSONAL SYSTEM INTERFACE  /  PROTOTYPE 0.1.0")
        self.system_status.setText("시스템 상태  ·  온라인" if korean else "SYSTEM STATUS  ·  ONLINE")
        self.headline.setText("무엇을\n도와드릴까요?" if korean else "At your service.")
        self.hint.setText("로컬 HUD 프로토타입\n한국어로 질문하거나 음성 입력을 누르세요."
                          if korean else "Local HUD prototype\nType a question or use voice input.")
        for card in self.engine_cards:
            card.set_language(self.language)
        for card in (self.cpu_card, self.memory_card):
            card.set_language(self.language)
        self.command_input.setPlaceholderText(
            "한국어 질문 또는 명령 입력 (예: 지금 몇 시야?)"
            if korean else
            "Type a question or command (e.g. what time is it?)"
        )
        self.voice_button.setText("음성 입력" if korean else "VOICE")
        self.voice_button.setToolTip(
            "말이 끝날 때까지 최대 15초 듣고 인식한 문장을 실행합니다."
            if korean else
            "Listens for up to 15 seconds and sends your recognized speech as a command or question."
        )
        self.screen_button.setText(
            ("화면 분석 · 켬" if self.screen_analysis_enabled else "화면 분석 · 끔")
            if korean else ("SCREEN ANALYSIS · ON" if self.screen_analysis_enabled
                            else "SCREEN ANALYSIS · OFF")
        )
        self.screen_button.setToolTip(
            "켜면 현재 주 화면을 15초마다 캡처해 로컬 Ollama 비전 모델로 설명합니다."
            if korean else
            "When enabled, captures the primary screen every 15 seconds and describes it with a local Ollama vision model."
        )
        self.gesture_button.setText(
            ("손짓 제어 · 켬" if self.gesture_button.isChecked() else "손짓 제어 · 끔")
            if korean else ("GESTURES · ON" if self.gesture_button.isChecked()
                            else "GESTURES · OFF")
        )
        self.gesture_button.setToolTip(
            "👌=동력 작동(웹슈터 발사·슈트 비행·아크 리액터 발광), 엄지 위=확대, 엄지 아래=축소, 손바닥 쓸기=회전, L자=시점 이동, 주먹=정지, V자=초기화. 영상은 이 PC에서만 처리됩니다."
            if korean else
            "OK sign=power (web shooter fires, suit flies, arc reactor flares), thumb up=zoom, thumb down=zoom out, open-palm swipe=spin, L pose=move view, fist=pause, Victory=reset. Video stays local."
        )
        if not self.gesture_button.isChecked():
            self.gesture_status.setText(
                "카메라 꺼짐 · 영상은 저장하거나 전송하지 않습니다."
                if korean else "Camera off · video is not saved or sent."
            )
        self._set_screen_status(
            ("화면은 분석하지 않습니다." if korean else "Screen analysis is off.")
            if not self.screen_analysis_enabled else
            ("비전 모델 연결 확인 중…" if korean else "Checking local vision model…")
        )
        self.speak_button.setText(
            ("말로 답변 · 켬" if self.voice_output_enabled else "말로 답변 · 끔") if korean
            else ("SPEAK ON" if self.voice_output_enabled else "SPEAK OFF")
        )
        self.speak_button.setToolTip(
            "JARVIS 답변을 로컬 음성으로 읽습니다. 눌러서 켜거나 끌 수 있어요."
            if korean else "Read JARVIS responses aloud using local speech. Click to toggle."
        )
        self.input_language_button.setText("한/영" if korean else "KOR/ENG")
        self.command_button.setText("실행" if korean else "RUN")
        self._render_transcript()
        self.footer.setText("읽기 전용 모니터 · F11 전체 화면 · ESC 종료" if korean
                            else "READ-ONLY MONITOR · F11 FULLSCREEN · ESC EXIT")
        self.language_button.setText("EN" if korean else "KO")
        self.suit_fullscreen_button.setText(
            "홀로그램 전체 화면" if korean else "HOLOGRAM FULL SCREEN"
        )
        self.hologram_model_button.setText(
            ({"suit": "웹슈터 홀로그램 보기",
              "web_shooter": "아크 리액터 홀로그램 보기",
              "arc_reactor": "아이언맨 손 홀로그램 보기",
              "iron_hand": "슈트 홀로그램 보기"}[self.core.model])
            if korean else
            ({"suit": "VIEW WEB SHOOTER",
              "web_shooter": "VIEW ARC REACTOR",
              "arc_reactor": "VIEW IRON MAN HAND",
              "iron_hand": "VIEW SUIT"}[self.core.model])
        )

    def _toggle_hologram_model(self) -> None:
        next_model = {"suit": "web_shooter", "web_shooter": "arc_reactor",
                      "arc_reactor": "iron_hand", "iron_hand": "suit"}[self.core.model]
        self.core.set_model(next_model)
        self.set_language(self.language)

    def _show_suit_fullscreen(self) -> None:
        if self.suit_fullscreen_dialog is not None:
            self.suit_fullscreen_dialog.raise_()
            return

        dialog = QDialog(self, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        dialog.setObjectName("suitFullscreen")
        dialog.setWindowTitle("J.A.R.V.I.S. · 3D Hologram")
        dialog.setStyleSheet(
            "QDialog#suitFullscreen { background: #030b13; }"
            "QPushButton { background: #12374a; border: 1px solid #24708b;"
            " border-radius: 5px; padding: 10px 20px; color: #aeeeff;"
            " font-weight: 700; }"
            "QPushButton:hover { background: #18516a; }"
        )
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 14, 18, 18)
        toolbar = QHBoxLayout()
        toolbar.addStretch(1)
        exit_button = QPushButton(
            "HUD로 돌아가기" if self.language == "ko" else "RETURN TO HUD"
        )
        exit_button.clicked.connect(dialog.close)
        toolbar.addWidget(exit_button)
        layout.addLayout(toolbar)

        self.center_row.removeWidget(self.core)
        layout.addWidget(self.core, 1)
        self.suit_fullscreen_dialog = dialog
        dialog.finished.connect(self._restore_suit_from_fullscreen)
        dialog.showFullScreen()

    def _restore_suit_from_fullscreen(self, _result: int) -> None:
        dialog = self.suit_fullscreen_dialog
        if dialog is None:
            return
        dialog.layout().removeWidget(self.core)
        self.core.setParent(self)
        self.center_row.insertWidget(1, self.core, 1)
        self.suit_fullscreen_dialog = None
        dialog.deleteLater()

    def _toggle_gesture_control(self, enabled: bool) -> None:
        korean = self.language == "ko"
        self.gesture_button.setText(
            ("손짓 제어 · 켬" if enabled else "손짓 제어 · 끔") if korean
            else ("GESTURES · ON" if enabled else "GESTURES · OFF")
        )
        if not enabled:
            worker = self.gesture_worker
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
            self.gesture_status.setText(
                "카메라 연결을 종료하는 중…" if self.language == "ko" else "Stopping camera…"
            )
            return
        self.gesture_last_error = False
        self.gesture_status.setText(
            "카메라 및 손짓 모델을 준비합니다…" if self.language == "ko"
            else "Preparing camera and gesture model…"
        )
        project_root = Path(__file__).resolve().parents[2]
        self.gesture_worker = GestureWorker(project_root / ".models" / "gesture_recognizer.task", self)
        self.gesture_worker.status.connect(self._set_gesture_status)
        self.gesture_worker.gesture.connect(self._handle_gesture)
        self.gesture_worker.failed.connect(self._gesture_failed)
        self.gesture_worker.finished.connect(self._gesture_finished)
        self.gesture_worker.start()

    def _set_gesture_status(self, message: str) -> None:
        translations = {
            "Downloading gesture model…": "손짓 인식 모델 다운로드 중…",
            "Gesture control is active. Video stays on this PC.": "손짓 제어 켬 · 영상은 이 PC에서만 처리됩니다.",
        }
        self.gesture_status.setText(translations.get(message, message) if self.language == "ko" else message)

    def _handle_gesture(self, name: str, hand_x: float, hand_y: float) -> None:
        self.core.apply_gesture(name, hand_x, hand_y)
        labels = {
            "OK_Gesture": "👌 동력 작동",
            "Open_Palm": "손바닥 쓸기: 방향 회전", "Closed_Fist": "주먹: 정지",
            "Thumb_Up": "엄지 위: 확대", "Thumb_Down": "엄지 아래: 축소",
            "Victory": "V자: 화면 초기화", "L_Gesture": "L자: 손 위치로 시점 이동",
            "None": "손짓 인식 중…",
        }
        english = {
            "OK_Gesture": "👌 Power activated",
            "Open_Palm": "Open-palm swipe: spin", "Closed_Fist": "Fist: pause",
            "Thumb_Up": "Thumb up: zoom in", "Thumb_Down": "Thumb down: zoom out",
            "Victory": "Victory: reset", "L_Gesture": "L pose: move view with hand",
            "None": "Recognizing gesture…",
        }
        text = labels.get(name, name) if self.language == "ko" else english.get(name, name)
        self.gesture_status.setText(text + (" · 영상은 이 PC에서만 처리됩니다." if self.language == "ko"
                                            else " · processed locally only"))

    def _gesture_failed(self, message: str) -> None:
        self.gesture_last_error = True
        if "No usable camera detected" in message:
            message = (
                "카메라를 찾지 못했습니다. 웹캠 셔터와 Windows 카메라 액세스, "
                "장치 관리자에서 카메라 드라이버가 활성 상태인지 확인하고, "
                "카메라를 사용하는 다른 앱을 닫은 뒤 다시 켜세요."
                if self.language == "ko" else message
            )
        self.gesture_status.setText(
            f"손짓 기능 오류: {message}" if self.language == "ko" else f"Gesture error: {message}"
        )
        self.gesture_button.blockSignals(True)
        self.gesture_button.setChecked(False)
        self.gesture_button.blockSignals(False)
        self.gesture_button.setText(
            "손짓 제어 · 끔" if self.language == "ko" else "GESTURES · OFF"
        )

    def _gesture_finished(self) -> None:
        if not self.gesture_button.isChecked() and not self.gesture_last_error:
            self.gesture_status.setText(
                "카메라 꺼짐 · 영상은 저장하거나 전송하지 않습니다."
                if self.language == "ko" else "Camera off · video is not saved or sent."
            )

    def toggle_input_language(self) -> None:
        enabled = not self.command_input.korean_input
        self.command_input.set_korean_input(enabled)
        self.command_input.setPlaceholderText(
            "한국어 질문 또는 명령 입력 (예: 지금 몇 시야?)" if enabled
            else "Type a question or command (e.g. what time is it?)"
        )

    def start_voice_input(self) -> None:
        if self.voice_worker is not None and self.voice_worker.isRunning():
            return
        self.voice_button.setEnabled(False)
        self.voice_button.setText("듣는 중…" if self.language == "ko" else "LISTENING…")
        self._set_voice_status("Listening", False)
        self._add_transcript(
            "SYSTEM",
            "듣고 있어요. 자연스럽게 말한 뒤 잠깐 멈추면 자동으로 인식해요. 최대 15초까지 들어요."
            if self.language == "ko" else
            "Listening. Speak naturally, then pause to finish. Up to 15 seconds."
        )
        self.voice_worker = VoiceCaptureWorker(self)
        self.voice_worker.recognized.connect(self.on_voice_recognized)
        self.voice_worker.failed.connect(self.on_voice_failed)
        self.voice_worker.finished.connect(self._voice_finished)
        self.voice_worker.finished.connect(self.voice_worker.deleteLater)
        self.voice_worker.start()

    def _voice_finished(self) -> None:
        self.voice_worker = None
        self.voice_button.setEnabled(
            self.speech_worker is None or not self.speech_worker.isRunning()
        )
        self.voice_button.setText("음성 입력" if self.language == "ko" else "VOICE")

    def on_voice_recognized(self, phrase: str) -> None:
        self._set_voice_status("Ready", True)
        self.command_input.setText(phrase)
        self.submit_command()

    def on_voice_failed(self, message: str) -> None:
        self._set_voice_status("Unavailable", False)
        self._add_transcript(
            "SYSTEM", f"음성 입력을 사용할 수 없습니다: {message}" if self.language == "ko"
            else f"Voice input unavailable: {message}"
        )

    def refresh_metrics(self) -> None:
        self.clock.setText(datetime.now().astimezone().strftime("%H:%M:%S  %Z"))
        try:
            snapshot = self.monitor.sample()
        except Exception:
            self.system_status.setText("시스템 모니터를 사용할 수 없음" if self.language == "ko"
                                       else "SYSTEM STATUS  ·  TELEMETRY UNAVAILABLE")
            for card in (self.cpu_card, self.memory_card):
                card.value.setText("--%")
                card.bar.setValue(0)
                card.detail.setText("Telemetry unavailable")
            return
        self.system_status.setText("시스템 상태  ·  온라인" if self.language == "ko"
                                   else "SYSTEM STATUS  ·  ONLINE")
        self.cpu_card.set_metric(
            snapshot.cpu_percent,
            "CPU 사용률 · 최근 60초" if self.language == "ko" else "Overall CPU utilization · 60s history",
        )
        self.memory_card.set_metric(
            snapshot.memory_percent,
            (f"사용 가능 {snapshot.memory_available_gb:.2f} GiB · "
             f"전체 {snapshot.memory_used_gb:.1f}/{snapshot.memory_total_gb:.1f} GiB · "
             f"JARVIS {snapshot.process_memory_mb:.0f} MiB"
             if self.language == "ko" else
             f"Available {snapshot.memory_available_gb:.2f} GiB · "
             f"System {snapshot.memory_used_gb:.1f}/{snapshot.memory_total_gb:.1f} GiB · "
             f"JARVIS {snapshot.process_memory_mb:.0f} MiB"),
        )
        memory_low = snapshot.memory_available_gb < MIN_SCREEN_FREE_GIB
        self.ram_badge.setText(
            (f"RAM 여유 {snapshot.memory_available_gb:.2f} GiB" if self.language == "ko"
             else f"RAM FREE {snapshot.memory_available_gb:.2f} GiB")
        )
        self.ram_badge.setObjectName("ramWarning" if memory_low else "ramReady")
        self.ram_badge.style().unpolish(self.ram_badge)
        self.ram_badge.style().polish(self.ram_badge)
        self.memory_card.detail.setObjectName("memoryWarning" if memory_low else "muted")
        self.memory_card.detail.style().unpolish(self.memory_card.detail)
        self.memory_card.detail.style().polish(self.memory_card.detail)
        self.memory_card.bar.setProperty("pressure", memory_low)
        self.memory_card.bar.style().unpolish(self.memory_card.bar)
        self.memory_card.bar.style().polish(self.memory_card.bar)

    def submit_command(self) -> None:
        command = self.command_input.text()
        if not command.strip():
            return
        if self.ai_worker is not None and self.ai_worker.isRunning():
            self._add_transcript(
                "SYSTEM", "답변을 기다리는 중입니다. 잠시 후 다시 입력해 주세요."
                if self.language == "ko" else "Please wait for the current answer to finish."
            )
            return
        self.command_input.remember(command)
        normalized = " ".join(command.strip().lower().split()).rstrip("?!.,。！？")
        if normalized in ("대화 지우기", "대화 초기화", "기록 지우기",
                          "clear chat", "clear conversation"):
            self.speech_queue.clear()
            SpeechOutputEngine.stop()
            self.ai_history.clear()
            self.transcript.clear()
            self._add_transcript(
                "SYSTEM", "대화 내용과 AI 문맥을 지웠습니다." if self.language == "ko"
                else "Chat display and AI context cleared."
            )
            self.command_input.clear()
            return
        result = self.command_router.handle(command)
        is_free_chat = result.text.startswith((
            "아직 자유 대화형 AI는 연결되지 않았어요.",
            "Free-form AI chat is not connected yet.",
        ))
        if is_free_chat:
            self._ask_local_ai(command)
            self.command_input.clear()
            return
        self._add_transcript("You" if self.language == "en" else "사용자", command)
        self._add_transcript("J.A.R.V.I.S.", result.text)
        self._speak_text(result.text)
        self.command_input.clear()

    def _ask_local_ai(self, prompt: str) -> None:
        self._last_ai_prompt = prompt
        self._add_transcript("You" if self.language == "en" else "사용자", prompt)
        self._add_transcript("J.A.R.V.I.S.", "생각 중…" if self.language == "ko" else "Thinking…")
        self._chat_ai_busy = True
        self._refresh_ai_load_mode()
        self.ai_worker = AIResponseWorker(
            self.ai_engine, prompt, list(self.ai_history), self.language, self
        )
        self.ai_worker.completed.connect(self._on_ai_response)
        self.ai_worker.failed.connect(self._on_ai_error)
        self.ai_worker.finished.connect(self._ai_worker_finished)
        self.ai_worker.start()

    def _refresh_ai_load_mode(self) -> None:
        self.core.set_ai_busy(
            self._chat_ai_busy or self._vision_ai_busy or self._speech_ai_busy
        )

    def _on_ai_response(self, answer: str) -> None:
        self._set_ai_status("Connected", True)
        self._remove_pending_line()
        self.ai_history.extend([
            {"role": "user", "content": self._last_ai_prompt},
            {"role": "assistant", "content": answer},
        ])
        self.ai_history = self.ai_history[-8:]
        self._add_transcript("J.A.R.V.I.S. · Ollama", answer)
        self._speak_text(answer)

    def _on_ai_error(self, message: str) -> None:
        self._set_ai_status("Unavailable", False)
        self._remove_pending_line()
        self._add_transcript("J.A.R.V.I.S. · Ollama", message)

    def _add_transcript(self, speaker: str, text: str) -> None:
        if speaker == "SYSTEM" and self.language == "ko":
            speaker = "안내"
        self.transcript.append((speaker, text))
        self.transcript = self.transcript[-20:]
        self._render_transcript()

    def _remove_pending_line(self) -> None:
        if self.transcript and self.transcript[-1][1] in ("생각 중…", "Thinking…"):
            self.transcript.pop()

    def _render_transcript(self) -> None:
        if self.transcript:
            content = "\n\n".join(f"{speaker}: {text}" for speaker, text in self.transcript)
        else:
            content = ("명령 채널 준비 · 자유 대화는 로컬 Ollama 사용"
                       if self.language == "ko" else
                       "Command channel ready · free-form chat uses local Ollama")
        self.command_output.setPlainText(content)
        cursor = self.command_output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.command_output.setTextCursor(cursor)

    def _set_ai_status(self, state: str, ready: bool) -> None:
        card = self.engine_cards[2]
        card.state_en = state
        card.ready = ready
        card.value.setObjectName("engineReady" if ready else "enginePending")
        card.set_language(self.language)
        card.value.style().unpolish(card.value)
        card.value.style().polish(card.value)

    def _set_voice_status(self, state: str, ready: bool) -> None:
        card = self.engine_cards[1]
        card.state_en = state
        card.ready = ready
        card.value.setObjectName("engineReady" if ready else "enginePending")
        card.set_language(self.language)
        card.value.style().unpolish(card.value)
        card.value.style().polish(card.value)

    def _set_screen_status(self, text: str) -> None:
        self.screen_status.setText(text)

    def _toggle_screen_analysis(self, enabled: bool) -> None:
        if not enabled:
            unload_now = self.screen_model_ready
            self.screen_analysis_enabled = False
            self.screen_button.setText("화면 분석 · 끔" if self.language == "ko"
                                       else "SCREEN ANALYSIS · OFF")
            self.screen_timer.stop()
            self.screen_model_ready = False
            self.screen_capture_pending = False
            self._set_screen_status("화면 분석을 끄고 캡처를 중지했습니다." if self.language == "ko"
                                    else "Screen analysis is off; capture stopped.")
            if unload_now and not (self.screen_worker and self.screen_worker.isRunning()):
                self._unload_vision_model()
            return
        free_gib = self.vision_engine.available_memory_gib()
        if free_gib < MIN_SCREEN_FREE_GIB:
            self.screen_button.blockSignals(True)
            self.screen_button.setChecked(False)
            self.screen_button.blockSignals(False)
            self.screen_button.setText("화면 분석 · 끔" if self.language == "ko"
                                       else "SCREEN ANALYSIS · OFF")
            self._set_screen_status(
                f"메모리 여유 부족 ({free_gib:.1f}GiB). "
                f"{MIN_SCREEN_FREE_GIB:.1f}GiB 이상일 때 켜 주세요."
                if self.language == "ko" else
                f"Low available memory ({free_gib:.1f}GiB). "
                f"Try again with at least {MIN_SCREEN_FREE_GIB:.1f}GiB free."
            )
            return
        self.screen_analysis_enabled = True
        self.screen_button.setText("화면 분석 · 켬" if self.language == "ko"
                                   else "SCREEN ANALYSIS · ON")
        self._set_screen_status("로컬 비전 모델 확인 중… 화면 캡처는 모델 확인 뒤 시작합니다."
                                if self.language == "ko" else
                                "Checking the local vision model. Capture starts only after it is ready.")
        worker = ScreenVisionWorker(self.vision_engine, parent=self)
        self.screen_worker = worker
        worker.checked.connect(self._on_screen_model_checked)
        worker.finished.connect(lambda: self._clear_screen_worker(worker))
        worker.start()

    def _clear_screen_worker(self, worker: ScreenVisionWorker) -> None:
        if self.screen_worker is worker:
            self.screen_worker = None
        worker.deleteLater()
        if worker.image is not None:
            self._vision_ai_busy = False
            self._refresh_ai_load_mode()
        if worker.image is not None and not self.screen_analysis_enabled:
            QTimer.singleShot(0, self._unload_vision_model)

    def _unload_vision_model(self) -> None:
        if self.screen_analysis_enabled:
            return
        if self.vision_unload_worker is not None and self.vision_unload_worker.isRunning():
            return
        worker = VisionUnloadWorker(self.vision_engine, self)
        self.vision_unload_worker = worker
        worker.finished.connect(lambda: self._clear_vision_unload_worker(worker))
        worker.start()

    def _clear_vision_unload_worker(self, worker: VisionUnloadWorker) -> None:
        if self.vision_unload_worker is worker:
            self.vision_unload_worker = None
        worker.deleteLater()

    def _on_screen_model_checked(self, available: bool) -> None:
        if not self.screen_analysis_enabled:
            return
        self.screen_model_ready = available
        if not available:
            self.screen_timer.stop()
            self._set_screen_status(
                f"Ollama 또는 비전 모델 '{self.vision_engine.model}'을 찾지 못했습니다. "
                "모델 설치 전에는 화면을 캡처하지 않습니다."
                if self.language == "ko" else
                f"Ollama or vision model '{self.vision_engine.model}' is unavailable. "
                "No screen capture will occur until it is installed."
            )
            return
        self._set_screen_status("로컬 비전 모델 연결됨 · 15초마다 주 화면 설명"
                                if self.language == "ko" else
                                "Local vision model connected · describing the primary screen every 15 seconds")
        self._capture_screen_for_analysis()
        self.screen_timer.start()

    def _capture_screen_for_analysis(self) -> None:
        if (not self.screen_analysis_enabled or not self.screen_model_ready
                or self.screen_capture_pending or (self.screen_worker and self.screen_worker.isRunning())):
            return
        screen = self.screen()
        if screen is None:
            self._set_screen_status("화면 장치를 찾을 수 없습니다." if self.language == "ko"
                                    else "No display is available.")
            return
        self.screen_capture_pending = True
        was_visible = self.isVisible()
        if was_visible:
            self.setWindowOpacity(0.0)
        QTimer.singleShot(180, lambda: self._finish_screen_capture(screen, was_visible))

    def _finish_screen_capture(self, screen, was_visible: bool) -> None:
        try:
            image = screen.grabWindow(0).toImage()
            if image.isNull():
                raise RuntimeError("화면 이미지를 가져오지 못했습니다.")
            image = image.scaled(1280, 900, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
            data = QByteArray()
            buffer = QBuffer(data)
            if not buffer.open(QIODevice.OpenModeFlag.WriteOnly):
                raise RuntimeError("화면 이미지를 인코딩할 수 없습니다.")
            image.save(buffer, "JPEG", 72)
            buffer.close()
            worker = ScreenVisionWorker(self.vision_engine, bytes(data), self)
            worker.language = self.language
            self.screen_worker = worker
            self._vision_ai_busy = True
            self._refresh_ai_load_mode()
            worker.completed.connect(self._on_screen_description)
            worker.failed.connect(self._on_screen_analysis_error)
            worker.finished.connect(lambda: self._clear_screen_worker(worker))
            worker.start()
        except Exception as error:
            self.screen_capture_pending = False
            self._set_screen_status(str(error))
        finally:
            if was_visible:
                self.setWindowOpacity(1.0)

    def _on_screen_description(self, description: str) -> None:
        self.screen_capture_pending = False
        if not self.screen_analysis_enabled:
            return
        self._set_screen_status("화면 설명 · " + description if self.language == "ko"
                                else "Screen · " + description)
        normalized = " ".join(description.split())
        if normalized != getattr(self, "_last_screen_description", None):
            self._last_screen_description = normalized
            self._add_transcript("J.A.R.V.I.S. · 화면" if self.language == "ko"
                                 else "J.A.R.V.I.S. · SCREEN", description)
            self._speak_text(description)

    def _on_screen_analysis_error(self, message: str) -> None:
        self.screen_capture_pending = False
        self.screen_timer.stop()
        self._set_screen_status(message)

    def _check_ai_availability(self) -> None:
        worker = AIAvailabilityWorker(self.ai_engine, self)
        self.ai_status_worker = worker
        worker.checked.connect(
            lambda available: self._set_ai_status(
                "Connected" if available else "Not connected", available
            )
        )
        worker.finished.connect(lambda: self._clear_ai_status_worker(worker))
        worker.start()

    def _clear_ai_status_worker(self, worker: AIAvailabilityWorker) -> None:
        if self.ai_status_worker is worker:
            self.ai_status_worker = None
        worker.deleteLater()

    def _set_voice_output_enabled(self, enabled: bool) -> None:
        self.voice_output_enabled = enabled
        if not enabled:
            self.speech_queue.clear()
            SpeechOutputEngine.stop()
        self.speak_button.setText(
            ("말로 답변 · 켬" if enabled else "말로 답변 · 끔") if self.language == "ko"
            else ("SPEAK ON" if enabled else "SPEAK OFF")
        )

    def _speak_text(self, text: str) -> None:
        if not self.voice_output_enabled or not text.strip():
            return
        if self.speech_worker is not None and self.speech_worker.isRunning():
            if len(self.speech_queue) < 3:
                self.speech_queue.append(text)
            return
        worker = SpeechOutputWorker(text, self)
        self.speech_worker = worker
        self._speech_ai_busy = True
        self._refresh_ai_load_mode()
        worker.failed.connect(self._on_speech_error)
        worker.finished.connect(self._speech_worker_finished)
        self.speak_button.setText("말하는 중…" if self.language == "ko" else "SPEAKING…")
        self.voice_button.setEnabled(False)
        worker.start()

    def _on_speech_error(self, message: str) -> None:
        self._add_transcript("SYSTEM", message)

    def _speech_worker_finished(self) -> None:
        worker = self.speech_worker
        self.speech_worker = None
        self._speech_ai_busy = False
        self._refresh_ai_load_mode()
        if worker is not None:
            worker.deleteLater()
        self.voice_button.setEnabled(
            self.voice_worker is None or not self.voice_worker.isRunning()
        )
        self.set_language(self.language)
        if self.voice_output_enabled and self.speech_queue:
            self._speak_text(self.speech_queue.pop(0))

    def _ai_worker_finished(self) -> None:
        worker = self.ai_worker
        self.ai_worker = None
        self._chat_ai_busy = False
        self._refresh_ai_load_mode()
        if worker is not None:
            worker.deleteLater()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() == Qt.Key.Key_F11:
            self.showNormal() if self.isFullScreen() else self.showFullScreen()
        else:
            super().keyPressEvent(event)
