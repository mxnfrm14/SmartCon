"""Windows notification-area application for SmartCon."""
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from types import SimpleNamespace
import winreg

import pystray
from PIL import Image, ImageDraw
import serial.tools.list_ports
import sounddevice as sd
from listen import run_bridge

DATA = Path(os.environ.get("APPDATA", Path.home())) / "SmartCon"
SETTINGS = DATA / "settings.json"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def load_settings():
    try:
        value = json.loads(SETTINGS.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(value):
    DATA.mkdir(parents=True, exist_ok=True)
    temporary = SETTINGS.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(SETTINGS)


def startup_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, "SmartCon")
        return True
    except FileNotFoundError:
        return False


def set_startup(enabled):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            command = [sys.executable]
            if not getattr(sys, "frozen", False):
                command.append(str(Path(__file__).resolve()))
            command.append("--startup")
            winreg.SetValueEx(key, "SmartCon", 0, winreg.REG_SZ,
                             subprocess.list2cmdline(command))
        else:
            try:
                winreg.DeleteValue(key, "SmartCon")
            except FileNotFoundError:
                pass


def icon_image(color):
    image = Image.new("RGBA", (64, 64))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((13, 3, 50, 60), radius=8, fill=color)
    draw.rounded_rectangle((19, 11, 44, 47), radius=3, fill="#112033")
    draw.ellipse((28, 51, 35, 57), fill="white")
    return image


