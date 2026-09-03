from src.agents.operator_checklist_agent import OperatorChecklistAgent
from src.agents.thermal_agent import ThermalExpert


def test_operator_checklist_agent_heuristics():
    """Verifies that OperatorChecklistAgent correctly processes visual shift inspections."""
    agent = OperatorChecklistAgent()

    # Case A: Healthy / No Flags
    data_healthy = {
        "grounding_context": {
            "operator_inspection": {
                "shaft_wobble": False,
                "bearing_grinding": False,
                "stator_clogged": False,
                "oil_leak": False,
                "operator_name": "Rizwin",
            }
        }
    }
    result_healthy = agent.analyze(data_healthy)
    assert result_healthy["severity"] == "NONE"
    assert result_healthy["failure_mode"] == "NONE"
    assert "nominal" in result_healthy["reasoning"]

    # Case B: Warning / Bearing Grinding
    data_warning = {
        "grounding_context": {
            "operator_inspection": {
                "shaft_wobble": False,
                "bearing_grinding": True,
                "stator_clogged": False,
                "oil_leak": False,
                "operator_name": "Rizwin",
            }
        }
    }
    result_warning = agent.analyze(data_warning)
    assert result_warning["severity"] == "WARNING"
    assert result_warning["failure_mode"] == "Mechanical Friction"
    assert "shaft wobble or bearing grinding" in result_warning["reasoning"]

    # Case C: Critical / Oil Leak
    data_critical = {
        "grounding_context": {
            "operator_inspection": {
                "shaft_wobble": False,
                "bearing_grinding": False,
                "stator_clogged": False,
                "oil_leak": True,
                "operator_name": "Rizwin",
            }
        }
    }
    result_critical = agent.analyze(data_critical)
    assert result_critical["severity"] == "CRITICAL"
    assert result_critical["failure_mode"] == "Seal Failure"
    assert "active casing oil leak" in result_critical["reasoning"]


def test_thermal_expert_dynamic_coefficients():
    """Verifies that ThermalExpert dynamically loads custom twin coefficients from grounding specs."""
    expert = ThermalExpert()

    # Default case (no custom specs, falls back to config)
    data_default = {"currents": [1.5, 1.5, 1.5], "temperatures": [40.0, 40.0, 40.0]}
    result_default = expert.analyze(data_default)
    assert result_default["severity"] == "NONE"
    assert (
        result_default["confidence"] in ["HIGH", 1.0, 0.75, 0.5]
        or float(result_default["confidence"]) >= 0.5
    )

    # Custom specs case (overriding R_TH and C_TH to make it extremely sensitive)
    data_sensitive = {
        "currents": [2.5, 2.5, 2.5],
        "temperatures": [40.0, 40.0, 40.0],
        "grounding_context": {
            "motor_specs": {
                "r_th": 150.0,  # Extremely high thermal resistance (overheats instantly)
                "c_th": 1.0,  # Extremely low thermal capacitance (no thermal damping)
                "rated_voltage": 230,
                "efficiency": 0.80,
                "max_temp_c": 125.0,
            }
        },
    }

    result_sensitive = expert.analyze(data_sensitive)

    # Due to extremely high R_TH and extremely low C_TH, predicted winding temp must saturate and trigger severe stress
    assert result_sensitive["predicted_max_temp"] > 200.0
    assert result_sensitive["severity"] in ["MEDIUM", "HIGH"]
    assert (
        "thermal saturation" in result_sensitive["reasoning"]
        or " winding stress" in result_sensitive["reasoning"]
    )
