"""Audio policy/lifetime tests without changing Windows volumes or using USB."""
import queue
import ctypes
import os
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from listen import DesktopOutput, run_bridge
from windows_audio import CommunicationSession, audio_thread_com, category_settings, desktop_output_device


def fake_audio():
    sd = MagicMock()
    sd.__version__ = "0.5.6"
    sd.PortAudioError = type("PortAudioError", (Exception,), {})
    sd._lib.eAudioCategoryMedia = 11
    sd._lib.eAudioCategoryCommunications = 3
    sd.WasapiSettings.side_effect = lambda **kw: SimpleNamespace(
        _streaminfo=SimpleNamespace(streamCategory=0), **kw)
    hosts = [dict(name="MME", default_output_device=4),
             dict(name="Windows WASAPI", default_output_device=15)]
    sd.query_hostapis.side_effect = lambda index=None: hosts if index is None else hosts[index]
    sd.query_devices.side_effect = lambda device: dict(name="Test headset", hostapi=0 if device == 4 else 1)
    sd.default.device = (1, 4)
    sd.RawOutputStream.side_effect = lambda **kw: MagicMock()
    return sd


class OutputTests(unittest.TestCase):
    def setUp(self):
        self.sd = fake_audio()
        self.messages = []
        protect = patch("windows_audio.protect_playback")
        protect.start()
        self.addCleanup(protect.stop)
        sessions = patch("windows_audio.CommunicationSession")
        self.sessions = sessions.start()
        self.sessions.side_effect = lambda *args: MagicMock()
        self.addCleanup(sessions.stop)
        self.output = DesktopOutput(self.sd, None, MagicMock(),
                                    True, self.messages.append)
        self.addCleanup(self.output.close)
        self.output.start()

    def state(self, now, **changes):
        status = dict(ready=True, hfp=True, call=True)
        status.update(changes)
        self.output.control(status, now)

    def categories(self):
        return [c.kwargs["extra_settings"]._streaminfo.streamCategory
                for c in self.sd.RawOutputStream.call_args_list]

    def test_default_prefers_wasapi_explicit_device_is_never_remapped(self):
        self.assertEqual(desktop_output_device(self.sd, None), 15)
        self.assertEqual(desktop_output_device(self.sd, 4), 4)
        self.assertEqual(desktop_output_device(self.sd, 16), 16)
        self.assertEqual(self.sd.RawOutputStream.call_args.kwargs["device"], 15)

    def test_call_session_closes_without_reopening_playback(self):
        media = self.output.stream
        self.state(10)
        session = self.output.session
        self.sessions.assert_called_once_with(self.sd, 15)
        self.state(11)
        self.assertIs(self.output.session, session)
        self.state(12, call=False)
        session.close.assert_called_once()
        self.assertIsNone(self.output.session)
        self.assertIs(self.output.stream, media)
        media.close.assert_not_called()
        self.assertEqual(self.categories(), [11])
        self.assertFalse(self.sd.RawOutputStream.call_args.kwargs["extra_settings"].exclusive)
        self.assertTrue(self.sd.RawOutputStream.call_args.kwargs["extra_settings"].auto_convert)
        self.state(13)
        self.assertIsNot(self.output.session, session)
        self.assertEqual(self.sessions.call_count, 2)

    def test_silence_does_not_end_call_but_missing_status_expires_at_five_seconds(self):
        self.state(10)
        self.output.tick(14.9)
        self.assertTrue(self.output.communication)
        self.state(14.9)  # A call snapshot, with no PCM at all, refreshes the lease.
        self.output.tick(19.8)
        self.assertTrue(self.output.communication)
        self.output.tick(19.9)
        self.assertFalse(self.output.communication)
        self.assertEqual(self.categories(), [11])

    def test_unready_disconnected_and_no_call_each_release_communication(self):
        for change in (dict(ready=False), dict(hfp=False), dict(call=False)):
            with self.subTest(change=change):
                self.state(10)
                self.assertTrue(self.output.communication)
                self.state(11, **change)
                self.assertFalse(self.output.communication)

    def test_media_never_triggers_ducking(self):
        self.state(10, call=False)
        self.output.tick(20)
        self.assertEqual(self.categories(), [11])

    def test_close_releases_call_and_is_idempotent(self):
        self.state(10)
        voice = self.output.session
        self.output.close()
        self.output.close()
        voice.close.assert_called_once()
        self.assertFalse(self.output.communication)

    def test_failed_call_session_keeps_playback_without_retry_loop(self):
        media = self.output.stream
        self.sessions.side_effect = OSError("communications refused")
        self.state(10)
        self.assertIs(self.output.stream, media)
        media.close.assert_not_called()
        self.assertIn("Atténuation indisponible", self.messages[-1])
        self.state(11)
        self.state(12, call=False)
        self.state(13)
        self.sessions.assert_called_once()
        self.assertEqual(self.categories(), [11])

    def test_pump_error_releases_session_and_preserves_playback(self):
        self.state(10)
        session = self.output.session
        session.pump.side_effect = OSError("device lost")
        self.output.tick(11)
        session.close.assert_called_once()
        self.assertIsNone(self.output.session)
        self.assertFalse(self.output.communication)
        self.output.stream.close.assert_not_called()
        self.assertIn("Atténuation indisponible", self.messages[-1])

    def test_protection_failure_disables_ducking_but_starts_playback(self):
        with patch("windows_audio.protect_playback", side_effect=OSError("no session control")):
            output = DesktopOutput(self.sd, 15, MagicMock(), True, self.messages.append)
            self.addCleanup(output.close)
            output.start()
            output.control(dict(ready=True, hfp=True, call=True), 10)
        self.assertFalse(output.communication)
        output.stream.start.assert_called_once()
        self.sessions.assert_not_called()

    def test_legacy_output_plays_unchanged_with_warning(self):
        messages = []
        output = DesktopOutput(self.sd, 4, MagicMock(), True, messages.append)
        self.addCleanup(output.close)
        output.start()
        output.control(dict(ready=True, hfp=True, call=True), 10)
        kwargs = self.sd.RawOutputStream.call_args.kwargs
        self.assertEqual(kwargs["device"], 4)
        self.assertNotIn("extra_settings", kwargs)
        self.assertIn("Windows WASAPI", messages[0])

    def test_disabled_option_keeps_media_category_during_call(self):
        output = DesktopOutput(self.sd, 15, MagicMock(), False, lambda _: None)
        self.addCleanup(output.close)
        output.start()
        output.control(dict(ready=True, hfp=True, call=True), 10)
        self.assertFalse(output.communication)
        self.assertEqual(self.categories(), [11, 11])

    def test_incompatible_adapter_preserves_shared_playback(self):
        self.sd.__version__ = "future"
        messages = []
        output = DesktopOutput(self.sd, 15, MagicMock(), True, messages.append)
        self.addCleanup(output.close)
        output.start()
        output.control(dict(ready=True, hfp=True, call=True), 10)
        self.assertFalse(output.communication)
        self.assertFalse(self.sd.RawOutputStream.call_args.kwargs["extra_settings"].exclusive)
        self.assertIn("Atténuation indisponible", messages[0])

    def test_real_installed_adapter_without_opening_audio(self):
        try:
            import sounddevice as sd
        except ImportError:
            self.skipTest("sounddevice not installed")
        media, voice = category_settings(sd, False), category_settings(sd, True)
        self.assertEqual(media._streaminfo.streamCategory, 11)
        self.assertEqual(voice._streaminfo.streamCategory, 3)


