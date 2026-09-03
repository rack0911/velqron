#ifndef ADC_FRONTEND_H
#define ADC_FRONTEND_H

#include "config.h"
#include <Arduino.h>

// --- Bias AUTO-ZEROING BIAS ENGINE ---
float performAutoCalibration(int samples, float &noise_floor_out) {
    float sum_v = 0;
    float sum_sq_v = 0;
    for(int i=0; i<samples; i++) {
        int raw = analogRead(PIN_CT);
        float voltage = (raw / 4095.0f) * 3.3f;
        sum_v += voltage;
        sum_sq_v += voltage * voltage;
        delayMicroseconds(500);
    }
    float bias = sum_v / (float)samples;
    float mean_sq = sum_sq_v / (float)samples;
    noise_floor_out = sqrt(abs(mean_sq - (bias * bias)));
    return bias;
}

extern float noise_floor;

// --- HARDENING: DYNAMIC HARDWARE SCALING ---
extern int system_samples;
extern float* wave_buffer;
extern const int MAX_WAVE_SAMPLES;

// --- HIGH-PRECISION RMS & FEATURE PREPROCESSING ---
float readCurrentRMSAndStats(float &mean_deviation, float &peak_centered, float &crest_factor) {
    float sum_sq_v = 0;
    float sum_v = 0;
    float max_centered = 0;

    // --- HARDENING: ZERO-CROSSING SYNC ---
    // Wait for a negative-to-positive transition to phase-lock the window
    float prev_centered = (analogRead(PIN_CT) / 4095.0f * 3.3f) - system_bias;
    unsigned long sync_start = millis();
    while (millis() - sync_start < 20) { // Max 1 cycle @ 50Hz
        float current_v = (analogRead(PIN_CT) / 4095.0f * 3.3f) - system_bias;
        if (prev_centered < 0 && current_v >= 0) break; 
        prev_centered = current_v;
    }

    for(int i=0; i<system_samples; i++) {
        int raw = analogRead(PIN_CT);
        float voltage = (raw / 4095.0f) * 3.3f;
        float centered = voltage - system_bias;
        
        sum_v += centered;
        sum_sq_v += centered * centered;
        
        // Store in PSRAM if available (For high-fidelity MCSA)
        if (wave_buffer != nullptr && i < MAX_WAVE_SAMPLES) {
            wave_buffer[i] = centered;
        }

        float abs_centered = abs(centered);
        if (abs_centered > max_centered) {
            max_centered = abs_centered;
        }
        delayMicroseconds(200);
    }
    
    float rms_voltage = sqrt(sum_sq_v / (float)system_samples);
    float mean_centered_v = sum_v / (float)system_samples;
    
    // Noise Gate: Hardening: Use dynamic noise floor (1.5x multiplier)
    if (rms_voltage < (noise_floor * 1.5f)) {
        rms_voltage = 0.0f;
        mean_centered_v = 0.0f;
        max_centered = 0.0f;
    }
    
    // Assign calculated statistics to output references
    mean_deviation = mean_centered_v;
    peak_centered = max_centered;
    crest_factor = rms_voltage > 0.001f ? (max_centered / rms_voltage) : 0.0f;
    
    return (CT_RATIO * rms_voltage) * calibration_scalar;
}

#endif // ADC_FRONTEND_H
