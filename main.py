import json
import os
import sys

from src.utils.logger import get_logger

# Add the root directory to PYTHONPATH so imports work
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.core.analyzer import reset_system_state, run_analysis
from src.core.config import CONFIG
from src.utils.simulator_engine import engine as simulator

logger = get_logger(__name__)

# Respect global config for simulation mode
SIMULATION_MODE = CONFIG.DATA_SOURCE == "SIMULATED"

SCENARIOS = {
    "gradual_failure_demo": [
        ("NORMAL_OPERATION", 3),
        ("STABLE_OVERLOAD", 5),
        ("DEGRADING_OVERLOAD", 5),
    ],
    "dry_run_demo": [("NORMAL_OPERATION", 3), ("DRY_RUN", 3)],
    "unstable_mechanical_demo": [("NORMAL_OPERATION", 3), ("UNSTABLE_LOAD", 5)],
}


def run_scenario(scenario_name):
    if scenario_name not in SCENARIOS:
        logger.error(f"Scenario {scenario_name} not found.")
        return

    # ver 36.0: Deep reset of all system states
    reset_system_state()

    logger.info(f"=== RUNNING SCENARIO: {scenario_name} ===")
    sequence = SCENARIOS[scenario_name]

    simulated_cycles = []

    for profile, count in sequence:
        logger.info(f"\n>>> Transitioning to Profile: {profile} ({count} cycles)")
        for _ in range(count):
            cycle_data = simulator.generate_cycle(profile)
            actual_detection = run_analysis(cycle_data)

            # Use 'NORMAL' when actual_detection is None (meaning no fault)
            actual_detection_str = actual_detection if actual_detection else "NORMAL"
            expected_detection = cycle_data["expected_detection"]

            logger.info(
                f"*** SIMULATION RESULT *** Expected: {expected_detection} | Actual: {actual_detection_str}"
            )

            # Save for record
            simulated_cycles.append(
                {
                    "cycle_id": cycle_data["cycle_id"],
                    "profile": profile,
                    "expected": expected_detection,
                    "actual": actual_detection_str,
                    "timestamp": cycle_data["timestamp"],
                    "current_series": cycle_data["current_series"],
                    "temperature_series": cycle_data["temperature_series"],
                    "time_series": cycle_data["time_series"],
                }
            )

    # Save the full history
    os.makedirs("data", exist_ok=True)
    with open("data/simulated_cycles.json", "w") as f:
        json.dump(simulated_cycles, f, indent=2)

    logger.info(f"\n=== SCENARIO {scenario_name} COMPLETED ===")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        scenario = sys.argv[1]
        run_scenario(scenario)
    else:
        # Default behavior: run gradual_failure_demo
        run_scenario("gradual_failure_demo")
