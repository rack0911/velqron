from abc import ABC, abstractmethod
from typing import Any, Dict


class ExpertAgent(ABC):
    """
    Base class for specialized motor intelligence agents.
    Each agent focuses on a specific failure mode or subsystem.
    """

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def analyze(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze the provided cycle data and return findings.
        Input 'data' contains: currents, temperatures, times, baseline, drifts.
        Output 'findings' contains: severity, confidence, reasoning, failure_mode.
        """
        pass

    def __repr__(self):
        return f"<ExpertAgent: {self.name}>"
