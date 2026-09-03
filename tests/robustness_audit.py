import json
import os
import random
import sys
import time

import numpy as np

# Add root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.analyzer import analyze_realtime, orchestrator
from src.engines import cycle_memory
from src.engines import logic_controller as logic
from src.utils.simulator_engine import engine as simulator


def run_scenario(name, config, clear=True):
    print(f"\n>>> RUNNING SCENARIO: {name}")

    motor_id = "SIM_MOTOR_01"
    context = orchestrator.get_context(motor_id)

    # CLEAN SLATE: Only if requested
    if clear:
        context.reset_state()
        cycle_memory.clear_history(context)
        logic.reset_persistence_state(context)

    simulator.enable_robustness(config)

    # ... rest of the logic ...
    stream_history = []
    detected_cycles = 0
    false_faults = 0
    in_cycle = False

    for t in range(120):
        is_on = (10 <= t < 40) or (60 <= t < 90)
        base_current = 2.0 if is_on else 0.0
        current = simulator._apply_robustness_current(np.array([base_current]), np.array([t]))[0]
        if config.get("adc_quantization"):
            current = simulator._apply_adc_limitations(np.array([current]))[0]

        stream_history.append({"current": current, "temperature": 30.0})
        if len(stream_history) > 30:
            stream_history.pop(0)

        res = analyze_realtime(stream_history, llm_mode="Local Only")
        state = res.get("status")
        event = res.get("event")

        if state == "FAULT_DETECTED" or state == "RUNNING":
            if not in_cycle:
                detected_cycles += 1
                in_cycle = True
        elif state == "OFF" or state == "WARMUP":
            in_cycle = False
        if event and event != "NORMAL":
            false_faults += 1

    # CRITICAL: Save a summary to history to establish baseline for subsequent scenarios
    if detected_cycles > 0:
        cycle_memory.save_cycle(
            context,
            {
                "avg_current": 2.0,
                "max_current": 2.2,
                "avg_temperature": 30.0,
                "max_temp": 32.0,
                "event": None,
                "timestamp": time.time(),
                "runtime": 60,
            },
        )
        print("  [INFO] Baseline cycle saved to history.")

    simulator.disable_robustness()
    return detected_cycles, false_faults


def run_scenario_no_reset(name, config):
    return run_scenario(name, config, clear=False)


def audit():
    print("=" * 60)
    print(" VELQRON SIGNAL ROBUSTNESS AUDIT")
    print("=" * 60)

    scenarios = {
        "Baseline (Clean)": {"config": {"adc_quantization": True}, "expected_cycles": 2},
        "Gaussian Chaos": {
            "config": {"gaussian_noise": 0.15, "adc_quantization": True},
            "expected_cycles": 2,
        },
        "Industrial Spikes": {
            "config": {"spike_noise": 0.05, "adc_quantization": True},
            "expected_cycles": 2,
        },
        "Dropout Gaps": {
            "config": {"dropouts": 0.02, "adc_quantization": True},
            "expected_cycles": 2,
        },
        "Low Amp (Threshold Stress)": {
            "config": {"baseline_drift": -0.2, "adc_quantization": True},  # Lowering signal
            "expected_cycles": 2,
        },
    }

    final_report = []

    for name, s_cfg in scenarios.items():
        detected, faults = run_scenario(name, s_cfg["config"])

        # We need to run one fault scenario to see confidence drop
        # Let's add an "Overload + Noise" scenario

        # Criteria 1: Cycle Detection (Miss/Split)
        cycle_ok = detected == s_cfg["expected_cycles"]
        # Criteria 2: False Positive Rate
        fault_ok = faults <= 6

        status = " PASS" if (cycle_ok and fault_ok) else "[FAIL] FAIL"
        detail = f"Cycles: {detected}/{s_cfg['expected_cycles']} | False Faults: {faults} ({(faults / 120) * 100:.1f}%)"

        print(f"{status} | {name.ljust(25)} | {detail}")

        final_report.append(
            {
                "Scenario": name,
                "Result": status,
                "Cycles": f"{detected}/{s_cfg['expected_cycles']}",
                "False Faults": faults,
                "Rate": f"{(faults / 120) * 100:.1f}%",
            }
        )

    # Confidence Check Scenario
    print("\n>>> RUNNING CONFIDENCE VALIDATION (Overload + High Noise)")
    motor_id = "SIM_MOTOR_01"
    context = orchestrator.get_context(motor_id)
    cycle_memory.clear_history(context)
    context.reset_state()
    # 1. Establish Clean Baseline (Cycle 1)
    run_scenario_no_reset("Baseline Build", {"adc_quantization": True})

    # 2. Trigger Overload with EXTREME Noise
    # DO NOT clear history here! We need the baseline from step 1.
    context.reset_state()
    # Manually simulate 25 samples of OVERLOAD (3.0A) with high noise
    # Standard deviation will be ~0.6, well above the 0.2 HIGH threshold
    overload_history = [
        {"current": 3.0 + random.normalvariate(0, 0.6), "temperature": 35.0} for _ in range(25)
    ]
    res = analyze_realtime(overload_history, llm_mode="Local Only")
    conf = res.get("confidence")
    var = res.get("variation_level")
    print(f"Detected Event: {res.get('event')} | Variation: {var} | Confidence: {conf}")

    if conf == "LOW":
        print(" PASS | Confidence correctly dropped to LOW due to high instability.")
    else:
        print(f"[FAIL] FAIL | Confidence was {conf} (Variation: {var})")

    # Save report
    os.makedirs("docs/reports", exist_ok=True)
    report_file = "docs/reports/robustness_audit_report.json"
    with open(report_file, "w") as f:
        json.dump(final_report, f, indent=2)

    print("\n" + "=" * 60)
    print(f"AUDIT COMPLETE. Report saved to {report_file}")
    print("=" * 60)


if __name__ == "__main__":
    audit()
