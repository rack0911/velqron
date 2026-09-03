#ifndef CONFIG_H
#define CONFIG_H

#include <Arduino.h>

// --- PIN CONFIGURATION ---
const int PIN_CT = 34;       
const int PIN_TEMP = 4;      
const int PIN_TRIP = 23;         // GPIO 23 to drive Siemens SIRIUS contactor safety relay

// --- SENSOR PARAMETERS ---
const float CT_RATIO = 30.0f;    // 30A/1V for SCT-013-030

// --- SAFETY INTERLOCK PARAMETERS ---
const int OVERLOAD_ACCUMULATOR_TRIP = 3;  // Trip after 3 consecutive/intermittent overload ticks
const float OVERLOAD_FACTOR = 1.25f;      // Overload triggers above 1.25x Rated Limit (FLA)

// --- GLOBAL VARIABLES (Declared extern for shared module access) ---
extern float current;
extern float temp;
extern float ambient_temp;
extern float system_bias;
extern uint8_t health_status;

extern float rated_current;
extern float calibration_scalar;
extern bool is_overloaded;
extern bool is_tripped;

#endif // CONFIG_H
