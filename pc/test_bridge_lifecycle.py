"""Verify tray stop requests release audio and the exclusive serial port."""
import threading
import queue
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from listen import run_bridge


class LifecycleTests(unittest.TestCase):
    def test_usb_control_uses_shared_port_and_cancels_pairing_on_exit(self):
        from test_phone_control import STATUS, status_frame
        from phone_control import command_frame
        stop = threading.Event()
        serial = MagicMock()
        sd = MagicMock()
        serial.SerialException = type("SerialException", (Exception,), {})
        sd.PortAudioError = type("PortAudioError", (Exception,), {})
        port = serial.Serial.return_value
        port.in_waiting = 0
        def read(_):
            stop.set()
            return status_frame(STATUS)
        port.read.side_effect = read
        port.write.side_effect = len
        commands = queue.Queue()
        selected = dict(cmd="select", address=STATUS["selected"])
        commands.put(selected)
        received = []
        args = SimpleNamespace(port="COM_TEST", baud=921600, device=None,
                               input_device=None, no_mic=True, mic_gain=1)
        with patch.dict("sys.modules", {"serial": serial, "sounddevice": sd}), patch("listen.MediaDecoder"):
            run_bridge(args, stop, commands=commands, on_control=received.append)
        self.assertEqual(received, [STATUS])
        sent = [call.args[0] for call in port.write.call_args_list]
        self.assertEqual(sent, [command_frame(dict(cmd="status")), command_frame(selected), command_frame(dict(cmd="cancel"))])
        port.__exit__.assert_called_once()

    def test_stop_releases_serial_and_both_audio_streams(self):
        stop = threading.Event()
        serial = MagicMock()
        sd = MagicMock()
        serial.SerialException = type("SerialException", (Exception,), {})
        sd.PortAudioError = type("PortAudioError", (Exception,), {})
        port = serial.Serial.return_value
        port.in_waiting = 0
        def read(_):
            stop.set()
            return b""
        port.read.side_effect = read
        statuses = []
        args = SimpleNamespace(port="COM_TEST", baud=921600, device=None,
                               input_device=None, no_mic=False, mic_gain=1)
        with patch.dict("sys.modules", {"serial": serial, "sounddevice": sd}), patch("listen.MediaDecoder"):
            run_bridge(args, stop, statuses.append)
        port.__exit__.assert_called_once()
        sd.RawOutputStream.return_value.__exit__.assert_called_once()
        sd.RawInputStream.return_value.__exit__.assert_called_once()
        self.assertTrue(statuses)


if __name__ == "__main__":
    unittest.main()
