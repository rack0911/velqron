/* motor_ai.ino (ver 59.0 - Modularized Edge-AI Node)
   
   Architecture:
   1. config.h (System assignments, settings, externs)
   2. adc_frontend.h (Zero-Bias Auto Calibration, True RMS Current, and preprocessed wave stats)
   3. safety_interlock.h (Leaky Bucket safety integrator & contactor trip relay control)
*/

#include <OneWire.h>
#include <DallasTemperature.h>
#include <Preferences.h>
#include "esp_adc_cal.h"
#include "esp_task_wdt.h"

#include "config.h"
#include "adc_frontend.h"
#include "safety_interlock.h"
#include "security.h"
#include "binary_packet.h"
#include "vibration_frontend.h"
#include "flashdb_store.h"

// --- Define Global Variables ---
#include <esp_arduino_version.h>

SemaphoreHandle_t i2c_mutex;
SemaphoreHandle_t sensor_timer_sem;
hw_timer_t* timer = NULL;
RingBuffer<float, 2048> vibration_ring_buffer;

void IRAM_ATTR onTimer() {
  BaseType_t xHigherPriorityTaskWoken = pdFALSE;
  xSemaphoreGiveFromISR(sensor_timer_sem, &xHigherPriorityTaskWoken);
  if (xHigherPriorityTaskWoken) {
    portYIELD_FROM_ISR();
  }
}

bool is_offline = false;
unsigned long last_heartbeat_ts = 0;
bool fdb_active = false;

float current = 0.0f;
float temp = 27.5f;
float ambient_temp = 25.0f;
float system_bias = 1.65f;
float noise_floor = 0.008f;
uint8_t health_status = 0x00;

float rated_current = 1.5f;
float calibration_scalar = 1.0f;
bool is_overloaded = false;
bool is_tripped = false;

// Statistics variables
float mean_deviation = 0.0f;
float peak_centered = 0.0f;
float crest_factor = 0.0f;

// Dynamic Hardware Scaling
int system_samples = 500;
float* wave_buffer = nullptr;
const int MAX_WAVE_SAMPLES = 5000;

// Vibration variables
float vib_rms = 0.0f;
float vib_peak = 0.0f;
float vib_kurtosis = 0.0f;
float vib_crest = 0.0f;

// --- Initialize sensors ---
OneWire oneWire(PIN_TEMP);
DallasTemperature sensors(&oneWire);
Preferences preferences;

esp_adc_cal_characteristics_t adc_chars;
VibrationFrontend vibration;

// Task declarations
void SensorTask(void *pvParameters);
void TelemetryTask(void *pvParameters);

