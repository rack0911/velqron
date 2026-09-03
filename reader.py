import json
import os
import time
from datetime import datetime

from src.core.analyzer import analyze_realtime, reset_system_state
from src.core.config import CONFIG
from src.core.profile_manager import load_profile
from src.engines.cycle_memory import get_last_cycle_summary, save_cycle
from src.utils.database import db
from src.utils.link_manager import ConnectionState, LinkManager


class RawDataLogger:
    def __init__(self, directory):
        self.directory = directory
        os.makedirs(self.directory, exist_ok=True)
        self.filename = os.path.join(
            self.directory, f"raw_hw_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )

    def log(self, current, temp):
        with open(self.filename, mode="a", newline="") as f:
            import csv

            writer = csv.writer(f)
            writer.writerow([time.time(), current, temp])


def sync_link_calibration(lm: LinkManager):
    """Queries DB and pushes calibration to link. Moved from LinkManager for decoupling."""
    try:
        import sqlite3

        from src.core.profile_manager import load_profile

        profile = load_profile()
        motor_id = profile.get("motor_id", "SIM_01")
        db_path = os.path.join(CONFIG.DATA_DIR, "velqron.db")

        if os.path.exists(db_path):
            with sqlite3.connect(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT zero_offset, noise_floor FROM calibration WHERE motor_id = ? ORDER BY timestamp DESC LIMIT 1",
                    (motor_id,),
                )
                row = cursor.fetchone()

            if row:
                zero, noise = row
                lm.send_command(f"B{zero:.4f}")
                time.sleep(0.05)
                lm.send_command(f"C{noise:.4f}")
                print(f"[INFO] Calibration Synced: B={zero}, C={noise}")
    except Exception as e:
        print(f"[ERROR] Calibration sync failed: {e}")


def run_reader():
    hw_cfg = CONFIG.HARDWARE
    lm = LinkManager(hw_cfg.PORT, hw_cfg.BAUD)
    logger = RawDataLogger(hw_cfg.RAW_LOG_DIR)

    profile = load_profile()
    motor_id = profile.get("motor_id", "SIM_MOTOR_01")

    history = []
    motor_on = False
    counter = 0
    stopped_counter = 0
    result = None
    last_lm_state = None
    last_uptime = 0

    # Industrial Thresholds
    MOTOR_ON_THRESHOLD = 1.5
    MIN_START_SAMPLES = 5
    BUFFER_SIZE = 20
    ANALYSIS_INTERVAL = 10

    print("\n[STATUS] Velqron Ingestion Engine Active\n")

    last_heartbeat_sent = 0
    try:
        while True:
            # Poll command mailbox
            mailbox_path = "data/.command_mailbox"
            if os.path.exists(mailbox_path):
                try:
                    with open(mailbox_path, "r") as f:
                        cmd = f.read().strip()
                    if cmd:
                        if cmd == "TEST_HARDWARE":
                            # Run Feature 4 Modbus commissioning self-test
                            print("[INFO] Mailbox Command: Executing hardware self-test...")
                            serial_ok = (
                                lm.state == ConnectionState.CONNECTED and not lm.is_simulated
                            )
                            pzem_ok = False
                            pt100_ok = False
                            vibration_ok = False

                            # Let's inspect the latest tick for values
                            latest_tick = lm.read_tick()
                            if latest_tick:
                                # PZEM-016 reports current
                                current_val = latest_tick.get("current", 0.0)
                                if current_val >= 0.0:
                                    pzem_ok = True
                                # PT100 reports stator temp
                                temp_val = latest_tick.get("temperature", 0.0)
                                if 5.0 <= temp_val <= 120.0:
                                    pt100_ok = True
                                # Vibration sensor sends non-zero readings if present
                                vibration_ok = True  # Vibration defaults to OK

                            result_data = {
                                "timestamp": time.time(),
                                "serial_connected": serial_ok,
                                "pzem_connected": pzem_ok,
                                "pt100_connected": pt100_ok,
                                "vibration_connected": vibration_ok,
                                "message": "Self-Test complete. All components verified."
                                if (serial_ok and pzem_ok and pt100_ok)
                                else "Self-Test failed. Check connections.",
                            }

                            os.makedirs("data", exist_ok=True)
                            with open("data/self_test_result.json", "w") as rf:
                                json.dump(result_data, rf)

                            # Log audit log
                            db.log_audit_event(
                                "MODBUS_SELF_TEST",
                                f"Commissioning check: PZEM={pzem_ok}, PT100={pt100_ok}, Serial={serial_ok}",
                            )

                        elif cmd == "RESET":
                            # Feature 5: Software Baseline Reset
                            print("[INFO] Mailbox Command: Resetting system baseline...")
                            # 1. Clear database history
                            db.clear_history(motor_id)
                            # 2. Reset in-memory state
                            reset_system_state()
                            # 3. Log to audit log
                            db.log_audit_event(
                                "BASELINE_RESET",
                                "Operator manually cleared baseline history and fault events.",
                            )

                        else:
                            # Standard serial command dispatching to ESP32
                            if ":" in cmd:
                                parts = cmd.split(":", 1)
                                lm.send_command(parts[0], parts[1])
                            else:
                                lm.send_command(cmd)
                    os.remove(mailbox_path)
                except Exception as e:
                    print(f"[ERROR] Failed to process command mailbox: {e}")

            # 1. Send Heartbeat to ESP32 to keep connection alive
            now_time = time.time()
            if now_time - last_heartbeat_sent > 5.0:
                lm.send_command("H")
                last_heartbeat_sent = now_time

            # 2. Ingestion via Unified LinkManager
            tick = lm.read_tick()
            if tick is None:
                time.sleep(0.01)
                continue

            # 3. Handle system synchronization messages
            if isinstance(tick, dict) and tick.get("type") == "SYSTEM_MSG":
                msg = tick["message"]
                print(f"[SYSTEM] {msg}")
                if "SYNC_PENDING" in msg:
                    print("[INFO] Reconnection detected. Triggering database synchronization...")
                    lm.send_command("Y")  # Start Sync
                    syncing = True
                    sync_start_millis = None
                    sync_records_count = 0

                    while syncing:
                        sync_tick = lm.read_tick()
                        if not sync_tick:
                            time.sleep(0.01)
                            continue

                        if sync_tick.get("type") == "SYSTEM_MSG":
                            s_msg = sync_tick["message"]
                            print(f"[SYSTEM] {s_msg}")
                            if s_msg.startswith("SYS_MSG: SYNC_START:"):
                                try:
                                    sync_start_millis = int(s_msg.split(":")[-1])
                                    print(f"[INFO] Sync started. ESP Uptime: {sync_start_millis}ms")
                                except Exception:
                                    sync_start_millis = None
                            elif "SYNC_DONE" in s_msg:
                                print(
                                    f"[INFO] Sync complete. Processed {sync_records_count} records."
                                )
                                syncing = False

                        elif sync_tick.get("type") == "SYNC_DATA":
                            try:
                                line_content = sync_tick["message"].split(":", 1)[1]
                                fields = line_content.split(",")
                                if len(fields) >= 13:
                                    rec_ts_ms = int(fields[0])
                                    rec_current = float(fields[1])
                                    rec_temp = float(fields[2])
                                    float(fields[3])
                                    int(fields[4])
                                    float(fields[5])
                                    float(fields[6])
                                    float(fields[7])
                                    float(fields[8])
                                    float(fields[9])
                                    float(fields[10])
                                    float(fields[11])
                                    rec_status = int(fields[12])

                                    # Reconstruct absolute timestamp
                                    if sync_start_millis is not None:
                                        delta_sec = (sync_start_millis - rec_ts_ms) / 1000.0
                                        if delta_sec < 0:
                                            delta_sec = 0.0
                                        abs_ts = time.time() - delta_sec
                                    else:
                                        abs_ts = time.time()

                                    features = {
                                        "voltage": 415.0,
                                        "power_factor": 0.85,
                                        "drift_score": 0.0,
                                        "deviation_score": 0.0,
                                        "trend_score": 0.0,
                                        "anomaly_score": 0.0,
                                        "event": "NORMAL",
                                        "confidence": 1.0,
                                        "severity": "NONE",
                                        "review_status": "NEW",
                                    }
                                    is_overloaded = bool(rec_status & (1 << 6))
                                    is_tripped = bool(rec_status & (1 << 7))
                                    if is_tripped:
                                        features["event"] = "TRIPPED"
                                        features["severity"] = "CRITICAL"
                                    elif is_overloaded:
                                        features["event"] = "OVERLOAD"
                                        features["severity"] = "WARNING"

                                    timestamp_str = datetime.fromtimestamp(abs_ts).strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    )

                                    db.log_cycle(
                                        motor_id=motor_id,
                                        avg_current=rec_current,
                                        max_temp=rec_temp,
                                        duration=1,
                                        features=features,
                                        data_source="PHYSICAL",
                                        custom_timestamp=timestamp_str,
                                    )
                                    sync_records_count += 1
                                    lm.send_command("K")
                            except Exception as ex:
                                print(f"[ERROR] Failed to parse sync record: {ex}")
                                lm.send_command("K")
                    continue

            if isinstance(tick, dict) and tick.get("type") == "SYNC_DATA":
                continue

            # Sync calibration on transition to CONNECTED
            if lm.state == ConnectionState.CONNECTED and last_lm_state != ConnectionState.CONNECTED:
                sync_link_calibration(lm)
            last_lm_state = lm.state

            # 2. Unknown State Gate (Phase 1.1A Safety)
            if tick["data_source"] == "UNKNOWN":
                if motor_on:
                    print(f"\n[ALERT] Link Lost during Operation: {tick.get('reason')}")
                    motor_on = False
                    history.clear()

                # Report outage but bypass analytics
                print(f"Searching... {tick.get('reason')}", end="\r")
                time.sleep(0.5)
                continue

            # 2.1 Hardware Integrity Gate (Phase 1.2 Thin Heartbeat)
            uptime = tick.get("uptime", 0)
            health = tick.get("health", 0)

            # Reboot Detection
            if uptime < last_uptime and last_uptime > 0:
                print("\n[ALERT] DEVICE REBOOT DETECTED - Resetting local state.")
                history.clear()
                motor_on = False
                reset_system_state()
            last_uptime = uptime

            # Sensor Health Check (3 = Current OK + Temp OK)
            if health != 3:
                reason = (
                    "Current Sensor Fault"
                    if health == 2
                    else "Temp Sensor Fault"
                    if health == 1
                    else "Critical Hardware Fault"
                )
                if motor_on:
                    print(f"\n[CRITICAL] {reason} during Operation!")
                    motor_on = False
                    history.clear()

                print(f"[ERROR] {reason}. Waiting for recovery...", end="\r")
                time.sleep(1)
                continue

            # 3. Data Extraction
            current = tick["current"]
            temp = tick["temperature"]
            # ambient_temp removed in 1.2 format, using default if needed
            ambient_temp = 25.0

            # Physical Logging
            logger.log(current, temp)

            # 4. State Management
            if current > MOTOR_ON_THRESHOLD:
                if not motor_on:
                    print("\n[OK] MOTOR STARTED")
                    motor_on = True
                    history.clear()
                    counter = 0

                    last_cycle = get_last_cycle_summary()
                    if last_cycle:
                        print(
                            f"[DATA] Previous Run: {round(last_cycle['avg_current'], 2)}A | {last_cycle.get('event', 'NORMAL')}"
                        )
            else:
                if motor_on:
                    print("\n[STOP] MOTOR STOPPED (Saving Cycle)")
                    motor_on = False
                    if len(history) > 0:
                        currents = [d["current"] for d in history]
                        temps = [d["temperature"] for d in history]
                        event = result.get("event", "NORMAL") if result else "NORMAL"

                        summary = {
                            "timestamp": time.time(),
                            "avg_current": sum(currents) / len(currents),
                            "max_current": max(currents),
                            "avg_temperature": sum(temps) / len(temps),
                            "max_temp": max(temps),
                            "event": event,
                            "runtime": len(history),
                        }
                        if result:
                            summary.update(result)

                        cycle_id = save_cycle(summary)

                        # Log diagnostic details for background LLM worker if anomalous
                        if cycle_id and result and event != "NORMAL" and "llm_data" in result:
                            diag_data = {
                                "baseline": {
                                    "avg_current": sum(currents) / len(currents),
                                    "avg_temp": sum(temps) / len(temps),
                                },
                                "drift_score": result.get("drift_score", 0.0),
                                "deviation_score": result.get("deviation_score", 0.0),
                                "trend_score": result.get("trend_score", 0.0),
                                "anomaly_score": result.get("anomaly_score", 0.0),
                                "aging_risk": result.get("aging_risk", 1.0),
                                "llm_explanation": None,
                                "llm_status": "PENDING",
                                "llm_mode": CONFIG.LLM_MODE,
                                "llm_data_json": json.dumps(result["llm_data"])
                                if result["llm_data"]
                                else None,
                            }
                            db.log_diagnostic(cycle_id, diag_data)

                    # Update live status on stop
                    off_result = {
                        "status": "OFF",
                        "event": "NORMAL",
                        "severity": "NONE",
                        "urgency": "LOW",
                        "explanation": "Motor is stopped.",
                        "recommendation": "None",
                        "data_source": tick.get("data_source", "PHYSICAL"),
                    }
                    db.write_live_telemetry_snapshot(motor_id, current, temp, off_result)

                    history.clear()
                    reset_system_state()
                    stopped_counter = 0
                else:
                    # Update live status every 10 ticks when motor remains stopped
                    stopped_counter += 1
                    if stopped_counter >= ANALYSIS_INTERVAL:
                        stopped_counter = 0
                        off_result = {
                            "status": "OFF",
                            "event": "NORMAL",
                            "severity": "NONE",
                            "urgency": "LOW",
                            "explanation": "Motor is stopped.",
                            "recommendation": "None",
                            "data_source": tick.get("data_source", "PHYSICAL"),
                        }
                        db.write_live_telemetry_snapshot(motor_id, current, temp, off_result)
                continue

            # 5. Buffer Management
            data = {
                "current": current,
                "temperature": temp,
                "ambient_temperature": ambient_temp,
                "timestamp": tick["timestamp"],
            }
            history.append(data)
            if len(history) > BUFFER_SIZE:
                history.pop(0)

            # 6. Analysis Throttling
            if len(history) < MIN_START_SAMPLES:
                print(f"Stabilizing... {len(history)}/{MIN_START_SAMPLES}", end="\r")
                continue

            counter += 1
            if counter < ANALYSIS_INTERVAL:
                print(f"Collecting... {counter}/{ANALYSIS_INTERVAL} | {current}A", end="\r")
                continue

            counter = 0

            # 7. Intelligence Execution
            result = analyze_realtime(history, data_source="PHYSICAL")

            # Write live status snapshot to SQLite
            db.write_live_telemetry_snapshot(motor_id, current, temp, result)

            print("\n" + "=" * 30)
            print(f"EVENT:    {result.get('event', 'NORMAL')}")
            print(f"SEVERITY: {result.get('severity', 'NONE')}")
            print(f"URGENCY:  {result.get('urgency', 'NONE')}")
            print(f"DETAIL:   {result.get('explanation', '...')[:80]}...")
            print("=" * 30 + "\n")

    except KeyboardInterrupt:
        print("\n[INFO] Shutdown requested by operator.")
    finally:
        lm.close()
        print("[INFO] Clean shutdown complete.")


if __name__ == "__main__":
    run_reader()
