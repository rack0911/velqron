import json
import logging
import os

from src.core.profile_manager import load_profile

logger = logging.getLogger(__name__)

KB_PATH = "knowledge/motors/standard_specs.json"

FAULT_KNOWLEDGE = {
    "Overload": {
        "diagnosis": "Current exceeds rated FLA.",
        "cause": "Possible mechanical jam or supply voltage drop.",
        "action": "Reduce load or check voltage.",
    },
    "Underload": {
        "diagnosis": "Current significantly below baseline.",
        "cause": "Possible coupling failure or pump dry run.",
        "action": "Check coupling or fluid level.",
    },
    "Winding Stress": {
        "diagnosis": "Abnormal thermal rise relative to current.",
        "cause": "Possible insulation degradation.",
        "action": "Verify insulation resistance.",
    },
    "Bearing Wear": {
        "diagnosis": "High-frequency current noise detected.",
        "cause": "Possible lubrication failure.",
        "action": "Check bearings and lubrication.",
    },
    "Thermal Drift": {
        "diagnosis": "Temperature rising without corresponding current increase.",
        "cause": "Cooling failure.",
        "action": "Check fan or cooling vents.",
    },
}

# Maps logic_controller fault names → knowledge base keys
EVENT_TO_KNOWLEDGE = {
    "STABLE_OVERLOAD": "Overload",
    "DEGRADING_OVERLOAD": "Overload",
    "DRY_RUN": "Underload",
    "UNSTABLE_LOAD": "Overload",
}


def get_motor_specs(motor_id=None):
    """
    Retrieves and prunes technical specifications for a specific motor.
    PRIORITY: Manual Commissioning Profile > Standard Library.
    """
    # 1. Check Manual Commissioning Profile (GROUND TRUTH)
    profile = load_profile()
    if profile:
        return {
            "model": profile.get("motor_name", "User Asset"),
            "manufacturer": profile.get("make", "Generic"),
            "rated_current_a": profile.get("rated_current"),
            "max_temp_c": profile.get("max_temp_c"),
            "insulation_class": profile.get("insulation_class"),
        }

    # 2. Fallback to Knowledge Base
    if not os.path.exists(KB_PATH):
        logger.warning(f"Knowledge Base not found at {KB_PATH}")
        return {}

    try:
        with open(KB_PATH, "r") as f:
            kb = json.load(f)
            specs = kb.get(motor_id, {})

            if not specs:
                logger.info(f"No specs found for motor_id: {motor_id}")
                return {}

            # Context Pruning: Return only essential fields
            essential_fields = [
                "model",
                "manufacturer",
                "rated_current_a",
                "max_temp_c",
                "insulation_class",
            ]
            return {k: v for k, v in specs.items() if k in essential_fields}
    except Exception as e:
        logger.error(f"Error reading Knowledge Base: {e}")
        return {}