class BridgeAudioTests(unittest.TestCase):
    def test_desktop_call_cleanup_on_stop_and_usb_error_without_microphone(self):
        from test_phone_control import STATUS, status_frame
        for usb_error in (False, True):
            with self.subTest(usb_error=usb_error):
                sd = fake_audio()
                streams = []
                def open_stream(**kwargs):
                    stream = MagicMock()
                    streams.append(stream)
                    return stream
                sd.RawOutputStream.side_effect = open_stream
                serial = MagicMock()
                serial.SerialException = type("SerialException", (Exception,), {})
                port = serial.Serial.return_value
                port.in_waiting = 0
                port.write.side_effect = len
                stop = threading.Event()
                first = True
                def read(_):
                    nonlocal first
                    if first:
                        first = False
                        return status_frame(dict(STATUS, ready=True, hfp=True, call=True))
                    if usb_error:
                        raise serial.SerialException("USB lost")
                    stop.set()
                    return b""
                port.read.side_effect = read
                args = SimpleNamespace(port="TEST", baud=921600, device=None,
                                       no_mic=True, mic_gain=1, input_device=None,
                                       desktop_audio=True, windows_ducking=True)
                with patch.dict("sys.modules", {"serial": serial, "sounddevice": sd}), patch("listen.MediaDecoder"), patch("windows_audio.protect_playback"), patch("windows_audio.CommunicationSession") as sessions:
                    if usb_error:
                        with self.assertRaises(SystemExit):
                            run_bridge(args, stop, commands=queue.Queue())
                    else:
                        run_bridge(args, stop, commands=queue.Queue())
                self.assertEqual(len(streams), 1)
                sessions.return_value.close.assert_called_once()
                for stream in streams:
                    stream.close.assert_called_once()
                port.__exit__.assert_called_once()
                sd.RawInputStream.assert_not_called()


class ComLifetimeTests(unittest.TestCase):
    def test_success_and_existing_mta_are_balanced_even_on_error(self):
        for code in (0, 1):
            with self.subTest(code=code):
                ole = MagicMock()
                ole.CoInitializeEx.return_value = code
                with patch("windows_audio.sys.platform", "win32"), patch("windows_audio.ctypes.WinDLL", return_value=ole, create=True):
                    with self.assertRaisesRegex(RuntimeError, "stream failed"):
                        with audio_thread_com():
                            ole.CoInitializeEx.assert_called_once_with(None, 0)
                            ole.CoUninitialize.assert_not_called()
                            raise RuntimeError("stream failed")
                ole.CoUninitialize.assert_called_once_with()

    def test_existing_sta_is_not_uninitialized_by_us(self):
        ole = MagicMock()
        ole.CoInitializeEx.return_value = -2147417850  # RPC_E_CHANGED_MODE
        with patch("windows_audio.sys.platform", "win32"), patch("windows_audio.ctypes.WinDLL", return_value=ole, create=True):
            with audio_thread_com():
                pass
        ole.CoUninitialize.assert_not_called()

    def test_initialization_failure_does_not_enter_body(self):
        ole = MagicMock()
        ole.CoInitializeEx.return_value = -2147024882  # E_OUTOFMEMORY
        with patch("windows_audio.sys.platform", "win32"), patch("windows_audio.ctypes.WinDLL", return_value=ole, create=True):
            with self.assertRaisesRegex(OSError, "0x8007000E"):
                with audio_thread_com():
                    self.fail("COM initialization failed")
        ole.CoUninitialize.assert_not_called()


