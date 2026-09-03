import json

from src.engines.decision_engine import calculate_time_to_trip
from src.utils.database import db


def test_calculate_time_to_trip():
    custom_profile = {
        "r_th": 0.1,  # 0.1 C/W
        "c_th": 1000.0,  # 1000 J/C -> tau = 100s
        "rated_voltage": 230.0,
        "efficiency": 0.90,  # 10% loss
        "insulation_class": "F",  # Class F threshold = 155C
    }

    # 1. Winding temp already above Class F threshold:
    t = calculate_time_to_trip(
        avg_current=10.0, current_temp=160.0, ambient_temp=25.0, profile=custom_profile
    )
    assert t == 0.0

    # 2. Case where steady state temp rise is lower than trip threshold:
    # current = 2.0A -> p_loss = 46W -> rise = 4.6C -> steady_state = 29.6C
    # current_temp = 27C, trip = 155C. 29.6C <= 155C -> Will never trip!
    t = calculate_time_to_trip(
        avg_current=2.0, current_temp=27.0, ambient_temp=25.0, profile=custom_profile
    )
    assert t is None

    # 3. Case where it will trip:
    # steady_state = 200C. current_temp = 100C. trip = 155C.
    # ratio = (200 - 155) / (200 - 100) = 45 / 100 = 0.45.
    # t = -100 * ln(0.45) = 79.9 seconds.
    t = calculate_time_to_trip(
        avg_current=76.08, current_temp=100.0, ambient_temp=25.0, profile=custom_profile
    )
    assert t is not None
    assert abs(t - 79.9) < 1.0

    # 4. Error path test: invalid profile dictionary causing exception
    invalid_profile = {
        "r_th": "invalid_string",
        "c_th": 1000.0,
        "rated_voltage": 230.0,
        "efficiency": 0.90,
        "insulation_class": "F",
    }
    t = calculate_time_to_trip(
        avg_current=76.08, current_temp=100.0, ambient_temp=25.0, profile=invalid_profile
    )
    assert t is None


def test_audit_logs():
    action = "TEST_ACTION"
    details = "Manual baseline calibration reset via test suite"
    operator = "UnitTest"

    success = db.log_audit_event(action, details, operator)
    assert success

    logs = db.get_audit_logs(limit=5)
    assert len(logs) > 0

    latest = logs[0]
    assert latest["action"] == action
    assert latest["details"] == details
    assert latest["operator"] == operator


def test_profile_synchronization():
    from src.core.profile_manager import save_profile

    test_motor_id = "TEST_SYNC_MOTOR_99"
    profile_data = {
        "motor_id": test_motor_id,
        "motor_name": "Test Sync Pump",
        "location": "Test Bay 2",
        "v_rated": 480.0,
        "rated_current": 5.5,
        "insulation_class": "H",
        "service_factor": 1.25,
    }

    # Save profile (which now triggers SQLite registry update)
    success = save_profile(profile_data)
    assert success

    # Query database directly to confirm synchronization
    with db._connect() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT asset_name, rated_current, insulation_class FROM machine_registry WHERE motor_id = ?",
            (test_motor_id,),
        )
        row = cursor.fetchone()

    assert row is not None
    assert row[0] == "Test Sync Pump"
    assert row[1] == 5.5
    assert row[2] == "H"


def test_save_system_state_error():
    import sqlite3
    from unittest.mock import patch

    with patch.object(db, "_connect") as mock_connect:
        mock_connect.side_effect = sqlite3.Error("Mock database connection error")
        success = db.save_system_state("TEST_MOTOR_99", "{}")
        assert not success


def test_get_last_event_types_empty():
    events = db.get_last_event_types("NON_EXISTENT_MOTOR_ID_XYZ_12345", limit=3)
    assert events == []


def test_generate_thermal_gradient_plot_error():
    from unittest.mock import MagicMock, patch

    import src.utils.thermal_visualizer as tv

    with (
        patch.object(tv, "HAS_MATPLOTLIB", True),
        patch.object(tv, "plt", MagicMock(), create=True) as mock_plt,
    ):
        mock_plt.figure.side_effect = Exception("Mock matplotlib rendering failure")
        img_str = tv.generate_thermal_gradient_plot([10.0, 11.0], [50.0, 52.0])
        assert img_str is None


