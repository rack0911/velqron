from typing import Any, Dict, List, Optional, TypedDict

from pydantic import BaseModel


class CycleMetrics(BaseModel):
    motor_id: str
    avg_current: float
    max_current: float
    std_current: float
    avg_temp: float
    max_temp: float
    runtime_sec: float
    startup_slope: float
    peak_to_mean: float
    variation_level: str
    timestamp: float

    # Vibration Features (New in Tier 2)
    vib_rms: Optional[float] = 0.0
    vib_peak: Optional[float] = 0.0
    vib_kurtosis: Optional[float] = 0.0
    vib_crest: Optional[float] = 0.0


class DriftData(TypedDict):
    current_drift: float
    temp_drift: float
    runtime_drift: float


class EnvelopeMetrics(TypedDict):
    current_pct: float
    temp_pct: float


class ExpertFinding(TypedDict):
    event: str
    severity: str
    reasoning: str
    failure_mode: str
    agent: str


class AnalysisResult(TypedDict):
    event: str
    severity: str
    confidence: float
    failure_mode: str
    state: str
    duration: str
    persistence: int
    recommendation: str
    urgency: str
    summary: str
    llm_data: Optional[Dict[str, Any]]
    envelope: EnvelopeMetrics
    fingerprint_drift: float
    aging_risk: Optional[Dict[str, Any]]
    remaining_useful_life: Optional[Dict[str, Any]]
    edge_ml_flag: Optional[str]
    root_cause_suspicions: List[str]
    shadow_ai: Optional[Any]
