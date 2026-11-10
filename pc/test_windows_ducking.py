"""Opt-in regression for actual Windows DUCK/UNDUCK, with silent playback."""
import ctypes as c
import os
import queue
import sys
import time
import unittest

from windows_audio import _guid, _method, _check_hresult, _portaudio, audio_thread_com
from listen import DesktopOutput


class DuckNotifications:
    """Observe all duck events; never change any application's volume."""
    def __init__(self, sd, device):
        self.events = queue.Queue()
        self.references = 1
        pointer = c.c_void_p
        unknown = bytes(_guid("00000000-0000-0000-C000-000000000046"))
        duck_id = bytes(_guid("C3B284D4-6D39-4359-B3CF-B56DDB3BB39C"))

        def add_ref(this):
            self.references += 1
            return self.references

        def release(this):
            self.references -= 1
            return self.references

        def query(this, iid, result):
            if c.string_at(iid, 16) in (unknown, duck_id):
                result[0] = this
                add_ref(this)
                return 0
            result[0] = None
            return -2147467262  # E_NOINTERFACE

        def duck(this, session, count):
            self.events.put(("duck", session.lower()))
            return 0

        def unduck(this, session):
            self.events.put(("unduck", session.lower()))
            return 0

        self.callbacks = [
            c.WINFUNCTYPE(c.c_long, pointer, pointer, c.POINTER(pointer))(query),
            c.WINFUNCTYPE(c.c_ulong, pointer)(add_ref),
            c.WINFUNCTYPE(c.c_ulong, pointer)(release),
            c.WINFUNCTYPE(c.c_long, pointer, c.c_wchar_p, c.c_uint)(duck),
            c.WINFUNCTYPE(c.c_long, pointer, c.c_wchar_p)(unduck)]
        self.vtable = (pointer * 5)(*[c.cast(cb, pointer).value for cb in self.callbacks])
        self.object = pointer(c.addressof(self.vtable))
        self.notification = c.cast(c.pointer(self.object), pointer)
        endpoint = pointer()
        getter = _portaudio(sd).PaWasapi_GetIMMDevice
        getter.argtypes = [c.c_int, c.POINTER(pointer)]
        getter.restype = c.c_int
        _check_hresult(getter(device, c.byref(endpoint)))
        self.manager = pointer()
        _check_hresult(_method(endpoint, 3, pointer, c.c_ulong, pointer, c.POINTER(pointer))(
            endpoint, _guid("77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F"), 23, None, c.byref(self.manager)))
        try:
            _check_hresult(_method(self.manager, 8, c.c_wchar_p, pointer)(self.manager, None, self.notification))
        except BaseException:
            _method(self.manager, 2)(self.manager)
            raise

    def close(self):
        if self.manager:
            try:
                _check_hresult(_method(self.manager, 9, c.c_void_p)(self.manager, self.notification))
            finally:
                _method(self.manager, 2)(self.manager)
                self.manager = c.c_void_p()


@unittest.skipUnless(sys.platform == "win32" and os.environ.get("SMARTCON_TEST_AUDIO") == "1",
                     "Set SMARTCON_TEST_AUDIO=1 for real Windows DUCK/UNDUCK notifications")
class WindowsDuckingTests(unittest.TestCase):
    def test_hangup_unducks_without_media_retriggering_communication(self):
        import sounddevice as sd
        messages = []
        with audio_thread_com():
            output = DesktopOutput(sd, None,
                                   lambda data, *args: data.__setitem__(slice(None), bytes(len(data))),
                                   True, messages.append)
            monitor = DuckNotifications(sd, output.device)
            observed = []

            def collect(duration, until=None):
                deadline = time.monotonic() + duration
                while time.monotonic() < deadline:
                    output.tick(time.monotonic())
                    try:
                        event = monitor.events.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    observed.append(event)
                    if until and until(event):
                        return

            try:
                output.start()
                self.assertIsNone(output.warning, messages)
                playback = output.stream
                session_ids = []
                for _ in range(2):
                    output.control(dict(ready=True, hfp=True, call=True), time.monotonic())
                    self.assertIsNotNone(output.session, messages)
                    session_id = output.session.session_id.lower()
                    session_ids.append(session_id)
                    matches = lambda e: session_id in e[1]
                    collect(3, lambda e: matches(e) and e[0] == "duck")
                    self.assertTrue(any(matches(e) and e[0] == "duck" for e in observed))
                    output.control(dict(ready=True, hfp=True, call=False), time.monotonic())
                    collect(3, lambda e: matches(e) and e[0] == "unduck")
                    collect(1)
                    self.assertEqual([e[0] for e in observed if matches(e)], ["duck", "unduck"])
                    self.assertIs(output.stream, playback)
                    self.assertTrue(playback.active)
                self.assertNotEqual(*session_ids)
            finally:
                output.close()
                monitor.close()
