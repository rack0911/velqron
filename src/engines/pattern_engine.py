import logging
from typing import Any, Dict

import numpy as np

from src.core.motor_context import MotorContext
from src.core.types import CycleMetrics

logger = logging.getLogger(__name__)


class PatternEngine:
    """
    Shadow AI Engine for 'Unknown Unknown' detection.
    Uses Distance-based Anomaly Detection (a precursor to Autoencoders).
    Learns the 'Healthy Shape' of the motor waveform and flags deviations.
    """

    def __init__(self, sensitivity: float = 2.5):
        self.sensitivity = sensitivity  # Sigma threshold for anomaly detection

    def analyze_cycle(
        self, context: MotorContext, metrics: CycleMetrics, current_series: np.ndarray
    ) -> Dict[str, Any]:
        """
        Analyzes the pattern of the current waveform vs the learned 'Gold Standard'.
        Returns a 'Shadow Score' [0.0 - 1.0] where 1.0 is a perfect pattern mismatch.
        """
        gold_standard = context.pattern_baseline

        if not gold_standard or len(current_series) < 100:
            return {"pattern_anomaly_score": 0.0, "status": "LEARNING"}

        # 1. Normalize current series (Shape analysis, not magnitude)
        norm_series = current_series / (np.mean(current_series) + 1e-6)

        # 2. Extract Pattern Features (Temporal Entropy & Crest Stability)
        # These are the same features a CNN would learn in its early layers
        entropy = -np.sum(np.square(norm_series) * np.log(np.square(norm_series) + 1e-9))
        peak_stability = np.max(norm_series) / (np.std(norm_series) + 1e-6)

        # 3. Compare with Gold Standard
        gold_entropy = gold_standard.get("entropy", entropy)
        gold_stability = gold_standard.get("peak_stability", peak_stability)

        # Euclidean distance in pattern space
        dist = np.sqrt((entropy - gold_entropy) ** 2 + (peak_stability - gold_stability) ** 2)

        # 4. Convert to Anomaly Score (Sigmoid)
        # Using a sensitivity of 2.5 sigma for shadow logging
        anomaly_score = 1.0 / (1.0 + np.exp(-(dist - self.sensitivity)))

        # 5. Update Gold Standard (Self-Supervised Learning)
        # We only update if the cycle is confirmed healthy by logic_controller
        # This will be handled by the orchestrator

        return {
            "pattern_anomaly_score": round(float(anomaly_score), 3),
            "status": "DETECTING" if anomaly_score > 0.5 else "NOMINAL",
            "features": {
                "entropy": round(float(entropy), 2),
                "peak_stability": round(float(peak_stability), 2),
            },
        }

    def update_pattern_baseline(self, context: MotorContext, entropy: float, stability: float):
        """Slowly adapts the gold standard to natural aging (EMA update)."""
        gold = context.pattern_baseline
        alpha = 0.1  # Learning rate

        gold["entropy"] = (1 - alpha) * gold.get("entropy", entropy) + alpha * entropy
        gold["peak_stability"] = (1 - alpha) * gold.get(
            "peak_stability", stability
        ) + alpha * stability

        context.pattern_baseline = gold
        logger.info(f"PatternEngine: Updated healthy baseline for {context.motor_id}")


pattern_engine = PatternEngine()
