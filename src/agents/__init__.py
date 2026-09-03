from typing import Any, Dict, List

from src.agents.bearing_agent import BearingExpert
from src.agents.insulation_agent import InsulationExpert
from src.agents.operator_checklist_agent import OperatorChecklistAgent
from src.agents.remediation_agent import RemediationAdvisor
from src.agents.thermal_agent import ThermalExpert


class AgentEnsemble:
    """
    Orchestrates a collection of expert agents to provide a unified diagnostic.
    """

    def __init__(self):
        self.experts = [
            BearingExpert(),
            ThermalExpert(),
            InsulationExpert(),
            OperatorChecklistAgent(),
        ]
        self.remediation = RemediationAdvisor()

    def get_diagnostics(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Collect findings from all agents.
        """
        results = []
        for agent in self.experts:
            try:
                results.append(agent.analyze(data))
            except Exception as e:
                # Fallback for agent failure
                results.append(
                    {
                        "severity": "NONE",
                        "confidence": "LOW",
                        "reasoning": f"Agent {agent.name} failed: {str(e)}",
                        "failure_mode": "UNKNOWN",
                        "event": "NORMAL",
                        "agent": agent.name,
                    }
                )
        return results

    def aggregate_findings(self, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Aggregates individual agent findings into a single system decision.
        Priority: CRITICAL > HIGH > MEDIUM > LOW > NONE.
        """
        severity_map = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "NONE": 0}

        best_finding = findings[0]
        max_score = -1

        for f in findings:
            score = severity_map.get(f["severity"], 0)
            if score > max_score:
                max_score = score
                best_finding = f
            elif score == max_score and score > 0:
                # If scores are tied, append reasoning
                if f["agent"] != best_finding["agent"]:
                    best_finding["reasoning"] += f" | {f['agent']} also notes: {f['reasoning']}"

        return best_finding
