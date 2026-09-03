import os
import sys
from collections import defaultdict

# Add root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.utils.dual_explainer as explainer_mod
from src.core.analyzer import reset_system_state, run_analysis
from src.utils.simulator_engine import engine as simulator


# Mock LLM calls to speed up tests
def mock_compare(data, mode=None):
    return "{}", "{}"


explainer_mod.compare_explanations = mock_compare


def is_match(actual, expected):
    if actual == expected:
        return True
    if expected == "STABLE_OVERLOAD" and actual == "DEGRADING_OVERLOAD":
        return True
    if expected == "DEGRADING_OVERLOAD" and actual == "STABLE_OVERLOAD":
        return True
    return False


SCENARIOS = {
    "gradual_failure_demo": [
        ("NORMAL_OPERATION", 3),
        ("STABLE_OVERLOAD", 5),
        ("DEGRADING_OVERLOAD", 5),
    ],
    "dry_run_demo": [("NORMAL_OPERATION", 3), ("DRY_RUN", 5)],
    "unstable_mechanical_demo": [("NORMAL_OPERATION", 3), ("UNSTABLE_LOAD", 5)],
    "hardware_survival_disconnect": [("NORMAL_OPERATION", 2), ("SENSOR_DISCONNECT", 5)],
    "hardware_survival_saturation": [("NORMAL_OPERATION", 2), ("SIGNAL_CLIPPING", 5)],
}


def run_accuracy_test():
    stats = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
    total_cycles = 0

    print("\n" + "=" * 50)
    print(" VELQRON ACCURACY SCORECARD")
    print("=" * 50)

    for name, sequence in SCENARIOS.items():
        reset_system_state()
        print(f"\nRunning Scenario: {name}")

        for profile, count in sequence:
            for _ in range(count):
                cycle_data = simulator.generate_cycle(profile)
                expected = cycle_data["expected_detection"]
                actual = run_analysis(cycle_data)
                actual = actual if actual else "NORMAL"

                total_cycles += 1

                # We give 1 cycle grace for persistence detection
                # but if it fails after that, it's an error.
                # Actually, let's be strict for accuracy calculation.

                if is_match(actual, expected):
                    if expected == "NORMAL":
                        stats["NORMAL"]["tn"] += 1
                    else:
                        stats[expected]["tp"] += 1
                else:
                    # Mismatch
                    if expected == "NORMAL":
                        stats[actual]["fp"] += 1
                    else:
                        stats[expected]["fn"] += 1
                        if actual != "NORMAL":
                            stats[actual]["fp"] += 1
                    print(f"  [MISS] Cycle {total_cycles}: Expected {expected}, got {actual}")

    print("\n" + "-" * 65)
    print(
        f"{'Fault Type':<20} | {'TP':<4} | {'FP':<4} | {'FN':<4} | {'Precision':<10} | {'Recall':<10}"
    )
    print("-" * 65)

    total_tp = 0
    total_fp = 0
    total_fn = 0

    for fault, s in stats.items():
        if fault == "NORMAL":
            continue

        tp, fp, fn = s["tp"], s["fp"], s["fn"]
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0

        total_tp += tp
        total_fp += fp
        total_fn += fn

        print(f"{fault:<20} | {tp:<4} | {fp:<4} | {fn:<4} | {precision:<10.2f} | {recall:<10.2f}")

    overall_acc = (
        total_tp / (total_tp + total_fp + total_fn) if (total_tp + total_fp + total_fn) > 0 else 0
    )

    print("-" * 65)
    print(f"\nOVERALL SYSTEM ACCURACY: {overall_acc * 100:.1f}%")
    print(f"TOTAL CYCLES ANALYZED: {total_cycles}")
    print("=" * 50 + "\n")

    return overall_acc


if __name__ == "__main__":
    # Ensure data directory exists for tests
    os.makedirs("data", exist_ok=True)
    accuracy = run_accuracy_test()

    # PHASE 1 STRICT GATING: Minimum 90% accuracy required
    if accuracy < 0.90:
        print(f"[FAILED] Accuracy {accuracy * 100:.1f}% is below the 90% threshold.")
        sys.exit(1)
    else:
        print("[PASSED] System meets Phase 1 reliability requirements.")
        sys.exit(0)
