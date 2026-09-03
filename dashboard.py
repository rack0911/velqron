import json
import os
import time
from datetime import datetime

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

from src.core.config import CONFIG
from src.core.profile_manager import load_profile, save_profile
from src.utils import database
from src.utils.dashboard_components import render_hero_insight, render_operating_envelope


def check_ingestion_status(motor_id):
    row = database.db.get_latest_telemetry_row(motor_id)
    if not row:
        return False, "No Telemetry Data Available", None
    try:
        ts = datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
        diff = (datetime.now() - ts).total_seconds()
        is_active = diff < 30.0
    except Exception:
        is_active = False

    if is_active:
        if row.get("data_source") == "PHYSICAL":
            return True, "Live Hardware Ingestion Active", row
        else:
            return True, "Simulated Telemetry Fallback", row
    else:
        return False, "Telemetry Ingestion Offline", row


# =========================
# INIT & PAGE CONFIG
# =========================
st.set_page_config(
    page_title="Velqron | Intelligence Dashboard",
    page_icon="assets/favicon.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for "Series A" Premium Look
st.markdown(
    """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400;700&display=swap');

  html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    color: #e6edf3;
  }

  .main {
    background-color: #0d1117;
  }

  /* Monospace for Numbers */
  [data-testid="stMetricValue"], [data-testid="stTable"] {
    font-family: 'JetBrains Mono', monospace !important;
  }

  /* Glassmorphism Metric Cards */
  [data-testid="stMetric"] {
    background: rgba(22, 27, 34, 0.7);
    backdrop-filter: blur(8px);
    border-radius: 16px;
    border: 1px solid rgba(48, 54, 61, 0.8);
    padding: 24px;
    box-shadow: 0 10px 40px rgba(0, 0, 0, 0.4);
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  }

  [data-testid="stMetric"]:hover {
    transform: translateY(-2px) scale(1.01);
    border-color: #58a6ff;
    box-shadow: 0 0 15px rgba(88, 166, 255, 0.3);
  }

  /* Severity Highlighting */
  .severity-NORMAL { color: #238636; }
  .severity-WARNING { color: #d29922; }
  .severity-CRITICAL { color: #f85149; }

  /* Custom UI Components */
  .gradient-text {
    background: linear-gradient(90deg, #58a6ff, #8a2be2);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent !important;
    font-weight: 800;
    margin-bottom: 0px;
    font-size: 1.8rem !important;
  }

  .tag-pill {
    background: rgba(48,54,61,0.5);
    padding: 4px 12px;
    border-radius: 12px;
    margin-right: 8px;
    margin-top: 8px;
    display: inline-block;
    border: 1px solid #30363d;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85em;
  }

  /* Pulsing Status */
  @keyframes heartbeat {
    0% { transform: scale(1); opacity: 0.8; box-shadow: 0 0 0 0px rgba(currentColor, 0.7); }
    50% { transform: scale(1.2); opacity: 1; box-shadow: 0 0 0 4px rgba(currentColor, 0); filter: drop-shadow(0 0 4px currentColor); }
    100% { transform: scale(1); opacity: 0.8; box-shadow: 0 0 0 0px rgba(currentColor, 0); }
  }

  .pulse {
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-right: 6px;
    animation: heartbeat 2s infinite ease-in-out;
  }

  .sidebar-logo {
    margin-bottom: 20px;
    filter: drop-shadow(0 0 8px rgba(88, 166, 255, 0.5));
  }

  /* Global Top Bar */
  .global-top-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: rgba(13, 17, 23, 0.85);
    backdrop-filter: blur(12px);
    padding: 12px 24px;
    border-radius: 12px;
    border-bottom: 1px solid rgba(88, 166, 255, 0.2);
    margin-bottom: 24px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
  }

  .top-bar-brand {
    font-weight: 800;
    letter-spacing: 2px;
    color: #e6edf3;
    font-size: 2.2rem;
  }

  .top-bar-version {
    font-family: 'JetBrains Mono', monospace;
    background: rgba(48,54,61,0.8);
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.75em;
    color: #8b949e;
    border: 1px solid #30363d;
  }

  .top-bar-time {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.9em;
    color: #58a6ff;
  }

  /* Sidebar Overhaul */
  [data-testid="stSidebar"] {
    border-right: 1px solid rgba(88, 166, 255, 0.1);
  }

  .sidebar-app-icon {
    width: 60px;
    height: 60px;
    background: #161b22;
    border-radius: 16px;
    border: 1px solid rgba(88, 166, 255, 0.3);
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 4px 12px rgba(88, 166, 255, 0.1);
    margin-bottom: 20px;
  }

  .sidebar-title {
    font-size: 1.8rem;
    font-weight: 800;
    color: #e6edf3;
    margin-bottom: 2px;
  }

  .sidebar-caption {
    font-size: 0.85rem;
    color: #8b949e;
    margin-bottom: 20px;
  }

  .sidebar-label {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #8b949e;
    font-weight: 600;
    margin-bottom: -10px;
  }
</style>
""",
    unsafe_allow_html=True,
)

# =========================
# SESSION STATE & PERSISTENCE
# =========================
if "profile" not in st.session_state:
    st.session_state.profile = load_profile()

if "history" not in st.session_state:
    st.session_state.history = []

if "demo_active" not in st.session_state:
    st.session_state.demo_active = False

if "demo_cycle_idx" not in st.session_state:
    st.session_state.demo_cycle_idx = 0


# =========================
# SIDEBAR / NAV
# =========================
with st.sidebar:
    st.markdown(
        """
    <div class='sidebar-app-icon'>
      <img src='data:image/png;base64,...' />
    </div>
    <div class='sidebar-title'>Velqron AI</div>
    <div class='sidebar-caption'>Fleqtor Industrial Intelligence</div>
  """,
        unsafe_allow_html=True,
    )

    st.divider()

    # 1. Decision Center
    st.markdown("<div class='sidebar-label'>Intelligence Layer</div><br>", unsafe_allow_html=True)

    mode_options = ["Local Priority", "Combined", "Cloud Only", "Local Only"]
    mode_idx = mode_options.index(CONFIG.LLM_MODE) if CONFIG.LLM_MODE in mode_options else 0

    llm_mode = st.radio(
        "Intelligence",
        options=mode_options,
        index=mode_idx,
        label_visibility="collapsed",
    )

    # 2. Data Source
    st.markdown(
        "<br><div class='sidebar-label'> Telemetry Source</div><br>", unsafe_allow_html=True
    )

    @st.cache_data(ttl=60)
    def get_ollama_model():
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=0.5)
            if r.status_code == 200:
                models = r.json().get("models", [])
                return models[0]["name"] if models else "Ollama (No Models)"
            return "Ollama Offline"
        except Exception:
            return "Ollama Offline"

    motor_id = st.session_state.profile.get("motor_id", "SIM_MOTOR_01")
    hw_detected, hw_status_text, _ = check_ingestion_status(motor_id)

    source_options = ["Live Hardware", "Cinematic Demo"]
    # Default to Live Hardware if config says PHYSICAL, otherwise Demo
    default_source_idx = 0 if CONFIG.DATA_SOURCE == "PHYSICAL" else 1
    if not hw_detected and default_source_idx == 0:
        default_source_idx = 1  # Fallback to demo if hardware missing

    data_source = st.radio(
        "Source",
        options=source_options,
        index=default_source_idx,
        label_visibility="collapsed",
        key="data_source_selector",
    )

    if not hw_detected and data_source == "Live Hardware":
        st.warning(" Searching for ESP32 hardware...")

    # 3. Motor Commissioning (Ground Truth)
    st.divider()
    with st.expander(" Motor Commissioning", expanded=False):
        name = st.text_input("Motor Nickname", value=st.session_state.profile["motor_name"])
        loc = st.text_input("Location", value=st.session_state.profile.get("location", ""))

        c1, c2 = st.columns(2)
        i_rated = c1.number_input(
            "Rated Current (A)", value=st.session_state.profile.get("rated_current", 1.5)
        )
        t_max = c2.number_input(
            "Max Temp (°C)", value=st.session_state.profile.get("max_temp_c", 125.0)
        )

        c3, c4 = st.columns(2)
        insul = c3.selectbox(
            "Insulation Class",
            options=["B", "F", "H"],
            index=["B", "F", "H"].index(st.session_state.profile.get("insulation_class", "F")),
        )
        sf = c4.number_input(
            "Service Factor", value=st.session_state.profile.get("service_factor", 1.15)
        )

        if st.button(" Save Commissioning Data", use_container_width=True):
            st.session_state.profile.update(
                {
                    "motor_name": name,
                    "location": loc,
                    "rated_current": i_rated,
                    "max_temp_c": t_max,
                    "insulation_class": insul,
                    "service_factor": sf,
                }
            )
            save_profile(st.session_state.profile)
            st.toast("Ground Truth Updated ")

    # 4. Maintenance & Hardware Ops
    st.divider()
    st.markdown("<div class='sidebar-label'> Maintenance Ops</div><br>", unsafe_allow_html=True)

    col_m1, col_m2 = st.columns(2)
    if col_m1.button("Reset Log Service", help="Resets fault state & baseline"):
        from src.core.analyzer import orchestrator
        from src.engines import logic_controller as logic
        from src.utils.database import db

        motor_id = st.session_state.profile.get("motor_id", "SIM_MOTOR_01")
        context = orchestrator.get_context(motor_id)

        context.reset_state()
        logic.reset_persistence_state(context)
        db.clear_history(motor_id)
        st.session_state.profile["last_maintenance_date"] = datetime.now().strftime("%Y-%m-%d")
        save_profile(st.session_state.profile)
        st.success("Maintenance Logged")
        time.sleep(1)
        st.rerun()

    if col_m2.button(" Re-Zero", help="Auto-calibrates sensor bias"):
        try:
            os.makedirs("data", exist_ok=True)
            with open("data/.command_mailbox", "w") as f:
                f.write("R")
            st.info("Calibration request queued in mailbox...")
        except Exception as e:
            st.error(f"Failed to queue command: {e}")

    # 5. Demo Controls (If Demo)
    if data_source == "Cinematic Demo":
        st.divider()
        st.markdown("### Showreel Sequence")

        with open("tests/fixtures/simulated_cycles.json", "r") as f:
            demo_data = json.load(f)

        profiles = list(set([d["profile"] for d in demo_data]))
        if "last_scenario" not in st.session_state:
            st.session_state.last_scenario = profiles[0]

        selected_scenario = st.selectbox("Select Story", options=profiles, key="selected_story")

        if selected_scenario != st.session_state.last_scenario:
            st.session_state.demo_cycle_idx = 0
            st.session_state.last_scenario = selected_scenario

        scenario_data = [d for d in demo_data if d["profile"] == selected_scenario]

        col1, col2 = st.columns(2)
        if col1.button(" Play Demo"):
            st.session_state.demo_active = True
            st.session_state.demo_cycle_idx = 0
            st.rerun()
        if col2.button(" Stop"):
            st.session_state.demo_active = False
            st.rerun()

        st.session_state.scenario_data = scenario_data

        if not st.session_state.demo_active and "scenario_data" in st.session_state:
            st.session_state.demo_cycle_idx = st.slider(
                "Manual Browse",
                0,
                len(st.session_state.scenario_data) - 1,
                st.session_state.demo_cycle_idx,
            )

