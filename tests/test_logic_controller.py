import time
from unittest.mock import patch

import pytest

from src.core.motor_context import MotorContext
from src.core.types import CycleMetrics
from src.engines import logic_controller
from src.utils.database import db


@pytest.fixture
def motor_context():
    return MotorContext(motor_id="TEST_MOTOR")


@pytest.fixture(autouse=True)
def setup_logic_tests(motor_context):
    logic_controller.reset_persistence_state(motor_context)
    db.clear_history(motor_context.motor_id)
    motor_context.event_history = []


def create_metrics(**kwargs):
    defaults = {
        "motor_id": "TEST_MOTOR",
        "avg_current": 2.0,
        "max_current": 2.2,
        "std_current": 0.01,
        "avg_temp": 30.0,
        "max_temp": 30.0,
        "runtime_sec": 60.0,
        "startup_slope": 0.05,
        "peak_to_mean": 1.4,
        "variation_level": "LOW",
        "timestamp": time.time(),
    }
    defaults.update(kwargs)
    return CycleMetrics(**defaults)


@pytest.fixture
def mock_profile():
    with patch("src.core.profile_manager.load_profile") as mock:
        mock.return_value = {"rated_current": 2.5, "max_temp_c": 125.0, "service_factor": 1.15}
        yield mock


def test_detect_fault_normal_op(motor_context, mock_profile):
    baseline = {"avg_current": 2.0, "avg_temp": 30.0}
    # 2.05A vs 2.0A baseline = 2.5% dev (well below 15% center)
    # 2.05A vs 2.5A rated = below rated
    metrics = create_metrics(avg_current=2.05)

    event, vote, confidence = logic_controller.detect_fault(
        motor_context, metrics, "RUNNING", baseline, "STABLE"
    )

    assert event == "NORMAL"
    assert vote is False
    assert confidence == 1.0


def test_detect_fault_stable_overload(motor_context, mock_profile):
    baseline = {"avg_current": 2.0, "avg_temp": 30.0}
    # 2.4A vs 2.0A baseline = 20% deviation. Center of sigmoid is 15% (0.15).
    metrics = create_metrics(avg_current=2.4)

    event, vote, confidence = logic_controller.detect_fault(
        motor_context, metrics, "RUNNING", baseline, "STABLE"
    )

    assert event == "STABLE_OVERLOAD"
    assert vote is True
    assert confidence > 0.8


def test_detect_fault_unstable_load(motor_context, mock_profile):
    baseline = {"avg_current": 2.0, "avg_temp": 30.0}
    # std_current 0.15 is above 0.10 threshold
    metrics = create_metrics(avg_current=2.0, std_current=0.15)

    event, vote, confidence = logic_controller.detect_fault(
        motor_context, metrics, "RUNNING", baseline, "STABLE"
    )

    assert event == "UNSTABLE_LOAD"
    assert vote is True
    assert confidence > 0.9
