import json
import os

from src.core.profile_manager import load_profile, save_profile


def test_profile_persistence():
    """Verifies that motor configuration is saved and loaded correctly."""
    test_profile = {
        "motor_name": "Test Motor X",
        "rated_current": 10.5,
        "rated_temp": 100.0,
        "location": "Test Lab",
    }

    # Save it
    save_profile(test_profile)

    # Load it
    loaded = load_profile()
    assert loaded["motor_name"] == "Test Motor X"
    assert loaded["rated_current"] == 10.5

    # Cleanup
    if os.path.exists("data/motor_profile.json"):
        os.remove("data/motor_profile.json")


def test_simulated_data_loading():
    """Ensures simulated_cycles.json exists and is valid for demo mode."""
    assert os.path.exists("tests/fixtures/simulated_cycles.json")
    with open("tests/fixtures/simulated_cycles.json", "r") as f:
        data = json.load(f)
    assert len(data) > 0
    assert "current_series" in data[0]
    assert "profile" in data[0]
