import time

import pytest

from src.engines import signal_controller
from src.utils.database import db


@pytest.fixture(autouse=True)
def setup_signal_tests(motor_context):
    db.clear_history(motor_context.motor_id)
    motor_context.state_buffer = []
    motor_context.last_state = "OFF"


def test_get_baseline_no_history(motor_context):
    assert signal_controller.get_baseline(motor_context) is None


def test_get_baseline_single_healthy(motor_context):
    db.log_cycle(motor_context.motor_id, 2.2, 35.0, 180, {}, "PHYSICAL")

    baseline = signal_controller.get_baseline(motor_context)
    assert baseline["avg_current"] == 2.2
    assert baseline["avg_temp"] == 35.0
    assert baseline["avg_runtime"] == 180


def test_get_baseline_ema_update(motor_context):
    # Cycle 1
    db.log_cycle(motor_context.motor_id, 2.0, 30.0, 100, {}, "PHYSICAL")
    time.sleep(0.1)  # Ensure unique timestamp

    # Cycle 2 (Fast move to 3.0)
    db.log_cycle(motor_context.motor_id, 3.0, 35.0, 110, {}, "PHYSICAL")

    baseline = signal_controller.get_baseline(motor_context)

    # α_slow = 0.05
    # slow = (0.95 * 2.0) + (0.05 * 3.0) = 1.9 + 0.15 = 2.05
    assert baseline["avg_current"] == pytest.approx(2.05)
    # slow_temp = (0.95 * 30.0) + (0.05 * 35.0) = 28.5 + 1.75 = 30.25
    assert baseline["avg_temp"] == pytest.approx(30.25)


def test_get_baseline_freeze_on_fault(motor_context):
    # 3 Healthy cycles
    for _ in range(3):
        db.log_cycle(motor_context.motor_id, 2.0, 30.0, 100, {}, "PHYSICAL")
        time.sleep(0.1)

    baseline_before = signal_controller.get_baseline(motor_context)

    # 4th cycle is a fault
    cycle_id = db.log_cycle(motor_context.motor_id, 5.0, 60.0, 100, {}, "PHYSICAL")
    db.log_event(cycle_id, {"event": "OVERLOAD", "severity": "HIGH"})

    baseline_after = signal_controller.get_baseline(motor_context)

    # Baseline should be identical (frozen)
    assert baseline_after["avg_current"] == baseline_before["avg_current"]
    assert baseline_after["avg_temp"] == baseline_before["avg_temp"]


def test_compute_drift_with_baseline(motor_context):
    db.log_cycle(motor_context.motor_id, 2.0, 30.0, 100, {}, "PHYSICAL")

    current_summary = {"avg_current": 2.2, "max_temp": 33.0, "runtime": 100}
    drifts = signal_controller.compute_drift(motor_context, current_summary)

    # current_drift = (2.2 - 2.0) / 2.0 = 0.1 (10%)
    assert drifts["current_drift"] == pytest.approx(0.1)
    # temp_drift = (33.0 - 30.0) / 30.0 = 0.1 (10%)
    assert drifts["temp_drift"] == pytest.approx(0.1)


def test_get_trend_type_gradual(motor_context):
    for i in range(5):
        db.log_cycle(motor_context.motor_id, 2.0 + (i * 0.1), 30.0, 100, {}, "PHYSICAL")
        time.sleep(0.1)

    # Current trend is increasing (0.1 increase per cycle)
    # window = [2.0, 2.1, 2.2, 2.3, 2.4]
    # compute_slope uses window[-5:]
    # window has [2.0, 2.1, 2.2, 2.3, 2.4, 2.5] (including current_avg)
    # window[-5:] = [2.1, 2.2, 2.3, 2.4, 2.5]
    # slope = (2.5 - 2.1) / 5 = 0.08
    # 0.08 > 0.02 threshold -> GRADUAL_INCREASE
    assert signal_controller.get_trend_type(motor_context, 2.5) == "GRADUAL_INCREASE"


def test_get_motor_state(motor_context):
    # OFF state
    assert signal_controller.get_motor_state(motor_context, 0.01, 0) == "OFF"

    # STARTING (current > threshold)
    # threshold = 0.5, hysteresis = 0.1. OFF -> RUNNING if > 0.6
    # Buffer has [0.01]. If we add 1.0, smooth = 0.505. Still OFF.
    # Add another 1.0, smooth = (0.01 + 1.0 + 1.0) / 3 = 0.67. Now STARTING.
    signal_controller.get_motor_state(motor_context, 1.0, 1)
    assert signal_controller.get_motor_state(motor_context, 1.0, 1) == "STARTING"

    assert signal_controller.get_motor_state(motor_context, 1.0, 2) == "STARTING"

    # RUNNING (after startup ignore time)
    # startup ignore time = 20 (from config.py)
    assert signal_controller.get_motor_state(motor_context, 1.0, 21) == "RUNNING"

    # Back to OFF
    # threshold = 0.5, hysteresis = 0.1. RUNNING -> OFF if < 0.4
    # Buffer has [1.0, 1.0, 1.0].
    # Add 0.1 -> [1.0, 1.0, 0.1] (0.7)
    # Add 0.1 -> [1.0, 0.1, 0.1] (0.4)
    # Add 0.1 -> [0.1, 0.1, 0.1] (0.1) -> OFF
    signal_controller.get_motor_state(motor_context, 0.1, 22)
    signal_controller.get_motor_state(motor_context, 0.1, 23)
    assert signal_controller.get_motor_state(motor_context, 0.1, 24) == "OFF"


def test_get_baseline_validation_valid(motor_context):
    from src.core.profile_manager import save_profile

    test_profile = {
        "motor_name": "Test Pump A",
        "rated_current": 3.0,
        "max_temp_c": 100.0,
        "service_factor": 1.15,
    }
    save_profile(test_profile)

    try:
        # Healthy current is 2.5 (less than 3.0 * 1.15)
        db.log_cycle(motor_context.motor_id, 2.5, 50.0, 120, {}, "PHYSICAL")
        baseline = signal_controller.get_baseline(motor_context)
        assert baseline is not None
        assert baseline["validation_status"] == "VALID"
        assert baseline["avg_current"] == 2.5
        assert len(baseline["validation_notes"]) == 0
    finally:
        # Restore default profile
        from src.core.profile_manager import DEFAULT_PROFILE

        save_profile(DEFAULT_PROFILE)


def test_get_baseline_validation_invalid(motor_context):
    from src.core.profile_manager import save_profile

    test_profile = {
        "motor_name": "Test Pump A",
        "rated_current": 2.0,
        "max_temp_c": 100.0,
        "service_factor": 1.15,
    }
    save_profile(test_profile)

    try:
        # Overloaded current is 3.5 (greater than 2.0 * 1.15)
        # Temp is 85.0 (greater than 100 * 0.8)
        db.log_cycle(motor_context.motor_id, 3.5, 85.0, 120, {}, "PHYSICAL")
        baseline = signal_controller.get_baseline(motor_context)
        assert baseline is not None
        assert baseline["validation_status"] == "INVALID"
        # Baseline current should be clamped to rated_current (2.0)
        assert baseline["avg_current"] == 2.0
        # Winding stress temp should also generate warning
        assert any("exceeds nameplate safety limit" in n for n in baseline["validation_notes"])
        assert any("Elevated thermal stress suspected" in n for n in baseline["validation_notes"])
    finally:
        # Restore default profile
        from src.core.profile_manager import DEFAULT_PROFILE

        save_profile(DEFAULT_PROFILE)