class Application:
    def __init__(self, root):
        self.root = root
        self.events = queue.Queue()
        self.settings = load_settings()
        self.worker = None
        self.device_maps = [{"Périphérique Windows par défaut": None}, {"Périphérique Windows par défaut": None}]
        self.stop_event = threading.Event()
        self.commands = queue.Queue(maxsize=32)
        self.phone_status = None
        self.phone_status_at = 0.0
        self.phone_text = tk.StringVar(value="Démarrez le pont pour gérer les téléphones.")
        self.pair_text = tk.StringVar(value="Appairage verrouillé")
        self.number_text = tk.StringVar()
        self.closing = False
        self.status = tk.StringVar(value="Arrêté")
        self.port = tk.StringVar(value=self.settings.get("port", "COM3"))
        self.output = tk.StringVar(value="Périphérique Windows par défaut")
        self.microphone = tk.StringVar(value="Périphérique Windows par défaut")
        self.no_mic = tk.BooleanVar(value=self.settings.get("no_mic", False))
        self.windows_ducking = tk.BooleanVar(value=self.settings.get("windows_ducking", True))
        self.audio_status = tk.StringVar(value="Atténuation : réglage appliqué au démarrage du pont.")
        self.autostart = tk.BooleanVar(value=startup_enabled())
        self.auto_bridge = tk.BooleanVar(value=self.settings.get("auto_bridge", True))
        root.title("SmartCon")
        root.resizable(False, False)
        root.protocol("WM_DELETE_WINDOW", root.withdraw)
        panel = ttk.Frame(root, padding=20)
        panel.grid()
        ttk.Label(panel, text="SmartCon", font=("Segoe UI", 17, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(panel, textvariable=self.status, wraplength=480).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 18))
        self.controls = []
        for row, label, variable in [(2, "Port COM", self.port), (3, "Casque / sortie audio", self.output), (4, "Microphone", self.microphone)]:
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky="w", pady=5)
            combo = ttk.Combobox(panel, textvariable=variable, state="readonly", width=55)
            combo.grid(row=row, column=1, padx=(15, 0), pady=5)
            self.controls.append(combo)
        ttk.Button(panel, text="Actualiser les périphériques", command=self.refresh).grid(row=5, column=1, sticky="e", pady=5)
        for row, text, variable in [(6, "Écoute seule (micro désactivé)", self.no_mic), (7, "Démarrer avec Windows", self.autostart), (8, "Démarrer le pont à l’ouverture de l’application", self.auto_bridge)]:
            control = ttk.Checkbutton(panel, text=text, variable=variable)
            control.grid(row=row, column=0, columnspan=2, sticky="w", pady=4)
            self.controls.append(control)
        buttons = ttk.Frame(panel)
        audio_panel = ttk.LabelFrame(panel, text="Écoute et diffusion", padding=10)
        audio_panel.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ducking = ttk.Checkbutton(audio_panel, text="Atténuation Windows pendant les appels",
                                 variable=self.windows_ducking)
        ducking.pack(anchor="w")
        self.controls.append(ducking)
        ttk.Button(audio_panel, text="Réglages Windows : Communications",
                   command=self.open_communications).pack(anchor="w", pady=4)
        ttk.Label(audio_panel, textvariable=self.audio_status, wraplength=600).pack(anchor="w")
        ttk.Label(audio_panel, text="OBS : capturez le son par application pour choisir de diffuser SmartCon.\n"
                  "Une capture de tout le son du PC inclut aussi SmartCon.",
                  foreground="#555555", wraplength=600).pack(anchor="w", pady=(5, 0))
        buttons.grid(row=10, column=0, columnspan=2, pady=(18, 5))
        self.start_button = ttk.Button(buttons, text="Démarrer", command=self.start)
        self.start_button.pack(side="left", padx=4)
        self.stop_button = ttk.Button(buttons, text="Arrêter", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=4)
        ttk.Button(buttons, text="Enregistrer", command=self.save).pack(side="left", padx=4)
        ttk.Button(buttons, text="Masquer", command=root.withdraw).pack(side="left", padx=4)
        ttk.Button(buttons, text="Quitter", command=self.quit).pack(side="left", padx=4)
        ttk.Label(panel, text="Fermer cette fenêtre laisse l’application près de l’horloge.\nL’état décrit le lien USB et l’audio reçu, pas l’appairage Bluetooth.", foreground="#555555").grid(row=11, column=0, columnspan=2, sticky="w", pady=(12, 0))
        phones_panel = ttk.LabelFrame(panel, text="Téléphones autorisés — un seul actif", padding=10)
        phones_panel.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(phones_panel, textvariable=self.phone_text, wraplength=620).pack(anchor="w")
        self.phones = ttk.Treeview(phones_panel, columns=("name", "address", "state"), show="headings", height=4, selectmode="browse")
        for key, title, width in [("name", "Téléphone", 160), ("address", "Adresse Bluetooth", 150), ("state", "État", 260)]:
            self.phones.heading(key, text=title)
            self.phones.column(key, width=width)
        self.phones.pack(fill="x", pady=6)
        phone_buttons = ttk.Frame(phones_panel)
        phone_buttons.pack(anchor="w")
        self.phone_buttons = []
        for text, command in [("Activer", lambda: self.phone_action("select")), ("Déconnecter", lambda: self.phone_action("disconnect")), ("Oublier", lambda: self.phone_action("forget")), ("Appairer (60 s)", lambda: self.phone_action("pair")), ("Annuler l’appairage", lambda: self.phone_action("cancel"))]:
            button = ttk.Button(phone_buttons, text=text, command=command, state="disabled")
            button.pack(side="left", padx=2)
            self.phone_buttons.append(button)
        ttk.Label(phones_panel, textvariable=self.pair_text).pack(anchor="w", pady=(8, 0))
        ttk.Label(phones_panel, textvariable=self.number_text, wraplength=620, font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=4)
        approval = ttk.Frame(phones_panel)
        approval.pack(anchor="w")
        self.approval_buttons = []
        for text, command in [("Les numéros correspondent : approuver", "approve"), ("Refuser", "reject")]:
            button = ttk.Button(approval, text=text, command=lambda cmd=command: self.phone_action(cmd), state="disabled")
            button.pack(side="left", padx=2)
            self.approval_buttons.append(button)
        self.tray = pystray.Icon("SmartCon", icon_image("#7c8798"), "SmartCon — Arrêté", menu=pystray.Menu(
            pystray.MenuItem(lambda item: self.tray.title, None, enabled=False),
            pystray.MenuItem("Ouvrir les réglages", lambda *_: self.events.put(("show", None)), default=True),
            pystray.MenuItem("Démarrer", lambda *_: self.events.put(("start", None))),
            pystray.MenuItem("Arrêter", lambda *_: self.events.put(("stop", None))),
            pystray.MenuItem("Quitter", lambda *_: self.events.put(("quit", None)))))
        self.refresh()
        self.tray.run_detached()
        root.after(100, self.poll)
        if "--startup" in sys.argv or "--smoke-test" in sys.argv:
            root.withdraw()
        if "--smoke-test" in sys.argv:
            root.after(1000, self.quit)
        elif self.auto_bridge.get():
            root.after(300, self.start)

    def refresh(self):
        if self.worker and self.worker.is_alive():
            return
        try:
            # Reinitialize PortAudio so hot-plugged headsets appear in the list.
            sd._terminate()
            sd._initialize()
            ports = [p.device for p in serial.tools.list_ports.comports()]
            self.controls[0]["values"] = ports
            devices = sd.query_devices()
            hosts = sd.query_hostapis()
            self.device_maps = []
            for combo, variable, field, saved in [(self.controls[1], self.output, "max_output_channels", "output"), (self.controls[2], self.microphone, "max_input_channels", "microphone")]:
                mapping = {"Périphérique Windows par défaut": None}
                for index, device in enumerate(devices):
                    if device[field] > 0:
                        label = f"{device['name']} [{hosts[device['hostapi']]['name']}]"
                        if label in mapping:
                            label += f" ({index})"
                        mapping[label] = index
                self.device_maps.append(mapping)
                choice = variable.get() if combo["values"] else self.settings.get(saved)
                combo["values"] = list(mapping)
                variable.set(choice if choice in mapping else next(iter(mapping)))
        except Exception as exc:
            logging.exception("Device enumeration failed")
            self.set_status(f"Erreur périphériques : {exc}")

    def save(self):
        try:
            # Refresh the executable path when an enabled app was moved/updated.
            if self.autostart.get() or startup_enabled():
                set_startup(self.autostart.get())
            self.settings = dict(port=self.port.get(), output=self.output.get(), microphone=self.microphone.get(), no_mic=self.no_mic.get(), auto_bridge=self.auto_bridge.get(), windows_ducking=self.windows_ducking.get())
            save_settings(self.settings)
            return True
        except Exception as exc:
            logging.exception("Saving settings failed")
            messagebox.showerror("SmartCon", f"Impossible d’enregistrer : {exc}")
            return False

    def set_status(self, value):
        self.status.set(value)
        self.tray.title = ("SmartCon — " + value)[:127]
        color = "#e05353" if value.startswith("Erreur") else "#7c8798" if value == "Arrêté" else "#35b97b"
        self.tray.icon = icon_image(color)

    def open_communications(self):
        try:
            # Open the Communications tab only; never write the global policy.
            subprocess.Popen(["control.exe", "mmsys.cpl,,3"])
        except OSError as exc:
            messagebox.showerror("SmartCon", f"Impossible d’ouvrir les réglages Windows : {exc}")

    def start(self):
        if self.closing or (self.worker and self.worker.is_alive()):
            return
        if not self.save():
            return
        if not self.port.get():
            messagebox.showerror("SmartCon", "Choisissez un port COM.")
            return
        args = SimpleNamespace(port=self.port.get(), baud=921600, device=self.device_maps[0][self.output.get()], input_device=self.device_maps[1][self.microphone.get()], no_mic=self.no_mic.get(), mic_gain=1.0,
                               desktop_audio=True, windows_ducking=self.windows_ducking.get())
        self.stop_event = threading.Event()
        self.commands = queue.Queue(maxsize=32)
        self.phone_status = None
        self.phone_status_at = 0.0
        self.set_status("Connexion en cours…")
        self.audio_status.set("Initialisation de la sortie audio…")
        self.start_button["state"] = "disabled"
        self.stop_button["state"] = "normal"
        for control in self.controls:
            control["state"] = "disabled"

        def work():
            error = None
            try:
                run_bridge(args, self.stop_event,
                           lambda value: self.events.put(("status", value)), self.commands,
                           lambda value: self.events.put(("phones", value)),
                           lambda value: self.events.put(("audio", value)))
            except (Exception, SystemExit) as exc:
                logging.exception("Bridge stopped with an error")
                error = str(exc)
            finally:
                self.events.put(("done", error))
        self.worker = threading.Thread(target=work, name="audio-bridge", daemon=False)
        self.worker.start()

    def stop(self):
        if self.worker and self.worker.is_alive():
            self.stop_event.set()
            self.set_status("Arrêt en cours…")
            self.stop_button["state"] = "disabled"

    def quit(self):
        self.closing = True
        self.stop()
        self.finish_quit()

    def finish_quit(self):
        if self.worker and self.worker.is_alive():
            self.root.after(100, self.finish_quit)
            return
        self.tray.stop()
        self.root.destroy()

    def poll(self):
        while not self.events.empty():
            action, value = self.events.get_nowait()
            if action == "show":
                self.root.deiconify()
                self.root.lift()
            elif action == "start":
                self.start()
            elif action == "stop":
                self.stop()
            elif action == "quit":
                self.quit()
                return
            elif action == "status" and not self.stop_event.is_set():
                self.set_status(value)
            elif action == "audio" and not self.stop_event.is_set():
                self.audio_status.set(value)
            elif action == "phones" and not self.stop_event.is_set():
                previous = self.phone_status or {}
                if any(previous.get(key) != value.get(key) for key in ("selected", "hfp", "a2dp", "call", "message", "pending")):
                    logging.info("Bluetooth state: %s", value)
                self.phone_status = value
                self.phone_status_at = time.monotonic()
            elif action == "done":
                self.audio_status.set("Atténuation SmartCon arrêtée.")
                self.set_status(f"Erreur : {value}" if value else "Arrêté")
                self.start_button["state"] = "normal"
                self.stop_button["state"] = "disabled"
                for index, control in enumerate(self.controls):
                    control["state"] = "readonly" if index < 3 else "normal"
        if not self.closing:
            self.render_phones()
            self.root.after(100, self.poll)

    def control_available(self):
        return bool(self.worker and self.worker.is_alive() and not self.stop_event.is_set()
                    and self.phone_status and self.phone_status.get("ready")
                    and time.monotonic() - self.phone_status_at < 5)

    def phone_action(self, command):
        if not self.control_available():
            return
        status = self.phone_status
        payload = {"cmd": command}
        if command in ("select", "forget"):
            selection = self.phones.selection()
            if not selection:
                messagebox.showinfo("SmartCon", "Sélectionnez un téléphone dans la liste.")
                return
            payload["address"] = selection[0]
        if command == "forget" and not messagebox.askyesno("SmartCon", "Oublier ce téléphone et supprimer son autorisation ? Un nouvel appairage sera nécessaire."):
            return
        if command in ("pair", "select", "disconnect", "forget") and status["call"]:
            if not messagebox.askyesno("SmartCon", "Un appel est en cours. Continuer coupera sa liaison audio avec SmartCon."):
                return
            payload["force"] = True
        if command in ("approve", "reject"):
            pending = status.get("pending")
            if not pending or pending["confirmed"]:
                return
            payload.update(address=pending["address"], challenge=pending["challenge"])
        try:
            self.commands.put_nowait(payload)
        except queue.Full:
            messagebox.showinfo("SmartCon", "Une commande est déjà en cours. Réessayez.")

    def render_phones(self):
        available = self.control_available()
        for button in self.phone_buttons:
            button["state"] = "normal" if available else "disabled"
        for button in self.approval_buttons:
            button["state"] = "disabled"
        if not available:
            for row in self.phones.get_children():
                values = self.phones.item(row, "values")
                self.phones.item(row, values=(values[0], values[1], "État indisponible"))
            self.number_text.set("")
            self.pair_text.set("État d’appairage indisponible — toute fenêtre ouverte expire sur l’ESP32 après 60 s.")
            if not self.worker or not self.worker.is_alive():
                self.phone_text.set("Démarrez le pont pour gérer les téléphones.")
            elif not self.phone_status:
                self.phone_text.set("En attente du firmware SmartCon avec gestion des téléphones. Mettez le firmware à jour si cet état persiste.")
            else:
                self.phone_text.set("Gestion des téléphones indisponible : liaison USB perdue ou erreur du firmware.")
            return
        status = self.phone_status
        self.phone_text.set(status["message"])
        wanted = {phone["address"] for phone in status["phones"]}
        for row in self.phones.get_children():
            if row not in wanted:
                self.phones.delete(row)
        for phone in status["phones"]:
            active = phone["address"] == status["selected"]
            state = "Enregistré"
            if active:
                state = "Sélectionné — " + ("appairage en cours" if status["pairing"] else
                        "appels + médias connectés" if status["hfp"] and status["a2dp"] else
                        "appels connectés" if status["hfp"] else "médias connectés" if status["a2dp"] else "en attente de connexion")
            values = (phone["name"] or "Téléphone", phone["address"], state)
            if self.phones.exists(phone["address"]):
                self.phones.item(phone["address"], values=values)
            else:
                self.phones.insert("", "end", iid=phone["address"], values=values)
        remaining = max(0, status["pairing"] - int(time.monotonic() - self.phone_status_at))
        self.pair_text.set(f"Appairage ouvert : {remaining} s — choisissez SmartCon sur le téléphone." if remaining else "Appairage verrouillé")
        self.phone_buttons[4]["state"] = "normal" if remaining else "disabled"
        pending = status.get("pending")
        if pending and remaining:
            self.number_text.set(f"{pending['number']:06d} — {pending['address']}\nComparez avec le numéro affiché sur VOTRE téléphone. Refusez s’il ne correspond pas." if not pending["confirmed"] else "Approbation envoyée — attente de confirmation du téléphone…")
            for button in self.approval_buttons:
                button["state"] = "disabled" if pending["confirmed"] else "normal"
        else:
            self.number_text.set("")


