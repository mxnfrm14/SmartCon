"""Bridge iPhone calls, stereo Bluetooth media and a PC microphone over ESP32 UART."""
import argparse
import array
import contextlib
import logging
import queue
import re
import sys
import struct
import threading
import time

MAGIC = b"PBAUD01!"
MEDIA_MAGIC = b"PBSBC01!"
CONTROL_MAGIC = b"PBCTL01!"


def checksum(data):
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xFFFFFFFF
    return value


class Parser:
    def __init__(self, on_noise=None):
        self.buffer = bytearray()
        self.bad = 0
        self.on_noise = on_noise or (lambda data: None)

    def feed(self, data):
        self.buffer.extend(data)
        while True:
            positions = [p for p in (self.buffer.find(MAGIC), self.buffer.find(MEDIA_MAGIC), self.buffer.find(CONTROL_MAGIC)) if p >= 0]
            pos = min(positions, default=-1)
            if pos < 0:
                if len(self.buffer) > 7:
                    self.on_noise(bytes(self.buffer[:-7]))
                del self.buffer[:-7]
                return
            if pos:
                self.on_noise(bytes(self.buffer[:pos]))
            del self.buffer[:pos]
            if len(self.buffer) < 20:
                return
            size, rate, sequence, expected = struct.unpack_from("<HHII", self.buffer, 8)
            media = self.buffer[:8] == MEDIA_MAGIC
            control = self.buffer[:8] == CONTROL_MAGIC
            if not 0 < size <= 1024 or (rate != 0 if media or control else
                    (size % 2 or rate not in (8000, 16000))):
                del self.buffer[0]
                self.bad += 1
                continue
            if len(self.buffer) < 20 + size:
                return
            pcm = bytes(self.buffer[20:20 + size])
            if checksum(self.buffer[8:16] + pcm) != expected:
                del self.buffer[0]
                self.bad += 1
                continue
            del self.buffer[:20 + size]
            yield -1 if control else rate, sequence, pcm


class FirmwareLog:
    """Keep ESP log lines discarded between frames, never audio payloads."""
    def __init__(self):
        self.pending = bytearray()

    def __call__(self, data):
        self.pending.extend(data)
        while b"\n" in self.pending:
            line, _, remaining = self.pending.partition(b"\n")
            self.pending = bytearray(remaining)
            line = re.sub(rb"\x1b\[[0-9;]*m", b"", line).strip()
            if line.startswith((b"I (", b"W (", b"E (")):
                logging.info("ESP32: %s", line.decode("utf-8", errors="replace"))
        if len(self.pending) > 2048:
            self.pending.clear()


def mic_frame(pcm, rate, sequence):
    fields = struct.pack("<HHI", len(pcm), rate, sequence & 0xFFFFFFFF)
    return b"PBMIC01!" + fields + struct.pack("<I", checksum(fields + pcm)) + pcm


class MediaDecoder:
    """Incremental SBC parser; reset after loss, pause or a call transition."""
    def __init__(self):
        import av
        self.av = av
        self.codec = av.CodecContext.create("sbc", "r")
        self.resampler = av.AudioResampler(format="s16", layout="stereo", rate=48000)
        self.input_format = None

    def feed(self, data):
        output = bytearray()
        for packet in self.codec.parse(data):
            for frame in self.codec.decode(packet):
                fmt = (frame.sample_rate, frame.layout.name, frame.format.name)
                if self.input_format != fmt:
                    self.resampler = self.av.AudioResampler(format="s16", layout="stereo", rate=48000)
                    self.input_format = fmt
                frame.pts = None
                for converted in self.resampler.resample(frame):
                    # Planes may include alignment padding beyond valid samples.
                    output.extend(bytes(converted.planes[0])[:converted.samples * 4])
        return bytes(output)


