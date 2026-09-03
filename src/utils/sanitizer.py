# sanitizer.py
import json
import re

from src.utils.logger import get_logger

logger = get_logger(__name__)


def sanitize_llm_output(text, data):
    # Load structured template data
    duration = data.get("duration_human", "N/A")
    persistence = data.get("persistence_cycles", 0)

    # 2. Attempt to Parse LLM Enhancement
    llm_enhancement = {}
    try:
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            llm_enhancement = json.loads(json_match.group())
    except Exception as e:
        logger.debug(f"Failed to parse LLM JSON: {e}")

    # 3. Final Construction with Quality Check
    enhancement_results = {
        "situation": validate_llm_content(
            llm_enhancement.get("situation"), duration, persistence, must_have_context=True
        ),
        "interpretation": validate_llm_content(
            llm_enhancement.get("interpretation"), duration, persistence, must_have_context=False
        ),
        "risk": validate_llm_content(
            llm_enhancement.get("risk"), duration, persistence, must_have_context=False
        ),
        "justification": validate_llm_content(
            llm_enhancement.get("justification"), duration, persistence, must_have_context=False
        ),
    }

    # STRICT REJECT: If ANY field failed validation, reject the entire LLM output
    if any(v is None for v in enhancement_results.values()):
        return None

    # 4. Final Formatting (only if 100% valid)
    final_output = {
        "1. Situation Summary:": enhancement_results["situation"],
        "2. Interpretation:": enhancement_results["interpretation"],
        "3. Risk Insight:": enhancement_results["risk"],
        "4. Decision Justification:": enhancement_results["justification"],
    }

    formatted = []
    for header, content in final_output.items():
        # Remove action verbs as a safety net
        content = strip_action_verbs(content)
        formatted.append(f"{header}\n{content}")

    return "\n".join(formatted)


def validate_llm_content(llm_text, duration, persistence, must_have_context=False):
    if not llm_text or not isinstance(llm_text, str):
        return None

    # Constraints: 12-60 words (Relaxed from 25 for local model nuance)
    word_count = len(llm_text.split())
    if word_count < 12 or word_count > 60:
        return None

    # Must be grammatically complete
    if not llm_text.strip().endswith((".", "!", "?")):
        return None

    # Context check (Only if mandatory for this field)
    if must_have_context:
        has_duration = (
            str(duration) in llm_text
            or "hour" in llm_text.lower()
            or "min" in llm_text.lower()
            or "sec" in llm_text.lower()
            or "time" in llm_text.lower()
        )
        has_persistence = str(persistence) in llm_text or "cycle" in llm_text.lower()
        if not (has_duration or has_persistence):
            return None

    # Must not contain action verbs (Safety net)
    forbidden = ["inspect", "check", "verify", "repair", "replace", "examine", "monitor"]
    if any(verb in llm_text.lower() for verb in forbidden):
        return None

    return llm_text


def strip_action_verbs(text):
    forbidden = ["inspect", "check", "verify", "repair", "replace", "examine", "monitor"]
    for verb in forbidden:
        text = re.sub(rf"\b{verb}\b", "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def get_contextual_fallback(data):
    return sanitize_llm_output("{}", data)