def test_build_static_grounding_str():
    from src.utils.dual_explainer import build_static_grounding_str

    # 1. Empty data
    assert build_static_grounding_str({}) == ""

    # 2. Populated specs
    mock_data = {
        "grounding_context": {
            "motor_specs": {
                "asset_name": "Test Pump X",
                "rated_voltage": 460,
                "rated_current": 10.5,
                "rated_power_kw": 5.5,
                "rated_speed_rpm": 1750,
                "insulation_class": "F",
                "service_factor": 1.15,
                "installation_date": "2026-01-01",
                "location": "Utility Room",
            }
        }
    }
    res = build_static_grounding_str(mock_data)
    assert "Test Pump X" in res
    assert "460 V" in res
    assert "10.5 A" in res


def test_build_dynamic_grounding_str():
    from src.utils.dual_explainer import build_dynamic_grounding_str

    # 1. Empty data
    assert build_dynamic_grounding_str({}) == ""

    # 2. Populated dynamic histories
    mock_data = {
        "grounding_context": {
            "cycle_summaries": [
                {
                    "timestamp": "2026-06-27 12:00:00",
                    "rule_flags": "STABLE_OVERLOAD",
                    "anomaly_score": 0.45,
                    "review_status": "NEW",
                }
            ],
            "maintenance_records": [
                {
                    "timestamp": "2026-06-20 08:00:00",
                    "action_taken": "Aligned shaft bearings",
                    "resolved": 1,
                }
            ],
        }
    }
    res = build_dynamic_grounding_str(mock_data)
    assert "STABLE_OVERLOAD" in res
    assert "0.45" in res
    assert "Aligned shaft bearings" in res


def test_log_agent_findings():
    # log_agent_findings is a backward-compatible placeholder pass method.
    # We call it and assert it does not crash or raise exceptions.
    db.log_agent_findings(999, "Dummy test agent findings")


def test_thermal_expert_empty_lists():
    from src.agents.thermal_agent import ThermalExpert

    agent = ThermalExpert()
    data = {"currents": [], "temperatures": [], "avg_current": None, "max_temp": None}
    res = agent.analyze(data)
    assert res is not None
    assert res["severity"] == "LOW"
    assert res["event"] == "NORMAL"


def test_local_explainer_timeout():
    from unittest.mock import patch

    import httpx

    from src.utils.dual_explainer import local_explainer

    with patch("httpx.Client.post") as mock_post:
        mock_post.side_effect = httpx.ConnectTimeout("Connection timed out")
        res = local_explainer({"grounding_context": {}})
        assert res == "ERROR: LOCAL_FAILED"


def test_insulation_expert_resistance():
    from src.agents.insulation_agent import InsulationExpert

    agent = InsulationExpert()

    # 1. Healthy state with resistance present
    data_healthy = {"features": {"insulation_resistance_mohm": 5.0}}
    res_healthy = agent.analyze(data_healthy)
    assert res_healthy["severity"] == "NONE"

    # 2. Critical degradation state
    data_degraded = {"features": {"insulation_resistance_mohm": 0.5}}
    res_degraded = agent.analyze(data_degraded)
    assert res_degraded["severity"] == "HIGH"
    assert res_degraded["failure_mode"] == "Insulation Degradation"

    # 3. Missing resistance check
    data_missing = {"features": {}}
    res_missing = agent.analyze(data_missing)
    assert res_missing["severity"] == "NONE"


def test_get_system_state():

    motor_id = "TEST_STATE_MOTOR_99"
    state_data = {"status": "operational", "load": "high"}

    # 1. Save state
    success = db.save_system_state(motor_id, json.dumps(state_data))
    assert success

    # 2. Retrieve state
    retrieved = db.get_system_state(motor_id)
    assert retrieved is not None
    assert retrieved["status"] == "operational"
    assert retrieved["load"] == "high"
