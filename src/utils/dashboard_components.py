import pandas as pd
import plotly.express as px
import streamlit as st


def render_expert_ensemble(result):
    """Renders the status grid and reasoning logs for all domain expert agents."""
    llm_data = result.get("llm_data", {})
    if not llm_data:
        return
    st.markdown("---")
    st.markdown("### Expert Agent Console")
    c1, c2, c3, c4 = st.columns(4)
    active_agent = llm_data.get("agent_name", "Generalist")
    reasoning = llm_data.get("expert_reasoning", "Normal operation.")
    with c1:
        st.markdown(
            "**Bearing Expert**\n[OK] HEALTHY"
            if "Bearing" not in active_agent
            else "[WARNING] WARNING"
        )
    with c2:
        st.markdown(
            "**Thermal Expert**\n[OK] HEALTHY" if "Thermal" not in active_agent else " OVERHEAT"
        )
    with c3:
        st.markdown(
            "**Electrical Expert**\n[OK] HEALTHY"
            if "Insulation" not in active_agent
            else "[WARNING] OVERLOAD"
        )
    with c4:
        st.markdown(
            "**Operator Checklist**\n[OK] HEALTHY"
            if "Checklist" not in active_agent
            else "[WARNING] FLAGGED"
        )
    st.info(f"**Agent Reasoning:** {reasoning}")


def render_operating_envelope(result, envelope_chart):
    """Renders the operating envelope mapping current load vs casing temperature rise."""
    env = result.get("envelope", {"current_pct": 0, "temp_pct": 0})
    df_env = pd.DataFrame([env])
    fig = px.scatter(df_env, x="current_pct", y="temp_pct", range_x=[0, 2], range_y=[0, 2])
    fig.add_shape(type="rect", x0=0, y0=0, x1=1.0, y1=0.85, fillcolor="Green", opacity=0.1)
    fig.update_layout(
        height=350,
        margin=dict(l=20, r=20, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    envelope_chart.plotly_chart(fig, use_container_width=True)


def render_hero_insight(result, insight_placeholder):
    """Renders the final combined AI diagnostic verdict and LPTN countdown clock."""
    event = result.get("event", "NORMAL")
    urgency = result.get("urgency", "LOW")
    rec_color = "green" if urgency == "LOW" else "orange" if urgency != "URGENT" else "red"
    explanation = result.get("explanation", "")
    time_to_trip = result.get("time_to_trip")

    with insight_placeholder.container():
        if explanation == "PENDING":
            st.info("[BUSY] AI Copilot drafting...")
        elif explanation == "ERROR: LOCAL_UNREACHABLE":
            st.error("[ALERT] Reasoning Engine Offline: Local Unreachable")
        elif explanation == "ERROR: CLOUD_UNREACHABLE":
            st.error("[ALERT] Reasoning Engine Offline: Cloud Unreachable")
        elif explanation and explanation.startswith("ERROR:"):
            st.error(f"[ALERT] Reasoning Engine Offline: {explanation}")
        else:
            # Render Warning Card if countdown is active
            if time_to_trip is not None:
                if time_to_trip == 0.0:
                    st.error(
                        "[ALERT] MOTOR TRIP CRITICAL: Temperature has reached absolute Class F thermal limit!"
                    )
                else:
                    mins = int(time_to_trip // 60)
                    secs = int(time_to_trip % 60)
                    st.error(
                        f"[WARNING] THERMAL OVERLOAD: Estimated time before safety thermal trip: **{mins}m {secs}s** (Based on physics-informed LPTN thermal twin projection)"
                    )

            st.markdown(f"### AI Diagnosis: {event}")
            st.markdown(f"**Recommendation:** :{rec_color}[{result.get('recommendation', 'N/A')}]")
            if explanation:
                st.write(explanation)
        render_expert_ensemble(result)
