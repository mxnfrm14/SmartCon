/*
 * SPDX-FileCopyrightText: 2021-2026 Espressif Systems (Shanghai) CO LTD
 *
 * SPDX-License-Identifier: Unlicense OR CC0-1.0
 */

#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <inttypes.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "esp_system.h"
#include "esp_log.h"
#include "esp_bt.h"
#include "bt_app_core.h"
#include "esp_bt_main.h"
#include "esp_bt_device.h"
#include "esp_gap_bt_api.h"
#include "esp_hf_client_api.h"
#include "esp_pbac_api.h"
#include "bt_app_hf.h"
#include "gpio_pcm_config.h"
#if CONFIG_EXAMPLE_ENABLE_CONSOLE_REPL
#include "esp_console.h"
#endif
#include "app_hf_msg_set.h"
#include "bt_app_pbac.h"
#include "audio_serial.h"
#include "bt_app_media.h"
#include "phone_manager.h"
#include "pairing_security.h"
#if !CONFIG_EXAMPLE_SSP_ENABLED
#error "SmartCon phone approval requires Secure Simple Pairing"
#endif
#include "driver/uart.h"


esp_bd_addr_t peer_addr = {0};
bool hf_client_connected = false;
static char *bda2str(esp_bd_addr_t bda, char *str, size_t size)
{
    if (bda == NULL || str == NULL || size < 18) {
        return NULL;
    }

    uint8_t *p = bda;
    sprintf(str, "%02x:%02x:%02x:%02x:%02x:%02x",
            p[0], p[1], p[2], p[3], p[4], p[5]);
    return str;
}

void esp_bt_gap_cb(esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t *param)
{
    phone_manager_gap(event, param);
}

/* event for handler "bt_av_hdl_stack_up */
enum {
    BT_APP_EVT_STACK_UP = 0,
};

/* handler for bluetooth stack enabled events */
static void bt_hf_client_hdl_stack_evt(uint16_t event, void *p_param);

void app_main(void)
{
    char bda_str[18] = {0};
    /* Initialize NVS — it is used to store PHY calibration data */
    esp_err_t ret = nvs_flash_init();
    if (ret == ESP_ERR_NVS_NO_FREE_PAGES) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ret = nvs_flash_init();
    }
    ESP_ERROR_CHECK( ret );

    ESP_ERROR_CHECK(esp_bt_controller_mem_release(ESP_BT_MODE_BLE));

    esp_bt_controller_config_t bt_cfg = BT_CONTROLLER_INIT_CONFIG_DEFAULT();
    if ((ret = esp_bt_controller_init(&bt_cfg)) != ESP_OK) {
        ESP_LOGE(BT_HF_TAG, "%s initialize controller failed: %s", __func__, esp_err_to_name(ret));
        return;
    }

    if ((ret = esp_bt_controller_enable(ESP_BT_MODE_CLASSIC_BT)) != ESP_OK) {
        ESP_LOGE(BT_HF_TAG, "%s enable controller failed: %s", __func__, esp_err_to_name(ret));
        return;
    }

    esp_bluedroid_config_t bluedroid_cfg = BT_BLUEDROID_INIT_CONFIG_DEFAULT();
#if (CONFIG_EXAMPLE_SSP_ENABLED == false)
    bluedroid_cfg.ssp_en = false;
#endif
    if ((ret = esp_bluedroid_init_with_cfg(&bluedroid_cfg)) != ESP_OK) {
        ESP_LOGE(BT_HF_TAG, "%s initialize bluedroid failed: %s", __func__, esp_err_to_name(ret));
        return;
    }

    if ((ret = esp_bluedroid_enable()) != ESP_OK) {
        ESP_LOGE(BT_HF_TAG, "%s enable bluedroid failed: %s", __func__, esp_err_to_name(ret));
        return;
    }

    ESP_LOGI(BT_HF_TAG, "Own address:[%s]", bda2str((uint8_t *)esp_bt_dev_get_address(), bda_str, sizeof(bda_str)));
    /* create application task */
    bt_app_task_start_up();

#if CONFIG_EXAMPLE_HFP_PCM_GPIO_SUPPORTED && CONFIG_BT_HFP_AUDIO_DATA_PATH_PCM
    /* configure the PCM interface and PINs used */
    app_gpio_pcm_io_cfg();
#elif CONFIG_BT_HFP_AUDIO_DATA_PATH_PCM
    ESP_LOGW(BT_HF_TAG, "PCM GPIO is not supported on this chip; use HCI SCO data path");
#endif

    /* configure external chip for acoustic echo cancellation */
#if ACOUSTIC_ECHO_CANCELLATION_ENABLE
    app_gpio_aec_io_cfg();
#endif /* ACOUSTIC_ECHO_CANCELLATION_ENABLE */
    /* Binary full-duplex transport owns UART0, including its RX path. */
    fflush(stdout);
    const uart_config_t audio_uart_config = {
        .baud_rate = CONFIG_ESP_CONSOLE_UART_BAUDRATE,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_APB,
    };
    ESP_ERROR_CHECK(uart_driver_install(UART_NUM_0, 8192, 0, 0, NULL, 0));
    ESP_ERROR_CHECK(uart_param_config(UART_NUM_0, &audio_uart_config));
    ESP_ERROR_CHECK(audio_serial_init() ? ESP_OK : ESP_ERR_NO_MEM);

    /* Accept connections only once the full-duplex audio transport is ready. */
    bt_app_work_dispatch(bt_hf_client_hdl_stack_evt, BT_APP_EVT_STACK_UP, NULL, 0, NULL, NULL);

}


static void bt_hf_client_hdl_stack_evt(uint16_t event, void *p_param)
{
    ESP_LOGD(BT_HF_TAG, "%s evt %d", __func__, event);
    switch (event) {
    case BT_APP_EVT_STACK_UP: {
        /* set up device name */
        char *dev_name = "SmartCon";
        esp_bt_gap_set_device_name(dev_name);

        pairing_security_init();
        phone_manager_init();

        /* register GAP callback function */
        esp_bt_gap_register_callback(esp_bt_gap_cb);
        esp_hf_client_register_callback(bt_app_hf_client_cb);
        esp_hf_client_init();
        bt_app_media_init();
        esp_pbac_register_callback(bt_app_pbac_cb);
        esp_pbac_init();

        ESP_LOGI(BT_HF_TAG, "SmartCon ready; pairing locked, use the Windows app to approve a phone");
        break;
    }
    default:
        ESP_LOGE(BT_HF_TAG, "%s unhandled evt %d", __func__, event);
        break;
    }
}
