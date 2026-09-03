// Minimal Hardware Test Script
// Use this to check your Serial Plotter for a clean sine wave

#define ADC_PIN 34

void setup() {
  Serial.begin(115200);
}

void loop() {
  // --- Step 1 & 2: Simple Plotter Test ---
  int raw = analogRead(ADC_PIN);
  Serial.println(raw);
  delay(2); // ~500 Hz sampling for smooth plotting
}
