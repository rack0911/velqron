# signal_controller.py (Consolidated Signal Processing)
from typing import List, Optional

import numpy as np

from src.core.config import CONFIG
from src.core.motor_context import MotorContext
from src.core.types import CycleMetrics


def get_baseline(context: MotorContext):
    """Calculates baseline from healthy cycles only with freeze logic."""
    from src.utils.database import db

    history = db.load_recent_cycles(context.motor_id)
    if not history:
        return None

    # Map database fields to internal logic names
    for h in history:
        if "duration_sec" in h:
            h["runtime"] = h["duration_sec"]

    recent_3 = history[-3:] if len(history) >= 3 else history
    recent_has_fault = any(c.get("event") not in [None, "NORMAL"] for c in recent_3)

    learning_cycles = [
        c
        for c in history
        if c.get("event") in [None, "NORMAL"] and (c.get("avg_current") or 0) > 0.1
    ]
    if not learning_cycles:
        learning_cycles = [c for c in history if (c.get("avg_current") or 0) > 0.1][:3]

    if not learning_cycles:
        return None

    if recent_has_fault:
        pre_fault_normals = []
        for c in history:
            if c.get("event") in [None, "NORMAL"] and (c.get("avg_current") or 0) > 0.1:
                pre_fault_normals.append(c)
        learning_cycles = pre_fault_normals if pre_fault_normals else learning_cycles

    alpha_fast = 0.3
    alpha_slow = 0.05

    fast_current = learning_cycles[0]["avg_current"]
    slow_current = learning_cycles[0]["avg_current"]
    fast_temp = learning_cycles[0]["max_temp"]
    slow_temp = learning_cycles[0]["max_temp"]
    avg_runtime = learning_cycles[0]["runtime"]

    for cycle in learning_cycles[1:]:
        fast_current = ((1 - alpha_fast) * fast_current) + (alpha_fast * cycle["avg_current"])
        slow_current = ((1 - alpha_slow) * slow_current) + (alpha_slow * cycle["avg_current"])
        fast_temp = ((1 - alpha_fast) * fast_temp) + (alpha_fast * cycle["max_temp"])
        slow_temp = ((1 - alpha_slow) * slow_temp) + (alpha_slow * cycle["max_temp"])
        avg_runtime = ((1 - alpha_slow) * avg_runtime) + (alpha_slow * cycle["runtime"])

    # Sanity check against nameplate specs
    from src.core.profile_manager import load_profile

    profile = load_profile()
    rated_current = profile.get("rated_current", 2.2)
    max_temp_limit = profile.get("max_temp_c", 125.0)
    service_factor = profile.get("service_factor", 1.15)

    validation_status = "VALID"
    validation_notes = []

    if slow_current > rated_current * service_factor:
        validation_status = "INVALID"
        validation_notes.append(
            f"Auto-learned baseline current ({slow_current:.2f}A) exceeds nameplate safety limit "
            f"({rated_current * service_factor:.2f}A). Pre-existing fault/overload suspected. "
            f"Clamping baseline to rated current ({rated_current:.2f}A)."
        )
        # Clamp to rated current to prevent masking faults
        slow_current = rated_current

    if slow_temp > max_temp_limit * 0.8:
        if validation_status != "INVALID":
            validation_status = "WARNING"
        validation_notes.append(
            f"Auto-learned baseline temperature ({slow_temp:.1f}°C) exceeds 80% of safety limit "
            f"({max_temp_limit * 0.8:.1f}°C). Elevated thermal stress suspected."
        )

    bdi_current = abs(fast_current - slow_current) / slow_current if slow_current > 0 else 0.0
    bdi_temp = abs(fast_temp - slow_temp) / slow_temp if slow_temp > 0 else 0.0

    return {
        "avg_current": slow_current,
        "avg_temp": slow_temp,
        "avg_runtime": avg_runtime,
        "fast_current": fast_current,
        "fast_temp": fast_temp,
        "bdi_current": round(bdi_current, 4),
        "bdi_temp": round(bdi_temp, 4),
        "validation_status": validation_status,
        "validation_notes": validation_notes,
    }


