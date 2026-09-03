# fallback_engine.py
import json


def generate_deterministic_fallback(llm_data):
    """
    Failure Survivability: Provides a 100% deterministic, schema-compliant
    diagnostic report when LLM reasoning fails or is rejected.
    """
    event = llm_data.get("event", "NORMAL")
    event_clean = llm_data.get("event_clean", "anomaly")
    duration = llm_data.get("duration_human", "0 sec")
    persistence = llm_data.get("persistence_cycles", 1)
    severity = llm_data.get("severity", "LOW")
    urgency = llm_data.get("urgency", "LOW")
    failure_mode = llm_data.get("failure_mode", "TRANSIENT")
    confidence = llm_data.get("confidence", "LOW")

    # 1. Situation Summary (Deterministic Reality)
    situation = f"{event_clean.capitalize()} detected. Condition has persisted for {duration} over {persistence} cycles."

    # 2. Interpretation (Simple Mapping)
    cause_map = {
        "STABLE_OVERLOAD": "partial blockage in piping",
        "UNSTABLE_LOAD": "early-stage bearing wear",
        "DRY_RUN": "no fluid supply / dry run",
        "DEGRADING_OVERLOAD": "mechanical resistance",
    }
    primary_cause = cause_map.get(event, "localized fluctuation")

    if failure_mode == "ACUTE":
        interpretation = f"Observation indicates a high-velocity deviation in load, likely caused by {primary_cause}."
    elif failure_mode == "CHRONIC":
        interpretation = (
            f"Observation indicates a stable, high-load baseline consistent with {primary_cause}."
        )
    else:
        interpretation = (
            f"Observation indicates a localized fluctuation, potentially linked to {primary_cause}."
        )

    # 3. Risk Insight (Weighted by Severity & Urgency)
    if urgency == "URGENT":
        risk_insight = "Critical risk of equipment failure or permanent damage if operation continues without intervention."
    elif severity == "HIGH":
        risk_insight = "Significant risk of efficiency loss and accelerated component wear under current thermal stress."
    else:
        risk_insight = "Moderate risk of gradual degradation; no immediate escalation detected in recent cycles."

    # 4. Decision Justification (Constraint: must match Urgency)
    if urgency == "URGENT":
        base_justification = (
            "Immediate response is required due to the acute nature and high severity of the fault."
        )
    elif urgency == "PLANNED":
        base_justification = (
            f"Scheduled maintenance is appropriate as the system shows "
            f"established {failure_mode.lower()} stress."
        )
    else:
        base_justification = "Continued monitoring is recommended while the system remains in a low-urgency stable state."

    justification = f"[FALLBACK] Fallback Active: {base_justification}"

    # Final Construction with JSON format for Dashboard stability
    report = {
        "situation": situation,
        "interpretation": interpretation,
        "risk": risk_insight,
        "justification": f"{justification} (Confidence: {confidence})",
    }

    return json.dumps(report, indent=2)
