import sqlite3

import pytest

from src.engines import anomaly_engine, baseline_engine
from src.utils.database import db


@pytest.fixture(autouse=True)
def setup_db(isolated_config):
    """Ensure clean isolated DB for each test."""
    db._init_db()
    yield db


def test_baseline_calculation_empty():
    """Verify that scores default to 0 on empty history."""
    scores = baseline_engine.calculate_baseline_scores(
        "TEST_MOTOR",
        {"avg_current": 2.2, "std_current": 0.05, "power_factor": 0.85, "avg_temp": 40.0},
    )
    assert scores["drift_score"] == 0.0
    assert scores["deviation_score"] == 0.0
    assert scores["trend_score"] == 0.0


def test_baseline_calculation_normal_progression():
    """Verify calculation of drift, deviation, and trend scores with some history."""
    # Write some historical cycles with variance
    for i in range(5):
        curr = [1.95, 2.05, 2.0, 1.98, 2.02][i]
        temp = [34.0, 36.0, 35.0, 34.5, 35.5][i]
        db.log_cycle("TEST_MOTOR", curr, temp, 100, {}, "PHYSICAL")

    # Calculate scores with a sudden change
    metrics = {"avg_current": 3.0, "std_current": 0.15, "power_factor": 0.9, "avg_temp": 50.0}
    scores = baseline_engine.calculate_baseline_scores("TEST_MOTOR", metrics)

    # Drift and deviation should be non-zero due to the sudden jump
    assert scores["drift_score"] > 0.0
    assert scores["deviation_score"] > 0.0
    # Trend score should also reflect positive slope
    assert scores["trend_score"] > 0.0


def test_anomaly_engine_unsupervised_trigger():
    """Verify IsolationForest anomaly detection behavior."""
    import numpy as np

    # Seed 50 normal cycles with variance
    np.random.seed(42)
    for _i in range(50):
        curr = float(np.random.normal(2.0, 0.1))
        temp = float(np.random.normal(35.0, 1.0))
        pf = float(np.random.normal(0.85, 0.02))
        std_curr = float(np.random.normal(0.05, 0.01))
        db.log_cycle(
            "TEST_MOTOR", curr, temp, 100, {"power_factor": pf, "current_std": std_curr}, "PHYSICAL"
        )

    # Anomaly metrics (significantly out of bounds)
    anomaly_metrics = {
        "avg_current": 10.0,
        "std_current": 1.5,
        "power_factor": 0.3,
        "avg_temp": 95.0,
    }
    score, is_anomaly = anomaly_engine.train_and_score_anomaly("TEST_MOTOR", anomaly_metrics)

    # Large deviation should trigger 3-sigma anomaly
    assert is_anomaly


def test_database_phase13_schemas():
    """Verify the 4 required Phase 13 schemas exist and function correctly."""
    with sqlite3.connect(db.db_path) as conn:
        cursor = conn.cursor()

        # Verify machine_registry columns
        cursor.execute("PRAGMA table_info(machine_registry)")
        cols = {row[1]: row[2] for row in cursor.fetchall()}
        assert "motor_id" in cols
        assert "asset_name" in cols
        assert "location" in cols
        assert "rated_voltage" in cols
        assert "rated_current" in cols
        assert "rated_power_kw" in cols
        assert "rated_speed_rpm" in cols
        assert "insulation_class" in cols
        assert "service_factor" in cols
        assert "installation_date" in cols

        # Verify fault_dataset columns
        cursor.execute("PRAGMA table_info(fault_dataset)")
        fds_cols = {row[1]: row[2] for row in cursor.fetchall()}
        assert "drift_score" in fds_cols
        assert "deviation_score" in fds_cols
        assert "trend_score" in fds_cols
        assert "anomaly_score" in fds_cols
        assert "rule_flags" in fds_cols
        assert "rule_confidence" in fds_cols
        assert "review_status" in fds_cols


