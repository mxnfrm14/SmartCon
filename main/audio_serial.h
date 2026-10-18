#pragma once
#include <stdint.h>
#include <stdbool.h>
bool audio_serial_init(void);
void audio_serial_send(const uint8_t *data, uint32_t size, uint16_t rate);
void audio_serial_send_sbc(const uint8_t *data, uint32_t size);
void audio_serial_control(const uint8_t *data, uint32_t size);
void audio_serial_clear(void);

void audio_serial_mic_rate(uint16_t rate);
uint32_t audio_serial_mic_read(uint8_t *data, uint32_t size);
