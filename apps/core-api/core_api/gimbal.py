from __future__ import annotations

"""Small, local visual-servo loop for the capture demo.

The browser owns the webcam. This module only sees short-lived preview JPEGs;
it owns the one USB serial connection and never stores those JPEGs.
"""

import io
import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError


class GimbalError(Exception):
    pass


@dataclass(frozen=True)
class PageBox:
    x: float
    y: float
    width: float
    height: float
    confidence: float
    source: str


@dataclass(frozen=True)
class GimbalResult:
    state: str
    message: str
    pan: int | None = None
    tilt: int | None = None
    box: PageBox | None = None
    direction: str | None = None
    sequence: int | None = None
    schema_version: Literal["0.1.0"] = "0.1.0"


@dataclass(frozen=True)
class Detection:
    x: float
    y: float
    width: float
    height: float
    confidence: float
    source: str

    def response_box(self) -> PageBox:
        return PageBox(**self.__dict__)


class PageDetector:
    """Use a nano object detector first; use page contours for loose sheets."""

    def __init__(self, model_path: str) -> None:
        try:
            from ultralytics import YOLO
        except Exception as exc:
            raise GimbalError("無法載入 ultralytics；請檢查雲台 demo 的 Python 套件。") from exc
        try:
            self.model = YOLO(model_path)
            names = self.model.names
            classes = names.items() if isinstance(names, dict) else enumerate(names)
            available = {str(name).lower(): int(index) for index, name in classes}
            self.page_class = available.get("page", available.get("book"))
            if self.page_class is None:
                raise ValueError("model has no page or book class")
        except Exception as exc:
            raise GimbalError("無法載入具有 page 或 book 類別的輕量視覺模型。") from exc

    def detect(self, image: Image.Image) -> Detection | None:
        import numpy as np

        width, height = image.size
        try:
            results = self.model.predict(
                source=image,
                classes=[self.page_class],
                conf=0.25,
                imgsz=640,
                device="cpu",
                verbose=False,
            )
        except Exception as exc:
            raise GimbalError("本機頁面模型推論失敗。") from exc
        if results and len(results[0].boxes):
            boxes = results[0].boxes
            index = int(boxes.conf.argmax().item())
            left, top, right, bottom = boxes.xyxy[index].tolist()
            return Detection(
                x=max(0.0, left / width),
                y=max(0.0, top / height),
                width=min(1.0, (right - left) / width),
                height=min(1.0, (bottom - top) / height),
                confidence=float(boxes.conf[index].item()),
                source="model",
            )

        # COCO's "book" class does not promise detection of a loose page.
        # This deliberately simple fallback is useful for a controlled demo.
        import cv2

        rgb = np.asarray(image)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 60, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates: list[tuple[float, tuple[int, int, int, int]]] = []
        area = width * height
        for contour in contours:
            perimeter = cv2.arcLength(contour, True)
            polygon = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
            if len(polygon) != 4:
                continue
            x, y, w, h = cv2.boundingRect(polygon)
            fraction = cv2.contourArea(polygon) / area
            if 0.08 <= fraction <= 0.90 and w > 0 and h > 0:
                candidates.append((fraction, (x, y, w, h)))
        if not candidates:
            return None
        _, (x, y, w, h) = max(candidates)
        return Detection(x / width, y / height, w / width, h / height, 0.35, "contour")


class SerialLink:
    """One request at a time; firmware echoes the request sequence in ACK."""

    def __init__(self, port: str, baud: int) -> None:
        try:
            import serial

            self.device = serial.Serial(port, baudrate=baud, timeout=3.0, write_timeout=3.0)
            # Opening a USB serial port commonly resets ESP32 boards.
            time.sleep(1.8)
            self.device.reset_input_buffer()
        except (ImportError, OSError) as exc:
            raise GimbalError(f"無法開啟 ESP32 序列埠 {port}。") from exc

    def command(self, sequence: int, name: str, *args: int) -> tuple[int, int]:
        line = " ".join([name, str(sequence), *(str(arg) for arg in args)]) + "\n"
        try:
            self.device.write(line.encode("ascii"))
            self.device.flush()
            response = self.device.readline().decode("ascii", errors="replace").strip().split()
        except (OSError, UnicodeError) as exc:
            raise GimbalError("ESP32 序列通訊失敗。") from exc
        if len(response) >= 4 and response[0] == "ACK" and response[1] == str(sequence):
            try:
                return int(response[2]), int(response[3])
            except ValueError as exc:
                raise GimbalError("ESP32 回覆格式錯誤。") from exc
        if len(response) >= 3 and response[0] == "ERR" and response[1] == str(sequence):
            raise GimbalError(f"ESP32 拒絕指令：{response[2]}。")
        raise GimbalError("ESP32 沒有在期限內確認指令；請檢查序列埠與韌體。")

    def close(self) -> None:
        self.device.close()