def call_playback(pcm, rate):
    """Duplicate mono voice to both output channels at 48 kHz."""
    return b"".join(pcm[i:i + 2] * (2 * (48000 // rate))
                    for i in range(0, len(pcm), 2))


def downsample(pcm, rate, gain=1.0, channels=1):
    """Average integer groups at 48 kHz; preserve signed little-endian PCM."""
    samples = array.array("h", pcm)
    if sys.byteorder != "little":
        samples.byteswap()
    factor = 48000 // rate * channels
    result = array.array("h", (max(-32768, min(32767, round(
        sum(samples[i:i + factor]) / factor * gain)))
        for i in range(0, len(samples) - factor + 1, factor)))
    if sys.byteorder != "little":
        result.byteswap()
    return result.tobytes()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", default="COM3")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--list-devices", action="store_true")
    ap.add_argument("--device", type=int, help="Output device index")
    ap.add_argument("--input-device", type=int, help="Headset microphone device index")
    ap.add_argument("--no-mic", action="store_true", help="Playback only")
    ap.add_argument("--mic-gain", type=float, default=1.0)
    args = ap.parse_args()
    if not 0 <= args.mic_gain <= 10:
        ap.error("--mic-gain doit etre compris entre 0 et 10")
    import serial
    import sounddevice as sd
    if args.list_devices:
        print(sd.query_devices())
        return
    run_bridge(args)


class DesktopOutput:
    """Keep playback separate from the short-lived call/ducking session."""
    def __init__(self, sd, device, callback, ducking, notify):
        from windows_audio import desktop_output_device, is_wasapi_output, category_settings
        self.sd = sd
        self.device = desktop_output_device(sd, device)
        self.callback = callback
        self.notify = notify
        self.stream = None
        self.session = None
        self.communication = False
        self.call = False
        self.control_at = None
        self.ducking = ducking
        self.settings = None
        self.warning = None
        self.wasapi = is_wasapi_output(sd, self.device)
        if self.wasapi:
            self.settings = sd.WasapiSettings(exclusive=False, auto_convert=True)
            try:
                self.settings = category_settings(sd, False)
            except (AttributeError, TypeError, ValueError, RuntimeError) as exc:
                self.unavailable(str(exc))
        elif ducking:
            self.unavailable("choisissez la variante Windows WASAPI de votre sortie")

    def unavailable(self, reason):
        self.ducking = False
        self.warning = f"Atténuation indisponible : {reason}"
        logging.warning(self.warning)
        self.notify(self.warning)

    def open(self):
        kwargs = dict(samplerate=48000, channels=2, dtype="int16",
                      device=self.device, blocksize=960, callback=self.callback)
        settings = self.settings
        if settings is not None:
            kwargs["extra_settings"] = settings
        info = self.sd.query_devices(self.device)
        logging.info("Opening output device=%s name=%s api=%s category=%s",
                     self.device, info["name"],
                     self.sd.query_hostapis(info["hostapi"])["name"],
                     "media")
        stream = self.sd.RawOutputStream(**kwargs)
        try:
            if self.wasapi and self.ducking:
                from windows_audio import protect_playback
                try:
                    protect_playback(self.sd, stream)
                except (OSError, AttributeError) as exc:
                    self.unavailable(str(exc))
            stream.start()
        except BaseException:
            stream.close()
            raise
        self.stream = stream
        logging.info("Audio output device=%s category=media", self.device)

    def start(self):
        self.open()
        if not self.warning:
            self.notify("Atténuation Windows : en attente d’appel" if self.ducking
                        else "Atténuation Windows désactivée dans SmartCon")

    def control(self, status, now):
        # Called only for a validated protocol snapshot, never audio activity.
        self.control_at = now
        self.call = bool(status["ready"] and status["hfp"] and status["call"])
        self.tick(now)

    def tick(self, now):
        wanted = bool(self.ducking and self.call and self.control_at is not None
                      and now < self.control_at + 5)
        changed = wanted != self.communication
        if not wanted:
            self.close_communication()
        else:
            from windows_audio import CommunicationSession
            try:
                if self.session is None:
                    self.session = CommunicationSession(self.sd, self.device)
                self.session.pump()
                self.communication = True
            except (OSError, AttributeError) as exc:
                self.close_communication()
                self.unavailable(str(exc))
        if changed and not self.warning:
            self.notify("Atténuation Windows : appel signalé à Windows" if wanted
                        else "Atténuation Windows : en attente d’appel")

    def close_communication(self):
        if self.session is not None:
            self.session.close()
            self.session = None
        self.communication = False

    def close(self):
        self.close_communication()
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        self.communication = False


def run_bridge(args, stop_event=None, on_status=None, commands=None, on_control=None,
               on_audio_status=None):
    """Run with Windows COM owned by the audio worker, not the GUI thread."""
    apartment = contextlib.nullcontext()
    if getattr(args, "desktop_audio", False):
        from windows_audio import audio_thread_com
        apartment = audio_thread_com()
    with apartment:
        return _run_bridge(args, stop_event, on_status, commands, on_control, on_audio_status)


def _run_bridge(args, stop_event=None, on_status=None, commands=None, on_control=None,
                on_audio_status=None):
    """Run until stopped; callbacks report the PC link, not Bluetooth pairing."""
    import serial
    import sounddevice as sd
    stop_event = stop_event or threading.Event()
    on_status = on_status or (lambda status: None)
    on_control = on_control or (lambda status: None)
    on_audio_status = on_audio_status or (lambda status: None)
    from phone_control import command_frame, decode_status
    try:
        decoder = MediaDecoder()
    except ImportError:
        raise SystemExit("Installer les dependances: python -m pip install -r pc/requirements.txt")

    input_channels = 1
    if not args.no_mic:
        try:
            sd.check_input_settings(device=args.input_device, channels=1,
                                    dtype="int16", samplerate=48000)
        except sd.PortAudioError:
            input_channels = 2
            try:
                sd.check_input_settings(device=args.input_device, channels=2,
                                        dtype="int16", samplerate=48000)
            except sd.PortAudioError as exc:
                raise SystemExit(f"Micro incompatible a 48 kHz: {exc}. Choisis --input-device.")

    pending = bytearray()
    lock = threading.Lock()
    underruns = 0
    overruns = 0

    def output(outdata, frames, timing, status):
        nonlocal underruns
        with lock:
            n = min(len(outdata), len(pending))
            outdata[:n] = pending[:n]
            outdata[n:] = bytes(len(outdata) - n)
            del pending[:n]
            if n < len(outdata):
                underruns += 1

    parser = Parser(on_noise=FirmwareLog())
    previous = None
    missing = 0
    packets = 0
    serial_bytes = 0
    last_report = time.monotonic()
    active_rate = 8000
    last_audio = 0.0
    last_packet_time = 0.0
    previous_rate = None
    decode_errors = 0
    mic_queue = queue.Queue(maxsize=5)
    stop = threading.Event()
    writer_errors = []
    mic_packets = 0
    mic_drops = 0
    mic_peak = 0
    write_lock = threading.Lock()

    def capture(indata, frames, timing, status):
        nonlocal mic_drops, mic_peak
        # No microphone data leaves the PC without recent call audio.
        with lock:
            rate, recent = active_rate, last_audio
        if rate not in (8000, 16000) or time.monotonic() - recent > 0.3:
            return
        pcm = downsample(bytes(indata), rate, args.mic_gain, input_channels)
        samples = struct.unpack("<" + "h" * (len(pcm) // 2), pcm)
        mic_peak = max((abs(v) for v in samples), default=0)
        try:
            mic_queue.put_nowait((rate, pcm, time.monotonic()))
        except queue.Full:
            mic_drops += 1

    def send_microphone():
        nonlocal mic_packets
        try:
            while not stop.is_set():
                try:
                    rate, pcm, captured = mic_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if time.monotonic() - captured > 0.1:
                    continue
                packet = mic_frame(pcm, rate, mic_packets)
                with write_lock:
                    if port.write(packet) != len(packet):
                        raise serial.SerialException("Trame micro incomplete")
                mic_packets += 1
        except (serial.SerialException, OSError) as exc:
            writer_errors.append(exc)
            stop.set()
    # Set control lines before opening to avoid the usual ESP32 reset pulse.
    port = serial.Serial(port=None, baudrate=args.baud, timeout=0.1, write_timeout=0.2)
    port.dtr = False
    port.rts = False
    port.port = args.port
    try:
        with contextlib.ExitStack() as stack:
            stack.enter_context(port)
            if commands is not None:
                def close_pairing():
                    with contextlib.suppress(serial.SerialException, OSError):
                        with write_lock:
                            port.write(command_frame({"cmd": "cancel"}))
                stack.callback(close_pairing)
            desktop_output = None
            if getattr(args, "desktop_audio", False):
                desktop_output = DesktopOutput(
                    sd, args.device, output,
                    getattr(args, "windows_ducking", True), on_audio_status)
                stack.callback(desktop_output.close)
                desktop_output.start()
            else:
                stack.enter_context(sd.RawOutputStream(
                    samplerate=48000, channels=2, dtype="int16",
                    device=args.device, blocksize=960, callback=output))
            if not args.no_mic:
                stack.enter_context(sd.RawInputStream(
                    samplerate=48000, channels=input_channels, dtype="int16",
                    device=args.input_device, blocksize=960, callback=capture))
                worker = threading.Thread(target=send_microphone, daemon=True)
                worker.start()
                def stop_worker():
                    stop.set()
                    worker.join(timeout=1)
                stack.callback(stop_worker)
            print(f"Ecoute sur {args.port} a {args.baud} bauds. Ctrl+C pour quitter.")
            print("Lance un media ou un appel et choisis SmartCon sur l'iPhone. Micro desactive." if args.no_mic else
                  "Micro actif pendant l'appel. Choisis SmartCon sur l'iPhone.")
            on_status("Connecté au pont — en attente audio")
            reported_status = None
            last_control_poll = 0.0
            while not stop_event.is_set():
                if writer_errors:
                    raise serial.SerialException(str(writer_errors[0]))
                if commands is not None:
                    outgoing = []
                    if time.monotonic() - last_control_poll >= 2:
                        outgoing.append({"cmd": "status"})
                        last_control_poll = time.monotonic()
                    for _ in range(8):
                        try:
                            outgoing.append(commands.get_nowait())
                        except queue.Empty:
                            break
                    for command in outgoing:
                        packet = command_frame(command)
                        with write_lock:
                            if port.write(packet) != len(packet):
                                raise serial.SerialException("Commande incomplete")
                chunk = port.read(max(1, min(port.in_waiting, 8192)))
                serial_bytes += len(chunk)
                for rate, sequence, pcm in parser.feed(chunk):
                    if rate == -1:
                        status = decode_status(pcm)
                        if status is not None:
                            if desktop_output is not None and not stop_event.is_set():
                                desktop_output.control(status, time.monotonic())
                            on_control(status)
                        continue
                    now = time.monotonic()
                    gap = previous is not None and sequence != ((previous + 1) & 0xFFFFFFFF)
                    transition = previous_rate != rate or now - last_packet_time > 0.3
                    if previous is not None:
                        delta = (sequence - previous - 1) & 0xFFFFFFFF
                        if delta < 0x80000000:
                            missing += delta
                    with lock:
                        active_rate = rate
                        last_audio = now if rate else 0.0
                        if transition:
                            pending.clear()
                    previous = sequence
                    previous_rate = rate
                    last_packet_time = now
                    packets += 1
                    if rate == 0:
                        if gap or transition:
                            decoder = MediaDecoder()
                        try:
                            expanded = decoder.feed(pcm)
                        except (decoder.av.error.FFmpegError, ValueError):
                            decode_errors += 1
                            decoder = MediaDecoder()
                            continue
                    else:
                        expanded = call_playback(pcm, rate)
                    with lock:
                        pending.extend(expanded)
                        # Bound latency to 200 ms; discard oldest samples if needed.
                        if len(pending) > 38400:
                            del pending[:-38400]
                            overruns += 1
                now = time.monotonic()
                if desktop_output is not None and not stop_event.is_set():
                    desktop_output.tick(now)
                status = ("Appel en cours" if previous_rate else "Lecture média") if now - last_packet_time < 0.5 else "Connecté au pont — en attente audio"
                if status != reported_status:
                    on_status(status)
                    reported_status = status
                if now - last_report >= 5:
                    print(f"octets_serie={serial_bytes} paquets={packets} pertes={missing} invalides={parser.bad} "
                          f"sous-remplissages={underruns} debordements={overruns} "
                          f"erreurs_sbc={decode_errors} "
                          f"micro_paquets={mic_packets} micro_pertes={mic_drops} micro_niveau={mic_peak}/32768")
                    last_report = now
    except KeyboardInterrupt:
        pass
    except (serial.SerialException, sd.PortAudioError) as exc:
        raise SystemExit(f"Erreur: {exc}. Ferme idf.py monitor et verifie le peripherique audio.")


if __name__ == "__main__":
    main()
