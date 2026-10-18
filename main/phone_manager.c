#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "esp_random.h"
#include "esp_hf_client_api.h"
#include "esp_a2dp_api.h"
#include "nvs.h"
#include "audio_serial.h"
#include "phone_manager.h"

#define MAX_PHONES 6
typedef struct { uint8_t address[6]; char name[49]; } phone_t;
typedef struct { uint32_t version; uint8_t selected[6]; phone_t phones[MAX_PHONES]; } roster_t;
static roster_t roster;
static nvs_handle_t storage;
static SemaphoreHandle_t mutex;
static bool ready, hfp_busy, a2dp_busy, hfp_up, a2dp_up;
static bool hfp_ready, a2dp_ready;
static uint32_t call_gate, media_gate;
static unsigned pending_profile;
static uint8_t attempt_address[6];
static int64_t attempt_deadline;
static uint8_t hfp_address[6], a2dp_address[6], pending[6];
static uint8_t candidate[6];
static int hfp_state, a2dp_state;
static uint16_t media_handle;
static bool confirmed;
static uint32_t number, challenge;
static int call_active, call_setup;
static bool voice_link;
static int64_t pairing_until, retry_at;
static char notice[100] = "Ready";
static const uint8_t empty[6];

static bool same(const uint8_t *a, const uint8_t *b) { return memcmp(a, b, 6) == 0; }
static bool present(const uint8_t *a) { return !same(a, empty); }
static bool pairing(void) { return pairing_until > esp_timer_get_time(); }
static int find(const uint8_t *address)
{
    for (int i = 0; i < MAX_PHONES; i++)
        if (present(address) && same(roster.phones[i].address, address)) return i;
    return -1;
}
static bool allowed(const uint8_t *address)
{
    return ready && !pairing_until && find(address) >= 0 && same(address, roster.selected);
}
static bool provisional(const uint8_t *address)
{
    /* Permit setup for one new phone during enrollment, never its audio. */
    if (!ready || !pairing() || find(address) >= 0) return false;
    if (present(candidate) && !same(candidate, address)) return false;
    memcpy(candidate, address, 6);
    return true;
}
bool phone_manager_pairing_approved(const uint8_t *address)
{
    if (!mutex) return false;
    xSemaphoreTake(mutex, portMAX_DELAY);
    bool approved = ready && pairing() && confirmed && same(pending, address);
    xSemaphoreGive(mutex);
    return approved;
}
static void address_text(const uint8_t *a, char *out)
{
    snprintf(out, 18, "%02X:%02X:%02X:%02X:%02X:%02X", a[0], a[1], a[2], a[3], a[4], a[5]);
}
static bool persist(void)
{
    esp_err_t error = nvs_set_blob(storage, "roster", &roster, sizeof(roster));
    if (error == ESP_OK) error = nvs_commit(storage);
    if (error != ESP_OK) {
        /* Fail closed: no unsaved authorization can remain live. */
        ready = false;
        snprintf(notice, sizeof(notice), "Storage error; restart required");
        ESP_LOGE("PHONES", "Policy persistence failed: %s", esp_err_to_name(error));
        return false;
    }
    return true;
}
static void visibility(void)
{
    esp_bt_gap_set_scan_mode(ready ? ESP_BT_CONNECTABLE : ESP_BT_NON_CONNECTABLE,
                            pairing() ? ESP_BT_GENERAL_DISCOVERABLE : ESP_BT_NON_DISCOVERABLE);
}
static void disconnect_all(void)
{
    /* Disable the data path before requesting asynchronous disconnections. */
    __atomic_store_n(&call_gate, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&media_gate, 0, __ATOMIC_RELEASE);
    audio_serial_mic_rate(0);
    audio_serial_clear();
    if (hfp_busy) esp_hf_client_disconnect(hfp_address);
    if (a2dp_busy) esp_a2d_sink_disconnect(a2dp_address);
    if (pending_profile == 1) esp_hf_client_disconnect(attempt_address);
    if (pending_profile == 2) esp_a2d_sink_disconnect(attempt_address);
    retry_at = esp_timer_get_time() + 1500000;
}
static void cancel_pairing(void)
{
    if (present(pending) && !confirmed) esp_bt_gap_ssp_confirm_reply(pending, false);
    if (present(pending) && find(pending) < 0) esp_bt_gap_remove_bond_device(pending);
    memset(pending, 0, 6);
    memset(candidate, 0, 6);
    confirmed = false;
    pairing_until = 0;
    visibility();
}
/* Names are labels only. Escape JSON and bound the wire representation. */
static void quote_name(const char *name, char *output)
{
    unsigned n = 0;
    for (const unsigned char *p = (const unsigned char *)name; *p && n < 48; p++) {
        if (*p < 32 || *p == 34 || *p == 92) {
            if (n + 6 > 48) break;
            output[n++] = 92;
            n += snprintf(output + n, 6, "u%04x", *p);
        } else if (*p < 128) output[n++] = *p;
        else {
            unsigned width = (*p & 0xe0) == 0xc0 ? 2 : (*p & 0xf0) == 0xe0 ? 3 : (*p & 0xf8) == 0xf0 ? 4 : 0;
            bool valid = width && n + width <= 48;
            for (unsigned i = 1; valid && i < width; i++) valid = p[i] && (p[i] & 0xc0) == 0x80;
            if (!valid) { output[n++] = '?'; break; }
            memcpy(output + n, p, width); n += width; p += width - 1;
        }
    }
    output[n] = 0;
}
static void snapshot(void)
{
    /* Audio callbacks must never wait on the control/NVS mutex. */
    __atomic_store_n(&call_gate, hfp_up && allowed(hfp_address), __ATOMIC_RELEASE);
    __atomic_store_n(&media_gate, a2dp_up && allowed(a2dp_address) ? (uint32_t)media_handle + 1 : 0, __ATOMIC_RELEASE);
    char json[1025], text[18];
    address_text(roster.selected, text);
    int64_t left = pairing_until - esp_timer_get_time();
    int n = snprintf(json, sizeof(json),
        "{\"v\":1,\"ready\":%s,\"selected\":\"%s\",\"hfp\":%s,\"a2dp\":%s,\"call\":%s,\"pairing\":%d,\"message\":\"%s\",\"phones\":[",
        ready ? "true" : "false", present(roster.selected) ? text : "",
        hfp_up && allowed(hfp_address) ? "true" : "false",
        a2dp_up && allowed(a2dp_address) ? "true" : "false",
        call_active || call_setup || voice_link ? "true" : "false",
        left > 0 ? (int)((left + 999999) / 1000000) : 0, notice);
    bool first = true;
    for (int i = 0; i < MAX_PHONES; i++) {
        if (!present(roster.phones[i].address)) continue;
        char name[64]; quote_name(roster.phones[i].name, name);
        address_text(roster.phones[i].address, text);
        if (n < 0 || n >= sizeof(json)) return;
        n += snprintf(json + n, sizeof(json) - n, "%s{\"address\":\"%s\",\"name\":\"%s\"}", first ? "" : ",", text, name);
        first = false;
    }
    if (n < 0 || n >= sizeof(json)) return;
    n += snprintf(json + n, sizeof(json) - n, "]");
    if (present(pending)) {
        address_text(pending, text);
        if (n < 0 || n >= sizeof(json)) return;
        n += snprintf(json + n, sizeof(json) - n,
            ",\"pending\":{\"address\":\"%s\",\"number\":%lu,\"challenge\":%lu,\"confirmed\":%s}",
            text, (unsigned long)number, (unsigned long)challenge, confirmed ? "true" : "false");
    }
    if (n < 0 || n >= sizeof(json)) return;
    n += snprintf(json + n, sizeof(json) - n, "}");
    if (n > 0 && n <= 1024) audio_serial_control((uint8_t *)json, n);
}

