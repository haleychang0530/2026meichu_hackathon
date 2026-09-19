from __future__ import annotations

import io
import sys
import types
import unittest
from unittest.mock import patch

from PIL import Image

from core_api.gimbal import Detection, GimbalController, GimbalError, SerialLink


class FakeSerial:
    def __init__(self) -> None:
        self.pan = 0
        self.tilt = 25
        self.commands: list[tuple[str, tuple[int, ...]]] = []

    def command(self, sequence: int, name: str, *args: int) -> tuple[int, int]:
        self.commands.append((name, args))
        if name == "STEP":
            self.pan += args[0]
            self.tilt += args[1]
        return self.pan, self.tilt

    def close(self) -> None:
        pass


class FakeDetector:
    def __init__(self, detections: list[Detection | None]) -> None:
        self.detections = iter(detections)

    def detect(self, image: Image.Image) -> Detection | None:
        return next(self.detections)


def frame() -> bytes:
    image = Image.new("RGB", (640, 480), "white")
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


def controller(detections: list[Detection | None]) -> tuple[GimbalController, FakeSerial]:
    gimbal = GimbalController("COM_TEST", 115200, "fake.pt")
    serial = FakeSerial()
    gimbal._detector = FakeDetector(detections)
    gimbal._serial = serial
    gimbal._active = True
    gimbal._start_pan = 0
    gimbal._start_tilt = 25
    return gimbal, serial


class GimbalLoopTests(unittest.TestCase):
    def test_three_centered_frames_enable_capture_without_movement(self) -> None:
        page = Detection(0.2, 0.2, 0.6, 0.6, 0.8, "model")
        gimbal, serial = controller([page, page, page])
        self.assertEqual(gimbal.observe(frame()).state, "settling")
        self.assertEqual(gimbal.observe(frame()).state, "settling")
        result = gimbal.observe(frame())
        self.assertEqual(result.state, "ready")
        self.assertEqual(result.box.source, "model")
        self.assertEqual(serial.commands, [])

    def test_off_center_page_sends_bounded_steps(self) -> None:
        page = Detection(0.65, 0.2, 0.25, 0.6, 0.8, "model")
        gimbal, serial = controller([page] * 8)
        states = [gimbal.observe(frame()).state for _ in range(8)]
        self.assertEqual(states[:4], ["aligning"] * 4)
        self.assertEqual(states[4], "limit")
        self.assertEqual(gimbal._pan, 8)
        self.assertEqual(serial.commands, [("STEP", (2, 0))] * 4)

    def test_missing_page_search_is_finite(self) -> None:
        gimbal, serial = controller([None] * 9)
        states = [gimbal.observe(frame()).state for _ in range(9)]
        self.assertEqual(states[-1], "not_found")
        self.assertEqual(len(serial.commands), 8)
        self.assertEqual(gimbal._pan, 0)
        self.assertEqual(gimbal._tilt, 25)

    def test_test_command_is_explicit(self) -> None:
        gimbal, serial = controller([])
        result = gimbal.test()
        self.assertEqual(result.state, "testing")
        self.assertEqual(serial.commands, [("TEST", ())])

    def test_serial_wire_command_and_ack(self) -> None:
        class Device:
            sent = b""

            def reset_input_buffer(self) -> None:
                pass

            def write(self, value: bytes) -> None:
                self.sent = value

            def flush(self) -> None:
                pass

            def readline(self) -> bytes:
                return b"ACK 17 2 23\n"

            def close(self) -> None:
                pass

        device = Device()
        with patch.dict(sys.modules, {"serial": types.SimpleNamespace(Serial=lambda *args, **kwargs: device)}):
            with patch("core_api.gimbal.time.sleep"):
                link = SerialLink("COM_TEST", 115200)
        self.assertEqual(link.command(17, "STEP", 2, -2), (2, 23))
        self.assertEqual(device.sent, b"STEP 17 2 -2\n")

    def test_serial_rejection_is_visible(self) -> None:
        class Device:
            def reset_input_buffer(self) -> None:
                pass

            def write(self, value: bytes) -> None:
                pass

            def flush(self) -> None:
                pass

            def readline(self) -> bytes:
                return b"ERR 18 BAD_STEP\n"

            def close(self) -> None:
                pass

        with patch.dict(sys.modules, {"serial": types.SimpleNamespace(Serial=lambda *args, **kwargs: Device())}):
            with patch("core_api.gimbal.time.sleep"):
                link = SerialLink("COM_TEST", 115200)
        with self.assertRaisesRegex(GimbalError, "BAD_STEP"):
            link.command(18, "STEP", 3, 0)



if __name__ == "__main__":
    unittest.main()
