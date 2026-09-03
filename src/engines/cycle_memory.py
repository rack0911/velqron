import time

from src.core.profile_manager import load_profile
from src.utils.database import db


def save_cycle(*args, **kwargs):
    """
    Saves a cycle run. Supports both:
      - save_cycle(summary)
      - save_cycle(context, summary)
    """
    context = None
    summary = None
    if len(args) == 2:
        context, summary = args
    elif len(args) == 1:
        summary = args[0]
    else:
        summary = kwargs.get("summary")
        context = kwargs.get("context")

    if context:
        motor_id = context.motor_id
    else:
        profile = load_profile()
        motor_id = profile.get("motor_id", "SIM_MOTOR_01")

    avg_current = summary.get("avg_current", 0.0)
    max_temp = summary.get("max_temp", 0.0)
    duration = summary.get("runtime", summary.get("duration_sec", 0))
    event = summary.get("event", "NORMAL") or "NORMAL"
    data_source = "PHYSICAL"
    if motor_id == "SIM_MOTOR_01":
        data_source = "SIMULATED"

    # Log the cycle
    cycle_id = db.log_cycle(
        motor_id=motor_id,
        avg_current=avg_current,
        max_temp=max_temp,
        duration=duration,
        features={},
        data_source=data_source,
    )

    # Log the event too, to match the diagnostic pipeline flow
    if cycle_id:
        event_data = {
            "event": event,
            "severity": "HIGH" if event != "NORMAL" else "NONE",
            "confidence": 1.0,
            "failure_mode": event,
            "persistence": 1,
            "summary": f"Historical cycle log for {event}",
        }
        db.log_event(cycle_id, event_data)

    return cycle_id


def get_last_cycle_summary(motor_id=None):
    """
    Fetches the summary of the last completed cycle.
    """
    if not motor_id:
        profile = load_profile()
        motor_id = profile.get("motor_id", "SIM_MOTOR_01")

    cycles = db.load_recent_cycles(motor_id, n=1)
    if not cycles:
        return None

    cycle = cycles[0]
    return {
        "avg_current": cycle.get("avg_current", 0.0),
        "max_current": cycle.get("avg_current", 0.0),  # fallback if not explicit
        "avg_temperature": cycle.get("max_temp", 0.0),  # fallback
        "max_temp": cycle.get("max_temp", 0.0),
        "event": cycle.get("event", "NORMAL") or "NORMAL",
        "runtime": cycle.get("duration_sec", 0),
        "timestamp": time.time(),
    }


def clear_history(context=None):
    """
    Clears cycle history.
    """
    if context:
        motor_id = context.motor_id
    else:
        profile = load_profile()
        motor_id = profile.get("motor_id", "SIM_MOTOR_01")
    db.clear_history(motor_id)
