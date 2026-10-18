#include "esp_a2dp_api.h"
#include "esp_log.h"
#include "audio_serial.h"
#include "bt_app_media.h"
#include "phone_manager.h"

static void register_sbc_endpoint(void);
static uint32_t received, blocked;

static void media_data(esp_a2d_conn_hdl_t handle, esp_a2d_audio_buff_t *buffer)
{
    if (!buffer) return;
    bool authorized = phone_manager_media_audio(handle);
    received++;
    if (!authorized) blocked++;
    if (received == 1 || received % 500 == 0)
        ESP_LOGI("BT_MEDIA", "SBC received=%lu blocked=%lu handle=%u", (unsigned long)received, (unsigned long)blocked, handle);
    if (authorized && buffer->data && buffer->data_len)
        audio_serial_send_sbc(buffer->data, buffer->data_len);
    esp_a2d_audio_buff_free(buffer);
}

static void media_event(esp_a2d_cb_event_t event, esp_a2d_cb_param_t *param)
{
    if (event == ESP_A2D_PROF_STATE_EVT &&
        param->a2d_prof_stat.init_state == ESP_A2D_INIT_SUCCESS) {
        /* sink_init is asynchronous. Registration requires completed init. */
        register_sbc_endpoint();
    } else if (event == ESP_A2D_SEP_REG_STATE_EVT) {
        if (param->a2d_sep_reg_stat.reg_state == ESP_A2D_SEP_REG_SUCCESS) {
            phone_manager_profile_ready(true);
            ESP_LOGI("BT_MEDIA", "A2DP SBC endpoint ready");
        } else {
            ESP_LOGE("BT_MEDIA", "A2DP endpoint registration failed: %d",
                     param->a2d_sep_reg_stat.reg_state);
        }
    } else if (event == ESP_A2D_CONNECTION_STATE_EVT) {
        phone_manager_a2dp(param->conn_stat.remote_bda, param->conn_stat.state, param->conn_stat.conn_hdl);
        ESP_LOGI("BT_MEDIA", "A2DP connection state: %d", param->conn_stat.state);
    } else if (event == ESP_A2D_AUDIO_STATE_EVT) {
        phone_manager_media_state(param->audio_stat.remote_bda, param->audio_stat.conn_hdl,
                                  param->audio_stat.state == ESP_A2D_AUDIO_STATE_STARTED);
        ESP_LOGI("BT_MEDIA", "A2DP audio state: %d", param->audio_stat.state);
    } else if (event == ESP_A2D_AUDIO_CFG_EVT) {
        ESP_LOGI("BT_MEDIA", "A2DP codec: %d", param->audio_cfg.mcc.type);
    }
}

void bt_app_media_init(void)
{
    ESP_ERROR_CHECK(esp_a2d_register_callback(media_event));
    ESP_ERROR_CHECK(esp_a2d_sink_init());
    ESP_ERROR_CHECK(esp_a2d_sink_register_audio_data_callback(media_data));
}

static void register_sbc_endpoint(void)
{
    /* SBC stays compressed across UART; the PC decodes stereo at source rate.
     * Limit bitpool to keep ample headroom at 921600 baud. */
    esp_a2d_mcc_t codec = {.type = ESP_A2D_MCT_SBC};
    codec.cie.sbc_info = (esp_a2d_cie_sbc_t) {
        .samp_freq = ESP_A2D_SBC_CIE_SF_44K | ESP_A2D_SBC_CIE_SF_48K,
        .ch_mode = ESP_A2D_SBC_CIE_CH_MODE_STEREO | ESP_A2D_SBC_CIE_CH_MODE_JOINT_STEREO,
        .block_len = ESP_A2D_SBC_CIE_BLOCK_LEN_16,
        .num_subbands = ESP_A2D_SBC_CIE_NUM_SUBBANDS_8,
        .alloc_mthd = ESP_A2D_SBC_CIE_ALLOC_MTHD_LOUDNESS,
        .min_bitpool = 2, .max_bitpool = 53,
    };
    ESP_ERROR_CHECK(esp_a2d_sink_register_stream_endpoint(0, &codec));
}
