import json
from unittest.mock import patch

import pytest

from src.core.orchestrator import EngineOrchestrator


@pytest.fixture
def orchestrator():
    return EngineOrchestrator()


def test_analysis_output_schema(orchestrator):
    """Verifies that the orchestrator returns all required MVP fields."""
    currents = [2.5, 2.6, 2.5]
    temps = [35.0, 35.1, 35.2]
    times = [0, 1, 2]

    results = orchestrator.process_data(currents, temps, times, is_realtime=True)

    # Check for core keys
    assert "event" in results
    assert "severity" in results
    assert "confidence" in results
    assert "summary" in results
    assert "recommendation" in results
    assert "urgency" in results
    assert "envelope" in results
    assert "aging_risk" in results


def test_llm_reasoning_compliance(orchestrator):
    """Verifies that even if LLM returns weird text, the sanitizer ensures MVP structure."""
    llm_data = {
        "fault": "OVERLOAD",
        "current": 1.2,
        "base_text": "Sample baseline",
        "duration_human": "10s",
        "persistence_cycles": 5,
        "event_clean": "overload",
        "urgency": "LOW",
        "failure_mode": "CHRONIC",
    }

    # Mocking generating_reasoning returning a compliant string
    compliant_report = {
        "situation": "The current motor overload has persisted for 10s across 5 cycles.",
        "interpretation": "Physical resistance detected.",
        "risk": "Condition has persisted for 10s showing no immediate escalation.",
        "justification": "A low maintenance approach is appropriate.",
    }
    compliant_json = json.dumps(compliant_report)

    with patch("src.utils.dual_explainer.generate_reasoning", return_value=compliant_json):
        explanation = orchestrator.get_explanation(llm_data, mode="On-Premise")

        assert "situation" in explanation
        assert "interpretation" in explanation


def test_llm_failure_fallback(orchestrator):
    """Verifies that fallback engine kicks in when LLM fails."""
    llm_data = {
        "event_clean": "overload",
        "duration_human": "5m",
        "persistence_cycles": 3,
        "severity": "HIGH",
        "urgency": "URGENT",
        "failure_mode": "ACUTE",
    }

    # Simulate total LLM failure (returning an error string)
    with (
        patch("src.utils.dual_explainer.local_explainer", return_value="ERROR: LOCAL_FAILED"),
        patch("src.utils.dual_explainer.nvidia_explainer", return_value="ERROR: CLOUD_FAILED"),
    ):
        explanation = orchestrator.get_explanation(llm_data, mode="On-Premise")

        # Should contain fallback keywords
        assert "situation" in explanation.lower()
        assert "interpretation" in explanation.lower()
        assert "Fallback Active" in explanation
