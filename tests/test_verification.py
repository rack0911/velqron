# test_verification.py
import json
import os
import sys

# Add root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.engines.fallback_engine import generate_deterministic_fallback
from src.utils.sanitizer import sanitize_llm_output


def test_fallback_parity():
    print("Testing Fallback Parity...")
    mock_llm_data = {
        "event": "DRY_RUN",
        "event_clean": "dry run fault",
        "duration_human": "15 min",
        "persistence_cycles": 3,
        "severity": "HIGH",
        "urgency": "URGENT",
        "failure_mode": "ACUTE",
        "confidence": "HIGH",
        "recommended_action": "Stop motor immediately",
    }

    fallback_report = generate_deterministic_fallback(mock_llm_data)
    print("\n--- GENERATED FALLBACK ---")
    print(fallback_report)

    parsed_report = json.loads(fallback_report)
    required_keys = ["situation", "interpretation", "risk", "justification"]
    for key in required_keys:
        assert key in parsed_report, f"Missing required key: {key}"
        assert parsed_report[key], f"Empty required key: {key}"

    print("\n Fallback Engine verified for schema parity.")


def test_sanitizer_strict_reject():
    print("\nTesting Sanitizer Strict Reject...")
    mock_data = {"duration_human": "10 min", "persistence_cycles": 2, "event_clean": "overload"}

    # Non-compliant text (too short)
    bad_text = '{"situation": "Motor hot.", "interpretation": "Bad.", "risk": "High.", "justification": "Stop."}'
    result = sanitize_llm_output(bad_text, mock_data)

    if result is None:
        print(" Sanitizer correctly REJECTED non-compliant output.")
    else:
        print("[FAIL] Sanitizer FAILED to reject non-compliant output.")


if __name__ == "__main__":
    test_fallback_parity()
    test_sanitizer_strict_reject()
