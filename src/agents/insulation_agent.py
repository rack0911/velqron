from typing import Any, Dict

from src.agents.base_agent import ExpertAgent


class InsulationExpert(ExpertAgent):
    """
    Expert agent focused on electrical health and winding insulation.
    Analyzes current peaks, surges, and phase balance.
    """

    def __init__(self):
        super().__init__("Electrical & Insulation Expert")

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Input data should include the current diagnosis/event.
        """
        currents = data.get("currents", [])
        baseline = data.get("baseline", {"avg_current": 0})
        features = data.get("features", {})
        resistance = features.get("insulation_resistance_mohm", None) if features else None

        severity = "NONE"
        confidence = "HIGH"
        reasoning = "Electrical signatures indicate healthy insulation state."
        failure_mode = "NONE"
        event = "NORMAL"

        # Check insulation resistance if available
        if resistance is not None:
            if resistance < 1.0:
                severity = "HIGH"
                failure_mode = "Insulation Degradation"
                reasoning = f"Stator insulation resistance has dropped critically to {resistance:.2f} MOhm, indicating breakdown risk."
                event = "UNSTABLE_LOAD"

        if currents and baseline.get("avg_current", 0) > 0:
            max_current = max(currents)
            avg_current = sum(currents) / len(currents)
            peak_ratio = max_current / baseline["avg_current"]
            avg_ratio = avg_current / baseline["avg_current"]

            # Overload / Insulation stress logic
            if avg_ratio > 1.15 or peak_ratio > 1.25:
                if severity != "HIGH":
                    severity = "LOW"
                    failure_mode = "Electrical Overload"
                    reasoning = f"Current sustained at {avg_ratio:.1f}x baseline. This degrades winding life over time."

                if avg_ratio > 1.5 or peak_ratio > 1.5:
                    if severity != "HIGH":
                        severity = "MEDIUM"
                        reasoning = "Heavy electrical overload detected. Insulation breakdown risk is elevated."

            if avg_ratio < 0.7:
                if severity != "HIGH":
                    severity = "MEDIUM"
                    failure_mode = "Dry Run / No Load"
                    reasoning = f"Current dropped to {avg_ratio:.1f}x baseline. This suggests a dry run or loss of fluid supply."

            if peak_ratio > 3.0:
                severity = "HIGH"
                failure_mode = "Locked Rotor / Short"
                reasoning = (
                    "Extreme current surge detected. Possible stator short or mechanical lock."
                )

            if severity != "NONE" and severity != "HIGH":
                if avg_ratio < 0.8:
                    event = "DRY_RUN"
                elif avg_ratio > 1.1:
                    event = "STABLE_OVERLOAD"
                else:
                    event = "UNSTABLE_LOAD"
        elif not currents and resistance is None:
            return {
                "severity": "NONE",
                "confidence": "LOW",
                "reasoning": "No electrical data.",
                "failure_mode": "NONE",
                "event": "NORMAL",
                "agent": self.name,
            }

        return {
            "severity": severity,
            "confidence": confidence,
            "reasoning": reasoning,
            "failure_mode": failure_mode,
            "event": event,
            "agent": self.name,
        }
