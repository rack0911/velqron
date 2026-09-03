#ifndef VIBRATION_FRONTEND_H
#define VIBRATION_FRONTEND_H

#include <Arduino.h>
#include <Wire.h>
#include "ring_buffer.h"

#define ADXL345_ADDR 0x53
#define ADXL_DATA_FORMAT 0x31
#define ADXL_POWER_CTL 0x2D
#define ADXL_DATAX0 0x32

extern SemaphoreHandle_t i2c_mutex;
extern RingBuffer<float, 2048> vibration_ring_buffer;

/**
 * Non-blocking I2C driver for ADXL345 Accelerometer.
 * Extracts "The Industrial Four" features from Thread-Safe Ring Buffer.
 */
class VibrationFrontend {
private:
    float _last_rms = 0;
    float _last_peak = 0;
    float _last_kurtosis = 0;

    void writeReg(uint8_t reg, uint8_t val) {
        if (xSemaphoreTake(i2c_mutex, pdMS_TO_TICKS(10)) == pdTRUE) {
            Wire.beginTransmission(ADXL345_ADDR);
            Wire.write(reg);
            Wire.write(val);
            Wire.endTransmission();
            xSemaphoreGive(i2c_mutex);
        }
    }

public:
    bool begin() {
        bool success = false;
        if (xSemaphoreTake(i2c_mutex, pdMS_TO_TICKS(50)) == pdTRUE) {
            Wire.begin();
            // Check for device ID
            Wire.beginTransmission(ADXL345_ADDR);
            Wire.write(0x00);
            if (Wire.endTransmission() == 0) {
                success = true;
            }
            xSemaphoreGive(i2c_mutex);
        }
        
        if (success) {
            writeReg(ADXL_DATA_FORMAT, 0x01); // +/- 4g range
            writeReg(ADXL_POWER_CTL, 0x08);   // Measure mode
            return true;
        }
        return false;
    }

    float readSingleSample() {
        float val = 0.0f;
        if (xSemaphoreTake(i2c_mutex, pdMS_TO_TICKS(2)) == pdTRUE) {
            Wire.beginTransmission(ADXL345_ADDR);
            Wire.write(ADXL_DATAX0);
            Wire.endTransmission(false);
            Wire.requestFrom(ADXL345_ADDR, 6);
            
            if (Wire.available() >= 6) {
                int16_t x = Wire.read() | (Wire.read() << 8);
                int16_t y = Wire.read() | (Wire.read() << 8);
                int16_t z = Wire.read() | (Wire.read() << 8);
                
                // Magnitude in g (0.0078g/LSB at +/-4g)
                float mag = sqrt(x*x + y*y + z*z) * 0.0078f;
                // Remove 1g gravity offset
                val = abs(mag - 1.0f);
            }
            xSemaphoreGive(i2c_mutex);
        }
        return val;
    }

    void sampleStats(int samples, float &rms, float &peak, float &kurtosis, float &crest) {
        float sum_sq = 0;
        float max_v = 0;
        float sum_q = 0;
        int count = 0;
        
        float val;
        // Pop available samples up to target limit from the RingBuffer
        while (count < samples && vibration_ring_buffer.pop(val)) {
            sum_sq += val * val;
            sum_q += val * val * val * val;
            if (val > max_v) max_v = val;
            count++;
        }
        
        if (count > 0) {
            rms = sqrt(sum_sq / count);
            peak = max_v;
            crest = rms > 0.001f ? (peak / rms) : 0.0f;
            
            float mean_sq = sum_sq / count;
            kurtosis = (sum_q / count) / (mean_sq * mean_sq + 0.0001f);
        } else {
            // Safe fallbacks if buffer is empty
            rms = 0.0f;
            peak = 0.0f;
            crest = 0.0f;
            kurtosis = 1.0f;
        }
    }
};

extern VibrationFrontend vibration;

#endif // VIBRATION_FRONTEND_H
