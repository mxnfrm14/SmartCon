/* ESP-IDF 6.1 Classic Bluetooth security adapter.
 * The public GAP API exposes IO capability but not Classic authentication
 * requirements. HFP/A2DP otherwise request authentication without MITM, and
 * btc_dm_sp_cfm_req_evt silently accepts Just Works without an app callback.
 * Linker wrappers keep the SDK unchanged and make both decisions explicit.
 */
#include <stdbool.h>
#include <stdint.h>
#include "esp_idf_version.h"
#include "esp_log.h"
#include "phone_manager.h"
#include "pairing_security.h"

#if ESP_IDF_VERSION_MAJOR != 6 || ESP_IDF_VERSION_MINOR != 1
#error "Review the Classic pairing adapter against this ESP-IDF version before building"
#endif

void pairing_security_init(void)
{
    esp_bt_io_cap_t capability = ESP_BT_IO_CAP_IO;
    ESP_ERROR_CHECK(esp_bt_gap_set_security_param(ESP_BT_SP_IOCAP_MODE, &capability, sizeof(capability)));
}

/* IDF 6.1 ABI: BD_ADDR=uint8_t[6], IO_CAP/OOB/AUTH_REQ=uint8_t, BOOLEAN=bool. */
extern void __real_bta_dm_co_io_req(uint8_t *address, uint8_t *io,
                                  uint8_t *oob, uint8_t *auth, bool originator);
void __wrap_bta_dm_co_io_req(uint8_t *address, uint8_t *io,
                            uint8_t *oob, uint8_t *auth, bool originator)
{
    __real_bta_dm_co_io_req(address, io, oob, auth, originator);
    *io = 1;       /* DisplayYesNo: the USB app displays and approves the number. */
    *auth |= 1;    /* BTM_AUTH_YN_BIT: require MITM, preserving bonding bits. */
    ESP_LOGI("PAIRING", "Request numeric comparison (auth=0x%02x)", *auth);
}

extern void __real_BTA_DmConfirm(uint8_t *address, bool accept);
void __wrap_BTA_DmConfirm(uint8_t *address, bool accept)
{
    /* Also intercept the SDK's automatic Just Works confirmation. */
    if (accept && !phone_manager_pairing_approved(address)) {
        ESP_LOGW("PAIRING", "Reject automatic or expired pairing confirmation");
        accept = false;
    }
    __real_BTA_DmConfirm(address, accept);
}
