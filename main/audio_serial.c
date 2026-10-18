#include <stdio.h>
#include <stddef.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "driver/uart.h"
#include "esp_timer.h"
#include "audio_serial.h"
#include "phone_manager.h"

/* Little endian: magic[8], size:u16, rate:u16, sequence:u32,
 * FNV-1a(header fields + PCM):u32, PCM signed 16-bit mono. */
typedef struct {
    uint8_t magic[8];
    uint16_t size;
    uint16_t rate;
    uint32_t sequence;
    uint32_t checksum;
    uint8_t pcm[1024];
} packet_t;
_Static_assert(offsetof(packet_t, pcm) == 20, "Unexpected serial header layout");
static QueueHandle_t queue;
static QueueHandle_t control_queue;
static uint32_t sequence;
static portMUX_TYPE mic_lock = portMUX_INITIALIZER_UNLOCKED;
static uint8_t mic[6400]; /* at most 200 ms at 16 kHz */
static size_t mic_count;
static uint16_t mic_rate;
static int64_t mic_updated;

void audio_serial_mic_rate(uint16_t rate)
{
    portENTER_CRITICAL(&mic_lock);
    mic_rate = rate;
    mic_count = 0;
    portEXIT_CRITICAL(&mic_lock);
}

uint32_t audio_serial_mic_read(uint8_t *data, uint32_t size)
{
    memset(data, 0, size);
    portENTER_CRITICAL(&mic_lock);
    if (esp_timer_get_time() - mic_updated > 200000) mic_count = 0;
    size_t n = size < mic_count ? size : mic_count;
    memcpy(data, mic, n);
    memmove(mic, mic + n, mic_count - n);
    mic_count -= n;
    portEXIT_CRITICAL(&mic_lock);
    return size;
}

static void receiver(void *arg)
{
    uint8_t buffer[sizeof(packet_t)];
    size_t used = 0;
    while (true) {
        int n = uart_read_bytes(UART_NUM_0, buffer + used, sizeof(buffer) - used, pdMS_TO_TICKS(20));
        if (n <= 0) continue;
        used += n;
        while (used >= 8) {
            bool control = !memcmp(buffer, "PBCTL01!", 8);
            if (!control && memcmp(buffer, "PBMIC01!", 8)) goto discard;
            if (used < 20) break;
            packet_t packet;
            memcpy(&packet, buffer, 20);
            if (!packet.size || packet.size > 1024 || (control ? packet.rate != 0 :
                (packet.size % 2 || (packet.rate != 8000 && packet.rate != 16000)))) goto discard;
            if (used < 20 + packet.size) break;
            uint32_t hash = 2166136261u;
            for (int i = 8; i < 16; ++i) hash = (hash ^ buffer[i]) * 16777619u;
            for (int i = 20; i < 20 + packet.size; ++i) hash = (hash ^ buffer[i]) * 16777619u;
            if (hash != packet.checksum) goto discard;
            if (control) {
                phone_manager_command(buffer + 20, packet.size);
                goto consumed;
            }
            portENTER_CRITICAL(&mic_lock);
            if (packet.rate == mic_rate) {
                size_t limit = mic_rate / 5 * 2;
                if (mic_count + packet.size > limit) {
                    size_t drop = mic_count + packet.size - limit;
                    memmove(mic, mic + drop, mic_count - drop);
                    mic_count -= drop;
                }
                memcpy(mic + mic_count, buffer + 20, packet.size);
                mic_count += packet.size;
                mic_updated = esp_timer_get_time();
            }
            portEXIT_CRITICAL(&mic_lock);
        consumed:;
            size_t consumed = 20 + packet.size;
            memmove(buffer, buffer + consumed, used - consumed);
            used -= consumed;
            continue;
        discard:
            memmove(buffer, buffer + 1, --used);
        }
    }
}

