# simulator_engine.py
import time

import numpy as np

from src.utils.motor_profiles import BASE_CURRENT, BASE_TEMP_START, PROFILES


class MotorSimulator:
    def __init__(self):
        self.cycle_count = 0
        self.profile_cycle_count = 0
        self.current_profile_name = None
        self.robustness_mode = False
        self.robustness_config = {
            "gaussian_noise": 0.0,
            "spike_noise": 0.0,
            "baseline_drift": 0.0,
            "dropouts": 0.0,
            "adc_quantization": False,
        }

    def set_profile(self, profile_name):
        if profile_name != self.current_profile_name:
            self.current_profile_name = profile_name
            self.profile_cycle_count = 0

    def generate_cycle(self, profile_name, duration_sec=180):
        self.set_profile(profile_name)
        self.cycle_count += 1
        self.profile_cycle_count += 1

        profile = PROFILES.get(profile_name, PROFILES["NORMAL_OPERATION"])

        # Time array (1Hz sampling)
        t = np.arange(0, duration_sec, 1)

        # 1. GENERATE CURRENT
        current_series = self._generate_current(profile, t)

        # 2. GENERATE TEMPERATURE
        temperature_series = self._generate_temperature(profile, t)

        # 3. APPLY ROBUSTNESS MODELS (NEW)
        if self.robustness_mode:
            current_series = self._apply_robustness_current(current_series, t)
            if self.robustness_config.get("adc_quantization"):
                current_series = self._apply_adc_limitations(current_series)

        # 4. VIBRATION SIGNATURES (Tier 2 Simulation)
        v_rms = 0.05 + np.random.uniform(0, 0.02)
        v_peak = v_rms * 1.414
        v_kurt = 3.0 + np.random.uniform(-0.1, 0.1)
        v_crest = 1.4 + np.random.uniform(-0.1, 0.1)

        # Generate simulated raw vibration waveform (2048 samples at 12kHz)
        t_raw = np.linspace(0, 2048 / 12000, 2048)
        if profile_name == "UNSTABLE_LOAD" or profile.get("current", {}).get("unstable"):
            v_kurt = 5.8 + np.random.uniform(0, 1.5)
            v_peak = v_rms * 4.5
            v_crest = 5.2
            # Simulate outer race defect raw signature with impacts
            raw_v = np.sin(2 * np.pi * 50 * t_raw) + np.sin(2 * np.pi * 230 * t_raw) * 0.5
            # Add noise
            raw_v += np.random.normal(0, 0.3, 2048)
            # Add periodic transient spikes
            for idx in range(0, 2048, 150):
                raw_v[idx : idx + 10] += 2.5
        else:
            # Healthy baseline noise + 50Hz electrical hum
            raw_v = 0.1 * np.sin(2 * np.pi * 50 * t_raw) + np.random.normal(0, 0.05, 2048)

        return {
            "current_series": current_series.tolist(),
            "temperature_series": temperature_series.tolist(),
            "time_series": t.tolist(),
            "vib_rms": [v_rms],
            "vib_peak": [v_peak],
            "vib_kurtosis": [v_kurt],
            "vib_crest": [v_crest],
            "vib_raw": raw_v.tolist(),
            "expected_detection": profile.get("expected_detection", "NORMAL"),
            "motor_id": "SIM_MOTOR_01",
            "timestamp": time.time(),
        }

        return {
            "cycle_id": self.cycle_count,
            "timestamp": time.time(),
            "time_series": t.tolist(),
            "current_series": current_series.tolist(),
            "temperature_series": temperature_series.tolist(),
            "expected_detection": profile["expected_detection"],
        }

    def enable_robustness(self, config=None):
        self.robustness_mode = True
        if config:
            self.robustness_config.update(config)

    def disable_robustness(self):
        self.robustness_mode = False

    def _apply_robustness_current(self, currents, t):
        # 1. Gaussian Noise
        g_noise = self.robustness_config.get("gaussian_noise", 0.0)
        if g_noise > 0:
            currents += np.random.normal(0, g_noise, len(currents))

        # 2. Spike Noise (Random high amplitude spikes)
        s_noise = self.robustness_config.get("spike_noise", 0.0)
        if s_noise > 0:
            for _ in range(int(len(t) * 0.05)):  # 5% chance of spikes
                if np.random.rand() < s_noise:
                    idx = np.random.randint(0, len(t))
                    currents[idx] += np.random.uniform(1.0, 3.0)  # 1-3A spikes

        # 3. Baseline Drift (Slow offset shift)
        b_drift = self.robustness_config.get("baseline_drift", 0.0)
        if b_drift > 0:
            drift = np.linspace(0, b_drift, len(t))
            currents += drift

        # 4. Signal Dropouts (Random zero segments)
        dropout_prob = self.robustness_config.get("dropouts", 0.0)
        if dropout_prob > 0:
            mask = np.random.rand(len(currents)) < dropout_prob
            if mask.any():
                indices = np.where(mask)[0]
                lengths = np.random.randint(1, 4, size=len(indices))
                for i, length in zip(indices, lengths, strict=False):
                    currents[i : i + length] = 0.0

        return currents

    def _apply_adc_limitations(self, currents):
        # 12-bit quantization (ESP32)
        # Assuming 0-30A maps to 0-4095
        MAX_A = 30.0
        ADC_STEPS = 4095

        # Map Amps to ADC counts
        counts = (currents / MAX_A) * ADC_STEPS

        # Constraints: 0-4095 (clipping)
        counts = np.clip(counts, 0, ADC_STEPS)

        # Quantize (Round to integer)
        counts = np.round(counts).astype(int)

        # Map back to Amps
        quantized_amps = (counts / ADC_STEPS) * MAX_A
        return quantized_amps

    def _generate_current(self, profile, t):
        c_cfg = profile["current"]
        base = c_cfg.get("base", BASE_CURRENT)
        noise_level = c_cfg.get("noise", 0.05)

        # 1. APPLY OVERLOAD (LIFT BASE)
        increase_percent = c_cfg.get("increase_percent", 0.0)
        if increase_percent > 0:
            base = base * (1 + increase_percent)

        # 2. APPLY PROGRESSIVE DEGRADATION
        if self.current_profile_name == "DEGRADING_OVERLOAD":
            increase = c_cfg.get("progressive_increase", 0.05)
            base = base * (1 + increase * (self.profile_cycle_count - 1))

        # 3. APPLY DRY RUN DROP
        drop = c_cfg.get("drop_percent", 0.0)
        if drop != 0:
            base = base * (1 + drop)

        # Base pattern
        currents = np.full_like(t, base, dtype=float)

        # 4. APPLY INSTABILITY (FLUCTUATION)
        fluct_range = c_cfg.get("fluctuation", 0.0)
        if fluct_range > 0:
            currents += np.random.uniform(-fluct_range, fluct_range, len(t))

        # 5. APPLY SINUSOIDAL FLUCTUATION
        if c_cfg.get("unstable"):
            fluct = 0.2 * np.sin(0.05 * t)
            currents += fluct

        # 6. APPLY RANDOM SPIKES
        if c_cfg.get("random_spikes"):
            for _ in range(int(len(t) * 0.02)):  # 2% chance of spike
                idx = np.random.randint(0, len(t))
                currents[idx] += np.random.uniform(-0.5, 0.5)

        # 7. ADD NOISE
        noise = np.random.normal(0, noise_level, len(t))
        currents += noise

        return currents

        return currents

    def _generate_temperature(self, profile, t):
        t_cfg = profile["temperature"]
        start_temp = t_cfg.get("start", BASE_TEMP_START)
        rise_rate = t_cfg.get("rise_per_min", 0.8) / 60.0  # per second
        plateau = t_cfg.get("plateau", 42.0)

        # Adjust for DEGRADING_OVERLOAD evolution
        if self.current_profile_name == "DEGRADING_OVERLOAD":
            rise_rate = (
                t_cfg.get("rise_per_min_base", 1.0)
                + t_cfg.get("rise_increase_per_cycle", 0.2) * (self.profile_cycle_count - 1)
            ) / 60.0
            plateau = t_cfg.get("plateau_base", 45.0) + t_cfg.get(
                "plateau_increase_per_cycle", 2.0
            ) * (self.profile_cycle_count - 1)

        temps = []
        curr_temp = start_temp

        for _ in range(len(t)):
            # Simple asymptotic approach to plateau
            # dT = (Plateau - T) * k
            # Here we use a linear rise until near plateau for simplicity as requested "rise_per_min"
            if curr_temp < plateau:
                curr_temp += rise_rate
            else:
                # Small oscillation around plateau
                curr_temp = plateau + np.random.uniform(-0.2, 0.2)

            # Add some randomness to rise
            if t_cfg.get("irregular_rise") or t_cfg.get("slow_rise"):
                curr_temp += np.random.uniform(-0.05, 0.05)

            temps.append(curr_temp)

        return np.array(temps)


# Singleton instance
engine = MotorSimulator()
