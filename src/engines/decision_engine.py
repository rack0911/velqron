# decision_engine.py (Merged Risk & Synthesis)
from typing import Dict, Optional

from src.core.config import CONFIG
from src.core.motor_context import MotorContext

# --- BAYESIAN KNOWLEDGE BASE (Consolidated) ---
BAYESIAN_KNOWLEDGE = {
    "electrical overload": {
        "event": "STABLE_OVERLOAD",
        "current_dev": 0.8,
        "temp_rise": 0.6,
        "variation_low": 0.9,
    },
    "bearing wear": {
        "event": "UNSTABLE_LOAD",
        "variation_high": 0.8,
        "current_dev": 0.3,
        "temp_rise": 0.4,
    },
    "pump cavitation": {
        "event": "UNSTABLE_LOAD",
        "variation_high": 0.8,
        "current_dev_low": 0.7,
        "temp_stable": 0.9,
    },
    "no fluid supply / dry run": {
        "event": "DRY_RUN",
        "current_dev_negative": 0.9,
        "temp_stable": 0.9,
    },
    "mechanical resistance": {
        "event": "DEGRADING_OVERLOAD",
        "slope_positive": 0.9,
        "current_dev": 0.7,
        "temp_rise": 0.6,
    },
}


def _calculate_evidence_score(evidence, current_dev, temp_dev, variation_level, slope):
    """Internal helper to score a hypothesis against observed evidence."""
    score = 0.0
    weights = 0

    if "current_dev" in evidence:
        score += evidence["current_dev"] if current_dev > 0.1 else 0
        weights += 1
    if "current_dev_low" in evidence:
        score += evidence["current_dev_low"] if current_dev < -0.1 else 0
        weights += 1
    if "current_dev_negative" in evidence:
        score += evidence["current_dev_negative"] if current_dev < -0.05 else 0
        weights += 1
    if "temp_stable" in evidence:
        score += evidence["temp_stable"] if abs(temp_dev) < 0.05 else 0
        weights += 1
    if "temp_rise" in evidence:
        score += evidence["temp_rise"] if temp_dev > 0.05 else 0
        weights += 1
    if "variation_low" in evidence:
        score += evidence["variation_low"] if variation_level == "LOW" else 0
        weights += 1
    if "variation_medium" in evidence:
        score += evidence["variation_medium"] if variation_level == "MEDIUM" else 0
        weights += 1
    if "variation_high" in evidence:
        score += evidence["variation_high"] if variation_level == "HIGH" else 0
        weights += 1
    if "slope_positive" in evidence:
        score += evidence["slope_positive"] if slope > 0.01 else 0
        weights += 1

    return score / weights if weights > 0 else 0.0


def calculate_aging_risk(context: MotorContext, max_temp, avg_current, current_event):
    """Estimates accelerated aging using Arrhenius 10°C rule."""
    from src.utils.database import db

    history = db.load_recent_cycles(context.motor_id, n=10)
    if not history:
        return {"stress_factor": 1.0, "aging_acceleration": "1x", "status": "HEALTHY"}

    safety_limit = CONFIG.MOTOR_SPECS.MAX_TEMP_SAFETY
    acceleration_factor = (
        2 ** ((max_temp - safety_limit) / 10.0) if max_temp > safety_limit else 1.0
    )
    stress_factor = acceleration_factor

    if len(history) >= 3:
        valid_currents = [c.get("avg_current") for c in history if c.get("avg_current") is not None]
        if len(valid_currents) >= 3:
            velocity = (valid_currents[-1] - valid_currents[0]) / len(valid_currents)
            if velocity > 0.01:
                stress_factor *= 1.0 + (velocity * 20.0)

    return {
        "stress_factor": round(stress_factor, 2),
        "aging_acceleration": f"{round(stress_factor, 1)}x",
        "status": "CRITICAL"
        if stress_factor > 8
        else "WARNING"
        if stress_factor > 2
        else "HEALTHY",
    }


def compute_confidence(severity, persistence, trend_dir, variation_level):
    """Trust score for the current diagnosis."""
    confidence = 0.6  # Base
    if persistence >= 3:
        confidence += 0.2
    if trend_dir != "STABLE":
        confidence += 0.1
    if variation_level == "HIGH":
        confidence += 0.1
    return round(min(confidence, 1.0), 2)


def get_decision(context: MotorContext, event, severity, failure_mode, confidence, trend_type):
    """Synthesizes action, urgency, and summary."""
    urgency = "LOW"
    action = "Continue Monitoring"

    if severity == "CRITICAL" or severity == "HIGH":
        urgency = "IMMEDIATE"
        action = "Stop Motor / Inspect"
    elif severity == "MEDIUM":
        urgency = "ELEVATED"
        action = "Schedule Maintenance"
    elif severity == "LOW" and event != "NORMAL":
        urgency = "LOW"
        action = "Inspect on next shift"

    if trend_type == "GRADUAL_INCREASE":
        urgency = "ELEVATED" if urgency == "LOW" else urgency

    summary = "Motor is operating within normal parameters."
    if event != "NORMAL":
        persistence = context.persistence_data.get("count", 1) if context.persistence_data else 1
        summary = f"[{severity}] {event} detected ({failure_mode}). Persistent for {persistence} cycles. Urgency: {urgency}."

    return {"action": action, "urgency": urgency, "summary": summary}


