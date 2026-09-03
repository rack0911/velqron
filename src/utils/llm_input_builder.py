import os
import sqlite3
from typing import Any, Dict

from src.utils.logger import get_logger

logger = get_logger(__name__)


def format_duration(duration_minutes):
    if duration_minutes < 1:
        return f"{int(duration_minutes * 60)} sec"
    elif duration_minutes < 60:
        return f"{round(duration_minutes, 1)} min"
    else:
        return f"{round(duration_minutes / 60, 1)} hr"


def get_grounding_context(motor_id="SIM_01"):
    db_path = "data/velqron.db"
    motor_specs = {}
    cycle_summaries = []
    maintenance_records = []

    if os.path.exists(db_path):
        try:
            with sqlite3.connect(db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Fetch nameplate specs from machine_registry
                cursor.execute("SELECT * FROM machine_registry WHERE motor_id = ?", (motor_id,))
                row = cursor.fetchone()
                if row:
                    motor_specs = dict(row)

                # Fetch last 5 cycle summaries from fault_dataset
                cursor.execute(
                    "SELECT timestamp, rule_flags, anomaly_score, review_status, current, temperature_rise FROM fault_dataset WHERE motor_id = ? ORDER BY timestamp DESC LIMIT 5",
                    (motor_id,),
                )
                cycle_summaries = [dict(r) for r in cursor.fetchall()]

                # Fetch last 5 maintenance actions from maintenance_action
                cursor.execute(
                    "SELECT timestamp, action_taken, downtime_minutes, resolved FROM maintenance_action WHERE motor_id = ? ORDER BY timestamp DESC LIMIT 5",
                    (motor_id,),
                )
                maintenance_records = [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to fetch grounding context from DB: {e}")

    # Fallback to defaults if empty
    if not motor_specs:
        motor_specs = {
            "motor_id": motor_id,
            "asset_name": "Primary Pump A",
            "location": "Central Utility Room",
            "rated_voltage": 415.0,
            "rated_current": 2.2,
            "rated_power_kw": 0.75,
            "rated_speed_rpm": 1440,
            "insulation_class": "F",
            "service_factor": 1.15,
            "installation_date": "2026-04-13",
        }

    return {
        "motor_specs": motor_specs,
        "cycle_summaries": cycle_summaries,
        "maintenance_records": maintenance_records,
    }


def build_llm_input(
    fault_type,
    current_val,
    temp_val,
    baseline,
    drifts,
    state,
    severity,
    persistence,
    duration_minutes,
    confidence,
    action_data,
    prev_summary,
    failure_mode,
    variation_level,
    possible_causes,
    schematics=None,
    motor_id="SIM_01",
) -> Dict[str, Any]:
    if not baseline:
        return {"error": "No baseline available"}

    duration_str = format_duration(duration_minutes)
    event_clean = str(fault_type).replace("_", " ").lower()

    avg_i = baseline.get("avg_current", 0.0)
    current_dev_pct = round(((current_val - avg_i) / avg_i) * 100, 2) if avg_i > 0 else 0.0
    deviation_level = "elevated" if current_dev_pct > 0 else "nominal"

    cycle_stage = "early"
    if persistence == 2:
        cycle_stage = "warning"
    elif persistence >= 3:
        cycle_stage = "critical"

    # Get Zero-Dependency Grounding Context
    grounding = get_grounding_context(motor_id)

    result = {
        "event": fault_type,
        "event_clean": event_clean,
        "deviation_level": deviation_level,
        "failure_mode": failure_mode,
        "persistence_cycles": persistence,
        "duration_human": duration_str,
        "trend": drifts.get("trend_direction", "STABLE"),
        "severity": severity,
        "urgency": action_data["urgency"],
        "recommended_action": action_data["action"],
        "variation_level": variation_level,
        "possible_causes": possible_causes,
        "state": state,
        "cycle_stage": cycle_stage,
        "current_vs_baseline_pct": current_dev_pct,
        "previous_summary": prev_summary,
        "bdi_current": baseline.get("bdi_current", 0.0),
        "bdi_temp": baseline.get("bdi_temp", 0.0),
        "motor_specs": grounding["motor_specs"],
        "grounding_context": grounding,
    }
    if schematics:
        result["schematics"] = schematics
    return result
