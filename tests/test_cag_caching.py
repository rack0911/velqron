from src.utils.dual_explainer import build_split_prompts


def test_build_split_prompts_separation():
    """Verifies that static context is isolated in system_prompt and dynamic context in user_prompt."""
    data = {
        "event_clean": "stable overload",
        "failure_mode": "Overload",
        "severity": "MEDIUM",
        "urgency": "MEDIUM",
        "recommended_action": "Check load bindings.",
        "duration_human": "3 min",
        "persistence_cycles": 3,
        "trend": "INCREASING",
        "bdi_current": 1.25,
        "bdi_temp": 0.45,
        "deviation_level": "elevated",
        "sanity_check": {"status": "HEALTHY"},
        "schematics": {"electrical_cabinet_id": "CAB-MAIN-04", "contactor_id": "K3-M1"},
        "grounding_context": {
            "motor_specs": {
                "manufacturer": "Baldor",
                "model": "M3546-5",
                "rated_current": 1.5,
                "max_temp_c": 135.0,
                "location": "Pump House 2",
                "rpm": 1440,
                "insulation_class": "H",
            },
            "commissioning_record": {
                "symmetry_ratio": 1.02,
                "zero_offset": 0.0456,
                "noise_floor": 0.0123,
            },
            "cycle_summaries": [
                {"cycle_id": 10, "avg_current": 1.48, "max_temp": 42.0, "verdict": "NORMAL"}
            ],
            "maintenance_records": [
                {
                    "timestamp": "2026-05-22",
                    "operator_status": "CLOSED",
                    "verdict": "RESOLVED",
                    "notes": "Fittings tightened",
                }
            ],
            "operator_inspection": {
                "shaft_wobble": False,
                "bearing_grinding": True,
                "stator_clogged": False,
                "oil_leak": False,
                "operator_name": "Rizwin",
                "notes": "Audible bearing chirp",
            },
        },
    }

    system_prompt, user_prompt = build_split_prompts(data)

    # Assert System Prompt holds the static specifications (CAG)
    assert "You are a senior industrial reliability engineer" in system_prompt
    assert "STATIC GROUNDING SPECIFICATIONS" in system_prompt
    assert "Manufacturer Baldor" in system_prompt
    assert "Model M3546-5" in system_prompt
    assert "Zero Offset 0.0456" in system_prompt
    assert "CAB-MAIN-04" in system_prompt
    assert "K3-M1" in system_prompt

    # Assert System Prompt does NOT hold transient cycle metrics
    assert "ANOMALY EVENT PARTICULARS" not in system_prompt
    assert "stable overload" not in system_prompt
    assert "Check load bindings." not in system_prompt

    # Assert User Prompt holds the dynamic parameters (RAG)
    assert "ANOMALY EVENT PARTICULARS" in user_prompt
    assert "Event: stable overload" in user_prompt
    assert "Failure Mode: Overload" in user_prompt
    assert "Duration: 3 min" in user_prompt
    assert "Persistence: 3 cycles" in user_prompt
    assert "Current BDI 1.25" in user_prompt
    assert "Temp BDI 0.45" in user_prompt
    assert "Active Visual Shift Checklist" in user_prompt
    assert "Bearing Grinding True" in user_prompt
    assert "Operator: Rizwin" in user_prompt
    assert "Audible bearing chirp" in user_prompt
    assert "Cycle ID 10" in user_prompt
    assert "Fittings tightened" in user_prompt

    # Assert User Prompt does NOT contain system instructions
    assert "You are a senior industrial reliability engineer" not in user_prompt