def main():
    # A second instance must never compete for the exclusive serial port.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, False, "Local\\SmartConSmokeTest" if "--smoke-test" in sys.argv else "Local\\SmartConTray")
    if not mutex:
        raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error() == 183:
        ctypes.windll.user32.MessageBoxW(None, "SmartCon est déjà ouvert près de l’horloge.", "SmartCon", 64)
        return
    DATA.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(DATA / "app.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(message)s")
    # The audio CLI prints statistics; windowed executables have no stdout.
    class LogStream:
        def write(self, value):
            if value.strip():
                logging.info(value.strip())
        def flush(self):
            pass
    sys.stdout = sys.stderr = LogStream()
    try:
        if "--smoke-test" in sys.argv:
            from listen import MediaDecoder
            from windows_audio import category_settings
            MediaDecoder()  # Verify bundled PyAV/FFmpeg can create the SBC decoder.
            category_settings(sd, False)
            category_settings(sd, True)
        root = tk.Tk()
        Application(root)
        root.mainloop()
        if "--smoke-test" in sys.argv:
            logging.info("Smoke test completed: Tk, tray, SBC decoder, WASAPI category adapter")
    except Exception as exc:
        logging.exception("Application error")
        if "--smoke-test" in sys.argv:
            raise
        ctypes.windll.user32.MessageBoxW(None, f"Erreur : {exc}\nJournal : {DATA / 'app.log'}", "SmartCon", 16)
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(mutex)


if __name__ == "__main__":
    main()
