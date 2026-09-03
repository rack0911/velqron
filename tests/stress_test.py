import os
import sys

# Add project root to path
sys.path.append(os.getcwd())

from src.core.analyzer import analyze_realtime
from src.utils.logger import get_logger
from src.utils.simulator_engine import MotorSimulator

logger = get_logger("StressTest")


def run_stress_test():
    simulator = MotorSimulator()
    scenario = "COMPOUND_FAULT"

    logger.info(f"=== STARTING STRESS TEST: {scenario} ===")
    logger.info(
        "Description: Simultaneous Severe Overload + High Instability + Rapid Thermal Stress"
    )

    # Generate 5 cycles of data to establish baseline and then trigger fault
    history = []

    # 1. Warmup Cycles (Healthy)
    logger.info("\n--- PHASE 1: Establishing Healthy Baseline ---")
    for i in range(3):
        cycle = simulator.generate_cycle("NORMAL_OPERATION")
        # Add samples to history as if they were coming in real-time
        for c, t in zip(cycle["current_series"], cycle["temperature_series"], strict=False):
            history.append({"current": c, "temperature": t})
            if len(history) > 100:  # Maintain a window
                history.pop(0)

        result = analyze_realtime(history)
        logger.info(f"Cycle {i + 1}: Event={result['event']} | Status={result['status']}")

    # 2. Stress Cycles (Compound Fault)
    logger.info("\n--- PHASE 2: Injecting Compound Fault ---")
    for i in range(5):
        cycle = simulator.generate_cycle(scenario)
        for c, t in zip(cycle["current_series"], cycle["temperature_series"], strict=False):
            history.append({"current": c, "temperature": t})
            if len(history) > 100:
                history.pop(0)

        result = analyze_realtime(history)
        logger.info(
            f"Cycle {i + 4}: Event={result['event']} | Severity={result.get('severity')} | Mode={result.get('failure_mode')}"
        )

        if result["event"] != "NORMAL":
            logger.info(f"AI Interpretation: {result.get('explanation')[:150]}...")

    logger.info("\n=== STRESS TEST COMPLETED ===")


if __name__ == "__main__":
    run_stress_test()
