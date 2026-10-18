#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_gap_bt_api.h"

/* USB commands and Bluetooth callbacks share one locked policy state. */
void phone_manager_init(void);
void phone_manager_command(const uint8_t *data, unsigned size);
bool phone_manager_gap(esp_bt_gap_cb_event_t event, esp_bt_gap_cb_param_t *param);
bool phone_manager_hfp(const uint8_t *address, int state);
bool phone_manager_a2dp(const uint8_t *address, int state, uint16_t handle);
bool phone_manager_call_audio(void);
bool phone_manager_media_audio(uint16_t handle);
void phone_manager_call_state(int call, int setup);
void phone_manager_audio_state(bool connected);
bool phone_manager_pairing_approved(const uint8_t *address);
void phone_manager_profile_ready(bool media);
void phone_manager_media_state(const uint8_t *address, uint16_t handle, bool playing);
