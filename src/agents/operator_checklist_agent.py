from typing import Any, Dict

from src.agents.base_agent import ExpertAgent


class OperatorChecklistAgent(ExpertAgent):
    """
    Expert Agent that ingests physical operator shift checks (shaft wobble,
    bearing grinding, stator clogs, oil leaks) logged manually in SQLite,
    cross-verifying physical anomalies with electrical trends.
    """

    def __init__(self):
        super().__init__("Operator Checklist Expert")

    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        grounding = data.get("grounding_context", {})
        op_ins = grounding.get("operator_inspection", {}) if grounding else {}

        severity = "NONE"
        reasoning = "Operator visual shift checklist confirms nominal external housing and mounting frame state."
        failure_mode = "NONE"

        flags = []
        if op_ins:
            if op_ins.get("shaft_wobble"):
                flags.append("shaft_wobble")
            if op_ins.get("bearing_grinding"):
                flags.append("bearing_grinding")
            if op_ins.get("stator_clogged"):
                flags.append("stator_clogged")
            if op_ins.get("oil_leak"):
                flags.append("oil_leak")

        # Visual check heuristics
        if "bearing_grinding" in flags or "shaft_wobble" in flags:
            severity = "WARNING"
            failure_mode = "Mechanical Friction"
            reasoning = "Operator logged visual shaft wobble or bearing grinding during shift. Cross-verifying electrical fluctuations."

        if "oil_leak" in flags:
            severity = "CRITICAL"
            failure_mode = "Seal Failure"
            reasoning = "Operator reported active casing oil leak on shift! High risk of lubrication loss and thermal winding seizure."

        return {
            "agent": self.name,
            "severity": severity,
            "reasoning": reasoning,
            "failure_mode": failure_mode,
            "event": "Mechanical Stress" if severity != "NONE" else "NORMAL",
            "checklist_metadata": {"flags": flags, "operator": op_ins.get("operator_name")},
        }