def compute_drift(context: MotorContext, metrics: CycleMetrics):
    """Computes deviations from baseline."""
    baseline = get_baseline(context)
    if not baseline:
        return {"current_drift": 0.0, "temp_drift": 0.0, "runtime_drift": 0.0}

    if isinstance(metrics, dict):
        avg_current = metrics.get("avg_current", 0.0)
        max_temp = metrics.get("max_temp", 30.0)
        runtime_sec = metrics.get("runtime_sec") or metrics.get("runtime", 0.0)
    else:
        avg_current = getattr(metrics, "avg_current", 0.0)
        max_temp = getattr(metrics, "max_temp", 30.0)
        runtime_sec = getattr(metrics, "runtime_sec", None)
        if runtime_sec is None:
            runtime_sec = getattr(metrics, "runtime", 0.0)

    return {
        "current_drift": (avg_current - baseline["avg_current"]) / baseline["avg_current"]
        if baseline["avg_current"] > 0
        else 0.0,
        "temp_drift": (max_temp - baseline["avg_temp"]) / baseline["avg_temp"]
        if baseline["avg_temp"] > 0
        else 0.0,
        "runtime_drift": (runtime_sec - baseline["avg_runtime"]) / baseline["avg_runtime"]
        if baseline["avg_runtime"] > 0
        else 0.0,
    }


def get_trend_type(context: MotorContext, metrics: CycleMetrics):
    """Determines if the current is increasing, decreasing, or stable."""
    from src.utils.database import db

    history = db.load_recent_cycles(context.motor_id, n=5)

    if isinstance(metrics, (int, float)):
        avg_current = float(metrics)
    elif isinstance(metrics, dict):
        avg_current = metrics.get("avg_current", 0.0)
    else:
        avg_current = getattr(metrics, "avg_current", 0.0)

    avgs = [c["avg_current"] for c in history] + [avg_current]
    window = avgs[-5:]

    if len(window) < 2:
        return "STABLE"

    slope = (window[-1] - window[0]) / len(window)

    if slope > 0.02:
        return "GRADUAL_INCREASE"
    elif slope < -0.02:
        return "DECREASING"
    else:
        return "STABLE"


def get_motor_state(context: MotorContext, current: float, time_since_start: float):
    """Tracks motor operational state (OFF/STARTING/RUNNING)."""
    context.state_buffer.append(current)
    if len(context.state_buffer) > 3:
        context.state_buffer.pop(0)

    smooth_current = sum(context.state_buffer) / len(context.state_buffer)

    if smooth_current < CONFIG.NOISE_FLOOR:
        context.last_state = "OFF"
        return "OFF"

    threshold = CONFIG.MINIMUM_CURRENT_THRESHOLD
    if context.last_state == "OFF":
        if smooth_current > (threshold + CONFIG.HYSTERESIS_OFFSET):
            context.last_state = "RUNNING"
        else:
            return "OFF"
    else:
        if smooth_current < (threshold - CONFIG.HYSTERESIS_OFFSET):
            context.last_state = "OFF"
            return "OFF"

    if time_since_start < CONFIG.STARTUP_IGNORE_TIME:
        return "STARTING"

    return "RUNNING"


def detect_statistical_anomalies(context: MotorContext, currents: List[float]) -> Optional[str]:
    """
    Implements a Z-score based statistical anomaly check as a secondary signal.
    Useful for detecting transient spikes not captured by cycle averages.
    """
    if len(currents) < 20:
        return None

    recent = np.array(currents[-10:])
    historical = np.array(currents[:-10])

    mean_h = np.mean(historical)
    std_h = np.std(historical)

    if std_h == 0:
        return None

    z_scores = (recent - mean_h) / std_h
    if np.any(np.abs(z_scores) > 3.0):
        return "SUSPICIOUS_SIGNATURE"

    return None
