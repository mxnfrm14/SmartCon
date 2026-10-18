"""Compile the security adapter against the installed SDK's real private types."""
import json
import os
from pathlib import Path
import re
import subprocess
import unittest


class PairingAdapterTests(unittest.TestCase):
    def test_audio_authorization_readers_cannot_wait_on_control_or_bluetooth_tasks(self):
        project = Path(__file__).resolve().parents[1]
        database = project / "build_audio_pc/compile_commands.json"
        if os.name != "nt" or not database.exists():
            self.skipTest("Requires a configured Windows ESP-IDF build")
        entry = next((entry for entry in json.loads(database.read_text()) if entry["file"].endswith("phone_manager.c")), None)
        if entry is None:
            self.skipTest("Phone manager compile command unavailable")
        output = project / "build_desktop/audio_gate_check.obj"
        output.parent.mkdir(exist_ok=True)
        command = re.sub(r" -o .*? -c ", f' -o "{output.as_posix()}" -c ', entry["command"])
        compiled = subprocess.run(command, cwd=entry["directory"], capture_output=True, text=True)
        self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
        compiler = entry["command"].split(" -", 1)[0].strip('"')
        objdump = compiler.replace("gcc.exe", "objdump.exe")
        assembly = subprocess.run([objdump, "-d", str(output)], capture_output=True, text=True, check=True).stdout
        for name in ("phone_manager_call_audio", "phone_manager_media_audio"):
            function = re.search(r"<" + name + r">:\n(.*?)(?=\n[0-9a-f]+ <|\Z)", assembly, re.S)
            self.assertIsNotNone(function, name)
            self.assertNotRegex(function[1], r"\bcall(?:0|4|8|12|x0|x4|x8|x12)\b", name + " must not call any blocking function")

    def test_wrapper_signatures_and_security_bits_match_sdk(self):
        project = Path(__file__).resolve().parents[1]
        database = project / "build_audio_pc/compile_commands.json"
        if os.name != "nt" or not database.exists():
            self.skipTest("Requires a configured Windows ESP-IDF build")
        entry = next((entry for entry in json.loads(database.read_text()) if "bta_dm_act.c" in entry["file"]), None)
        if entry is None:
            self.skipTest("Classic Bluetooth compile command unavailable")
        check = project / "build_desktop/adapter_check.c"
        check.parent.mkdir(exist_ok=True)
        adapter = (project / "main/pairing_security.c").as_posix()
        check.write_text('''#include "common/bt_target.h"
#include "stack/bt_types.h"
#include "bta/bta_sys.h"
#include "bta/bta_api.h"
#include "bta/bta_dm_co.h"
#include "stack/btm_api.h"
''' + f'#include "{adapter}"\n' + '''
_Static_assert(__builtin_types_compatible_p(__typeof__(&__wrap_bta_dm_co_io_req), __typeof__(&bta_dm_co_io_req)), "IO request ABI mismatch");
_Static_assert(__builtin_types_compatible_p(__typeof__(&__wrap_BTA_DmConfirm), __typeof__(&BTA_DmConfirm)), "Confirmation ABI mismatch");
_Static_assert(BTM_IO_CAP_IO == 1 && BTM_AUTH_YN_BIT == 1, "Security constant mismatch");
''')
        command = entry["command"].replace(entry["file"], str(check))
        command = re.sub(r" -o .*? -c ", f' -o "{check.with_suffix(".obj").as_posix()}" -c ', command)
        result = subprocess.run(command, cwd=entry["directory"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