class GimbalController:
    """Bounded position controller. The next image is the movement feedback."""

    def __init__(self, port: str | None, baud: int, model_path: str) -> None:
        self.port = port
        self.baud = baud
        self.model_path = model_path
        self._lock = threading.RLock()
        self._serial: SerialLink | None = None
        self._detector: Any = None
        self._sequence = 0
        self._active = False
        self._pan = 0
        self._tilt = 25
        self._start_pan = 0
        self._start_tilt = 25
        self._stable = 0
        self._last_axis: str | None = None
        self._last_error = 0.0
        self._pan_sign = 1
        self._tilt_sign = 1
        self._search_index = 0

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def start(self) -> GimbalResult:
        with self._lock:
            if not self.port:
                raise GimbalError("尚未設定 GIMBAL_PORT；請指定 ESP32 的 COM 埠。")
            if self._serial is None:
                self._serial = SerialLink(self.port, self.baud)
            sequence = self._next_sequence()
            try:
                self._pan, self._tilt = self._serial.command(sequence, "PING")
            except GimbalError:
                self._serial.close()
                self._serial = None
                raise
            self._active = True
            self._start_pan, self._start_tilt = self._pan, self._tilt
            self._stable = 0
            self._last_axis = None
            self._search_index = 0
            return GimbalResult(state="searching", message="ESP32 已連線，正在尋找頁面。", pan=self._pan, tilt=self._tilt, sequence=sequence)

    def test(self) -> GimbalResult:
        with self._lock:
            if not self._active or self._serial is None:
                raise GimbalError("請先啟動雲台對準。")
            sequence = self._next_sequence()
            self._pan, self._tilt = self._serial.command(sequence, "TEST")
            return GimbalResult(state="testing", message="ESP32 已完成上下左右測試動作。", pan=self._pan, tilt=self._tilt, sequence=sequence)

    def _move(self, pan_delta: int, tilt_delta: int, box: PageBox | None, state: str) -> GimbalResult:
        assert self._serial is not None
        target_pan = max(-180, min(180, self._pan + pan_delta))
        target_tilt = max(0, min(50, self._tilt + tilt_delta))
        target_pan = max(self._start_pan - 24, min(self._start_pan + 24, target_pan))
        target_tilt = max(self._start_tilt - 5, min(self._start_tilt + 5, target_tilt))
        pan_delta, tilt_delta = target_pan - self._pan, target_tilt - self._tilt
        if pan_delta == 0 and tilt_delta == 0:
            return GimbalResult(state="limit", message="已到 demo 的小範圍移動邊界，可手動調整紙張或拍照。", pan=self._pan, tilt=self._tilt, box=box)
        sequence = self._next_sequence()
        self._pan, self._tilt = self._serial.command(sequence, "STEP", pan_delta, tilt_delta)
        direction = "right" if pan_delta > 0 else "left" if pan_delta < 0 else "down" if tilt_delta > 0 else "up"
        return GimbalResult(state=state, message="雲台已小幅調整，正在檢查下一張畫面。", pan=self._pan, tilt=self._tilt, box=box, direction=direction, sequence=sequence)

    def observe(self, image_bytes: bytes) -> GimbalResult:
        with self._lock:
            if not self._active or self._serial is None:
                raise GimbalError("請先啟動雲台對準。")
            if len(image_bytes) > 1_000_000:
                raise ValueError("預覽影格過大。")
            try:
                image = Image.open(io.BytesIO(image_bytes))
                image.load()
                if image.width > 1280 or image.height > 1280 or image.width < 64 or image.height < 64:
                    raise ValueError("預覽影格尺寸不正確。")
                image = image.convert("RGB")
            except (UnidentifiedImageError, OSError) as exc:
                raise ValueError("預覽影格不是有效圖片。") from exc

            if self._detector is None:
                self._detector = PageDetector(self.model_path)
            detected = self._detector.detect(image)
            if detected is None:
                self._stable = 0
                self._last_axis = None
                # A tiny, finite search gives the model another view without
                # sweeping the whole table or moving outside the demo window.
                search_steps = ((8, 0), (-8, 0), (-8, 0), (8, 0), (0, 2), (0, -2), (0, -2), (0, 2))
                if self._search_index >= len(search_steps):
                    return GimbalResult(state="not_found", message="找不到頁面；請先把紙張移到鏡頭附近。", pan=self._pan, tilt=self._tilt)
                step = search_steps[self._search_index]
                self._search_index += 1
                return self._move(*step, box=None, state="searching")

            self._search_index = 0
            box = detected.response_box()
            error_x = detected.x + detected.width / 2 - 0.5
            error_y = detected.y + detected.height / 2 - 0.5
            complete = detected.x > 0.02 and detected.y > 0.02 and detected.x + detected.width < 0.98 and detected.y + detected.height < 0.98
            if abs(error_x) < 0.08 and abs(error_y) < 0.08 and complete:
                self._stable += 1
                self._last_axis = None
                if self._stable >= 3:
                    return GimbalResult(state="ready", message="頁面位置已穩定，可以拍照。", pan=self._pan, tilt=self._tilt, box=box)
                return GimbalResult(state="settling", message="頁面已接近中央，正在確認畫面穩定。", pan=self._pan, tilt=self._tilt, box=box)

            self._stable = 0
            if abs(error_x) < 0.08 and abs(error_y) < 0.08 and not complete:
                return GimbalResult(state="limit", message="頁面已在中央但未完整入鏡；請調整紙張或鏡頭距離。", pan=self._pan, tilt=self._tilt, box=box)
            axis = "pan" if abs(error_x) >= abs(error_y) else "tilt"
            error = error_x if axis == "pan" else error_y
            if self._last_axis == axis and abs(error) > abs(self._last_error) + 0.015:
                if axis == "pan":
                    self._pan_sign *= -1
                else:
                    self._tilt_sign *= -1
            self._last_axis, self._last_error = axis, error
            step = int(math.copysign(8 if axis == "pan" else 2, error))
            if axis == "pan":
                return self._move(step * self._pan_sign, 0, box, "aligning")
            return self._move(0, step * self._tilt_sign, box, "aligning")

    def stop(self) -> GimbalResult:
        with self._lock:
            self._active = False
            if self._serial is not None:
                try:
                    self._serial.command(self._next_sequence(), "STOP")
                finally:
                    self._serial.close()
                    self._serial = None
            return GimbalResult(state="stopped", message="雲台已停止調整。", pan=self._pan, tilt=self._tilt)