void setup() {
  Serial.begin(115200);
  
  // 0. Initialize I2C Mutex and Timer Semaphore
  i2c_mutex = xSemaphoreCreateMutex();
  sensor_timer_sem = xSemaphoreCreateBinary();
  
  pinMode(PIN_CT, INPUT);
  pinMode(PIN_TRIP, OUTPUT);
  digitalWrite(PIN_TRIP, LOW); // Close contactor loop (normally operational)
  
  // 1. Initialize ADC Calibration parameters on ESP32
  analogSetPinAttenuation(PIN_CT, ADC_11db);
  analogReadResolution(12);
  esp_adc_cal_characterize(ADC_UNIT_1, ADC_ATTEN_DB_11, ADC_WIDTH_BIT_12, 1100, &adc_chars);

  // 2. Temp Sensors Setup
  sensors.begin();
  sensors.setWaitForConversion(false); 
  
  // 3. Vibration Setup
  if (vibration.begin()) {
    Serial.println("SYS_MSG: Vibration_Sensor_Found");
  } else {
    Serial.println("SYS_MSG: Vibration_Sensor_Not_Found");
  }

  // 4. Hardware-Adaptive Scaling (S3 Terminal Detection)
  if (psramFound()) {
    system_samples = 2000; // High-fidelity for S3
    wave_buffer = (float*)ps_malloc(MAX_WAVE_SAMPLES * sizeof(float));
    if (wave_buffer != nullptr) {
      Serial.println("SYS_MSG: PSRAM_Fidelity_Unlocked_2000Hz");
    }
  } else {
    system_samples = 500;  // Standard for basic ESP32
    Serial.println("SYS_MSG: Standard_Fidelity_Active_500Hz");
  }
  
  // 3. Load preferences
  preferences.begin("velqron", false);
  if (!preferences.isKey("bias")) {
    Serial.print("SYS_MSG: Calibrating_Zero...");
    system_bias = performAutoCalibration(2000, noise_floor);
    preferences.putFloat("bias", system_bias);
    preferences.putFloat("noise", noise_floor);
    Serial.println(" Done.");
  } else {
    system_bias = preferences.getFloat("bias", 1.65f);
    noise_floor = preferences.getFloat("noise", 0.008f);
    Serial.printf("SYS_MSG: Loaded saved Bias: %.4f, Noise: %.4f\n", system_bias, noise_floor);
  }
  
  calibration_scalar = preferences.getFloat("scalar", 1.0f);
  rated_current = preferences.getFloat("rated_current", 1.5f);
  preferences.end();
  
  // Watchdog setup
  esp_task_wdt_config_t wdt_config = {
      .timeout_ms = 10000,
      .idle_core_mask = 0,
      .trigger_panic = true
  };
  esp_task_wdt_init(&wdt_config); 
  esp_task_wdt_add(NULL);
  
  if (init_flashdb_store()) {
    fdb_active = true;
    Serial.println("SYS_MSG: Local_Buffer_Initialized");
  } else {
    Serial.println("SYS_MSG: Local_Buffer_Failed");
  }
  last_heartbeat_ts = millis();

  // Initialize hardware timer (2000Hz -> 500us interval)
  #if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3, 0, 0)
    timer = timerBegin(1000000); // 1MHz clock
    timerAttachInterrupt(timer, &onTimer);
    timerAlarm(timer, 500, true, 0); // 500us, auto-reload
  #else
    timer = timerBegin(0, 80, true); // timer 0, prescaler 80, count up
    timerAttachInterrupt(timer, &onTimer, true);
    timerAlarmWrite(timer, 500, true); // 500us, auto-reload
    timerAlarmEnable(timer);
  #endif

  // 5. Spin up FreeRTOS tasks pinned to opposite cores
  xTaskCreatePinnedToCore(SensorTask, "SensorTask", 4096, NULL, 5, NULL, 0);
  xTaskCreatePinnedToCore(TelemetryTask, "TelemetryTask", 8192, NULL, 1, NULL, 1);

  Serial.println("STATUS: PRODUCTION_READY");
}

void loop() {
  // Feed watchdog and yield main task
  delay(1000);
}

void SensorTask(void *pvParameters) {
  (void) pvParameters;
  for (;;) {
    // Block indefinitely until timer semaphore is released (at 2000Hz)
    if (xSemaphoreTake(sensor_timer_sem, portMAX_DELAY) == pdTRUE) {
      float v_sample = vibration.readSingleSample();
      vibration_ring_buffer.push(v_sample);
    }
  }
}

