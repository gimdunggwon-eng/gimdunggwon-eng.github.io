"""Opt-in local hand gesture recognition for the JARVIS HUD."""

from __future__ import annotations

import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QThread, Signal


MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/"
    "gesture_recognizer/float16/1/gesture_recognizer.task"
)


class GestureWorker(QThread):
    status = Signal(str)
    gesture = Signal(str, float, float)
    failed = Signal(str)

    def __init__(self, model_path: Path, parent=None) -> None:
        super().__init__(parent)
        self.model_path = model_path

    def run(self) -> None:
        capture = None
        try:
            try:
                import cv2
                import mediapipe as mp
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "Optional gesture packages are missing. Install them with "
                    r'.\.venv\Scripts\python.exe -m pip install -r requirements-gestures.txt'
                ) from exc

            if not self.model_path.is_file():
                self.status.emit("Downloading gesture model…")
                self.model_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.model_path.with_suffix(".download")
                try:
                    request = urllib.request.Request(
                        MODEL_URL, headers={"User-Agent": "JARVIS-OS/0.1"}
                    )
                    with urllib.request.urlopen(request, timeout=45) as response:
                        with temporary.open("wb") as target:
                            while True:
                                if self.isInterruptionRequested():
                                    return
                                chunk = response.read(1024 * 256)
                                if not chunk:
                                    break
                                target.write(chunk)
                    temporary.replace(self.model_path)
                finally:
                    temporary.unlink(missing_ok=True)

            if self.isInterruptionRequested():
                return

            vision = mp.tasks.vision
            options = vision.GestureRecognizerOptions(
                base_options=mp.tasks.BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=vision.RunningMode.VIDEO,
                num_hands=1,
            )
            backends = list(dict.fromkeys((
                getattr(cv2, "CAP_MSMF", 0),
                getattr(cv2, "CAP_DSHOW", 0),
                getattr(cv2, "CAP_ANY", 0),
            )))
            initial_frame = None
            for index in range(6):
                for backend in backends:
                    candidate = cv2.VideoCapture(index, backend)
                    if candidate.isOpened():
                        candidate.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                        candidate.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                        ok, frame = candidate.read()
                        if ok and frame is not None:
                            capture = candidate
                            initial_frame = frame
                            break
                    candidate.release()
                if capture is not None:
                    break
            if capture is None:
                raise RuntimeError(
                    "No usable camera detected. Check the webcam shutter or Windows camera access, "
                    "close other apps using it, and retry."
                )
            self.status.emit("Gesture control is active. Video stays on this PC.")
            last_emit = 0
            with vision.GestureRecognizer.create_from_options(options) as recognizer:
                while not self.isInterruptionRequested():
                    if initial_frame is not None:
                        frame, initial_frame = initial_frame, None
                        ok = True
                    else:
                        ok, frame = capture.read()
                    if not ok:
                        self.msleep(40)
                        continue
                    frame = cv2.flip(frame, 1)
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                    # MediaPipe requires strictly increasing timestamps in video mode.
                    timestamp = max(getattr(self, "_timestamp", 0) + 1,
                                     int(time.monotonic() * 1000))
                    self._timestamp = timestamp
                    result = recognizer.recognize_for_video(image, timestamp)
                    if not result.hand_landmarks:
                        continue
                    category = (result.gestures[0][0]
                                if result.gestures and result.gestures[0] else None)
                    name = (category.category_name or "None") if category else "None"
                    now = timestamp
                    if now - last_emit < 100:
                        continue
                    last_emit = now
                    points = result.hand_landmarks[0]
                    # MediaPipe's canned labels do not include an L pose, so
                    # recognize thumb + index extended with the other fingers folded.
                    def distance(a, b):
                        return ((points[a].x - points[b].x) ** 2
                                + (points[a].y - points[b].y) ** 2) ** .5

                    index_extended = distance(8, 0) > distance(6, 0) * 1.12
                    middle_folded = distance(12, 0) < distance(10, 0) * 1.12
                    ring_folded = distance(16, 0) < distance(14, 0) * 1.12
                    pinky_folded = distance(20, 0) < distance(18, 0) * 1.12
                    thumb_extended = distance(4, 5) > distance(3, 5) * 1.22
                    palm_width = max(distance(5, 17), .001)
                    ok_circle = distance(4, 8) < palm_width * .34
                    middle_extended = distance(12, 0) > distance(10, 0) * 1.12
                    ring_extended = distance(16, 0) > distance(14, 0) * 1.10
                    pinky_extended = distance(20, 0) > distance(18, 0) * 1.08
                    if (ok_circle and middle_extended and ring_extended
                            and pinky_extended):
                        name = "OK_Gesture"
                    elif (index_extended and thumb_extended and middle_folded
                            and ring_folded and pinky_folded):
                        name = "L_Gesture"
                    self.gesture.emit(name, float(points[9].x), float(points[9].y))
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            if capture is not None:
                capture.release()

