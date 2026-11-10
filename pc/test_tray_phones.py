"""Exercise the real Tk phone controls without USB, registry or tray changes."""
import copy
import time
import unittest
from unittest.mock import MagicMock, patch

from test_phone_control import STATUS


class TrayPhoneTests(unittest.TestCase):
    def setUp(self):
        try:
            import tray_app
            self.module = tray_app
            self.root = tray_app.tk.Tk()
        except Exception as exc:
            raise unittest.SkipTest(f"Desktop environment unavailable: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        for target, kwargs in [("load_settings", dict(return_value={"auto_bridge": False})),
                               ("startup_enabled", dict(return_value=False)),
                               ("pystray.Icon", {}), ("Application.refresh", {})]:
            patcher = patch.object(tray_app, target, **kwargs) if "." not in target else patch("tray_app." + target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.app = tray_app.Application(self.root)
        self.app.worker = MagicMock()
        self.app.worker.is_alive.return_value = True
        self.app.phone_status = copy.deepcopy(STATUS)
        self.app.phone_status["pairing"] = 0
        self.app.phone_status_at = time.monotonic()

    def test_select_phone_sends_address_and_preserves_other_saved_phones(self):
        self.app.phone_status["phones"].append(dict(address="11:22:33:44:55:66", name="Second phone"))
        self.app.render_phones()
        self.assertEqual(len(self.app.phones.get_children()), 2)
        self.app.phones.selection_set("11:22:33:44:55:66")
        self.app.phone_action("select")
        self.assertEqual(self.app.commands.get_nowait(), dict(cmd="select", address="11:22:33:44:55:66"))

    def test_approval_carries_current_challenge_and_expired_state_disables_controls(self):
        self.app.phone_status.update(pairing=50, pending=dict(address=STATUS["selected"], number=1234, challenge=42, confirmed=False))
        self.app.render_phones()
        self.assertIn("001234", self.app.number_text.get())
        self.app.phone_action("approve")
        self.assertEqual(self.app.commands.get_nowait(), dict(cmd="approve", address=STATUS["selected"], challenge=42))
        self.app.phone_status_at -= 6
        self.app.render_phones()
        self.app.phone_action("approve")
        self.assertTrue(self.app.commands.empty())
        self.assertTrue(all(str(button["state"]) == "disabled" for button in self.app.approval_buttons))

    def test_call_confirmation_controls_force_flag(self):
        self.app.phone_status["call"] = True
        with patch("tray_app.messagebox.askyesno", return_value=False):
            self.app.phone_action("disconnect")
        self.assertTrue(self.app.commands.empty())
        with patch("tray_app.messagebox.askyesno", return_value=True):
            self.app.phone_action("disconnect")
        self.assertEqual(self.app.commands.get_nowait(), dict(cmd="disconnect", force=True))

    def test_enabled_startup_is_updated_to_current_executable_path(self):
        self.app.autostart.set(True)
        with patch("tray_app.startup_enabled", return_value=True), patch("tray_app.set_startup") as startup, patch("tray_app.save_settings"):
            self.assertTrue(self.app.save())
        startup.assert_called_once_with(True)

    def test_old_settings_enable_ducking_and_disabled_setting_is_saved(self):
        self.assertTrue(self.app.windows_ducking.get())
        self.app.windows_ducking.set(False)
        self.app.output.set("Mon casque [MME]")
        with patch("tray_app.startup_enabled", return_value=False), patch("tray_app.save_settings") as save:
            self.assertTrue(self.app.save())
        self.assertFalse(save.call_args.args[0]["windows_ducking"])
        self.assertEqual(save.call_args.args[0]["output"], "Mon casque [MME]")

    def test_audio_warning_survives_regular_status_updates(self):
        self.app.events.put(("audio", "Atténuation indisponible : test"))
        self.app.events.put(("status", "Appel en cours"))
        self.app.poll()
        self.assertEqual(self.app.audio_status.get(), "Atténuation indisponible : test")

    def test_windows_button_only_opens_communications_settings(self):
        with patch("tray_app.subprocess.Popen") as launch:
            self.app.open_communications()
        launch.assert_called_once_with(["control.exe", "mmsys.cpl,,3"])


if __name__ == "__main__":
    unittest.main()
