import json
import sqlite3
import time
from unittest.mock import MagicMock, patch

import pytest

import src.core.analyzer as analyzer
from src.core.config import CONFIG
from src.core.profile_manager import save_profile
from src.utils.database import db
from src.utils.pdf_parser import parse_motor_datasheet


@pytest.fixture
def temp_db(tmp_path):
    """Fixture to isolate SQLite database for tests."""
    db_file = tmp_path / "test_velqron.db"
    original_path = db.db_path
    db.db_path = str(db_file)
    db._init_db()
    yield db
    db.db_path = original_path


def test_async_llm_worker_remediation(temp_db, monkeypatch):
    """Verifies that background worker processes PENDING SQLite jobs end-to-end."""
    monkeypatch.setenv("CI_MODE", "true")

    # 1. Mock compare_explanations to return a 100% compliant JSON string
    compliant_json = json.dumps(
        {
            "situation": "The motor overload has persisted for 2 min across 2 cycles, indicating a stable and established pattern in the electrical drawing.",
            "interpretation": "Over the past 2 cycles, observation indicates sustained mechanical resistance causing elevated load relative to the normal baseline, consistent with chronic stress.",
            "risk": "Condition has persisted for 2 min showing no immediate escalation, but continued operation leads to gradual efficiency loss and thermal stress on components.",
            "justification": "A medium maintenance approach is appropriate since the condition has been stable over 2 cycles and is currently non-accelerating and chronic.",
        }
    )

    def mock_generate(data, mode=None):
        return "CI_MOCK: " + compliant_json

    monkeypatch.setattr("src.utils.dual_explainer.generate_reasoning", mock_generate)

    # 2. Stop existing analyzer background worker and start a fresh one on temp db
    analyzer._stop_worker.set()
    # Wait briefly for the thread to exit if it is running
    time.sleep(0.1)

    analyzer._worker_started = False
    analyzer._stop_worker.clear()
    analyzer.start_llm_worker()

    # 3. Log cycle and event
    cycle_id = temp_db.log_cycle("SIM_01", 1.5, 40.0, 10, {})
    event_id = temp_db.log_event(
        cycle_id,
        {
            "event": "STABLE_OVERLOAD",
            "severity": "MEDIUM",
            "confidence": 0.8,
            "failure_mode": "Overload",
            "persistence": 2,
            "summary": "Motor overload detected.",
        },
    )

    # 4. Log diagnostic with status PENDING
    llm_data = {
        "fault_type": "STABLE_OVERLOAD",
        "current_val": 1.8,
        "temp_val": 50.0,
        "duration_human": "2 min",
        "persistence_cycles": 2,
        "event_clean": "stable overload",
        "urgency": "MEDIUM",
        "failure_mode": "Overload",
        "trend": "INCREASING",
        "severity": "MEDIUM",
    }

    diag_id = temp_db.log_diagnostic(
        event_id,
        {
            "baseline": {"avg_current": 1.5, "avg_temp": 40.0},
            "thresholds": {},
            "reasoning": "High current draw.",
            "llm_explanation": None,
            "recommendation": "Check load.",
            "urgency": "MEDIUM",
            "aging_risk": 1.1,
            "version": "1.0.0",
            "llm_data_json": json.dumps(llm_data),
            "llm_status": "PENDING",
            "llm_mode": "Local Only",
        },
    )

    # Verify PENDING status in temp db
    conn = sqlite3.connect(temp_db.db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT llm_status, llm_explanation FROM fault_dataset WHERE id = ?", (diag_id,))
    row = cursor.fetchone()
    assert row[0] == "PENDING"
    assert row[1] is None
    conn.close()

    # 5. Wait for the background worker to poll and process
    found = False
    for _ in range(15):
        time.sleep(0.2)
        conn = sqlite3.connect(temp_db.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT llm_status, llm_explanation FROM fault_dataset WHERE id = ?", (diag_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if row and row[0] == "COMPLETED":
            assert "CI_MOCK" in row[1]
            found = True
            break
    assert found, "Background LLM worker failed to process PENDING diagnostic job"

    # Stop background worker thread to prevent thread leakage
    analyzer._stop_worker.set()
    analyzer._worker_started = False
    time.sleep(0.1)


def test_pdf_datasheet_parser_and_overrides(monkeypatch):
    """Verifies that PDF parser extracts manufacturer fields and profile manager applies overrides."""
    mock_reader = MagicMock()
    mock_page = MagicMock()
    dummy_text = """
    Manufacturer: Baldor Electric Co.
    Model: M3546-5
    Rated Current / FLA: 1.5 Amps
    Service Factor / SF: 1.25
    Insulation Class: H
    Max Temp: 135 C
    """
    mock_page.extract_text.return_value = dummy_text
    mock_reader.pages = [mock_page]

    with patch("src.utils.pdf_parser.PdfReader", return_value=mock_reader):
        parsed = parse_motor_datasheet("dummy.pdf")

    assert parsed["make"] == "Baldor Electric Co."
    assert parsed["model"] == "M3546-5"
    assert parsed["rated_current"] == 1.5
    assert parsed["service_factor"] == 1.25
    assert parsed["insulation_class"] == "H"
    assert parsed["max_temp_c"] == 135.0

    # Apply to profile and check CONFIG overrides
    test_profile = {
        "motor_name": "Baldor Pump",
        "rated_current": 1.5,
        "max_temp_c": 135.0,
        "insulation_class": "H",
        "service_factor": 1.25,
    }

    save_profile(test_profile)

    assert CONFIG.MOTOR_SPECS.SERVICE_FACTOR == 1.25
    from src.utils.link_manager import LinkManager

    ...

    def test_serial_calibration_sync(temp_db, monkeypatch, tmp_path):
        """Verifies that serial detector queries the calibration baseline and pushes correct commands."""
        conn = sqlite3.connect(temp_db.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO calibration (motor_id, zero_offset, noise_floor, rated_current, service_factor) VALUES (?, ?, ?, ?, ?)",
            ("SIM_01", 0.0456, 0.0123, 1.5, 1.15),
        )
        conn.commit()
        conn.close()

        # Configure DATA_DIR to point to our isolated tmp_path
        monkeypatch.setattr(CONFIG, "DATA_DIR", str(tmp_path))
        # Copy temporary database to tmp_path/velqron.db
        import shutil

        shutil.copy(temp_db.db_path, tmp_path / "velqron.db")

        lm = LinkManager()
        mock_ser = MagicMock()
        mock_ser.is_open = True
        lm.ser = mock_ser

        from reader import sync_link_calibration

        sync_link_calibration(lm)

        write_calls = [call[0][0] for call in mock_ser.write.call_args_list]
        assert b"B0.0456\n" in write_calls
        assert b"C0.0123\n" in write_calls
