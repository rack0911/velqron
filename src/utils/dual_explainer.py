# dual_explainer.py
import json
import os

import httpx
from dotenv import load_dotenv

from src.utils.logger import get_logger

# Load API key from .env file
load_dotenv()
api_key = os.getenv("NVIDIA_API_KEY", "")

# ---------- STATIC SYSTEM PROMPT TEMPLATE (CAG) ----------
STATIC_REASONING_INSTRUCTIONS = """
You are a senior industrial reliability engineer specializing in Electrical Signature Analysis (ESA).
Your task is to analyze motor telemetry and generate a structured technical reasoning report.

Output MUST be a valid JSON object with these EXACT keys:
{
  "situation": "Sentence describing the electromechanical condition",
  "interpretation": "Sentence explaining the physical failure mechanism or signature pattern",
  "risk": "Sentence explaining the long-term impact on machine health (insulation, bearings, or windings)",
  "justification": "Sentence explaining why the specific urgency level is technically appropriate"
}

TECHNICAL GUIDELINES:
- Use industry-standard terminology: 'thermal degradation,' 'winding insulation integrity,'
  'mechanical impedance,' 'rotor bar anomalies,' 'transient surges.'
- Be precise and descriptive (15-30 words per section).
- Use professional, analytical language. Avoid 'dramatic' or 'scary' words.
- DO NOT use imperative verbs or issue instructions (e.g., do NOT use 'check', 'inspect', 'verify', 'repair', 'monitor').
- Only describe the observed state and the physical physics behind it.
- MUST incorporate reference to the observed duration and persistence cycle count in every section to establish the timeline.
- Link the Interpretation specifically to the telemetry signature (current deviation, persistence, and trends).
"""


def build_static_grounding_str(data):
    grounding = data.get("grounding_context", {})
    if not grounding:
        return ""
    specs = grounding.get("motor_specs", {})
    comm = grounding.get("commissioning_record", {})

    grounding_str = "\nSTATIC GROUNDING SPECIFICATIONS (CAG-Cachable):\n"
    if specs:
        manufacturer = specs.get("manufacturer") or specs.get("make") or "Unknown"
        model = specs.get("model") or "Unknown"
        rated_current = specs.get("rated_current")
        max_temp = specs.get("max_temp_c")
        location = specs.get("location")
        rpm = specs.get("rpm") or specs.get("rated_speed_rpm")
        ins_class = specs.get("insulation_class")
        grounding_str += f"- Motor Specifications: Manufacturer {manufacturer}, Model {model}, Rated Current {rated_current}A, Max Temp {max_temp}C, Location {location}, RPM {rpm}, Insulation Class {ins_class}\n"
        if "asset_name" in specs:
            grounding_str += f"- Asset Name: {specs.get('asset_name')}\n"
            grounding_str += f"- Rated Voltage: {specs.get('rated_voltage')} V\n"
            grounding_str += f"- Rated Current: {specs.get('rated_current')} A\n"
            grounding_str += f"- Rated Power: {specs.get('rated_power_kw')} kW\n"
            grounding_str += f"- Service Factor: {specs.get('service_factor')}\n"
            grounding_str += f"- Installation Date: {specs.get('installation_date')}\n"

    if comm:
        grounding_str += f"- Calibration Baseline: Symmetry Ratio {comm.get('symmetry_ratio')}, Zero Offset {comm.get('zero_offset')}, Noise Floor {comm.get('noise_floor')}\n"
    return grounding_str


def build_dynamic_grounding_str(data):
    grounding = data.get("grounding_context", {})
    if not grounding:
        return ""
    cycles = grounding.get("cycle_summaries", [])
    maint = grounding.get("maintenance_records", [])
    op_ins = grounding.get("operator_inspection", {})

    grounding_str = "\nDYNAMIC OPERATING HISTORY (RAG):\n"
    if op_ins:
        grounding_str += f"- Active Visual Shift Checklist: Shaft Wobble {bool(op_ins.get('shaft_wobble'))}, Bearing Grinding {bool(op_ins.get('bearing_grinding'))}, Stator Clogged {bool(op_ins.get('stator_clogged'))}, Oil Leak {bool(op_ins.get('oil_leak'))}, Operator: {op_ins.get('operator_name')}, Notes: {op_ins.get('notes')}\n"

    if cycles:
        grounding_str += "- Recent Cycle Logs:\n"
        for c in cycles[:5]:
            cycle_id = c.get("cycle_id") or "N/A"
            avg_i = c.get("avg_current") if c.get("avg_current") is not None else c.get("current")
            max_t = (
                c.get("max_temp") if c.get("max_temp") is not None else c.get("temperature_rise")
            )
            verdict = c.get("verdict") or c.get("rule_flags") or "NORMAL"
            anom = c.get("anomaly_score", 0.0)
            status = c.get("review_status") or "NEW"
            ts = c.get("timestamp") or "N/A"
            grounding_str += f"  * Cycle ID {cycle_id}: Timestamp: {ts}, Current {avg_i}A, Temp {max_t}C, Verdict: {verdict}, Anomaly Score: {anom}, Review Status: {status}\n"

    if maint:
        grounding_str += "- Operator Feedback History:\n"
        for m in maint[:5]:
            ts = m.get("timestamp")
            action = m.get("action_taken") or m.get("notes") or "Maintenance"
            status = m.get("operator_status") or ("Yes" if m.get("resolved") else "No")
            verdict = m.get("verdict") or ("RESOLVED" if m.get("resolved") else "PENDING")
            grounding_str += (
                f"  * Date: {ts}, Status: {status}, Verdict: {verdict}, Notes: {action}\n"
            )

    return grounding_str


