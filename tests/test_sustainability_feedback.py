import pytest

from src.core.config import CONFIG
from src.engines.decision_engine import calculate_sustainability_impact
from src.utils.database import EvidenceStore


def test_calculate_sustainability_impact():
    # Test no deviation
    res = calculate_sustainability_impact(
        avg_current=1.0, baseline_current=1.0, duration_sec=3600.0
    )
    assert res["excess_kwh"] == 0.0
    assert res["excess_co2_kg"] == 0.0
    assert res["excess_cost_usd"] == 0.0

    # Test active deviation
    res = calculate_sustainability_impact(
        avg_current=2.0, baseline_current=1.0, duration_sec=3600.0, voltage=230.0, power_factor=0.9
    )
    # Power = sqrt(3) * 230 * 1 * 0.9 / 1000 = 0.3585 kW
    # Energy = 0.3585 kW * 1 hour = 0.3585 kWh
    # CO2 = 0.3585 * 0.4 = 0.1434 kg
    # Cost = 0.3585 * 0.12 = 0.043 USD
    assert res["excess_kwh"] == pytest.approx(0.3585, abs=0.001)
    assert res["excess_co2_kg"] == pytest.approx(0.3585 * CONFIG.UTILITY_CO2_PER_KWH, abs=0.001)
    assert res["excess_cost_usd"] == pytest.approx(0.3585 * CONFIG.UTILITY_COST_PER_KWH, abs=0.001)


def test_operator_feedback_retrieval(tmp_path):
    db_file = tmp_path / "test_velqron.db"
    store = EvidenceStore(str(db_file))

    # Verify empty feedback list
    logs = store.get_operator_feedback_list("TEST_MOTOR")
    assert len(logs) == 0

    # Log some dummy cycle and event
    cycle_id = store.log_cycle(
        motor_id="TEST_MOTOR",
        avg_current=1.2,
        max_temp=40.0,
        duration=60,
        features={"event": "OVERLOAD", "severity": "MEDIUM"},
    )
    assert cycle_id is not None

    # Submit feedback
    store.add_operator_feedback(cycle_id, "CORRECT", "Verifiably correct overload diagnosis")

    # Retrieve and check
    logs = store.get_operator_feedback_list("TEST_MOTOR")
    assert len(logs) == 1
    assert logs[0]["rule_diagnosis"] == "OVERLOAD"
    assert logs[0]["actual_root_cause"] == "CORRECT"
    assert logs[0]["is_correct"] == 1
    assert logs[0]["notes"] == "Verifiably correct overload diagnosis"