/* Fixed 12-byte commands: opcode, force flag, address[6], challenge LE32. */
enum { STATUS = 1, PAIR, CANCEL, APPROVE, REJECT, SELECT, DISCONNECT, FORGET };
void phone_manager_command(const uint8_t *data, unsigned size)
{
    if (!mutex || size != 12 || data[0] < STATUS || data[0] > FORGET || data[1] > 1) return;
    unsigned command = data[0];
    bool force = data[1];
    uint8_t target[6]; memcpy(target, data + 2, 6);
    uint32_t token = (uint32_t)data[8] | ((uint32_t)data[9] << 8) |
                     ((uint32_t)data[10] << 16) | ((uint32_t)data[11] << 24);
    xSemaphoreTake(mutex, portMAX_DELAY);
    if (!ready || command == STATUS) goto done;
    if (command == CANCEL) {
        if (pairing_until) disconnect_all();
        cancel_pairing();
        snprintf(notice, sizeof(notice), "Pairing locked");
    } else if (command == APPROVE || command == REJECT) {
        if (!pairing() || !present(pending) || confirmed || token != challenge || !same(target, pending)) {
            snprintf(notice, sizeof(notice), "Pairing request expired");
            goto done;
        }
        bool accept = command == APPROVE;
        confirmed = accept;
        esp_err_t error = esp_bt_gap_ssp_confirm_reply(pending, accept);
        if (error != ESP_OK || !accept) {
            disconnect_all(); cancel_pairing();
            snprintf(notice, sizeof(notice), "Pairing rejected");
        } else snprintf(notice, sizeof(notice), "Waiting for phone authentication");
    } else if (command == PAIR || command == SELECT || command == DISCONNECT || command == FORGET) {
        if (command == SELECT && !pairing_until && allowed(target)) {
            /* Clicking the active row must not tear down a working audio link. */
            snprintf(notice, sizeof(notice), "Phone already selected");
            goto done;
        }
        if ((call_active || call_setup || voice_link) && !force) {
            snprintf(notice, sizeof(notice), "Call in progress; confirmation required");
            goto done;
        }
        int index = -1;
        if (command == SELECT || command == FORGET) {
            if ((index = find(target)) < 0) {
                snprintf(notice, sizeof(notice), "Unknown phone"); goto done;
            }
        }
        disconnect_all();
        cancel_pairing();
        if (command == PAIR) {
            int slot = -1;
            for (int i = 0; i < MAX_PHONES; i++) if (!present(roster.phones[i].address)) { slot = i; break; }
            if (slot < 0) { snprintf(notice, sizeof(notice), "Phone list full; forget a phone first"); goto done; }
            pairing_until = esp_timer_get_time() + 60000000;
            visibility();
            snprintf(notice, sizeof(notice), "Select SmartCon in the phone Bluetooth settings");
        } else if (command == SELECT) {
            memcpy(roster.selected, target, 6);
            if (persist()) snprintf(notice, sizeof(notice), "Switching phone");
        } else if (command == DISCONNECT) {
            memset(roster.selected, 0, 6);
            if (persist()) snprintf(notice, sizeof(notice), "Disconnected; select a phone to reconnect");
        } else {
            if (same(roster.selected, target)) memset(roster.selected, 0, 6);
            memset(&roster.phones[index], 0, sizeof(phone_t));
            if (persist()) {
                esp_bt_gap_remove_bond_device(target);
                snprintf(notice, sizeof(notice), "Phone forgotten");
            }
        }
    }
done:
    if (!ready) { disconnect_all(); visibility(); }
    snapshot();
    xSemaphoreGive(mutex);
}

