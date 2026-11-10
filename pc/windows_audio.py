"""Small, version-checked adapter for PortAudio's Windows stream categories."""
import contextlib
import ctypes
import logging
import sys
import uuid


@contextlib.contextmanager
def audio_thread_com():
    """WASAPI needs COM on the thread opening/starting its streams.

    Importing sounddevice initializes PortAudio on the GUI thread, not the
    bridge worker. Keep COM alive until all of that worker's streams are closed.
    """
    if sys.platform != "win32":
        yield
        return
    ole = ctypes.WinDLL("ole32")
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    result = ole.CoInitializeEx(None, 0)  # COINIT_MULTITHREADED
    code = result & 0xFFFFFFFF
    # A caller already using STA owns its initialization. It may continue to
    # use COM, but this failed MTA request must not be balanced by Uninitialize.
    if code & 0x80000000 and code != 0x80010106:  # RPC_E_CHANGED_MODE
        raise OSError(f"Initialisation audio Windows COM impossible (0x{code:08X})")
    try:
        yield
    finally:
        if code in (0, 1):  # S_OK and S_FALSE each acquire a reference.
            ole.CoUninitialize()


def desktop_output_device(sd, selected):
    """Resolve the default once; never reroute an explicitly selected output."""
    if selected is not None:
        return selected
    for host in sd.query_hostapis():
        if host["name"] == "Windows WASAPI" and host["default_output_device"] >= 0:
            return host["default_output_device"]
    return sd.default.device[1]


def is_wasapi_output(sd, device):
    info = sd.query_devices(device)
    return sd.query_hostapis(info["hostapi"])["name"] == "Windows WASAPI"


def category_settings(sd, communication):
    # sounddevice does not expose streamCategory publicly. Keep this private
    # access here, pin the supported version, and fail without changing volumes.
    if sd.__version__ != "0.5.6":
        raise RuntimeError("Version sounddevice incompatible (0.5.6 requise)")
    settings = sd.WasapiSettings(exclusive=False, auto_convert=True)
    if not hasattr(settings._streaminfo, "streamCategory"):
        raise RuntimeError("Catégories WASAPI indisponibles")
    settings._streaminfo.streamCategory = (
        sd._lib.eAudioCategoryCommunications if communication else sd._lib.eAudioCategoryMedia)
    return settings


def _guid(value):
    return (ctypes.c_byte * 16).from_buffer_copy(uuid.UUID(value).bytes_le)


def _method(obj, slot, *types):
    pointer = ctypes.c_void_p
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(pointer))).contents
    return ctypes.WINFUNCTYPE(ctypes.c_long, pointer, *types)(vtable[slot])


def _check_hresult(result):
    if result < 0:
        raise OSError(f"Erreur de session audio Windows (0x{result & 0xFFFFFFFF:08X})")


def _portaudio(sd):
    if sd.__version__ != "0.5.6":
        raise OSError("Version sounddevice incompatible (0.5.6 requise)")
    return ctypes.CDLL(sd._libname)


def protect_playback(sd, stream):
    """Keep our audible media/voice session at its own volume during calls."""
    pointer = ctypes.c_void_p
    # The audio client is borrowed from PortAudio; only release GetService/QI.
    getter = _portaudio(sd).PaWasapi_GetAudioClient
    getter.argtypes = [pointer, ctypes.POINTER(pointer), ctypes.c_int]
    getter.restype = ctypes.c_int
    client, control, control2 = pointer(), pointer(), pointer()
    error = getter(int(sd._ffi.cast("uintptr_t", stream._ptr)), ctypes.byref(client), 1)
    if error or not client:
        raise OSError(f"Accès au flux WASAPI impossible ({error})")
    try:
        _check_hresult(_method(client, 14, pointer, ctypes.POINTER(pointer))(
            client, _guid("F4B1A599-7266-4319-A8CA-E70ACB11E8CD"), ctypes.byref(control)))
        _check_hresult(_method(control, 0, pointer, ctypes.POINTER(pointer))(
            control, _guid("BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D"), ctypes.byref(control2)))
        # IAudioSessionControl2::SetDuckingPreference, for OUR session only.
        _check_hresult(_method(control2, 16, ctypes.c_int)(control2, 1))
    finally:
        if control2:
            _method(control2, 2)(control2)
        if control:
            _method(control, 2)(control)


