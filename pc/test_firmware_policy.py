"""Execute the production C phone policy with mocked ESP APIs on Windows.

Requires clang + lld (the ESP-IDF clang installation is detected automatically).
The mocks replace hardware and storage, not the policy being tested.
"""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from phone_control import command_frame, decode_status

MOCK_HEADER = r"""
#pragma once
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
int snprintf(char *, size_t, const char *, ...);
void *memcpy(void *, const void *, size_t);
void *memset(void *, int, size_t);
int memcmp(const void *, const void *, size_t);
void *calloc(size_t, size_t);
void free(void *);
typedef int esp_err_t;
typedef int nvs_handle_t;
typedef int SemaphoreHandle_t;
typedef uint8_t esp_bd_addr_t[6];
typedef uint8_t esp_bt_pin_code_t[16];
typedef int esp_bt_gap_cb_event_t;
typedef union {
    struct { uint8_t bda[6]; uint32_t num_val; } cfm_req;
    struct { uint8_t bda[6]; } pin_req;
    struct { uint8_t bda[6]; } key_req;
    struct { int stat; uint8_t bda[6]; char device_name[249]; } auth_cmpl;
    struct { int status; } remove_bond_dev_cmpl;
} esp_bt_gap_cb_param_t;
enum { ESP_BT_GAP_CFM_REQ_EVT=1, ESP_BT_GAP_PIN_REQ_EVT, ESP_BT_GAP_KEY_REQ_EVT,
       ESP_BT_GAP_KEY_NOTIF_EVT, ESP_BT_GAP_AUTH_CMPL_EVT, ESP_BT_GAP_REMOVE_BOND_DEV_COMPLETE_EVT };
enum { ESP_HF_CLIENT_CONNECTION_STATE_DISCONNECTED, ESP_HF_CLIENT_CONNECTION_STATE_CONNECTING,
       ESP_HF_CLIENT_CONNECTION_STATE_CONNECTED, ESP_HF_CLIENT_CONNECTION_STATE_SLC_CONNECTED,
       ESP_HF_CLIENT_CONNECTION_STATE_DISCONNECTING };
enum { ESP_A2D_CONNECTION_STATE_DISCONNECTED, ESP_A2D_CONNECTION_STATE_CONNECTING,
       ESP_A2D_CONNECTION_STATE_CONNECTED, ESP_A2D_CONNECTION_STATE_DISCONNECTING };
#define ESP_OK 0
#define ESP_ERR_NO_MEM 1
#define ESP_BT_STATUS_SUCCESS 0
#define ESP_BT_CONNECTABLE 1
#define ESP_BT_NON_CONNECTABLE 0
#define ESP_BT_GENERAL_DISCOVERABLE 1
#define ESP_BT_NON_DISCOVERABLE 0
#define NVS_READWRITE 1
#define portMAX_DELAY 0
#define pdPASS 1
#define pdMS_TO_TICKS(n) (n)
#define ESP_ERROR_CHECK(x) do { if ((x) != 0) mock_error = 1; } while (0)
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGI(...) ((void)0)
#define xSemaphoreCreateMutex() 1
#define xSemaphoreTake(...) ((void)0)
#define xSemaphoreGive(...) ((void)0)
#define xTaskCreate(...) 1
#define vTaskDelay(...) ((void)0)
static int mock_error;
static int64_t mock_time;
static int counts[7], fail_commit;
static char last_status[1025];
static uint8_t saved[1024];
static size_t saved_size;
static int64_t esp_timer_get_time(void) { return mock_time; }
static uint32_t esp_random(void) { return 1000; }
static const char *esp_err_to_name(int e) { return "mock"; }
static int nvs_open(const char *a, int b, nvs_handle_t *c) { *c=1; return 0; }
static int nvs_get_blob(int h, const char *k, void *p, size_t *n) {
    if (!saved_size) return 1;
    memcpy(p,saved,saved_size); *n=saved_size; return 0;
}
static int nvs_set_blob(int h, const char *k, const void *p, size_t n) {
    if (fail_commit) return 1;
    memcpy(saved,p,n); saved_size=n; return 0;
}
static int nvs_commit(int h) { return fail_commit ? 1 : 0; }
static int esp_bt_gap_set_scan_mode(int c, int d) { return 0; }
static int esp_hf_client_disconnect(uint8_t *a) { counts[4]++; return 0; }
static int esp_a2d_sink_disconnect(uint8_t *a) { counts[5]++; return 0; }
static int esp_hf_client_connect(uint8_t *a) { counts[2]++; return 0; }
static int esp_a2d_sink_connect(uint8_t *a) { counts[3]++; return 0; }
static int esp_bt_gap_ssp_confirm_reply(uint8_t *a, bool accept) { counts[accept ? 0 : 1]++; return 0; }
static int esp_bt_gap_remove_bond_device(uint8_t *a) { counts[6]++; return 0; }
static int esp_bt_gap_pin_reply(uint8_t *a, bool accept, int len, uint8_t *p) { return 0; }
static int esp_bt_gap_ssp_passkey_reply(uint8_t *a, bool accept, uint32_t p) { return 0; }
static int esp_bt_gap_get_bond_device_num(void) { return 0; }
static int esp_bt_gap_get_bond_device_list(int *n, esp_bd_addr_t *b) { *n=0; return 0; }
"""