# =========================
# MAIN DASHBOARD
# =========================

st.markdown(
    f"<div class='global-top-bar'>"
    f"<div class='top-bar-brand'> VELQRON OS</div>"
    f"<div class='top-bar-version'>MVP BUILD v1.5</div>"
    f"<div class='top-bar-time'>"
    f"SYS.TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>"
    f"</div>",
    unsafe_allow_html=True,
)

if data_source == "Cinematic Demo":
    st.info(" **DEMO MODE ACTIVE**")

st.divider()

col_header, col_status = st.columns([3, 1])
with col_header:
    st.markdown(
        f"<h2 class='gradient-text' style='margin-top: 0; padding-top: 5px;'>{st.session_state.profile['motor_name']}</h2>",
        unsafe_allow_html=True,
    )
    p = st.session_state.profile
    tech_specs = [
        f"<span class='tag-pill'> $I_{{rated}}$: {p.get('rated_current', 1.5)}A</span>",
        f"<span class='tag-pill'> $T_{{max}}$: {p.get('max_temp_c', 125)}°C</span>",
    ]
    st.markdown("".join(tech_specs), unsafe_allow_html=True)

with col_status:
    o_status = get_ollama_model()
    o_color = "#238636" if "Offline" not in o_status else "#f85149"
    st.markdown(
        f"<div style='margin-bottom: 8px;'><span class='pulse' style='background-color:{o_color}; color:{o_color}'></span> {o_status}</div>",
        unsafe_allow_html=True,
    )

    if hw_detected:
        hw_color, hw_text = "#238636", hw_status_text
    else:
        hw_color, hw_text = "#f85149", hw_status_text

    st.markdown(
        f"<div><span class='pulse' style='background-color:{hw_color}; color:{hw_color}'></span> {hw_text}</div>",
        unsafe_allow_html=True,
    )

