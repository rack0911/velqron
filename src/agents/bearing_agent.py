from typing import Any, Dict

from src.agents.base_agent import ExpertAgent


class BearingExpert(ExpertAgent):
    """
    Expert agent focused on mechanical health, specifically bearings and alignment.
    Analyzes current signature drift and mechanical impedance.
    """

    def __init__(self):
        super().__init__("Mechanical Health Expert")

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detects mechanical wear using fused Vibration + Current Analysis.
        High Kurtosis (> 4.2) or Crest Factor (> 5.0) in vibration signals
        is a high-confidence indicator of bearing pitting/misalignment.
        """
        variation_level = data.get("variation_level", "LOW")
        drift = data.get("fingerprint_drift", 0.0)

        # Vibration features (New in Tier 2)
        v_kurtosis = data.get("vib_kurtosis", 3.0)  # Baseline kurtosis is ~3.0
        v_crest = data.get("vib_crest", 1.4)

        severity = "NONE"
        confidence = 0.85
        reasoning = "Mechanical health appears stable."
        failure_mode = "NONE"
        event = "NORMAL"
        vote = False

        # --- MULTI-MODAL FUSION LOGIC ---
        # 1. Primary: Vibration Kurtosis (Impact detection)
        if v_kurtosis > 6.0:
            severity = "HIGH"
            failure_mode = "Bearing Pitting / Spalling"
            reasoning = f"CRITICAL: High vibration kurtosis ({v_kurtosis:.1f}) detected. Immediate mechanical shock suspected."
            event = "UNSTABLE_LOAD"
            vote = True
            confidence = 0.95
        elif v_kurtosis > 4.2:
            severity = "MEDIUM"
            failure_mode = "Progressive Mechanical Wear"
            reasoning = f"Elevated vibration kurtosis ({v_kurtosis:.1f}) suggests early-stage bearing fatigue."
            event = "UNSTABLE_LOAD"
            vote = True
            confidence = 0.90

        # 2. Secondary: Vibration Crest Factor (Impulsiveness)
        if v_crest > 8.0:
            severity = "HIGH"
            reasoning += (
                f" | Extreme vibration crest factor ({v_crest:.1f}) confirms mechanical imbalance."
            )
            event = "UNSTABLE_LOAD"
            vote = True

        # 3. Tertiary: Electrical Fingerprint Drift (The old proxy)
        if drift > 0.12:
            if severity == "NONE":
                severity = "MEDIUM"
                failure_mode = "Mechanical Friction"
                reasoning = (
                    f"Motor signature drift ({drift:.2f}) detected. Mechanical wear suspected."
                )
                event = "UNSTABLE_LOAD"
                vote = True
            else:
                reasoning += f" | Grounded by electrical fingerprint drift ({drift:.2f})."
                confidence = 1.0  # Cross-modal agreement

        # 4. Ripple / Variation Correlation
        if variation_level == "HIGH" and not vote:
            severity = "MEDIUM"
            reasoning += " High current ripple indicates unstable load."
            event = "UNSTABLE_LOAD"
            vote = True

        # 5. TinyML Classifier Integration
        tinyml_result = data.get("tinyml_result")
        if tinyml_result and tinyml_result.get("class") != "NORMAL":
            pred_class = tinyml_result["class"]
            ml_conf = tinyml_result.get("confidence", 0.0)

            # Map classes to severity
            severity_map = {"INNER_RACE": "MEDIUM", "BALL_FAULT": "MEDIUM", "OUTER_RACE": "HIGH"}
            class_severity = severity_map.get(pred_class, "MEDIUM")

            if severity == "NONE" or (class_severity == "HIGH" and severity != "HIGH"):
                severity = class_severity
                failure_mode = f"TinyML Detected Bearing Fault: {pred_class}"
                reasoning = f"TinyML Classifier detected {pred_class} defect with {ml_conf * 100:.1f}% confidence."
                event = "UNSTABLE_LOAD"
                vote = True
                confidence = max(confidence, ml_conf)
            else:
                reasoning += f" | TinyML Classifier confirmed {pred_class} defect ({ml_conf * 100:.1f}% conf)."
                confidence = max(confidence, (confidence + ml_conf) / 2.0)

        return {
            "severity": severity,
            "confidence": round(float(confidence), 2),
            "reasoning": reasoning,
            "failure_mode": failure_mode,
            "event": event,
            "vote": vote,
            "agent": self.name,
            "vibration": {"kurtosis": v_kurtosis, "crest": v_crest},
        }