bool phone_manager_gap(esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t *param)
{
    if (!mutex) return false;
    bool handled = true;
    xSemaphoreTake(mutex, portMAX_DELAY);
    switch (event) {
    case ESP_BT_GAP_CFM_REQ_EVT:
        /* Never auto-confirm, including old bonds that need to pair again. */
        if (present(pending) || !provisional(param->cfm_req.bda)) {
            esp_bt_gap_ssp_confirm_reply(param->cfm_req.bda, false);
        } else {
            memcpy(pending, param->cfm_req.bda, 6);
            number = param->cfm_req.num_val;
            challenge++;
            confirmed = false;
            ESP_LOGI("PHONES", "Numeric confirmation requested; awaiting USB approval");
            snprintf(notice, sizeof(notice), "Compare the number on both devices before approving");
        }
        break;
    case ESP_BT_GAP_PIN_REQ_EVT: {
        esp_bt_pin_code_t pin = {0};
        esp_bt_gap_pin_reply(param->pin_req.bda, false, 0, pin);
        break;
    }
    case ESP_BT_GAP_KEY_REQ_EVT:
        esp_bt_gap_ssp_passkey_reply(param->key_req.bda, false, 0);
        break;
    case ESP_BT_GAP_KEY_NOTIF_EVT:
        /* Passkey/legacy fallback is deliberately unsupported. */
        snprintf(notice, sizeof(notice), "Phone must support numeric comparison");
        disconnect_all(); cancel_pairing();
        break;
    case ESP_BT_GAP_AUTH_CMPL_EVT:
        ESP_LOGI("PHONES", "Authentication status=0x%02x approved=%d window=%d",
                 param->auth_cmpl.stat, confirmed, pairing());
        if (param->auth_cmpl.stat == ESP_BT_STATUS_SUCCESS) {
            if (ready && pairing() && confirmed && same(pending, param->auth_cmpl.bda)) {
                int slot = -1;
                for (int i = 0; i < MAX_PHONES; i++) if (!present(roster.phones[i].address)) { slot = i; break; }
                if (slot >= 0) {
                    memcpy(roster.phones[slot].address, pending, 6);
                    snprintf(roster.phones[slot].name, sizeof(roster.phones[slot].name), "%.48s", param->auth_cmpl.device_name);
                    memcpy(roster.selected, pending, 6);
                    if (persist()) snprintf(notice, sizeof(notice), "Phone approved; pairing locked");
                    /* Do not remove the newly saved bond in cancel_pairing(). */
                    memset(pending, 0, 6);
                    cancel_pairing();
                    /* Profile callbacks may arrive before the GAP auth callback. */
                    hfp_up = hfp_busy && allowed(hfp_address) && hfp_state == ESP_HF_CLIENT_CONNECTION_STATE_SLC_CONNECTED;
                    a2dp_up = a2dp_busy && allowed(a2dp_address) && a2dp_state == ESP_A2D_CONNECTION_STATE_CONNECTED;
                    retry_at = esp_timer_get_time() + 5000000;
                }
            } else if (!allowed(param->auth_cmpl.bda)) {
                esp_hf_client_disconnect(param->auth_cmpl.bda);
                esp_a2d_sink_disconnect(param->auth_cmpl.bda);
                if (find(param->auth_cmpl.bda) < 0) esp_bt_gap_remove_bond_device(param->auth_cmpl.bda);
            }
        } else if (same(candidate, param->auth_cmpl.bda)) {
            cancel_pairing();
            snprintf(notice, sizeof(notice), "Authentication failed (0x%02x); forget SmartCon on phone, then retry", param->auth_cmpl.stat);
        }
        break;
    case ESP_BT_GAP_REMOVE_BOND_DEV_COMPLETE_EVT:
        if (param->remove_bond_dev_cmpl.status != ESP_BT_STATUS_SUCCESS)
            snprintf(notice, sizeof(notice), "Bond deletion failed; phone remains unauthorized");
        break;
    default: handled = false; break;
    }
    if (handled) snapshot();
    xSemaphoreGive(mutex);
    return handled;
}