st.divider()

tab_live, tab_evidence, tab_calib = st.tabs(
    [" Live Intelligence", " Evidence Store", " System Calibration"]
)

with tab_live:
    insight_placeholder = st.empty()

st.divider()
t1, t2, t3, t4, t5 = st.columns(5)
c_metric = t1.empty()
p_metric = t2.empty()
r_metric = t3.empty()
u_metric = t4.empty()
h_metric = t5.empty()

col_chart, col_envelope = st.columns([2, 1])
with col_chart:
    st.subheader(" Electrical Performance")
    wave_chart = st.empty()

with col_envelope:
    st.subheader(" Operating Envelope")
    envelope_chart = st.empty()

# =========================
# ANALYTICS RENDERERS (IMPORTED)
# =========================


# =========================
# LIVE LOOP
# =========================
st.sidebar.divider()
live_updates = st.sidebar.toggle(" Live Updates", value=True)

if live_updates:
    if data_source == "Cinematic Demo":
        st.info("Cinematic Demo logic runs locally in session.")
        # (Demo logic omitted for brevity, but would be here)
        time.sleep(1.0)
        st.rerun()
    else:
        # LIVE HARDWARE MODE (Decoupled, reads exclusively from SQLite)
        motor_id = st.session_state.profile.get("motor_id", "SIM_MOTOR_01")
        row = database.db.get_latest_telemetry_row(motor_id)
        if not row:
            st.warning("Waiting for live telemetry from ingestion daemon...")
            time.sleep(1.0)
            st.rerun()
        assert row is not None

        from src.core.analyzer import orchestrator
        from src.engines import signal_controller
        from src.engines.decision_engine import calculate_sustainability_impact

        context = orchestrator.get_context(motor_id)
        baseline = signal_controller.get_baseline(context)
        baseline_current = baseline.get("avg_current", 0.0) if baseline else 0.0

        # Reconstruct tick and result from database row
        tick = {
            "current": row["current"],
            "temperature": row["temperature"],
            "health": 3,
            "data_source": row.get("data_source", "PHYSICAL"),
            "timestamp": row["timestamp"],
        }

        result = {
            "event": row.get("rule_flags", "NORMAL") or "NORMAL",
            "status": row.get("operating_mode", "OFF"),
            "severity": row.get("severity", "NONE") or "NONE",
            "confidence": row.get("rule_confidence", 1.0)
            if row.get("rule_confidence") is not None
            else 1.0,
            "failure_mode": row.get("rule_flags", "NONE") or "NONE",
            "explanation": row.get("explanation", "System operating normally.")
            or "System operating normally.",
            "recommendation": row.get("recommendation", "Continue Monitoring")
            or "Continue Monitoring",
            "urgency": row.get("urgency", "LOW") or "LOW",
            "drift_score": row.get("drift_score", 0.0),
            "deviation_score": row.get("deviation_score", 0.0),
            "trend_score": row.get("trend_score", 0.0),
            "anomaly_score": row.get("anomaly_score", 0.0),
            "voltage": row.get("voltage", 415.0),
            "power_factor": row.get("power_factor", 0.85),
            "time_to_trip": row.get("time_to_trip"),
            "envelope": {
                "current_pct": round(
                    row["current"] / st.session_state.profile.get("rated_current", 2.2), 2
                )
                if st.session_state.profile.get("rated_current", 2.2) > 0
                else 0,
                "temp_pct": round(
                    row["temperature"] / st.session_state.profile.get("max_temp_c", 125.0), 2
                )
                if st.session_state.profile.get("max_temp_c", 125.0) > 0
                else 0,
            },
        }

        # Initialize session state for sustainability accumulators
        if "sustainability" not in st.session_state:
            st.session_state.sustainability = {
                "total_kwh": 0.0,
                "total_co2": 0.0,
                "total_cost": 0.0,
            }

        # Calculate impact rate for this second (duration_sec = 1.0)
        impact = calculate_sustainability_impact(
            avg_current=tick["current"],
            baseline_current=baseline_current,
            duration_sec=1.0,
            voltage=result.get("voltage", 415.0),
            power_factor=result.get("power_factor", 0.85),
        )

        # Accumulate
        st.session_state.sustainability["total_kwh"] += impact["excess_kwh"]
        st.session_state.sustainability["total_co2"] += impact["excess_co2_kg"]
        st.session_state.sustainability["total_cost"] += impact["excess_cost_usd"]

        # Calculate hourly rate (duration_sec = 3600.0)
        hourly_impact = calculate_sustainability_impact(
            avg_current=tick["current"],
            baseline_current=baseline_current,
            duration_sec=3600.0,
            voltage=result.get("voltage", 415.0),
            power_factor=result.get("power_factor", 0.85),
        )

        if "rt_history" not in st.session_state:
            st.session_state.rt_history = []
        st.session_state.rt_history.append(tick)
        if len(st.session_state.rt_history) > 50:
            st.session_state.rt_history.pop(0)

        # Render metrics
        c_metric.metric("Load", f"{tick['current']:.2f} A")
        p_metric.metric("Temp", f"{tick['temperature']:.1f} °C")
        r_metric.metric("Excess Cost Rate", f"${hourly_impact['excess_cost_usd']:.2f}/hr")
        u_metric.metric("CO2 Rate", f"{hourly_impact['excess_co2_kg']:.2f} kg/hr")
        h_metric.metric("Accumulated Loss", f"${st.session_state.sustainability['total_cost']:.4f}")

        # Render chart
        df_chart = pd.DataFrame(st.session_state.rt_history)
        if not df_chart.empty:
            fig_chart = px.line(
                df_chart, y=["current", "temperature"], title="Real-time Telemetry (Last 50 Ticks)"
            )
            fig_chart.update_layout(
                height=350,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color="#e6edf3"),
            )
            wave_chart.plotly_chart(fig_chart, use_container_width=True)

        render_operating_envelope(result, envelope_chart)
        render_hero_insight(result, insight_placeholder)

        # Render Sustainability Section in Live Tab
        with tab_live:
            st.markdown("---")
            st.subheader(" Sustainability & Eco-Impact")
            col_sust1, col_sust2, col_sust3 = st.columns(3)
            with col_sust1:
                st.metric(
                    "Total Excess Energy Wasted",
                    f"{st.session_state.sustainability['total_kwh']:.4f} kWh",
                )
            with col_sust2:
                st.metric(
                    "Total Excess CO2 Wasted",
                    f"{st.session_state.sustainability['total_co2']:.4f} kg CO2",
                )
            with col_sust3:
                st.metric(
                    "Total Financial Loss",
                    f"${st.session_state.sustainability['total_cost']:.4f} USD",
                )
            st.info(
                f"[INFO] Calculations are grounded on standard factory settings (Nominal Voltage: {result.get('voltage', 415.0)}V, Power Factor: {result.get('power_factor', 0.85)}). Excess consumption is calculated as deviations from the active auto-learned baseline current of {baseline_current:.2f}A."
            )

        time.sleep(1.0)
        st.rerun()


