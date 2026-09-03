#ifndef SAFETY_INTERLOCK_H
#define SAFETY_INTERLOCK_H

#include "config.h"
#include <Arduino.h>

// --- LEAKY BUCKET ACCUMULATOR CONTROL ---
int overload_accumulator = 0;

void updateSafetyTrip(float current_val, unsigned long now) {
    if (is_tripped) {
        digitalWrite(PIN_TRIP, HIGH); // Keep safety relay open
        health_status = 2;            // Tripped status code
        return;
    }

    // Accumulator-based overload detection: Current > 1.25x Rated FLA
    if (current_val > (rated_current * OVERLOAD_FACTOR)) {
        overload_accumulator++;
        if (overload_accumulator >= OVERLOAD_ACCUMULATOR_TRIP) {
            is_tripped = true;
            digitalWrite(PIN_TRIP, HIGH); // Break safety circuit (energize relay to trip)
            health_status = 2;
            Serial.println("SYS_MSG: EMERGENCY_TRIP");
        } else {
            is_overloaded = true;
            Serial.println("SYS_MSG: OVERLOAD_WARNING");
        }
    } else {
        // Leaky bucket release
        if (overload_accumulator > 0) {
            overload_accumulator--;
        }
        is_overloaded = (overload_accumulator > 0);
        
        if (!is_overloaded) {
            health_status = 0; // Operational / Healthy state
        }
    }
}

void resetSafetyTrip() {
    is_tripped = false;
    is_overloaded = false;
    overload_accumulator = 0;
    digitalWrite(PIN_TRIP, LOW); // Close safety relay
    health_status = 0;
    Serial.println("SYS_MSG: Emergency Trip Reset.");
}

#endif // SAFETY_INTERLOCK_H