def build_split_prompts(data):
    """Splits unified diagnostic context into Cachable Static System Context and Dynamic User Context."""
    schematic_str = ""
    if "schematics" in data and data["schematics"]:
        schematic_str = f"\nPhysical Schematics Coordinate Reference:\n{json.dumps(data['schematics'], indent=2)}"

    spectral_str = ""
    if "spectral_analysis" in data and data["spectral_analysis"]:
        spectral_str = (
            f"\nSpectral Signature Analysis:\n{json.dumps(data['spectral_analysis'], indent=2)}"
        )

    static_grounding = build_static_grounding_str(data)
    dynamic_grounding = build_dynamic_grounding_str(data)

    system_prompt = f"""{STATIC_REASONING_INSTRUCTIONS}
{static_grounding}
{schematic_str}
{spectral_str}
"""

    user_prompt = f"""ANOMALY EVENT PARTICULARS:
- Event: {data.get("event_clean")}
- Failure Mode: {data.get("failure_mode")}
- Severity: {data.get("severity")}
- Urgency: {data.get("urgency")}
- Recommended Action: {data.get("recommended_action")}

TELEMETRY SIGNATURE:
- Duration: {data.get("duration_human")}
- Persistence: {data.get("persistence_cycles")} cycles
- Trend: {data.get("trend")}
- Baseline Divergence: Current BDI {data.get("bdi_current", 0.0)}, Temp BDI {data.get("bdi_temp", 0.0)}
- Deviation Level: {data.get("deviation_level", "nominal")}
- Sanity Check: {json.dumps(data.get("sanity_check", {"status": "HEALTHY"}))}

{dynamic_grounding}
"""
    return system_prompt, user_prompt


logger = get_logger(__name__)


# ---------- LOCAL (OLLAMA CHAT WITH KV CACHE) ----------
def local_explainer(data):
    system_prompt, user_prompt = build_split_prompts(data)

    try:
        with httpx.Client(verify=True) as client:
            response = client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": "qwen2.5:3b",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"num_ctx": 4096},
                },
                timeout=5.0,
            )
            response_data = response.json()
            if "message" in response_data and "content" in response_data["message"]:
                return response_data["message"]["content"].strip()
            return response_data.get("response", "").strip()
    except Exception as e:
        logger.warning(f"Ollama local explainer failed: {e}")
        return "ERROR: LOCAL_FAILED"


# ---------- NVIDIA CHAT COMPLETIONS (NIM) ----------
def nvidia_explainer(data):
    if not api_key:
        return "ERROR: NO_API_KEY"

    system_prompt, user_prompt = build_split_prompts(data)

    try:
        with httpx.Client(verify=True) as client:
            response = client.post(
                url="https://integrate.api.nvidia.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                data=json.dumps(
                    {
                        "model": "google/gemma-4-31b-it",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 512,
                    }
                ),
                timeout=60.0,
            )
            response_data = response.json()
            if "choices" in response_data:
                return response_data["choices"][0]["message"]["content"].strip()
            else:
                logger.error(f"NVIDIA API Error: {response_data}")
                return "ERROR: CLOUD_FAILED"
    except Exception as e:
        logger.error(f"NVIDIA cloud explainer failed: {e}")
        return "ERROR: CLOUD_FAILED"


# ---------- MODES ----------
def generate_reasoning(data, mode="Local Priority"):
    """
    Unified reasoning generator.
    Modes:
      - "Local Priority" or "Local Only": Uses local Ollama. Returns ERROR: LOCAL_UNREACHABLE on failure.
      - "Combined" or "Cloud Only": Uses NVIDIA NIM. Returns ERROR: CLOUD_UNREACHABLE on failure.
    """
    from src.utils import sanitizer

    # CI/CD Survivability Mode
    if os.getenv("CI_MODE") == "true":
        mock_report = {
            "situation": "CI_MOCK: Steady operation observed.",
            "interpretation": "CI_MOCK: Signal signature matches healthy baseline.",
            "risk": "CI_MOCK: No immediate risk detected.",
            "justification": "CI_MOCK: Analysis verified by automated test.",
        }
        return json.dumps(mock_report)

    is_local_preferred = mode in ["Local Priority", "Local Only", "On-Premise"]

    if is_local_preferred:
        res = local_explainer(data)
        if res == "ERROR: LOCAL_FAILED":
            return "ERROR: LOCAL_UNREACHABLE"
    else:  # Cloud preferred
        res = nvidia_explainer(data)
        if res in ["ERROR: CLOUD_FAILED", "ERROR: NO_API_KEY"]:
            return "ERROR: CLOUD_UNREACHABLE"

    if res and not res.startswith("ERROR:"):
        sanitized = sanitizer.sanitize_llm_output(res, data)
        if sanitized:
            return sanitized

    return res
