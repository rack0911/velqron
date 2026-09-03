import json
import os

from src.core.config import CONFIG
from src.utils.logger import get_logger

logger = get_logger(__name__)

PROFILE_PATH = CONFIG.get("MOTOR_CONFIG_FILE", "data/motor_config.json")

DEFAULT_PROFILE = {
    "motor_name": "Primary Pump A",
    "rated_current": 2.2,
    "max_temp_c": 125.0,
    "insulation_class": "F",
    "install_date": "2026-04-13",
    "last_maintenance_date": None,
    "location": "Central Utility Room",
    "rpm": 1440,
    "v_rated": 415,
    "frequency": 50.0,
    "phase": "3-Phase",
    "make": "Generic",
    "hil_scaling": CONFIG.HARDWARE.HIL_CALIBRATION_FACTOR,
}


def load_profile():
    """Loads motor configuration from disk or returns default and overrides global CONFIG."""
    if not os.path.exists(PROFILE_PATH):
        save_profile(DEFAULT_PROFILE)
        _apply_profile_to_config(DEFAULT_PROFILE)
        return DEFAULT_PROFILE

    try:
        with open(PROFILE_PATH, "r") as f:
            profile = json.load(f)
            _apply_profile_to_config(profile)
            return profile
    except Exception as e:
        logger.error(f"Failed to load motor profile from {PROFILE_PATH}: {e}")
        _apply_profile_to_config(DEFAULT_PROFILE)
        return DEFAULT_PROFILE


def _apply_profile_to_config(profile):
    """Helper to inject customized limits into global CONFIG thresholds."""
    if "service_factor" in profile:
        CONFIG.MOTOR_SPECS.SERVICE_FACTOR = float(profile["service_factor"])
    if "max_temp_c" in profile:
        CONFIG.MOTOR_SPECS.MAX_TEMP_SAFETY = float(profile["max_temp_c"])
    if "insulation_class" in profile:
        CONFIG.MOTOR_SPECS.INSULATION_CLASS = str(profile["insulation_class"])


def save_profile(profile_data):
    """Persists motor configuration to disk."""
    os.makedirs(os.path.dirname(PROFILE_PATH), exist_ok=True)
    with open(PROFILE_PATH, "w") as f:
        json.dump(profile_data, f, indent=4)
    # Re-apply updated profile parameters to CONFIG immediately
    _apply_profile_to_config(profile_data)

    # Sync with SQLite machine_registry to prevent de-synchronization
    try:
        from src.utils.database import db

        db.update_machine_registry(profile_data)
    except Exception as e:
        logger.error(f"Failed to sync profile update with database: {e}")

    return True


def get_profile_value(key, default=None):
    profile = load_profile()
    return profile.get(key, default)