def test_evidence_store_logs_mapped():
    """Verify that logging and updates map correctly to fault_dataset."""
    cycle_id = db.log_cycle("MTR_01", 2.2, 45.0, 120, {"power_factor": 0.82})
    assert cycle_id is not None

    # Update event details
    db.log_event(cycle_id, {"event": "OVERHEAT", "severity": "HIGH", "confidence": 0.88})

    # Update diagnostic details
    db.log_diagnostic(
        cycle_id,
        {
            "baseline": {"avg_current": 2.0, "avg_temp": 40.0},
            "drift_score": 0.1,
            "deviation_score": 1.2,
            "trend_score": 0.05,
            "anomaly_score": 0.15,
            "aging_risk": {"risk": "LOW"},
            "llm_explanation": "Test explanation.",
            "llm_status": "COMPLETED",
            "llm_mode": "Local Only",
            "llm_data_json": "{}",
        },
    )

    # Verify the final state in the SQLite database
    with sqlite3.connect(db.db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM fault_dataset WHERE id = ?", (cycle_id,)).fetchone()
        assert row is not None
        assert row["motor_id"] == "MTR_01"
        assert row["current"] == 2.2
        assert row["temperature_rise"] == 45.0
        assert row["rule_flags"] == "OVERHEAT"
        assert row["severity"] == "HIGH"
        assert row["rule_confidence"] == 0.88
        assert row["drift_score"] == 0.1
        assert row["deviation_score"] == 1.2
        assert row["trend_score"] == 0.05
        assert row["anomaly_score"] == 0.15
        assert row["llm_explanation"] == "Test explanation."


def test_usb_disconnect_recovery(monkeypatch):
    """
    USB disconnect recovery integration test.
    Scenario:
      1. Hardware connected: reads physical ticks.
      2. USB disconnected: read raises SerialException, transitions to simulation.
      3. USB reconnected after 15 seconds: reader reconnects and reads physical ticks again.
      4. Verify database writes survive.
    """
    import serial

    from src.utils.link_manager import LinkManager
    from src.utils.serial_detector import ConnectionState

    port_present = True

    class MockSerialPort:
        def __init__(self, port, baud, timeout=1.0):
            self.port = port
            self.is_open = True

        def readline(self):
            if not port_present:
                raise serial.SerialException("USB Disconnected")
            return b"2.2,35.0,3\n"

        def write(self, data):
            pass

        def flush(self):
            pass

        def close(self):
            self.is_open = False

    def mock_find_esp32_port():
        return "/dev/ttyUSB0" if port_present else None

    monkeypatch.setattr("serial.Serial", MockSerialPort)
    monkeypatch.setattr("src.utils.serial_detector.find_esp32_port", mock_find_esp32_port)

    # 1. Start connected
    lm = LinkManager(port=None)
    assert lm.connect() is True
    assert lm.is_simulated is False
    assert lm.state == ConnectionState.CONNECTED

    tick = lm.read_tick()
    assert tick is not None
    assert tick["data_source"] == "PHYSICAL"
    assert tick["current"] == 2.2

    # 2. USB Disconnected
    port_present = False

    # First read tick after disconnect triggers SerialException and sets RECONNECTING
    tick_dis = lm.read_tick()
    assert lm.is_simulated is True
    assert lm.state == ConnectionState.RECONNECTING
    assert tick_dis["data_source"] == "SIMULATED"

    # 3. Simulate 15 seconds passing (reset backoff throttle)
    lm.last_connection_attempt_ts = 0.0

    # Read should continue simulation
    tick_sim = lm.read_tick()
    assert lm.is_simulated is True
    assert tick_sim["data_source"] == "SIMULATED"

    # 4. USB Reconnected
    port_present = True
    lm.last_connection_attempt_ts = 0.0

    # Read should try to reconnect and succeed
    tick_rec = lm.read_tick()
    assert lm.is_simulated is False
    assert lm.state == ConnectionState.CONNECTED
    assert tick_rec["data_source"] == "PHYSICAL"
    assert tick_rec["current"] == 2.2

    # 5. Verify database survives
    db.write_live_telemetry_snapshot(
        "TEST_MOTOR", tick_rec["current"], tick_rec["temperature"], {"status": "RUNNING"}
    )
    row = db.get_latest_telemetry_row("TEST_MOTOR")
    assert row is not None
    assert row["current"] == 2.2
    assert row["operating_mode"] == "RUNNING"