bool phone_manager_hfp(const uint8_t *address, int state)
{
    if (!mutex) return false;
    xSemaphoreTake(mutex, portMAX_DELAY);
    bool ok = allowed(address);
    if (pending_profile == 1 && same(address, attempt_address) && state != ESP_HF_CLIENT_CONNECTION_STATE_CONNECTING)
        pending_profile = 0;
    if (state == ESP_HF_CLIENT_CONNECTION_STATE_DISCONNECTED) {
        if (same(address, hfp_address)) {
            hfp_busy = hfp_up = voice_link = false;
            call_active = call_setup = 0;
            audio_serial_mic_rate(0);
        }
        retry_at = esp_timer_get_time() + 10000000;
    } else {
        memcpy(hfp_address, address, 6);
        hfp_state = state;
        hfp_busy = true;
        hfp_up = ok && state == ESP_HF_CLIENT_CONNECTION_STATE_SLC_CONNECTED;
        if (hfp_up) retry_at = esp_timer_get_time() + 3000000;
        if (!ok && !provisional(address))
            esp_hf_client_disconnect((uint8_t *)address);
    }
    if (hfp_up && a2dp_up) snprintf(notice, sizeof(notice), "Calls and media connected");
    snapshot();
    xSemaphoreGive(mutex);
    return ok;
}
bool phone_manager_a2dp(const uint8_t *address, int state, uint16_t handle)
{
    if (!mutex) return false;
    xSemaphoreTake(mutex, portMAX_DELAY);
    bool ok = allowed(address);
    if (pending_profile == 2 && same(address, attempt_address) && state != ESP_A2D_CONNECTION_STATE_CONNECTING)
        pending_profile = 0;
    if (state == ESP_A2D_CONNECTION_STATE_DISCONNECTED) {
        if (same(address, a2dp_address)) a2dp_busy = a2dp_up = false;
        retry_at = esp_timer_get_time() + 10000000;
    } else {
        memcpy(a2dp_address, address, 6); media_handle = handle;
        a2dp_state = state;
        a2dp_busy = true;
        a2dp_up = ok && state == ESP_A2D_CONNECTION_STATE_CONNECTED;
        if (!ok && !provisional(address))
            esp_a2d_sink_disconnect((uint8_t *)address);
    }
    if (hfp_up && a2dp_up) snprintf(notice, sizeof(notice), "Calls and media connected");
    snapshot();
    xSemaphoreGive(mutex);
    return ok;
}
bool phone_manager_call_audio(void)
{
    return __atomic_load_n(&call_gate, __ATOMIC_ACQUIRE) != 0;
}
bool phone_manager_media_audio(uint16_t handle)
{
    return __atomic_load_n(&media_gate, __ATOMIC_ACQUIRE) == (uint32_t)handle + 1;
}
void phone_manager_profile_ready(bool media)
{
    if (!mutex) return;
    xSemaphoreTake(mutex, portMAX_DELAY);
    if (media) a2dp_ready = true; else hfp_ready = true;
    xSemaphoreGive(mutex);
}
void phone_manager_media_state(const uint8_t *address, uint16_t handle, bool playing)
{
    if (!mutex) return;
    xSemaphoreTake(mutex, portMAX_DELAY);
    if (allowed(address) && playing) {
        memcpy(a2dp_address, address, 6);
        media_handle = handle;
        a2dp_state = ESP_A2D_CONNECTION_STATE_CONNECTED;
        a2dp_up = a2dp_busy = true;
        if (pending_profile == 2 && same(address, attempt_address)) pending_profile = 0;
    }
    snapshot();
    xSemaphoreGive(mutex);
}
void phone_manager_call_state(int call, int setup)
{
    xSemaphoreTake(mutex, portMAX_DELAY);
    if (call >= 0) call_active = call;
    if (setup >= 0) call_setup = setup;
    snapshot();
    xSemaphoreGive(mutex);
}
void phone_manager_audio_state(bool connected)
{
    if (!mutex) return;
    xSemaphoreTake(mutex, portMAX_DELAY);
    voice_link = connected;
    if (!connected) audio_serial_mic_rate(0);
    snapshot();
    xSemaphoreGive(mutex);
}
static void tick(void)
{
    xSemaphoreTake(mutex, portMAX_DELAY);
    int64_t now = esp_timer_get_time();
    if (pairing_until && !pairing()) {
        disconnect_all(); cancel_pairing();
        snprintf(notice, sizeof(notice), "Pairing expired; locked");
    }
    if (pending_profile && now >= attempt_deadline) {
        if (pending_profile == 1) esp_hf_client_disconnect(attempt_address);
        else esp_a2d_sink_disconnect(attempt_address);
        pending_profile = 0;
        retry_at = now + 15000000;
    }
    if (ready && hfp_ready && a2dp_ready && !pairing_until && present(roster.selected) && now >= retry_at) {
        /* Never start the next phone until both previous profiles report disconnected. */
        bool previous = (hfp_busy && !same(hfp_address, roster.selected)) ||
                        (a2dp_busy && !same(a2dp_address, roster.selected)) ||
                        (pending_profile && !same(attempt_address, roster.selected));
        if (previous) disconnect_all();
        else if (!pending_profile) {
            /* Establish one profile at a time. Give the phone time to attach
             * its own media profile after HFP instead of racing both connects. */
            esp_err_t result = ESP_OK;
            unsigned profile = 0;
            if (!hfp_busy) {
                profile = 1;
                result = esp_hf_client_connect(roster.selected);
            } else if (hfp_up && !a2dp_busy && !voice_link && !call_active && !call_setup) {
                profile = 2;
                result = esp_a2d_sink_connect(roster.selected);
            }
            if (profile && result == ESP_OK) {
                pending_profile = profile;
                memcpy(attempt_address, roster.selected, 6);
                attempt_deadline = now + 40000000;
            }
            retry_at = now + 10000000;
        }
    }
    snapshot();
    xSemaphoreGive(mutex);
}
static void monitor(void *arg)
{
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        tick();
    }
}
void phone_manager_init(void)
{
    challenge = esp_random();
    mutex = xSemaphoreCreateMutex();
    ESP_ERROR_CHECK(mutex ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(nvs_open("smartcon", NVS_READWRITE, &storage));
    size_t size = sizeof(roster);
    esp_err_t error = nvs_get_blob(storage, "roster", &roster, &size);
    if (error != ESP_OK || size != sizeof(roster) || roster.version != 1) {
        memset(&roster, 0, sizeof(roster)); roster.version = 1;
    }
    if (find(roster.selected) < 0) memset(roster.selected, 0, 6);
    /* Legacy automatic pairings are not silently trusted after this upgrade. */
    int count = esp_bt_gap_get_bond_device_num();
    esp_bd_addr_t *bonds = count > 0 ? calloc(count, sizeof(esp_bd_addr_t)) : NULL;
    if (bonds && esp_bt_gap_get_bond_device_list(&count, bonds) == ESP_OK)
        for (int i = 0; i < count; i++) if (find(bonds[i]) < 0) esp_bt_gap_remove_bond_device(bonds[i]);
    free(bonds);
    ready = true;
    retry_at = esp_timer_get_time() + 5000000;
    visibility();
    ESP_ERROR_CHECK(xTaskCreate(monitor, "phone_policy", 6144, NULL, 4, NULL) == pdPASS ? ESP_OK : ESP_ERR_NO_MEM);
}
