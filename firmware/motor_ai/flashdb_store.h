#ifndef FLASHDB_STORE_H
#define FLASHDB_STORE_H

#include <Arduino.h>
#include "esp_partition.h"

// Define this macro to enable real FlashDB compilation.
// If commented out, the codebase compiles a compile-safe LittleFS circular buffer.
//#define USE_FLASHDB

struct TelemetryRecord {
    uint32_t timestamp;
    float current;
    float temp;
    float amb_temp;
    uint8_t health;
    float mean_dev;
    float peak;
    float crest;
    float v_rms;
    float v_peak;
    float v_kurt;
    float v_crest;
    uint8_t status;
} __attribute__((packed));

#ifdef USE_FLASHDB
#include <flashdb.h>

static int esp32_flash_init(void) { return 0; }
static int esp32_flash_read(long offset, uint8_t *buf, size_t size) {
    const esp_partition_t *part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "fdb_tsdb1");
    if (!part) return -1;
    esp_err_t err = esp_partition_read(part, offset, buf, size);
    return (err == ESP_OK) ? size : -1;
}
static int esp32_flash_write(long offset, const uint8_t *buf, size_t size) {
    const esp_partition_t *part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "fdb_tsdb1");
    if (!part) return -1;
    esp_err_t err = esp_partition_write(part, offset, buf, size);
    return (err == ESP_OK) ? size : -1;
}
static int esp32_flash_erase(long offset, size_t size) {
    const esp_partition_t *part = esp_partition_find_first(ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "fdb_tsdb1");
    if (!part) return -1;
    esp_err_t err = esp_partition_erase_range(part, offset, size);
    return (err == ESP_OK) ? size : -1;
}

const struct fal_flash_dev esp32_onchip_flash = {
    .name = "onchip_flash",
    .addr = 0,
    .len = 1024 * 1024,
    .blk_size = 4096,
    .ops = {
        .init = esp32_flash_init,
        .read = esp32_flash_read,
        .write = esp32_flash_write,
        .erase = esp32_flash_erase,
    }
};

const struct fal_flash_dev *fal_flash_dev_tbl[] = {
    &esp32_onchip_flash,
};

static struct fdb_tsdb tsdb_db;

static fdb_time_t get_db_time(void) {
    return (fdb_time_t)millis();
}

static bool tsdb_query_cb(fdb_tsdb_t db, fdb_blob_t blob, void *arg) {
    TelemetryRecord rec;
    if (blob->size == sizeof(TelemetryRecord)) {
        fdb_blob_read((fdb_db_t)db, blob, &rec);
        Serial.printf("SYN_DATA:%u,%.3f,%.2f,%.2f,%d,%.4f,%.4f,%.2f,%.4f,%.4f,%.2f,%.2f,%d\n",
                      rec.timestamp, rec.current, rec.temp, rec.amb_temp, rec.health,
                      rec.mean_dev, rec.peak, rec.crest,
                      rec.v_rms, rec.v_peak, rec.v_kurt, rec.v_crest, rec.status);
                      
        // Blocking handshake ACK
        unsigned long start_wait = millis();
        bool ack_received = false;
        while (millis() - start_wait < 2000) {
            if (Serial.available()) {
                char c = Serial.read();
                if (c == 'K') {
                    ack_received = true;
                    break;
                }
            }
            delay(1);
        }
        return ack_received;
    }
    return false;
}

inline bool init_flashdb_store() {
    fal_init();
    fdb_err_t err = fdb_tsdb_init(&tsdb_db, "telemetry_ts", "fdb_tsdb1", get_db_time, sizeof(TelemetryRecord), NULL);
    return (err == FDB_NO_ERR);
}

inline bool write_telemetry_to_buffer(float cur, float t, float amb, uint8_t hlth, 
                                     float m_dev, float pk, float crst, 
                                     float v_rms, float v_pk, float v_kt, float v_crst, uint8_t stat) {
    TelemetryRecord rec = {
        .timestamp = millis(), .current = cur, .temp = t, .amb_temp = amb, .health = hlth,
        .mean_dev = m_dev, .peak = pk, .crest = crst,
        .v_rms = v_rms, .v_peak = v_pk, .v_kurt = v_kt, .v_crest = v_crst, .status = stat
    };
    struct fdb_blob blob;
    fdb_blob_make(&blob, &rec, sizeof(rec));
    fdb_err_t err = fdb_tsdb_append(&tsdb_db, &blob);
    return (err == FDB_NO_ERR);
}

inline void dump_and_sync_buffer() {
    fdb_tsdb_query(&tsdb_db, 0, 0xFFFFFFFF, tsdb_query_cb, NULL);
    fdb_tsdb_clean(&tsdb_db);
}

#else
// Fallback: Using LittleFS (included in standard ESP32 Core, wear-leveled circular file)
#include <LittleFS.h>

inline bool init_flashdb_store() {
    if (!LittleFS.begin(true)) {
        return false;
    }
    return true;
}

inline bool write_telemetry_to_buffer(float cur, float t, float amb, uint8_t hlth, 
                                     float m_dev, float pk, float crst, 
                                     float v_rms, float v_pk, float v_kt, float v_crst, uint8_t stat) {
    File f = LittleFS.open("/buffer.bin", "ab");
    if (!f) return false;
    
    TelemetryRecord rec = {
        .timestamp = millis(), .current = cur, .temp = t, .amb_temp = amb, .health = hlth,
        .mean_dev = m_dev, .peak = pk, .crest = crst,
        .v_rms = v_rms, .v_peak = v_pk, .v_kurt = v_kt, .v_crest = v_crst, .status = stat
    };
    size_t written = f.write((uint8_t*)&rec, sizeof(rec));
    f.close();
    return (written == sizeof(rec));
}

inline void dump_and_sync_buffer() {
    if (!LittleFS.exists("/buffer.bin")) {
        return;
    }
    File f = LittleFS.open("/buffer.bin", "rb");
    if (!f) return;
    
    bool aborted = false;
    while (f.available() >= sizeof(TelemetryRecord)) {
        TelemetryRecord rec;
        f.read((uint8_t*)&rec, sizeof(rec));
        
        Serial.printf("SYN_DATA:%u,%.3f,%.2f,%.2f,%d,%.4f,%.4f,%.2f,%.4f,%.4f,%.2f,%.2f,%d\n",
                      rec.timestamp, rec.current, rec.temp, rec.amb_temp, rec.health,
                      rec.mean_dev, rec.peak, rec.crest,
                      rec.v_rms, rec.v_peak, rec.v_kurt, rec.v_crest, rec.status);
                      
        unsigned long start_wait = millis();
        bool ack_received = false;
        while (millis() - start_wait < 2000) {
            if (Serial.available()) {
                char c = Serial.read();
                if (c == 'K') {
                    ack_received = true;
                    break;
                }
            }
            delay(1);
        }
        if (!ack_received) {
            aborted = true;
            break;
        }
    }
    f.close();
    
    if (!aborted) {
        LittleFS.remove("/buffer.bin");
    }
}
#endif

#endif // FLASHDB_STORE_H