def render_evidence_store():
    st.markdown("## Evidence Store & Operator Verification")
    st.write(
        "Review recent anomalous cycles, assess local LLM explanations, and verify diagnostic verdicts to maintain ground truth."
    )

    from src.utils.database import db

    motor_id = st.session_state.profile.get("motor_id", "SIM_MOTOR_01")
    cycles = db.get_recent_cycles_with_details(limit=50)

    if not cycles:
        st.info("No historical cycles recorded in the Evidence Store.")
        return

    df_cycles = pd.DataFrame(cycles)
    df_display = df_cycles[
        [
            "id",
            "timestamp",
            "avg_current",
            "max_temp",
            "event_type",
            "severity",
            "confidence",
            "data_source",
        ]
    ].copy()
    df_display.columns = [
        "Cycle ID",
        "Timestamp",
        "Current (A)",
        "Temp (°C)",
        "AI Verdict",
        "Severity",
        "Confidence",
        "Source",
    ]

    st.dataframe(df_display, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader(" Log Verification & Operator Feedback")

    cycle_ids = df_cycles["id"].tolist()
    selected_cycle_id = st.selectbox(
        "Select Cycle ID to Verify",
        options=cycle_ids,
        format_func=lambda x: (
            f"Cycle {x} - {df_cycles[df_cycles['id'] == x]['timestamp'].values[0]} ({df_cycles[df_cycles['id'] == x]['event_type'].values[0]})"
        ),
    )

    if selected_cycle_id:
        cycle_row = df_cycles[df_cycles["id"] == selected_cycle_id].iloc[0]
        trail = db.get_cycle_audit_trail(selected_cycle_id)
        llm_explanation = "No explanation recorded."
        if trail:
            llm_explanation = trail.get("explanation") or "No explanation recorded."

        st.markdown(
            f"**AI Verdict:** `{cycle_row['event_type']}` | **Severity:** `{cycle_row['severity']}` | **Confidence:** `{cycle_row['confidence']:.2f}`"
        )
        st.markdown("**AI Recommendation & Explanation:**")
        st.info(llm_explanation)

        col_fb1, col_fb2 = st.columns(2)
        with col_fb1:
            feedback_status = st.selectbox(
                "Verification Verdict", options=["CORRECT", "INCORRECT", "NOISE"]
            )
        with col_fb2:
            operator_notes = st.text_input("Shift Notes / Root Cause Findings")

        if st.button("Submit Verification & Log Feedback", use_container_width=True):
            db.add_operator_feedback(selected_cycle_id, feedback_status, operator_notes)
            st.toast(f"Logged verification for Cycle {selected_cycle_id}")
            st.success(f"Feedback successfully logged for Cycle {selected_cycle_id}!")
            time.sleep(1.0)
            st.rerun()

    st.divider()
    st.subheader(" Ground Truth Verification History")
    feedback_logs = db.get_operator_feedback_list(motor_id, limit=30)
    if feedback_logs:
        df_fb = pd.DataFrame(feedback_logs)
        df_fb_disp = df_fb[
            ["timestamp", "rule_diagnosis", "actual_root_cause", "is_correct", "notes"]
        ].copy()
        df_fb_disp.columns = [
            "Timestamp",
            "AI Verdict",
            "Operator Verification",
            "Is Correct",
            "Operator Notes",
        ]
        df_fb_disp["Is Correct"] = df_fb_disp["Is Correct"].apply(
            lambda x: "Yes" if x == 1 else "No"
        )
        st.dataframe(df_fb_disp, use_container_width=True, hide_index=True)
    else:
        st.info("No operator verifications logged yet.")


with tab_evidence:
    render_evidence_store()


def render_system_calibration():
    st.markdown("## System Calibration & Baseline Grounding")
    st.write(
        "Ground your edge-based AI with local manual calibration resets and manufacturer nameplate specifications."
    )

    from src.core.analyzer import orchestrator
    from src.engines import signal_controller

    motor_id = st.session_state.profile.get("motor_id", "SIM_MOTOR_01")
    context = orchestrator.get_context(motor_id)

    # Load baseline parameters
    baseline = signal_controller.get_baseline(context)
    profile = st.session_state.profile

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("[INFO] Manufacturer Ground Truth")
        st.markdown(f"**Motor Nickname:** `{profile.get('motor_name', 'N/A')}`")
        st.markdown(f"**Location:** `{profile.get('location', 'N/A')}`")
        st.markdown(f"**Rated Current (FLA):** `{profile.get('rated_current', 1.5):.2f} A`")
        st.markdown(f"**Service Factor (SF):** `{profile.get('service_factor', 1.15):.2f}`")
        st.markdown(f"**Max Temp Limit:** `{profile.get('max_temp_c', 125.0):.1f} °C`")
        st.markdown(f"**Insulation Class:** `{profile.get('insulation_class', 'F')}`")

    with col2:
        st.subheader("[BASELINE] Current Auto-Learned Baseline")
        if baseline:
            st.markdown(f"**Steady-State Current:** `{baseline.get('avg_current', 0.0):.2f} A`")
            st.markdown(f"**Steady-State Temp:** `{baseline.get('avg_temp', 0.0):.1f} °C`")
            st.markdown(f"**Average Cycle Runtime:** `{baseline.get('avg_runtime', 0.0):.1f} sec`")
            st.markdown(
                f"**Baseline Current Fluctuation (BDI Current):** `{baseline.get('bdi_current', 0.0):.4f}`"
            )
            st.markdown(
                f"**Baseline Thermal Fluctuation (BDI Temp):** `{baseline.get('bdi_temp', 0.0):.4f}`"
            )
        else:
            st.info(
                "No auto-learned baseline active. Run motor for healthy operating cycles to establish baseline."
            )

    st.divider()

    # 2. Validation Checks Display
    st.subheader("[SECURITY] Baseline Grounding Check")
    if baseline:
        status = baseline.get("validation_status", "VALID")
        notes = baseline.get("validation_notes", [])

        if status == "VALID":
            st.success(
                "[OK] Baseline Grounding is Healthy. Auto-learned parameters are within manufacturer ratings."
            )
        elif status == "WARNING":
            st.warning(
                "[WARNING] Baseline Grounding Warning: Elevated stress detected during learning phase."
            )
            for note in notes:
                st.markdown(f"- {note}")
        else:  # INVALID
            st.error(
                "[ALERT] Baseline Grounding Invalid: Overloaded operational cycles detected during learning!"
            )
            for note in notes:
                st.markdown(f"- {note}")
            st.info(
                "[TIP] Clamping has been automatically applied to restrict baseline reference to rated values, protecting overload sensitivity."
            )
    else:
        st.info("Awaiting calibration data to perform grounding validation.")

    st.divider()

    # 3. Action Buttons
    st.subheader("[RESET] Calibration & Commissioning Operations")
    st.write("Perform system diagnostics or clear baseline metrics after machine servicing.")

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button(
            "[RESET] Reset Baseline & Re-Calibrate",
            help="Resets fault states and clears historical cycle records locally",
            use_container_width=True,
        ):
            try:
                import os

                os.makedirs("data", exist_ok=True)
                with open("data/.command_mailbox", "w") as f:
                    f.write("RESET")

                from src.engines import logic_controller as logic
                from src.utils.database import db

                context.reset_state()
                logic.reset_persistence_state(context)
                db.clear_history(motor_id)

                st.session_state.profile["last_maintenance_date"] = datetime.now().strftime(
                    "%Y-%m-%d"
                )
                save_profile(st.session_state.profile)

                # Log audit event
                db.log_audit_event(
                    "BASELINE_RESET",
                    "Operator manually cleared baseline history and fault events.",
                    "Operator",
                )

                st.toast("Baseline reset successfully. Calibrating next cycle...")
                st.success("Baseline cleared! Run the motor now to re-learn baseline parameters.")
                time.sleep(1.5)
                st.rerun()
            except Exception as e:
                st.error(f"Failed to reset baseline: {e}")

    with col_btn2:
        if st.button(
            "[SCAN] Commissioning Self-Test",
            help="Tests Modbus connections & sensor health",
            use_container_width=True,
        ):
            try:
                import os

                result_file = "data/self_test_result.json"
                if os.path.exists(result_file):
                    os.remove(result_file)

                os.makedirs("data", exist_ok=True)
                with open("data/.command_mailbox", "w") as f:
                    f.write("TEST_HARDWARE")

                st.toast("Commissioning Self-Test request sent...")

                found = False
                with st.spinner("Executing hardware self-test, please wait..."):
                    for _ in range(20):
                        time.sleep(0.5)
                        if os.path.exists(result_file):
                            found = True
                            break

                if found:
                    with open(result_file, "r") as rf:
                        res = json.load(rf)

                    st.markdown("### Self-Test Results")
                    st.write(
                        f"Executed: `{datetime.fromtimestamp(res['timestamp']).strftime('%Y-%m-%d %H:%M:%S')}`"
                    )

                    def check_icon(val):
                        return "[OK]" if val else "[ERROR]"

                    st.markdown(
                        f"{check_icon(res.get('serial_connected'))} **Modbus USB-Serial Port Active**"
                    )
                    st.markdown(
                        f"{check_icon(res.get('pzem_connected'))} **PZEM-016 Modbus Meter (Current/Voltage)**"
                    )
                    st.markdown(
                        f"{check_icon(res.get('pt100_connected'))} **PT100 Modbus Converter (Temperature)**"
                    )
                    st.markdown(
                        f"{check_icon(res.get('vibration_connected'))} **ADXL345 Vibration Sensor (I2C)**"
                    )

                    if (
                        res.get("serial_connected")
                        and res.get("pzem_connected")
                        and res.get("pt100_connected")
                    ):
                        st.success(res.get("message", "All components verified successfully!"))
                    else:
                        st.error(
                            res.get(
                                "message",
                                "Some components failed verification. Check wiring & RS485 connections.",
                            )
                        )
                else:
                    st.error(
                        "Timeout: Telemetry reader daemon did not respond. Is `reader.py` running?"
                    )
            except Exception as e:
                st.error(f"Failed to execute self-test: {e}")

    st.divider()
    st.subheader("[AUDIT] Configuration & Action Audit Trail")
    st.write("A permanent record of operator configuration edits and baseline modifications.")

    from src.utils.database import db

    logs = db.get_audit_logs(limit=15)
    if logs:
        import pandas as pd

        df = pd.DataFrame(logs)
        df.columns = ["Timestamp", "Operator", "Action", "Details"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No audit logs recorded yet.")


with tab_calib:
    render_system_calibration()