class NativeSessionCleanupTests(unittest.TestCase):
    def exercise(self, failure=None):
        released = []
        stopped = []
        library, ole = MagicMock(), MagicMock()

        def put(target, value, kind=ctypes.c_void_p):
            ctypes.cast(target, ctypes.POINTER(kind)).contents.value = value

        def endpoint(device, result):
            put(result, 100)
            return 0
        library.PaWasapi_GetIMMDevice.side_effect = endpoint

        def method(obj, slot, *types):
            def invoke(this, *args):
                address = obj.value
                if slot == 2:
                    released.append(address)
                elif address == 100 and slot == 3:
                    put(args[-1], 200)
                elif address == 200:
                    if (slot, failure) in ((3, "initialize"), (14, "service"), (10, "start")):
                        return -2147467259
                    if slot == 8:
                        put(args[-1], 400)
                    elif slot == 14:
                        put(args[-1], 300)
                    elif slot == 4:
                        put(args[-1], 960, ctypes.c_uint)
                    elif slot == 6:
                        put(args[-1], 0, ctypes.c_uint)
                    elif slot == 11:
                        stopped.append(address)
                elif address == 300 and slot == 3:
                    put(args[-1], 500)
                return 0
            return invoke

        with patch("windows_audio._portaudio", return_value=library), \
                patch("windows_audio._method", side_effect=method), \
                patch("windows_audio.ctypes.WinDLL", return_value=ole, create=True):
            if failure:
                with self.assertRaises(OSError):
                    CommunicationSession(fake_audio(), 15)
            else:
                session = CommunicationSession(fake_audio(), 15)
                session.close()
                session.close()
        return released, stopped, ole

    def test_partial_initialization_releases_owned_references_only(self):
        for stage in ("initialize", "service", "start"):
            with self.subTest(stage=stage):
                released, stopped, ole = self.exercise(stage)
                self.assertEqual(released, [300, 200] if stage == "start" else [200])
                self.assertEqual(stopped, [])
                ole.CoTaskMemFree.assert_called_once()

    def test_close_stops_once_and_releases_renderer_before_client(self):
        released, stopped, ole = self.exercise()
        self.assertEqual(stopped, [200])
        self.assertEqual(released, [300, 200])
        ole.CoTaskMemFree.assert_called_once()


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("SMARTCON_TEST_AUDIO") == "1",
                     "Set SMARTCON_TEST_AUDIO=1 to test real Windows output (silence, no microphone or USB)")
class RealWorkerAudioTests(unittest.TestCase):
    def test_gui_initialized_portaudio_then_worker_runs_media_call_media_twice(self):
        import sounddevice as sd  # Initialize PortAudio on the test/main thread.
        from test_phone_control import STATUS, status_frame
        # Match Application.refresh() before creating the audio worker.
        sd._terminate()
        sd._initialize()
        for run in range(2):
            with self.subTest(run=run):
                serial = MagicMock()
                serial.SerialException = type("SerialException", (Exception,), {})
                port = serial.Serial.return_value
                port.in_waiting = 0
                port.write.side_effect = len
                stop = threading.Event()
                frames = iter([status_frame(dict(STATUS, ready=True, hfp=True, call=call))
                               for call in (False, True, True, False)])
                def read(_):
                    try:
                        return next(frames)
                    except StopIteration:
                        stop.set()
                        return b""
                port.read.side_effect = read
                args = SimpleNamespace(port="TEST", baud=921600, device=None,
                                       no_mic=True, mic_gain=1, input_device=None,
                                       desktop_audio=True, windows_ducking=True)
                messages, failures = [], []
                def work():
                    try:
                        run_bridge(args, stop, commands=queue.Queue(), on_audio_status=messages.append)
                    except BaseException as exc:
                        failures.append(exc)
                with patch.dict("sys.modules", {"serial": serial}):
                    worker = threading.Thread(target=work)
                    worker.start()
                    worker.join(15)
                    stop.set()
                    worker.join(5)
                self.assertFalse(worker.is_alive(), "Audio worker failed to stop")
                self.assertEqual(failures, [])
                self.assertEqual(messages, ["Atténuation Windows : en attente d’appel",
                                            "Atténuation Windows : appel signalé à Windows",
                                            "Atténuation Windows : en attente d’appel"])


if __name__ == "__main__":
    unittest.main()
