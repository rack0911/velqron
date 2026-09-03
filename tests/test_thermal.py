import json

from src.agents.thermal_agent import ThermalExpert


def test_thermal_physics():
    expert = ThermalExpert()

    # Simulate a high load cycle
    # 5A current (way above typical 0.68A baseline)
    data = {
        "currents": [5.0] * 100,
        "temperatures": [25.0] * 100,
        "baseline": {"avg_current": 0.68, "avg_temp": 25.0},
    }

    result = expert.analyze(data)
    print(json.dumps(result, indent=4))

    assert result["severity"] != "NONE"
    assert result["predicted_max_temp"] > 25.0
    print(" Thermal Physics Test Passed!")


if __name__ == "__main__":
    try:
        test_thermal_physics()
    except Exception as e:
        print(f"[FAIL] Test Failed: {e}")