SHIM = r"""
#include "mock.h"
#include "phone_manager.c"
void audio_serial_mic_rate(uint16_t rate) {}
void audio_serial_clear(void) {}
void audio_serial_control(const uint8_t *p, uint32_t n) {
    if (n <= 1024) { memcpy(last_status,p,n); last_status[n]=0; }
}
#define EXPORT __declspec(dllexport)
static void address(int id, uint8_t *p) { uint8_t a[6]={0xAA,0xBB,0xCC,0,0,id}; memcpy(p,a,6); }
EXPORT void test_reset(int preserve) {
    if (!preserve) saved_size=0;
    memset(&roster,0,sizeof(roster)); memset(pending,0,6); memset(candidate,0,6);
    memset(hfp_address,0,6); memset(a2dp_address,0,6);
    memset(counts,0,sizeof(counts));
    ready=hfp_busy=a2dp_busy=hfp_up=a2dp_up=confirmed=voice_link=false;
    hfp_ready=a2dp_ready=false; call_gate=media_gate=pending_profile=0;
    attempt_deadline=0; memset(attempt_address,0,6);
    pairing_until=retry_at=0; call_active=call_setup=hfp_state=a2dp_state=0; number=challenge=0;
    mock_time=1000000; fail_commit=mock_error=0;
    snprintf(notice,sizeof(notice),"Ready");
    phone_manager_init(); phone_manager_profile_ready(false); phone_manager_profile_ready(true); snapshot();
}
EXPORT const char *test_status(void) { snapshot(); return last_status; }
EXPORT void test_command(const uint8_t *p, unsigned n) { phone_manager_command(p,n); }
EXPORT void test_request(int id, int number) {
    esp_bt_gap_cb_param_t p={0}; address(id,p.cfm_req.bda); p.cfm_req.num_val=number;
    phone_manager_gap(ESP_BT_GAP_CFM_REQ_EVT,&p);
}
EXPORT void test_auth(int id, int success) {
    esp_bt_gap_cb_param_t p={0}; address(id,p.auth_cmpl.bda); p.auth_cmpl.stat=success ? 0 : 1;
    snprintf(p.auth_cmpl.device_name,sizeof(p.auth_cmpl.device_name),"Phone %d",id);
    phone_manager_gap(ESP_BT_GAP_AUTH_CMPL_EVT,&p);
}
EXPORT int test_link(int id, int media, int state) {
    uint8_t a[6]; address(id,a);
    return media ? phone_manager_a2dp(a,state,1) : phone_manager_hfp(a,state);
}
EXPORT int test_audio(int media) { return media ? phone_manager_media_audio(1) : phone_manager_call_audio(); }
EXPORT void test_advance(int seconds) { mock_time+=(int64_t)seconds*1000000; tick(); }
EXPORT void test_call(int active) { phone_manager_call_state(active,0); }
EXPORT void test_storage_failure(void) { fail_commit=1; }
EXPORT int test_count(int n) { return counts[n]; }
"""


class FirmwarePolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name != "nt":
            raise unittest.SkipTest("Native firmware policy harness requires Windows clang/lld")
        clang = os.environ.get("SMARTCON_CLANG") or shutil.which("clang")
        if not clang:
            matches = list(Path("C:/Espressif/tools/esp-clang").glob("*/esp-clang/bin/clang.exe"))
            clang = str(matches[-1]) if matches else None
        if not clang:
            raise unittest.SkipTest("Install clang/lld or set SMARTCON_CLANG")
        targets = subprocess.run([clang, "--print-targets"], capture_output=True, text=True)
        if "x86-64" not in targets.stdout and "x86_64" not in targets.stdout:
            raise unittest.SkipTest("This clang only targets ESP chips; set SMARTCON_CLANG to a Windows host clang")
        cls.directory = tempfile.TemporaryDirectory(prefix="smartcon-policy-")
        cls.addClassCleanup(cls.directory.cleanup)
        work = Path(cls.directory.name)
        (work / "mock.h").write_text(MOCK_HEADER)
        for header in ("stdio.h", "stdlib.h", "string.h", "freertos/FreeRTOS.h", "freertos/semphr.h",
                       "freertos/task.h", "esp_timer.h", "esp_log.h", "esp_random.h", "esp_hf_client_api.h",
                       "esp_a2dp_api.h", "nvs.h", "esp_gap_bt_api.h"):
            path = work / header
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('#include "mock.h"\n')
        (work / "shim.c").write_text(SHIM)
        lld = str(Path(clang).with_name("lld.exe"))
        link = [lld, "-flavor", "link", "/dll", "/noentry", "/machine:x64"]
        # Forward the few libc calls to Windows' installed CRT; no SDK required.
        exports = [f"/export:{name}=msvcrt.{name}" for name in ("memcpy", "memset", "memcmp", "calloc", "free", "snprintf")]
        def run(args):
            result = subprocess.run(args, cwd=work, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
        (work / "empty.c").write_text("typedef int dummy;\n")
        run([clang, "--target=x86_64-pc-windows-msvc", "-c", "empty.c", "-o", "empty.obj"])
        run(link + exports + ["empty.obj", "/out:policy_crt.dll", "/implib:policy_crt.lib"])
        run([clang, "--target=x86_64-pc-windows-msvc", "-c", "-fno-builtin", "-fno-stack-protector",
             "-I", str(work), "-I", str(Path(__file__).resolve().parents[1] / "main"),
             "shim.c", "-o", "shim.obj"])
        run(link + ["shim.obj", "policy_crt.lib", "/out:policy.dll"])
        cls.crt = ctypes.CDLL(str(work / "policy_crt.dll"))
        cls.lib = ctypes.CDLL(str(work / "policy.dll"))
        cls.lib.test_status.restype = ctypes.c_char_p
        import _ctypes
        cls.addClassCleanup(_ctypes.FreeLibrary, cls.crt._handle)
        cls.addClassCleanup(_ctypes.FreeLibrary, cls.lib._handle)

    def setUp(self):
        self.lib.test_reset(0)

    def status(self):
        raw = self.lib.test_status()
        result = decode_status(raw)
        self.assertIsNotNone(result, raw)
        return result

    def command(self, name, **kwargs):
        payload = command_frame(dict(cmd=name, **kwargs))[20:]
        self.lib.test_command(payload, len(payload))

    def pair(self, id):
        self.command("pair")
        self.lib.test_request(id, 123456)
        request = self.status()["pending"]
        self.command("approve", address=request["address"], challenge=request["challenge"])
        self.lib.test_auth(id, 1)
        return self.status()["selected"]

    def test_locked_boot_never_auto_confirms(self):
        self.assertEqual(self.status()["pairing"], 0)
        self.lib.test_request(1, 123456)
        self.assertEqual(self.lib.test_count(0), 0)
        self.assertEqual(self.lib.test_count(1), 1)
        self.assertNotIn("pending", self.status())
        self.lib.test_auth(1, 1)
        self.assertEqual(self.status()["phones"], [])
        self.assertFalse(self.lib.test_link(1, 0, 3))
        self.assertFalse(self.lib.test_link(1, 1, 2))

    def test_approval_is_bound_to_phone_and_current_request(self):
        self.command("pair")
        self.lib.test_request(1, 123456)
        request = self.status()["pending"]
        self.assertEqual(self.lib.test_count(0), 0)
        self.command("approve", address=request["address"], challenge=request["challenge"] + 1)
        self.assertEqual(self.lib.test_count(0), 0)
        self.command("approve", address=request["address"], challenge=request["challenge"])
        self.assertEqual(self.lib.test_count(0), 1)
        self.lib.test_auth(1, 1)
        self.assertEqual(len(self.status()["phones"]), 1)

    def test_profiles_before_authentication_remain_connected_but_cannot_pass_audio(self):
        self.command("pair")
        self.lib.test_request(1, 123456)
        request = self.status()["pending"]
        self.lib.test_link(1, 0, 3)
        self.lib.test_link(1, 1, 2)
        self.assertEqual(self.lib.test_count(4), 0)
        self.assertEqual(self.lib.test_count(5), 0)
        self.assertFalse(self.lib.test_audio(0))
        self.assertFalse(self.lib.test_audio(1))
        self.command("approve", address=request["address"], challenge=request["challenge"])
        self.lib.test_auth(1, 1)
        self.assertTrue(self.lib.test_audio(0))
        self.assertTrue(self.lib.test_audio(1))
        self.assertEqual(self.status()["pairing"], 0)
        self.lib.test_reset(1)
        self.assertEqual(self.status()["selected"], request["address"])
        self.assertEqual(len(self.status()["phones"]), 1)

    def test_expired_pairing_rejects_delayed_approval_and_authentication(self):
        self.command("pair")
        self.lib.test_request(1, 123456)
        request = self.status()["pending"]
        self.lib.test_advance(61)
        self.command("approve", address=request["address"], challenge=request["challenge"])
        self.lib.test_auth(1, 1)
        self.assertEqual(self.lib.test_count(0), 0)
        self.assertEqual(self.status()["phones"], [])
        self.assertEqual(self.status()["pairing"], 0)

    def test_switch_blocks_old_audio_and_waits_for_both_profiles(self):
        first = self.pair(1)
        self.pair(2)
        self.lib.test_link(2, 0, 3)
        self.lib.test_link(2, 1, 2)
        self.assertTrue(self.lib.test_audio(0))
        self.assertTrue(self.lib.test_audio(1))
        self.command("select", address=first)
        self.assertFalse(self.lib.test_audio(0))
        self.assertFalse(self.lib.test_audio(1))
        self.lib.test_advance(3)
        self.assertEqual(self.lib.test_count(2), 0)
        self.lib.test_link(2, 0, 0)
        self.lib.test_advance(3)
        self.assertEqual(self.lib.test_count(2), 0)
        self.lib.test_link(2, 1, 0)
        self.lib.test_advance(11)
        self.assertEqual(self.lib.test_count(2), 1)
        self.assertTrue(self.lib.test_link(1, 0, 3))
        self.assertTrue(self.lib.test_link(1, 1, 2))

    def test_call_switch_requires_confirmation_and_forget_revokes_access(self):
        first = self.pair(1)
        second = self.pair(2)
        self.lib.test_link(2, 0, 3)
        self.lib.test_call(1)
        self.command("select", address=first)
        self.assertEqual(self.status()["selected"], second)
        self.command("select", address=first, force=True)
        self.assertEqual(self.status()["selected"], first)
        self.command("forget", address=first, force=True)
        self.assertEqual(self.status()["selected"], "")
        self.assertFalse(self.lib.test_link(1, 0, 3))
        self.assertFalse(self.lib.test_link(1, 1, 2))
        self.lib.test_reset(1)
        self.assertEqual([p["address"] for p in self.status()["phones"]], [second])

    def test_storage_failure_disables_all_access(self):
        first = self.pair(1)
        self.lib.test_link(1, 0, 3)
        self.lib.test_storage_failure()
        self.command("disconnect")
        self.assertFalse(self.status()["ready"])
        self.assertFalse(self.lib.test_audio(0))
        self.assertFalse(self.lib.test_link(1, 1, 2))

    def test_reselect_active_phone_keeps_media_link_and_audio(self):
        first = self.pair(1)
        self.lib.test_link(1, 0, 3)
        self.lib.test_link(1, 1, 2)
        self.command("select", address=first)
        self.assertEqual(self.lib.test_count(4), 0)
        self.assertEqual(self.lib.test_count(5), 0)
        self.assertTrue(self.lib.test_audio(0))
        self.assertTrue(self.lib.test_audio(1))

    def test_connects_profiles_sequentially_without_duplicate_pending_requests(self):
        self.pair(1)
        self.lib.test_advance(6)
        self.assertEqual(self.lib.test_count(2), 1)
        self.assertEqual(self.lib.test_count(3), 0)
        self.lib.test_advance(10)
        self.assertEqual(self.lib.test_count(2), 1)
        self.lib.test_link(1, 0, 3)
        self.lib.test_advance(4)
        self.assertEqual(self.lib.test_count(3), 1)
        self.lib.test_advance(10)
        self.assertEqual(self.lib.test_count(3), 1)


if __name__ == "__main__":
    unittest.main()
