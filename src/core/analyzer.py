import json
import os
import sqlite3
import sys
import threading

import pandas as pd

from src.core.orchestrator import EngineOrchestrator
from src.utils.database import db
from src.utils.logger import get_logger

logger = get_logger(__name__)
orchestrator = EngineOrchestrator()

# Background worker controls
_worker_started = False
_worker_lock = threading.Lock()
_stop_worker = threading.Event()


def llm_worker_loop():
    """Background daemon worker to process PENDING LLM explanations."""
    logger.info("LLM background worker thread started.")
    while not _stop_worker.is_set():
        try:
            # Poll database for a PENDING diagnostic record
            conn = db._connect()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, llm_data_json, llm_mode
                FROM fault_dataset
                WHERE llm_status = 'PENDING' AND llm_data_json IS NOT NULL
                ORDER BY id ASC
                LIMIT 1
            """)
            row = cursor.fetchone()
            conn.close()

            if row:
                diag_id = row["id"]
                llm_data_json = row["llm_data_json"]
                llm_mode = row["llm_mode"] or "Local Priority"

                logger.info(f"LLM Worker: Processing pending diagnostic ID {diag_id}")

                try:
                    llm_data = json.loads(llm_data_json)
                    # Generate explanation using the orchestrator's get_explanation
                    explanation = orchestrator.get_explanation(llm_data, mode=llm_mode)

                    # Update database record
                    db.update_diagnostic_explanation(diag_id, explanation)
                    logger.info(f"LLM Worker: Successfully completed diagnostic ID {diag_id}")
                except Exception as ex:
                    logger.error(
                        f"LLM Worker: Failed to generate explanation for ID {diag_id}: {ex}",
                        exc_info=True,
                    )
                    db.update_diagnostic_explanation(
                        diag_id, f"ERROR: Explanation generation failed: {ex}"
                    )
            else:
                # Sleep briefly before polling again
                _stop_worker.wait(0.5)
        except Exception as e:
            logger.error(f"LLM Worker: Loop error: {e}", exc_info=True)
            _stop_worker.wait(1.0)


def start_llm_worker():
    """Starts the background LLM worker thread if not already running."""
    global _worker_started
    with _worker_lock:
        if not _worker_started:
            _stop_worker.clear()
            t = threading.Thread(target=llm_worker_loop, daemon=True, name="LLMWorkerThread")
            t.start()
            _worker_started = True
            logger.info("LLM background worker thread spawned.")


if "pytest" not in sys.modules and os.getenv("CI_MODE") != "true":
    start_llm_worker()


def reset_system_state():
    """Resets all engine states for a fresh start."""
    from src.core.profile_manager import DEFAULT_PROFILE, load_profile, save_profile

    save_profile(DEFAULT_PROFILE)
    profile = load_profile()
    motor_id = profile.get("motor_id", "SIM_MOTOR_01")
    context = orchestrator.get_context(motor_id)

    from src.engines import logic_controller as logic
    from src.utils.database import db

    context.reset_state()
    logic.reset_persistence_state(context)
    db.clear_history(motor_id)

    # Note: MotorContext.reset_state() handles in-memory buffers


def run_analysis(cycle_data=None, llm_mode="Local Priority"):
    """
    Standard cycle-based analysis coordinator.
    """
    from src.core.profile_manager import load_profile

    profile = load_profile()
    motor_id = profile.get("motor_id", "SIM_MOTOR_01")
    orchestrator.get_context(motor_id)

    # Load data
    if cycle_data:
        df = pd.DataFrame(
            {
                "time": cycle_data["time_series"],
                "current": cycle_data["current_series"],
                "temperature": cycle_data["temperature_series"],
            }
        )
    else:
        try:
            df = pd.read_csv("data/motor_data.csv")
        except Exception as e:
            logger.error(f"Failed to load motor data: {e}")
            return None

    logger.info("--- Industrial Decision Engine Start ---")

    # Run Orchestrator
    results = orchestrator.process_data(
        df["current"].tolist(),
        df["temperature"].tolist(),
        df["time"].tolist(),
        is_realtime=False,
        vibrations={
            "rms": cycle_data.get("vib_rms", [0.0]),
            "peak": cycle_data.get("vib_peak", [0.0]),
            "kurtosis": cycle_data.get("vib_kurtosis", [3.0]),
            "crest": cycle_data.get("vib_crest", [1.4]),
            "raw": cycle_data.get("vib_raw", []),
        }
        if cycle_data
        else None,
    )

    # Logging
    if results["event"] != "NORMAL":
        logger.info("\n--- SYSTEM SUMMARY ---")
        logger.info(results["summary"])
        logger.info("\n--- DECISION ENGINE OUTPUT ---")
        logger.info(f"Event: {results['event']}")
        logger.info(f"Failure Mode: {results['failure_mode']}")
        logger.info(f"Severity: {results['severity']} | Confidence: {results['confidence']}")
        logger.info(
            f"Persistence: {results['persistence']} cycles | Duration: {results['duration']}"
        )
        logger.info(f"\nRecommended Action: {results['recommendation']}")
        logger.info(f"Urgency: {results['urgency']}")

        # Reasoning
        explanation = orchestrator.get_explanation(results["llm_data"], mode=llm_mode)
        logger.info("\n--- SYSTEM JUSTIFICATION ---")
        logger.info(explanation)
    else:
        logger.info("\n--- SYSTEM SUMMARY ---")
        logger.info(results["summary"])
        logger.info("\nStatus: Operational | No Faults Detected")

    # Industrial Decision Engine Output
    logger.info(f"\nFinal Diagnosis: {results['event']}")
    return results["event"]


def analyze_realtime(history, llm_mode="Local Priority", data_source="PHYSICAL"):
    """
    Intelligent multi-cycle real-time analyzer.
    """
    if len(history) < 5:
        return {"status": "WARMUP", "event": "NONE"}

    try:
        currents = [d["current"] for d in history]
        temps = [d["temperature"] for d in history]
        times = [
            float(i) for i in range(len(history))
        ]  # Use indices as pseudo-time if not provided
        ambient_temps = [d.get("ambient_temperature", 25.0) for d in history]

        results = orchestrator.process_data(
            currents,
            temps,
            times,
            is_realtime=True,
            ambient_temperatures=ambient_temps,
            data_source=data_source,
            llm_mode=llm_mode,
        )

        event = results["event"]
        if event == "NORMAL":
            explanation = "Motor is operating within normal parameters."
        else:
            # Query the database to retrieve the latest status
            from src.core.profile_manager import load_profile

            profile = load_profile()
            motor_id = profile.get("motor_id", "SIM_MOTOR_01")

            latest_diag = db.get_latest_diagnostic(motor_id)
            if latest_diag:
                if latest_diag.get("llm_status") == "COMPLETED" and latest_diag.get(
                    "llm_explanation"
                ):
                    explanation = latest_diag["llm_explanation"]
                else:
                    explanation = "PENDING"
            else:
                explanation = "PENDING"

        return {
            "event": results["event"],
            "status": results["state"],
            "severity": results["severity"],
            "confidence": results["confidence"],
            "failure_mode": results["failure_mode"],
            "explanation": explanation,
            "recommendation": results["recommendation"],
            "aging_risk": results.get("aging_risk"),
            "llm_data": results.get("llm_data"),
            "drift_score": results.get("drift_score", 0.0),
            "deviation_score": results.get("deviation_score", 0.0),
            "trend_score": results.get("trend_score", 0.0),
            "anomaly_score": results.get("anomaly_score", 0.0),
            "voltage": results.get("voltage", 415.0),
            "power_factor": results.get("power_factor", 0.85),
        }

    except Exception as e:
        logger.error(f"Realtime analysis failed: {e}", exc_info=True)
        return {
            "status": "ERROR",
            "event": "UNKNOWN",
            "severity": "NONE",
            "explanation": "Internal pipeline evaluation failed.",
            "recommendation": "Check application logs.",
        }


if __name__ == "__main__":
    run_analysis()
