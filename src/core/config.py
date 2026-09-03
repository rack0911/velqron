from typing import Dict, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class HardwareConfig(BaseSettings):
    PORT: Optional[str] = None
    BAUD: int = 115200
    PIN_CT: int = 34
    PIN_TEMP: int = 4
    VOLTAGE_REF: float = 3.3
    CURRENT_SCALAR: float = 1.0
    RAW_LOG_DIR: str = "logs/raw_hardware/"
    BIAS_STABILITY_THRESHOLD: float = 0.01
    BIAS_MAX_RETRIES: int = 3
    HIL_CALIBRATION_FACTOR: float = 1.0
    NOISE_CEILING: float = 0.03
    WATCHDOG_TIMEOUT_SEC: float = 5.0
    RECONNECT_BACKOFF_MIN_SEC: float = 1.0
    RECONNECT_BACKOFF_MAX_SEC: float = 30.0


class ThermalModelConfig(BaseSettings):
    R_TH: float = 0.5
    C_TH: float = 5000.0
    EFFICIENCY: float = 0.85
    VOLTAGE_NOMINAL: float = 230.0
    AMBIENT_DEFAULT: float = 25.0


class MotorSpecsConfig(BaseSettings):
    INSULATION_CLASS: str = "F"
    SERVICE_FACTOR: float = 1.15
    MAX_TEMP_SAFETY: float = 125.0


class DeviationThresholds(BaseSettings):
    OVERLOAD: float = 0.10
    DRY_RUN: float = -0.15
    TEMP_RISE: float = 0.15
    TREND_WARNING: float = 0.10
    DRIFT_THRESHOLD: float = 0.15


class AnomalyConfig(BaseSettings):
    MIN_STD: float = 0.02


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VELQRON_", env_file=".env", extra="ignore")

    DATA_DIR: str = Field(default="data")
    BASELINE_WINDOW: int = 20
    STARTUP_IGNORE_TIME: int = 20
    MINIMUM_CURRENT_THRESHOLD: float = 0.5
    HYSTERESIS_OFFSET: float = 0.1
    NOISE_FLOOR: float = 0.15
    SCHEMA_VERSION: str = "1.1"

    # Hybrid Intelligence Split (Testing vs Commercial)
    DATA_SOURCE: str = "SIMULATED"  # "PHYSICAL" or "SIMULATED"
    LLM_MODE: str = "Local Priority"  # "Local Only", "Cloud Only", or "Local Priority"

    # Sustainability & Energy Cost Parameters
    UTILITY_CO2_PER_KWH: float = 0.4
    UTILITY_COST_PER_KWH: float = 0.12

    VARIATION_THRESHOLD: Dict[str, float] = {"MEDIUM": 0.10, "HIGH": 0.18}
    SMALL_THRESHOLD: float = 0.05

    DEVIATION_THRESHOLDS: DeviationThresholds = DeviationThresholds()

    HARDWARE: HardwareConfig = HardwareConfig()
    MOTOR_CONFIG_FILE: str = "data/motor_profile.json"

    THERMAL_MODEL: ThermalModelConfig = ThermalModelConfig()
    MOTOR_SPECS: MotorSpecsConfig = MotorSpecsConfig()
    ANOMALY: AnomalyConfig = AnomalyConfig()
    ANOMALY_MIN_STD: float = 0.02

    def get(self, item, default=None):
        return getattr(self, item, default)


# Singleton instance
CONFIG = AppConfig()
