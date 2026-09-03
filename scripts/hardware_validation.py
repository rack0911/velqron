import argparse
import os
import re
import sys
import time

import numpy as np
import serial

# Add root to path for analyzer imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.core.analyzer import analyze_realtime, reset_system_state


class HardwareValidator:
    def __init__(self, port, baud=115200, mock=False):
        self.port = port
        self.baud = baud
        self.mock = mock
        self.ser = None
        self.last_cmd = "N"
        self.log = []

    def connect(self):
        if self.mock:
            print(f"[MOCK] Connected to {self.port} at {self.baud}")
            return True
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=2)
            time.sleep(2)  # Wait for ESP32 reboot
            self.ser.flushInput()
            print(f"Connected to {self.port}")
            return True
        except Exception as e:
            print(f"Connection failed: {e}")
            return False

    def send(self, cmd):
        print(f"Sending: {cmd}")
        self.last_cmd = cmd
        if self.mock:
            return
        self.ser.write(cmd.encode())
        time.sleep(0.1)

    def read_line(self, timeout=2):
        if self.mock:
            if self.last_cmd == "N":
                return "0.820,28.0,0"
            if self.last_cmd == "O":
                return "1.650,32.0,0"
            if self.last_cmd == "S":
                return "0.000,27.5,0"
            if self.last_cmd == "B":
                return f"BIAS:{1.650 + np.random.normal(0, 0.001):.4f}"
            if self.last_cmd == "V":
                return f"RAW:2048,V:{1.650 + np.random.normal(0, 0.005):.4f}"
            if self.last_cmd == "H":
                return "SURVIVABILITY v55.1 ACTIVE"
            return "0.800,28.0,0"

        start = time.time()
        while time.time() - start < timeout:
            if self.ser.in_waiting:
                return self.ser.readline().decode("utf-8").strip()
        return None

    def test_hil_bridge(self):
        print("\n--- TEST: HIL Bridge Validation ---")
        results = {}
        for mode, cmd in [("NORMAL", "N"), ("OVERLOAD", "O"), ("STOP", "S")]:
            self.send(cmd)
            time.sleep(2)  # Let EMA stabilize
            line = self.read_line()
            print(f"[{mode}] Output: {line}")
            if line:
                try:
                    current = float(line.split(",")[0])
                    results[mode] = current
                except (ValueError, IndexError) as e:
                    print(f"  [ERROR] Failed to parse current from '{line}': {e}")
                    results[mode] = -1

        # Check logic
        if results.get("NORMAL", 0) > 0.1 and results.get("OVERLOAD", 0) > results.get("NORMAL", 0):
            print(" HIL Bridge PASS")
            return True
        else:
            print("[FAIL] HIL Bridge FAIL")
            return False

    def test_bias_stability(self, duration=60):
        print(f"\n--- TEST: Bias Stability ({duration}s) ---")
        if not self.mock:
            self.ser.reset_input_buffer()
        self.send("B+")  # Enable bias stream
        biases = []
        start = time.time()
        while time.time() - start < duration:
            line = self.read_line()
            if line and "BIAS:" in line and "ON" not in line and "OFF" not in line:
                try:
                    val = float(line.split(":")[1])
                    biases.append(val)
                    if len(biases) % 10 == 0:
                        print(f"  Progress: {len(biases)}s...")
                except (ValueError, IndexError) as e:
                    print(f"  [DEBUG] Failed to parse bias: {e}")
                    pass

        self.send("B-")  # Disable bias stream
        if not biases:
            print("[FAIL] No bias data received")
            return False

        drift = max(biases) - min(biases)
        mean = np.mean(biases)
        print(f"Mean Bias: {mean:.4f}V | Max Drift: {drift * 1000:.2f}mV")

        if drift < 0.050:  # 50mV threshold
            print(" Bias Stability PASS")
            return True
        else:
            print("[FAIL] Bias Stability FAIL (Drift too high)")
            return False

    def test_noise_floor(self, samples=100):
        print("\n--- TEST: ADC Noise Floor ---")
        self.send("S")  # Stop signal
        time.sleep(0.5)
        if not self.mock:
            self.ser.reset_input_buffer()
        self.send("V+")  # Enable raw stream
        voltages = []
        timeout_limit = 10  # Seconds of no data
        last_data_time = time.time()

        print(f"Waiting for {samples} samples...")
        while len(voltages) < samples:
            line = self.read_line()
            if line:
                last_data_time = time.time()
                # Debug: Show the first few lines to prove we are receiving
                if len(voltages) < 5:
                    print(f"  [DEBUG] Received: {line}")

                if "V:" in line and "RAW:ON" not in line:
                    try:
                        m = re.search(r"V:(\d+\.\d+)", line)
                        if m:
                            voltages.append(float(m.group(1)))
                            if len(voltages) % 20 == 0:
                                print(f"  Progress: {len(voltages)}/{samples} samples...")
                    except ValueError as e:
                        print(f"  [DEBUG] Failed to parse voltage: {e}")
                        pass

            if time.time() - last_data_time > timeout_limit:
                print("[FAIL] ERROR: No data received from ESP32 for 10 seconds.")
                print("Tip: Try pressing the 'EN' button on your ESP32 to reset it.")
                break

        self.send("V-")  # Disable raw stream
        if not voltages:
            return False
        mean = np.mean(voltages)
        std = np.std(voltages)
        print(f"Noise Mean: {mean:.4f}V | StdDev: {std * 1000:.2f}mV")
        print(f"Suggested NOISE_THRESHOLD: {std * 3:.4f}V")
        return True

    def test_resilience(self):
        print("\n--- TEST: Firmware Resilience (Watchdog) ---")
        self.send("H")  # Trigger Hang
        print("Hang triggered. Waiting for reboot (max 15s)...")
        start = time.time()
        rebooted = False
        while time.time() - start < 15:
            line = self.read_line(timeout=5)
            if line and "SURVIVABILITY" in line:
                print(f"Reboot detected: {line}")
                rebooted = True
                break

        if rebooted:
            print(" Watchdog Recovery PASS")
            return True
        else:
            print("[FAIL] Watchdog Recovery FAIL")
            return False

    def test_waveform_integrity(self, samples=500):
        print("\n--- TEST: Waveform Integrity (Symmetry & Clipping) ---")
        if not self.mock:
            self.ser.reset_input_buffer()
        self.send("V+")  # Raw stream
        voltages = []
        clipping_hits = 0
        timeout_limit = 10
        last_data_time = time.time()

        print(f"Waiting for {samples} samples...")
        while len(voltages) < samples:
            line = self.read_line()
            if line:
                last_data_time = time.time()
                if len(voltages) < 5:
                    print(f"  [DEBUG] Received: {line}")

                if "V:" in line and "RAW:ON" not in line:
                    try:
                        v = float(line.split("V:")[1])
                        voltages.append(v)
                        if v <= 0.01 or v >= 3.29:
                            clipping_hits += 1
                        if len(voltages) % 50 == 0:
                            print(f"  Progress: {len(voltages)}/{samples} samples...")
                    except (ValueError, IndexError) as e:
                        print(f"  [DEBUG] Failed to parse waveform voltage: {e}")
                        pass

            if time.time() - last_data_time > timeout_limit:
                print("[FAIL] ERROR: No data received for Waveform analysis.")
                break

        self.send("V-")  # Disable

        if not voltages:
            return False

        v_min, v_max = min(voltages), max(voltages)
        v_mean = np.mean(voltages)

        # Symmetry check relative to mean
        peak_above = v_max - v_mean
        peak_below = v_mean - v_min
        symmetry_ratio = peak_above / peak_below if peak_below > 0 else 0

        print(f"Mean: {v_mean:.3f}V | Range: [{v_min:.3f}V - {v_max:.3f}V]")
        print(f"Symmetry Ratio: {symmetry_ratio:.2f} (Target: 1.0 ± 0.2)")
        print(f"Clipping Hits: {clipping_hits} ({(clipping_hits / samples) * 100:.1f}%)")

        passed = True
        if not (0.8 <= symmetry_ratio <= 1.2):
            print("[FAIL] FAIL: Waveform asymmetry detected")
            passed = False
        if clipping_hits > (samples * 0.01):
            print("[FAIL] FAIL: Significant clipping detected")
            passed = False

        if passed:
            print(" Waveform Integrity PASS")
        return passed

    def test_pipeline_dry_run(self, duration_s=10):
        print(f"\n--- TEST: Pipeline Dry Run ({duration_s}s) ---")
        reset_system_state()
        history = []
        start = time.time()

        while time.time() - start < duration_s:
            line = self.read_line()
            if line and "," in line and "B:" not in line:
                try:
                    parts = line.split(",")
                    curr = float(parts[0])
                    temp = float(parts[1])
                    history.append({"current": curr, "temperature": temp})

                    if len(history) % 5 == 0:
                        res = analyze_realtime(history, llm_mode="Local Only")
                        print(f"  [Pipeline] Status: {res['status']} | Event: {res['event']}")
                except (ValueError, IndexError) as e:
                    print(f"  [ERROR] Line processing failed: {e}")
                    pass
                except Exception as e:
                    print(f"  [CRITICAL] Unexpected error in pipeline dry run: {e}")
                    pass
            time.sleep(0.5)

        final_res = analyze_realtime(history, llm_mode="Local Only")
        print(f"Final Prediction: {final_res['event']} ({final_res['status']})")

        if final_res["event"] in ["NORMAL", "NONE"] or final_res["status"] in ["IDLE", "WARMUP"]:
            print(" Pipeline Dry Run PASS")
            return True
        else:
            print("[FAIL] Pipeline Dry Run FAIL (Unexpected event detected)")
            return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="/dev/ttyUSB0")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--stage", type=int, default=0, help="Validation Stage (0 or 1)")
    args = parser.parse_args()

    validator = HardwareValidator(args.port, mock=args.mock)
    if not validator.connect():
        sys.exit(1)

    print("=" * 40)
    print(f" VELQRON HARDWARE VALIDATION STAGE {args.stage}")
    print("=" * 40)

    if args.stage == 0:
        validator.test_hil_bridge()
        validator.test_bias_stability(duration=60)
        validator.test_noise_floor()
        validator.test_resilience()
    elif args.stage == 1:
        # Physical Assembly Check (Assumed if running)
        print("[INFO] Starting Ambient Noise Capture (120s)...")
        validator.test_noise_floor(samples=200)  # Increased samples for baseline
        validator.test_bias_stability(duration=60)  # Bias under load check
        validator.test_waveform_integrity()
        validator.test_pipeline_dry_run()

    print("\n--- Validation Complete ---")


if __name__ == "__main__":
    main()