static void sender(void *arg)
{
    packet_t packet;
    while (true) {
        if (xQueueReceive(control_queue, &packet, 0) || xQueueReceive(queue, &packet, pdMS_TO_TICKS(20))) {
            portENTER_CRITICAL(&mic_lock);
            bool skip = !memcmp(packet.magic, "PBSBC01!", 8) && mic_rate != 0;
            portEXIT_CRITICAL(&mic_lock);
            if (skip) continue;
            /* Share stdout's lock with printf/logs, bypassing text LF conversion. */
            flockfile(stdout);
            fflush(stdout);
            uart_write_bytes(UART_NUM_0, &packet, 20 + packet.size);
            funlockfile(stdout);
        }
    }
}

bool audio_serial_init(void)
{
    if (queue) return true;
    queue = xQueueCreate(24, sizeof(packet_t));
    if (!queue) return false;
    control_queue = xQueueCreate(1, sizeof(packet_t));
    if (!control_queue) return false;
    if (xTaskCreate(sender, "audio_serial", 4096, NULL, 5, NULL) != pdPASS) {
        vQueueDelete(queue);
        queue = NULL;
        return false;
    }
    if (xTaskCreate(receiver, "mic_serial", 8192, NULL, 5, NULL) != pdPASS) return false;
    return true;
}

void audio_serial_clear(void)
{
    if (queue) xQueueReset(queue);
}

void audio_serial_control(const uint8_t *data, uint32_t size)
{
    if (!control_queue || !size || size > 1024) return;
    packet_t packet = {.magic = {'P','B','C','T','L','0','1','!'}, .size = size};
    memcpy(packet.pcm, data, size);
    uint32_t hash = 2166136261u;
    const uint8_t *fields = (const uint8_t *)&packet.size;
    for (int i = 0; i < 8; ++i) hash = (hash ^ fields[i]) * 16777619u;
    for (unsigned i = 0; i < size; ++i) hash = (hash ^ data[i]) * 16777619u;
    packet.checksum = hash;
    xQueueOverwrite(control_queue, &packet);
}

void audio_serial_send(const uint8_t *data, uint32_t size, uint16_t rate)
{
    if (!queue || size > 1024 || size == 0 || size % 2) return;
    uint32_t seq = __atomic_fetch_add(&sequence, 1, __ATOMIC_RELAXED);
    packet_t packet = {.magic = {'P','B','A','U','D','0','1','!'},
                       .size = size, .rate = rate, .sequence = seq};
    memcpy(packet.pcm, data, size);
    uint32_t hash = 2166136261u;
    const uint8_t *fields = (const uint8_t *)&packet.size;
    for (int i = 0; i < 8; ++i) hash = (hash ^ fields[i]) * 16777619u;
    for (uint32_t i = 0; i < size; ++i) hash = (hash ^ data[i]) * 16777619u;
    packet.checksum = hash;
    /* Never block the Bluetooth callback. Sequence gaps expose queue drops. */
    xQueueSend(queue, &packet, 0);
}

void audio_serial_send_sbc(const uint8_t *data, uint32_t size)
{
    while (queue && size) {
        uint16_t n = size > 1024 ? 1024 : size;
        packet_t packet = {.magic = {'P','B','S','B','C','0','1','!'},
                           .size = n, .rate = 0};
        portENTER_CRITICAL(&mic_lock);
        bool call = mic_rate != 0;
        portEXIT_CRITICAL(&mic_lock);
        if (call) return;
        packet.sequence = __atomic_fetch_add(&sequence, 1, __ATOMIC_RELAXED);
        memcpy(packet.pcm, data, n);
        uint32_t hash = 2166136261u;
        const uint8_t *fields = (const uint8_t *)&packet.size;
        for (int i = 0; i < 8; ++i) hash = (hash ^ fields[i]) * 16777619u;
        for (int i = 0; i < n; ++i) hash = (hash ^ data[i]) * 16777619u;
        packet.checksum = hash;
        xQueueSend(queue, &packet, 0);
        data += n;
        size -= n;
    }
}