class _ClientProperties(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint), ("offload", ctypes.c_int),
                ("category", ctypes.c_int), ("options", ctypes.c_int)]


class CommunicationSession:
    """Silent, shared WASAPI session with a fresh GUID for each call.

    The audible PortAudio stream stays Media. Reusing its default GUID for
    Communications makes Windows retain ducking after it is reopened as Media.
    This independent session is destroyed at hangup, while playback continues.
    All methods run on the bridge's COM-initialized worker thread.
    """
    def __init__(self, sd, device):
        pointer = ctypes.c_void_p
        self.client = pointer()
        self.renderer = pointer()
        self.started = False
        self.session_id = str(uuid.uuid4())
        getter = _portaudio(sd).PaWasapi_GetIMMDevice
        getter.argtypes = [ctypes.c_int, ctypes.POINTER(pointer)]
        getter.restype = ctypes.c_int
        endpoint = pointer()
        error = getter(device, ctypes.byref(endpoint))
        if error or not endpoint:
            raise OSError(f"Accès au périphérique WASAPI impossible ({error})")
        # IMMDevice is borrowed from PortAudio and refers to exactly the same
        # selected endpoint, even when it is not the Windows default.
        try:
            _check_hresult(_method(endpoint, 3, pointer, ctypes.c_ulong, pointer, ctypes.POINTER(pointer))(
                endpoint, _guid("726778CD-F60A-4EDA-82DE-E47610CD78AA"), 23, None, ctypes.byref(self.client)))
            properties = _ClientProperties(ctypes.sizeof(_ClientProperties), 0, 3, 0)
            _check_hresult(_method(self.client, 16, pointer)(self.client, ctypes.byref(properties)))
            fmt = pointer()
            _check_hresult(_method(self.client, 8, ctypes.POINTER(pointer))(self.client, ctypes.byref(fmt)))
            try:
                # Shared, NOPERSIST, 200 ms, device mix format, unique session.
                _check_hresult(_method(self.client, 3, ctypes.c_int, ctypes.c_ulong,
                                       ctypes.c_longlong, ctypes.c_longlong, pointer, pointer)(
                    self.client, 0, 0x80000, 2000000, 0, fmt, _guid(self.session_id)))
            finally:
                ole = ctypes.WinDLL("ole32")
                ole.CoTaskMemFree.argtypes = [pointer]
                ole.CoTaskMemFree.restype = None
                ole.CoTaskMemFree(fmt)
            _check_hresult(_method(self.client, 14, pointer, ctypes.POINTER(pointer))(
                self.client, _guid("F294ACFC-3146-4483-A7BF-ADDCA7C260E2"), ctypes.byref(self.renderer)))
            self.pump()
            _check_hresult(_method(self.client, 10)(self.client))
            self.started = True
            logging.info("Communication session started: %s device=%s", self.session_id, device)
        except BaseException:
            self.close()
            raise

    def pump(self):
        size, padding, data = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_void_p()
        _check_hresult(_method(self.client, 4, ctypes.POINTER(ctypes.c_uint))(self.client, ctypes.byref(size)))
        _check_hresult(_method(self.client, 6, ctypes.POINTER(ctypes.c_uint))(self.client, ctypes.byref(padding)))
        frames = size.value - padding.value
        if frames > 0:
            _check_hresult(_method(self.renderer, 3, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(
                self.renderer, frames, ctypes.byref(data)))
            # AUDCLNT_BUFFERFLAGS_SILENT: no audio data is read or copied.
            _check_hresult(_method(self.renderer, 4, ctypes.c_uint, ctypes.c_ulong)(self.renderer, frames, 2))

    def close(self):
        if self.client and self.started:
            result = _method(self.client, 11)(self.client)  # Stop before Release.
            if result < 0:
                logging.warning("Communication stop failed: 0x%08X; releasing client", result & 0xFFFFFFFF)
        if self.renderer:
            _method(self.renderer, 2)(self.renderer)
            self.renderer = ctypes.c_void_p()
        if self.client:
            _method(self.client, 2)(self.client)
            self.client = ctypes.c_void_p()
            logging.info("Communication session released: %s", self.session_id)
        self.started = False