def estimate_rul(context: MotorContext, risk_data: Dict) -> Dict:
    stress_factor = risk_data.get("stress_factor", 1.0)
    nominal_life_days = 365 * 5  # 5 years
    estimated_days = nominal_life_days / stress_factor
    return {
        "days_to_maintenance": round(estimated_days),
        "confidence": 0.6 if stress_factor > 1.2 else 0.8,
    }


def get_risk_summary(risk_data):
    if not risk_data:
        return "Normal operating stress."
    factor = risk_data["stress_factor"]
    if factor > 4.0:
        return f"URGENT: Extreme stress detected ({factor}x aging)."
    elif factor > 1.2:
        return f"Accelerated aging ({factor}x)."
    else:
        return "Normal operating stress."


def get_ranked_hypotheses(event, current_dev, temp_dev, variation_level, slope):
    """Ranks probable root causes using sensor evidence."""
    rankings = []
    for cause, evidence in BAYESIAN_KNOWLEDGE.items():
        if evidence.get("event") == event:
            score = _calculate_evidence_score(
                evidence, current_dev, temp_dev, variation_level, slope
            )
            rankings.append((cause, round(score, 2)))

    return sorted(rankings, key=lambda x: x[1], reverse=True)


def calculate_time_to_trip(
    avg_current: float, current_temp: float, ambient_temp: float, profile: dict
) -> Optional[float]:
    """
    Calculates projected time in seconds before stator temperature reaches absolute Class F ceiling (155°C).
    Uses the same LPTN ODE model parameters from ThermalExpert.
    """
    import math

    try:
        # Load LPTN coefficients
        r_th = float(profile.get("r_th", 15.0))
        if r_th <= 0.0:
            r_th = 15.0

        c_th = float(profile.get("c_th", 80.0))
        if c_th <= 0.0:
            c_th = 80.0

        v_nom = float(profile.get("rated_voltage", 230.0))
        if v_nom <= 0.0:
            v_nom = 230.0

        eff = float(profile.get("efficiency", 0.85))
        if eff <= 0.0 or eff >= 1.0:
            eff = 0.85

        t_trip = float(profile.get("max_temp_c", 125.0))  # Safety limit
        if t_trip <= 0.0:
            t_trip = 125.0

        # Absolute insulation limit is Class F (155°C)
        ins_class = profile.get("insulation_class", "F")
        if ins_class == "F":
            t_trip = 155.0
        elif ins_class == "B":
            t_trip = 130.0
        elif ins_class == "H":
            t_trip = 180.0

        if current_temp >= t_trip:
            return 0.0

        tau = r_th * c_th  # Thermal time constant in seconds
        p_loss = v_nom * avg_current * (1.0 - eff)
        steady_state_rise = p_loss * r_th
        steady_state_temp = ambient_temp + steady_state_rise

        if steady_state_temp <= t_trip:
            return None  # Will never trip at this current

        ratio = (steady_state_temp - t_trip) / (steady_state_temp - current_temp)
        if ratio <= 0.0:
            return None

        time_to_trip = -tau * math.log(ratio)
        return round(time_to_trip, 1)
    except Exception:
        return None


def calculate_sustainability_impact(
    avg_current: float,
    baseline_current: float,
    duration_sec: float,
    voltage: float = 415.0,
    power_factor: float = 0.85,
) -> dict:
    """Calculates estimated carbon footprint increase and utility cost overhead from current deviation."""
    import math

    try:
        if baseline_current <= 0.0 or avg_current <= baseline_current:
            return {"excess_kwh": 0.0, "excess_co2_kg": 0.0, "excess_cost_usd": 0.0}

        delta_i = avg_current - baseline_current
        # P = sqrt(3) * V * I * PF / 1000 (3-phase active power in kW)
        excess_power_kw = math.sqrt(3.0) * voltage * delta_i * power_factor / 1000.0

        # Energy = Power * hours
        hours = duration_sec / 3600.0
        excess_kwh = excess_power_kw * hours

        excess_co2_kg = excess_kwh * CONFIG.UTILITY_CO2_PER_KWH
        excess_cost_usd = excess_kwh * CONFIG.UTILITY_COST_PER_KWH

        return {
            "excess_kwh": round(excess_kwh, 4),
            "excess_co2_kg": round(excess_co2_kg, 4),
            "excess_cost_usd": round(excess_cost_usd, 4),
        }
    except Exception:
        return {"excess_kwh": 0.0, "excess_co2_kg": 0.0, "excess_cost_usd": 0.0}
