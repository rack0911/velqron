import time
from typing import Tuple

import numpy as np

from src.core.motor_context import MotorContext
from src.core.types import CycleMetrics
from src.utils.logger import get_logger

logger = get_logger(__name__)

# --- FUZZY LOGIC UTILS ---


def sigmoid_membership(x, center, width=0.10):
    """
    Returns a membership degree [0, 1] using a sigmoid function.
    x: input value
    center: the threshold where membership is 0.5
    width: controls the sharpness of the transition (widened to 0.10 for better 'Gray Area' coverage)
    """
    return 1.0 / (1.0 + np.exp(-(x - center) / (width / 4.0)))


# --- EVENT & PERSISTENCE ---


def detect_fault(
    context: MotorContext, metrics: CycleMetrics, state, baseline, trend_type, slope=0.0
) -> Tuple[str, bool, float]:
    """
    Returns (raw_event, vote, confidence).
    Optimized for industrial signal-to-noise ratio using Fuzzy Sigmoids.
    """
    from src.core.profile_manager import load_profile

    # Safety: If motor is off, return NORMAL
    if state != "RUNNING":
        return "NORMAL", False, 1.0

    profile = load_profile()
    rated_current = profile.get("rated_current", 2.2)
    max_temp_limit = profile.get("max_temp_c", 125.0)
    service_factor = profile.get("service_factor", 1.15)

    # 1. BASELINE FALLBACK (Jump-start logic)
    avg_i_baseline = baseline.get("avg_current", 0)
    if avg_i_baseline < 0.1:
        avg_i_baseline = rated_current  # Fallback to nameplate grounding

    current_dev = (
        (metrics.avg_current - avg_i_baseline) / avg_i_baseline if avg_i_baseline > 0 else 0
    )
    temp_rise = metrics.max_temp - baseline.get("avg_temp", 30.0)

    # 2. HARDWARE ANOMALIES & SENSOR DROPS
    if metrics.avg_current < 0.05:
        if metrics.max_temp < (baseline.get("avg_temp", 30.0) + 10):
            return "NORMAL", False, 1.0
        return "HARDWARE_ANOMALY", True, 1.0

    # 3. ABSOLUTE LIMIT CHECKS (Safety First)
    thermal_conf = sigmoid_membership(metrics.max_temp, max_temp_limit, width=5.0)
    if thermal_conf > 0.5:
        return "STABLE_OVERLOAD", True, thermal_conf

    # 4. BASELINE-RELATIVE CHECKS
    # DRY RUN (Sigmoid transition around -20%)
    dry_run_conf = sigmoid_membership(-current_dev, 0.20)
    if dry_run_conf > 0.5 and temp_rise < 5:
        return "DRY_RUN", True, dry_run_conf

    # OVERLOAD (Sigmoid transition around 12% - tuned for sensitivity)
    overload_conf = sigmoid_membership(current_dev, 0.12)

    spec_overload_val = (
        (metrics.avg_current - rated_current) / rated_current if rated_current > 0 else 0
    )
    spec_overload_conf = sigmoid_membership(spec_overload_val, service_factor - 1.05)

    combined_overload_conf = max(overload_conf, spec_overload_conf)

    if combined_overload_conf > 0.5:
        event = "DEGRADING_OVERLOAD" if trend_type == "GRADUAL_INCREASE" else "STABLE_OVERLOAD"
        return event, True, combined_overload_conf

    # UNSTABLE LOAD (Mechanical Ripple - Sigmoid at 0.10)
    unstable_conf = sigmoid_membership(metrics.std_current, 0.10, width=0.05)
    if unstable_conf > 0.5:
        return "UNSTABLE_LOAD", True, unstable_conf

    # GRADUAL DEGRADATION (Sub-threshold but trending - Sigmoid at 0.08)
    degrade_conf = sigmoid_membership(current_dev, 0.08)
    if degrade_conf > 0.5 and trend_type == "GRADUAL_INCREASE":
        return "DEGRADING_OVERLOAD", True, degrade_conf

    return "NORMAL", False, 1.0


def stabilize_event(context: MotorContext, raw_event):
    """Prevents false positives through anti-flip and mode filtering."""
    prev_event = context.event_history[-1] if context.event_history else None

    if raw_event == "NORMAL":
        context.record_event(raw_event)
        return raw_event

    # Impossible transitions prevent jitter between fault types
    impossible_transitions = {
        ("UNSTABLE_LOAD", "DRY_RUN"),
        ("DRY_RUN", "UNSTABLE_LOAD"),
    }
    if (prev_event, raw_event) in impossible_transitions:
        raw_event = prev_event

    context.record_event(raw_event)
    return raw_event


def update_persistence(context: MotorContext, event_type, severity=None, duration=None):
    """
    Tracks duration and cross-cycle stability of faults.
    Updated for Phase 1.3: Uses crash-safe Core Memory fields.
    """
    current_ts = time.time()

    # Track previous summary for LLM context (stays in RAM/Reconstructed)
    if context.active_event and context.active_event != "NORMAL":
        context.persistence_data = {
            "event": context.active_event,
            "severity": severity or "LOW",
            "duration": duration or "0 sec",
        }

    had_any_fault = context.active_event is not None and context.active_event != "NORMAL"
    has_any_fault = event_type is not None and event_type != "NORMAL"

    if has_any_fault and had_any_fault:
        context.fault_count += 1
        context.active_event = event_type
    elif has_any_fault:
        context.active_event = event_type
        context.fault_count = 1
        context.first_seen_ts = current_ts
    else:
        # Reset state if current cycle is NORMAL
        context.active_event = "NORMAL"
        context.fault_count = 0
        context.first_seen_ts = None

    # Force persistence check at end of cycle
    return context.fault_count


def reset_persistence_state(context: MotorContext):
    """Clears all persistent and in-memory context."""
    from src.utils.database import db

    db.clear_history(context.motor_id)
    context.reset_state()


def get_event_duration(context: MotorContext):
    """Calculates duration based on persistent first_seen_ts."""
    if not context.first_seen_ts:
        return 0.0
    return round((time.time() - context.first_seen_ts) / 60, 2)


def get_previous_summary(context: MotorContext):
    """Returns the last summary for context assembly."""
    return context.persistence_data


def calculate_drift(context: MotorContext, current_features):
    """Compares current cycle against the 'Gold Standard' fingerprint."""
    # We load gold standard from DB on demand (Phase 1.3 Audit Decision)
    from src.utils.database import db

    gold = db.load_gold_fingerprint(context.motor_id)
    if not gold or not current_features:
        return 0.0
    distances = [
        abs(current_features[k] - gold[k]) / gold[k]
        for k in gold
        if k in current_features and gold[k] != 0
    ]
    return round(float(np.mean(distances)), 3) if distances else 0.0


def update_gold_fingerprint(context: MotorContext, new_features, is_healthy=True):
    """Updates gold standard in the Evidence Store."""
    if not is_healthy or not new_features:
        return
    from src.utils.database import db

    db.update_gold_standard(context.motor_id, new_features)