void TelemetryTask(void *pvParameters) {
  (void) pvParameters;
  unsigned long last_data_ts = 0;
  
  for (;;) {
    unsigned long now = millis();

    // 1Hz Execution Tick
    if (now - last_data_ts > 1000) {
      // A. Temperature Readings (Stator casing and Ambient)
      sensors.requestTemperatures();
      float t_read = sensors.getTempCByIndex(0);
      if (t_read > -50 && t_read < 150) temp = t_read; 
      
      float t_amb_read = sensors.getTempCByIndex(1);
      if (t_amb_read > -50 && t_amb_read < 150) ambient_temp = t_amb_read;

      // B. RMS Current Calculation & Statistics Preprocessing
      current = readCurrentRMSAndStats(mean_deviation, peak_centered, crest_factor);

      // C. Non-blocking Vibration features extracted from RingBuffer
      vibration.sampleStats(100, vib_rms, vib_peak, vib_kurtosis, vib_crest);

      // Read and report buffer watermark and overrun diagnostics
      size_t max_occ = vibration_ring_buffer.getMaxOccupancy();
      size_t overruns = vibration_ring_buffer.getOverrunCount();
      vibration_ring_buffer.resetMetrics();

      if (overruns > 0) {
        health_status |= (1 << 4); // Bit 4 set indicates buffer overrun
        Serial.printf("SYS_MSG: Diagnostics: MaxOccupancy=%d, OVERRUNS_DETECTED=%d\n", max_occ, overruns);
      } else {
        health_status &= ~(1 << 4); // Clear overrun warning bit
        Serial.printf("SYS_MSG: Diagnostics: MaxOccupancy=%d, Overruns=0\n", max_occ);
      }

      // D. Safety Interlock Trip Monitoring
      updateSafetyTrip(current, now);

      // Outage check: if no heartbeat received for 10s, toggle offline mode
      if (!is_offline && (now - last_heartbeat_ts > 10000)) {
        is_offline = true;
        Serial.println("SYS_MSG: Gateway_Link_Lost_Offline_Buffering");
      }

      if (is_offline) {
        if (fdb_active) {
          uint8_t stat_flag = 0;
          if (is_tripped) stat_flag |= (1 << 7);
          if (is_overloaded) stat_flag |= (1 << 6);
          write_telemetry_to_buffer(current, temp, ambient_temp, health_status,
                                    mean_deviation, peak_centered, crest_factor,
                                    vib_rms, vib_peak, vib_kurtosis, vib_crest, stat_flag);
        }
      } else {
        Serial.printf("%.3f,%.2f,%.2f,%d,%.4f,%.4f,%.2f,%.4f,%.4f,%.2f,%.2f\n", 
                      current, temp, ambient_temp, health_status, 
                      mean_deviation, peak_centered, crest_factor,
                      vib_rms, vib_peak, vib_kurtosis, vib_crest);
      }
      
      last_data_ts = now;
    }

    // Handle Serial inputs (Calibration and manual overrides)
    if (Serial.available()) {
      String cmd = Serial.readStringUntil('\n');
      cmd.trim();
      if (cmd.length() > 0) {
        char type = cmd.charAt(0);
        
        // PUBLIC COMMANDS (No signature required)
        if (type == 'H') {
          last_heartbeat_ts = millis();
          if (is_offline) {
            is_offline = false;
            Serial.println("SYS_MSG: SYNC_PENDING");
          }
        } else if (type == 'Y') {
          Serial.printf("SYS_MSG: SYNC_START:%u\n", millis());
          dump_and_sync_buffer();
          Serial.println("SYS_MSG: SYNC_DONE");
          last_heartbeat_ts = millis();
        } else if (type == 'R') { // Trigger auto bias offset calibration
          Serial.print("SYS_MSG: Re-Calibrating...");
          system_bias = performAutoCalibration(1000, noise_floor);
          preferences.begin("velqron", false);
          preferences.putFloat("bias", system_bias);
          preferences.putFloat("noise", noise_floor);
          preferences.end();
          Serial.println(" Done.");
        } else if (type == 'X') { // Dump 8-byte binary packet
          uint8_t pkt[8];
          getBinaryPacket(pkt);
          Serial.print("BIN_PKT:");
          for(int i=0; i<8; i++) Serial.printf("%02x", pkt[i]);
          Serial.println();
        }
        
        // SIGNED COMMANDS (Require HMAC-SHA256 verification)
        else if (validateCommandSignature(cmd)) {
          if (type == 'B') { // Manually assign zero-offset bias
            float val = cmd.substring(2, cmd.lastIndexOf(':')).toFloat();
            system_bias = val;
            preferences.begin("velqron", false);
            preferences.putFloat("bias", system_bias);
            preferences.end();
            Serial.printf("SYS_MSG: Bias updated to %.4f\n", system_bias);
          } else if (type == 'C') { // Adjust current scaling scalar
            float val = cmd.substring(2, cmd.lastIndexOf(':')).toFloat();
            calibration_scalar = val;
            preferences.begin("velqron", false);
            preferences.putFloat("scalar", calibration_scalar);
            preferences.end();
            Serial.printf("SYS_MSG: Scalar updated to %.4f\n", calibration_scalar);
          } else if (type == 'S') { // Configure Rated Current (FLA)
            float val = cmd.substring(2, cmd.lastIndexOf(':')).toFloat();
            rated_current = val;
            preferences.begin("velqron", false);
            preferences.putFloat("rated_current", rated_current);
            preferences.end();
            Serial.printf("SYS_MSG: Rated current limit set to %.2f\n", rated_current);
          } else if (type == 'U') { // Reset safety trip
            resetSafetyTrip();
          }
        } else {
          Serial.println("SEC_ERR: Command rejected. Signature missing or invalid.");
        }
      }
    }
    
    vTaskDelay(pdMS_TO_TICKS(10)); // Yield to allow other Core 1 background operations
  }
}
