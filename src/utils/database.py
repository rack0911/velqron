import csv
import gzip
import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from src.utils.db_connection import DatabaseConnection
from src.utils.logger import get_logger

logger = get_logger(__name__)


class EvidenceStore(DatabaseConnection):
    def __init__(self, db_path=None):
        super().__init__(db_path)
        # Execute rolling wave files 30-day purge policy during startup initialization
        try:
            self.purge_old_raw_waveforms()
        except Exception as e:
            logger.warning(f"Initial raw waveform purge failed: {e}")

    # --- Persistence/State check-point helpers ---

    def get_system_state(self, motor_id: str) -> Optional[Dict]:
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT state_json FROM system_state WHERE motor_id = ?", (motor_id,)
                )
                row = cursor.fetchone()
                return json.loads(row[0]) if row else None
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch system state for motor {motor_id}: {e}")
            return None

    def save_system_state(self, motor_id: str, state_json: str) -> bool:
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO system_state (motor_id, state_json, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(motor_id) DO UPDATE SET
                        state_json = excluded.state_json,
                        updated_at = CURRENT_TIMESTAMP
                """,
                    (motor_id, state_json),
                )
                conn.commit()
                return True
        except sqlite3.Error as e:
            logger.error(f"Failed to save system state for motor {motor_id}: {e}")
            return False

    def get_last_event_types(self, motor_id: str, limit: int = 3) -> List[str]:
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT rule_flags FROM fault_dataset
                    WHERE motor_id = ? AND rule_flags IS NOT NULL AND rule_flags != ''
                    ORDER BY timestamp DESC LIMIT ?
                """,
                    (motor_id, limit),
                )
                rows = cursor.fetchall()
                return [row[0] for row in rows][::-1]  # Chronological
        except sqlite3.Error:
            return []

    def get_last_current_averages(self, motor_id: str, limit: int = 5) -> List[float]:
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT current FROM fault_dataset
                    WHERE motor_id = ? AND current IS NOT NULL
                    ORDER BY timestamp DESC LIMIT ?
                """,
                    (motor_id, limit),
                )
                rows = cursor.fetchall()
                return [row[0] for row in rows][::-1]  # Chronological
        except sqlite3.Error:
            return []

    # --- Evidence Store logging mapping to Phase 13 schemas ---

    def log_cycle(
        self,
        motor_id,
        avg_current,
        max_temp,
        duration,
        features,
        data_source="PHYSICAL",
        times=None,
        currents=None,
        temperatures=None,
        custom_timestamp=None,
    ):
        features = features if isinstance(features, dict) else {}
        try:
            timestamp_str = (
                custom_timestamp if custom_timestamp else time.strftime("%Y-%m-%d %H:%M:%S")
            )
            with self._connect() as conn:
                cursor = conn.cursor()
                # Ensure machine_registry has this motor
                cursor.execute("SELECT 1 FROM machine_registry WHERE motor_id = ?", (motor_id,))
                if not cursor.fetchone():
                    cursor.execute(
                        """
                        INSERT INTO machine_registry (motor_id, asset_name, location, rated_voltage, rated_current, insulation_class, service_factor)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            motor_id,
                            "Motor " + motor_id,
                            "Central Utility Room",
                            415.0,
                            2.2,
                            "F",
                            1.15,
                        ),
                    )

                cursor.execute(
                    """
                    INSERT INTO fault_dataset (
                        motor_id, timestamp, operating_mode, voltage, current, power_factor, temperature_rise,
                        drift_score, deviation_score, trend_score, anomaly_score, rule_flags, rule_confidence,
                        review_status, severity, duration_sec, data_source
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        motor_id,
                        timestamp_str,
                        "RUNNING",
                        features.get("voltage", 415.0),
                        avg_current,
                        features.get("power_factor", 0.85),
                        max_temp,
                        features.get("drift_score", 0.0),
                        features.get("deviation_score", 0.0),
                        features.get("trend_score", 0.0),
                        features.get("anomaly_score", 0.0),
                        features.get("event", "NORMAL"),
                        features.get("confidence", 1.0),
                        features.get("review_status", "NEW"),
                        features.get("severity", "NONE"),
                        duration,
                        data_source,
                    ),
                )
                cycle_id = cursor.lastrowid
                conn.commit()

            # Save Compressed Waveform
            if times is not None and currents is not None:
                try:
                    self.save_raw_waveform(
                        cycle_id, times, currents, temperatures or [max_temp] * len(times)
                    )
                except Exception as e:
                    logger.error(f"Failed to save raw waveform for cycle {cycle_id}: {e}")

            return cycle_id
        except sqlite3.Error as e:
            logger.error(f"Failed to log cycle to database: {e}")
            return None

    def log_event(self, cycle_id, event_data):
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE fault_dataset
                    SET rule_flags = ?, severity = ?, rule_confidence = ?
                    WHERE id = ?
                """,
                    (
                        event_data["event"],
                        event_data["severity"],
                        event_data.get("confidence", 0.0),
                        cycle_id,
                    ),
                )
                conn.commit()
                return cycle_id
        except sqlite3.Error as e:
            logger.error(f"Failed to log event for cycle {cycle_id}: {e}")
            return None

    def log_diagnostic(self, event_id, diag_data):
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE fault_dataset
                    SET baseline_current = ?, baseline_temperature = ?, baseline_pf = ?,
                        drift_score = ?, deviation_score = ?, trend_score = ?, anomaly_score = ?,
                        aging_risk = ?, llm_explanation = ?, llm_status = ?, llm_mode = ?, llm_data_json = ?
                    WHERE id = ?
                """,
                    (
                        diag_data["baseline"].get("avg_current"),
                        diag_data["baseline"].get("avg_temp"),
                        diag_data["baseline"].get("avg_pf", 0.85),
                        diag_data.get("drift_score", 0.0),
                        diag_data.get("deviation_score", 0.0),
                        diag_data.get("trend_score", 0.0),
                        diag_data.get("anomaly_score", 0.0),
                        json.dumps(diag_data.get("aging_risk")),
                        diag_data.get("llm_explanation"),
                        diag_data.get("llm_status", "PENDING"),
                        diag_data.get("llm_mode"),
                        diag_data.get("llm_data_json"),
                        event_id,
                    ),
                )
                conn.commit()
                return event_id
        except sqlite3.Error as e:
            logger.error(f"Failed to log diagnostic for event {event_id}: {e}")
            return None

    def log_agent_findings(self, diagnostic_id, findings):
        # Kept for interface backward-compatibility (agent findings omitted or logged to warnings)
        pass

    def add_operator_feedback(self, event_id, feedback_type, note=""):
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT motor_id, rule_flags FROM fault_dataset WHERE id = ?", (event_id,)
                )
                row = cursor.fetchone()
                if row:
                    motor_id, rule_diagnosis = row
                    timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")
                    is_correct = 1 if feedback_type == "CORRECT" else 0
                    cursor.execute(
                        """
                        INSERT INTO engineer_feedback (motor_id, timestamp, rule_diagnosis, actual_root_cause, is_correct, notes)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """,
                        (motor_id, timestamp_str, rule_diagnosis, feedback_type, is_correct, note),
                    )

                    cursor.execute(
                        """
                        UPDATE fault_dataset SET review_status = ? WHERE id = ?
                    """,
                        (feedback_type, event_id),
                    )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to add operator feedback for event {event_id}: {e}")

    def get_operator_feedback_list(self, motor_id: str, limit: int = 50) -> List[Dict]:
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, timestamp, rule_diagnosis, actual_root_cause, is_correct, notes
                    FROM engineer_feedback
                    WHERE motor_id = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                """,
                    (motor_id, limit),
                )
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch operator feedback list: {e}")
            return []

    def get_recent_cycles_with_details(self, limit=50):
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                query = """
                    SELECT id, timestamp, motor_id, current as avg_current, temperature_rise as max_temp,
                           duration_sec, rule_flags as event_type, severity, rule_confidence as confidence,
                           aging_risk, data_source
                    FROM fault_dataset
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                cursor.execute(query, (limit,))
                rows = cursor.fetchall()
                res = []
                for row in rows:
                    d = dict(row)
                    if d.get("aging_risk"):
                        try:
                            d["aging_risk"] = json.loads(d["aging_risk"])
                        except Exception:
                            pass
                    res.append(d)
                return res
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch recent cycles: {e}")
            return []

    def get_fleet_baseline(self, motor_model: str):
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                query = """
                    SELECT AVG(current) as fleet_avg_i, AVG(temperature_rise) as fleet_avg_t
                    FROM fault_dataset
                """
                cursor.execute(query)
                row = cursor.fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch fleet baseline: {e}")
            return None

    def get_cycle_audit_trail(self, cycle_id):
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM fault_dataset WHERE id = ?", (cycle_id,))
                row = cursor.fetchone()
                if not row:
                    return None

                d = dict(row)
                event_dict = {
                    "id": d["id"],
                    "cycle_id": d["id"],
                    "timestamp": d["timestamp"],
                    "event_type": d["rule_flags"],
                    "severity": d["severity"],
                    "confidence": d["rule_confidence"],
                    "failure_mode": d["rule_flags"],
                    "explanation": d["llm_explanation"],
                    "operator_status": d["review_status"],
                }

                event_dict["diagnostic"] = {
                    "baseline_json": json.dumps(
                        {
                            "avg_current": d["baseline_current"],
                            "avg_temp": d["baseline_temperature"],
                        }
                    ),
                    "thresholds_json": "{}",
                    "reasoning": "",
                    "llm_explanation": d["llm_explanation"],
                    "recommendation": "",
                    "urgency": "",
                    "aging_risk": d["aging_risk"],
                }

                cursor.execute(
                    "SELECT * FROM engineer_feedback WHERE motor_id = ? ORDER BY timestamp DESC",
                    (d["motor_id"],),
                )
                feedback = cursor.fetchall()
                event_dict["operator_feedback"] = [dict(fb) for fb in feedback]

                return event_dict
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch audit trail for cycle {cycle_id}: {e}")
            return None

    def save_raw_waveform(self, cycle_id, times, currents, temperatures):
        try:
            data_dir = os.path.expanduser("~/.mcsa_data/raw_waves")
            os.makedirs(data_dir, exist_ok=True)
            file_path = os.path.join(data_dir, f"{cycle_id}.csv.gz")

            with gzip.open(file_path, "wt", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["time", "current", "temperature"])
                for t, c, temp in zip(times, currents, temperatures, strict=False):
                    writer.writerow([t, c, temp])
            return file_path
        except Exception as e:
            logger.error(f"Failed to save raw waveform for cycle {cycle_id}: {e}")
            return None

    def purge_old_raw_waveforms(self):
        try:
            data_dir = os.path.expanduser("~/.mcsa_data/raw_waves")
            if not os.path.exists(data_dir):
                return

            now = time.time()
            cutoff = now - (30 * 24 * 60 * 60)

            for filename in os.listdir(data_dir):
                if filename.endswith(".csv.gz"):
                    file_path = os.path.join(data_dir, filename)
                    try:
                        mtime = os.path.getmtime(file_path)
                        if mtime < cutoff:
                            os.remove(file_path)
                    except Exception as e:
                        logger.warning(f"Failed to purge waveform {filename}: {e}")
        except Exception as e:
            logger.error(f"Purge process failed: {e}")

    def log_operator_inspection(
        self,
        motor_id,
        shaft_wobble,
        bearing_grinding,
        stator_clogged,
        oil_leak,
        operator_name="Operator",
        notes="",
    ):
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO operator_inspections (motor_id, shaft_wobble, bearing_grinding, stator_clogged, oil_leak, operator_name, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        motor_id,
                        int(shaft_wobble),
                        int(bearing_grinding),
                        int(stator_clogged),
                        int(oil_leak),
                        operator_name,
                        notes,
                    ),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to log operator inspection for motor {motor_id}: {e}")

    def get_latest_operator_inspection(self, motor_id):
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM operator_inspections
                    WHERE motor_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """,
                    (motor_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch latest inspection for motor {motor_id}: {e}")
            return None

    def get_latest_diagnostic(self, motor_id):
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, timestamp, rule_flags as event_type, severity, rule_confidence as confidence,
                           llm_explanation, llm_status, llm_mode
                    FROM fault_dataset
                    WHERE motor_id = ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """,
                    (motor_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch latest diagnostic: {e}")
            return None

    def get_latest_completed_explanation(self, motor_id, event_type):
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT llm_explanation, llm_data_json
                    FROM fault_dataset
                    WHERE motor_id = ? AND rule_flags = ? AND llm_status = 'COMPLETED' AND llm_explanation IS NOT NULL
                    ORDER BY timestamp DESC
                    LIMIT 1
                """,
                    (motor_id, event_type),
                )
                row = cursor.fetchone()
                if row:
                    return row[0], row[1]
                return None, None
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch cached explanation: {e}")
            return None, None

    def load_recent_cycles(self, motor_id, n=None):
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                if n:
                    query = """
                        SELECT *, rule_flags as event, current as avg_current, temperature_rise as max_temp,
                               duration_sec as runtime
                        FROM fault_dataset
                        WHERE motor_id = ?
                        ORDER BY timestamp DESC, id DESC
                        LIMIT ?
                    """
                    cursor.execute(query, (motor_id, n))
                else:
                    query = """
                        SELECT *, rule_flags as event, current as avg_current, temperature_rise as max_temp,
                               duration_sec as runtime
                        FROM fault_dataset
                        WHERE motor_id = ?
                        ORDER BY timestamp ASC, id ASC
                    """
                    cursor.execute(query, (motor_id,))
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Failed to load recent cycles: {e}")
            return []

    def clear_history(self, motor_id):
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM fault_dataset WHERE motor_id = ?", (motor_id,))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to clear history for motor {motor_id}: {e}")

    def load_persistence(self, motor_id):
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM fault_dataset WHERE motor_id = ? ORDER BY timestamp DESC LIMIT 1",
                    (motor_id,),
                )
                row = cursor.fetchone()
                if row:
                    return {
                        "last_event": row["rule_flags"],
                        "count": row["drift_score"],  # compatibility count mapped to drift_score
                        "first_seen_ts": time.time(),
                        "last_seen_ts": time.time(),
                        "last_severity": row["severity"],
                        "schema_version": "1.1",
                    }
                return {
                    "last_event": None,
                    "count": 0,
                    "first_seen_ts": None,
                    "last_seen_ts": None,
                    "prev_summary": None,
                    "schema_version": "1.1",
                }
        except sqlite3.Error as e:
            logger.error(f"Failed to load persistence: {e}")
            return {
                "last_event": None,
                "count": 0,
                "first_seen_ts": None,
                "last_seen_ts": None,
                "prev_summary": None,
                "schema_version": "1.1",
            }

    def load_gold_fingerprint(self, motor_id):
        return None

    def update_gold_standard(self, motor_id, fingerprint):
        return True

    def update_diagnostic_explanation(self, diag_id, explanation):
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE fault_dataset
                    SET llm_explanation = ?, llm_status = 'COMPLETED'
                    WHERE id = ?
                """,
                    (explanation, diag_id),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to update diagnostic {diag_id} explanation: {e}")

    def write_live_telemetry_snapshot(self, motor_id, current, temp, results):
        try:
            timestamp_str = time.strftime("%Y-%m-%d %H:%M:%S")
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO live_status (
                        motor_id, timestamp, current, temperature, operating_mode,
                        voltage, power_factor, drift_score, deviation_score, trend_score, anomaly_score,
                        rule_flags, rule_confidence, severity, urgency, explanation, recommendation, data_source,
                        time_to_trip
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        motor_id,
                        timestamp_str,
                        current,
                        temp,
                        results.get("status", "RUNNING"),
                        results.get("voltage", 415.0),
                        results.get("power_factor", 0.85),
                        results.get("drift_score", 0.0),
                        results.get("deviation_score", 0.0),
                        results.get("trend_score", 0.0),
                        results.get("anomaly_score", 0.0),
                        results.get("event", "NORMAL"),
                        results.get("confidence", 1.0),
                        results.get("severity", "NONE"),
                        results.get("urgency", "LOW"),
                        results.get("explanation", "System operating normally."),
                        results.get("recommendation", "Continue Monitoring"),
                        results.get("data_source", "PHYSICAL"),
                        results.get("time_to_trip"),
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to write live telemetry snapshot: {e}")

    def get_latest_telemetry_row(self, motor_id):
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM live_status WHERE motor_id = ?", (motor_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        except sqlite3.Error as e:
            logger.error(f"Failed to get latest telemetry row: {e}")
            return None

    def log_audit_event(self, action: str, details: str = "", operator: str = "System") -> bool:
        try:
            with self._connect() as conn:
                cursor = conn.conn.cursor() if hasattr(conn, "conn") else conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO audit_log (operator, action, details)
                    VALUES (?, ?, ?)
                """,
                    (operator, action, details),
                )
                conn.commit()
                return True
        except sqlite3.Error as e:
            logger.error(f"Failed to log audit event: {e}")
            return False

    def get_audit_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT timestamp, operator, action, details FROM audit_log
                    ORDER BY timestamp DESC LIMIT ?
                """,
                    (limit,),
                )
                rows = cursor.fetchall()
                return [
                    {"timestamp": row[0], "operator": row[1], "action": row[2], "details": row[3]}
                    for row in rows
                ]
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch audit logs: {e}")
            return []

    def update_machine_registry(self, profile: dict):
        try:
            motor_id = profile.get("motor_id", "SIM_MOTOR_01")
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM machine_registry WHERE motor_id = ?", (motor_id,))
                exists = cursor.fetchone()
                if exists:
                    query = """
                        UPDATE machine_registry
                        SET asset_name = ?,
                            location = ?,
                            rated_voltage = ?,
                            rated_current = ?,
                            insulation_class = ?,
                            service_factor = ?
                        WHERE motor_id = ?
                    """
                    cursor.execute(
                        query,
                        (
                            profile.get("motor_name", "Primary Pump A"),
                            profile.get("location", "Central Utility Room"),
                            float(profile.get("v_rated", 415.0)),
                            float(profile.get("rated_current", 2.2)),
                            profile.get("insulation_class", "F"),
                            float(profile.get("service_factor", 1.15)),
                            motor_id,
                        ),
                    )
                else:
                    query = """
                        INSERT INTO machine_registry (
                            motor_id, asset_name, location, rated_voltage, rated_current, insulation_class, service_factor
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """
                    cursor.execute(
                        query,
                        (
                            motor_id,
                            profile.get("motor_name", "Primary Pump A"),
                            profile.get("location", "Central Utility Room"),
                            float(profile.get("v_rated", 415.0)),
                            float(profile.get("rated_current", 2.2)),
                            profile.get("insulation_class", "F"),
                            float(profile.get("service_factor", 1.15)),
                        ),
                    )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to update machine_registry: {e}")


# Singleton instance
db = EvidenceStore()
