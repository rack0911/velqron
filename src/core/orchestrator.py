import json
import time
from typing import Any, Dict, List, Optional

import numpy as np

from src.agents import AgentEnsemble
from src.core.config import CONFIG
from src.core.knowledge import EVENT_TO_KNOWLEDGE, FAULT_KNOWLEDGE, get_motor_specs
from src.core.motor_context import MotorContext
from src.core.profile_manager import load_profile
from src.core.types import AnalysisResult, CycleMetrics, EnvelopeMetrics
from src.engines import (
    decision_engine as decision,
)
from src.engines import (
    logic_controller as logic,
)
from src.engines import (
    pattern_engine as pattern,
)
from src.engines import (
    signal_controller as signal,
)
from src.utils import dual_explainer, llm_input_builder
from src.utils.dsp import analyze_spectral, cache_currents_for_mcsa
from src.utils.logger import get_logger

logger = get_logger(__name__)
ensemble = AgentEnsemble()


class EngineOrchestrator:
    """
    Orchestrates the multi-agent intelligence pipeline for motor analysis.
    Uses a Weighted Ensemble to stabilize industrial diagnostics.
    """

    def __init__(self):
        self.motor_contexts: Dict[str, MotorContext] = {}

    def get_context(self, motor_id: str) -> MotorContext:
        if motor_id not in self.motor_contexts:
            context = MotorContext(motor_id)
            # Phase 1.3: Hydrate context from persistence on first access
            context.load_persistent_state()
            self.motor_contexts[motor_id] = context
        return self.motor_contexts[motor_id]

    def _preprocess_cycle(
        self,
        motor_id: str,
        currents: List[float],
        temperatures: List[float],
        times: List[float],
        vibrations: Optional[Dict[str, List[float]]] = None,
    ) -> CycleMetrics:
        """Centralized preprocessing of raw telemetry data including vibration fusion."""
        avg_i = float(np.mean(currents)) if currents else 0.0
        max_i = float(np.max(currents)) if currents else 0.0
        std_i = float(np.std(currents)) if currents else 0.0

        avg_t = float(np.mean(temperatures)) if temperatures else 0.0
        max_t = float(np.max(temperatures)) if temperatures else 0.0

        runtime = (times[-1] - times[0]) if len(times) > 1 else float(len(times))
        startup_slope = (currents[4] - currents[0]) / 5 if len(currents) > 5 else 0.0
        peak_to_mean = max_i / avg_i if avg_i > 0 else 1.0

        variation = "LOW"
        if std_i > CONFIG.VARIATION_THRESHOLD["HIGH"]:
            variation = "HIGH"
        elif std_i > CONFIG.VARIATION_THRESHOLD["MEDIUM"]:
            variation = "MEDIUM"

        # Vibration Feature Extraction (Aggregated if series provided)
        v_rms = 0.0
        v_peak = 0.0
        v_kurt = 0.0
        v_crest = 0.0

        if vibrations:
            v_rms = float(np.mean(vibrations.get("rms", [0.0])))
            v_peak = float(np.max(vibrations.get("peak", [0.0])))
            v_kurt = float(np.mean(vibrations.get("kurtosis", [3.0])))
            v_crest = float(np.mean(vibrations.get("crest", [1.4])))

        return CycleMetrics(
            motor_id=motor_id,
            avg_current=round(avg_i, 3),
            max_current=round(max_i, 3),
            std_current=round(std_i, 3),
            avg_temp=round(avg_t, 2),
            max_temp=round(max_t, 2),
            runtime_sec=round(runtime, 1),
            startup_slope=round(startup_slope, 4),
            peak_to_mean=round(peak_to_mean, 3),
            variation_level=variation,
            timestamp=time.time(),
            vib_rms=round(v_rms, 4),
            vib_peak=round(v_peak, 4),
            vib_kurtosis=round(v_kurt, 2),
            vib_crest=round(v_crest, 2),
        )

    def process_data(
        self,
        currents: List[float],
        temperatures: List[float],
        times: List[float],
        is_realtime: bool = False,
        ambient_temperatures: Optional[List[float]] = None,
        data_source: str = "PHYSICAL",
        llm_mode: str = "Local Priority",
        vibrations: Optional[Dict[str, List[float]]] = None,
    ) -> AnalysisResult:
        """
        Runs the multi-expert intelligence pipeline on provided series data.
        """
        profile = load_profile()
        motor_id = profile.get("motor_id", "SIM_MOTOR_01")
        context = self.get_context(motor_id)

        if not currents or not temperatures or not times:
            return self._handle_invalid_input()

        # 1. Preprocessing
        metrics = self._preprocess_cycle(motor_id, currents, temperatures, times, vibrations)

        # 2. Signal Context & State Tracking
        baseline = signal.get_baseline(context) or {
            "avg_current": 0,
            "avg_temp": 30.0,
            "avg_runtime": 0,
        }
        drifts = signal.compute_drift(context, metrics)
        trend_type = signal.get_trend_type(context, metrics)

        # Update Last State for Persistence
        prev_state = context.last_state
        final_state = signal.get_motor_state(context, currents[-1], times[-1])
        context.last_state = final_state

        # Phase 1.3: Track cycle start for continuous run survival
        if final_state == "RUNNING" and prev_state == "OFF":
            context.cycle_start_ts = time.time()
            logger.info(f"Cycle Start recorded for {motor_id}")

        # 3. Statistical Anomalies
        ml_suspicion = signal.detect_statistical_anomalies(context, currents)

        # Baseline & Anomaly Engines Integration (Phase 13)
        from src.engines import anomaly_engine, baseline_engine

        # Estimate power factor
        rated_i = profile.get("rated_current", 2.2)
        power_factor = 0.85
        if rated_i > 0:
            load_ratio = metrics.avg_current / rated_i
            power_factor = min(0.95, max(0.5, 0.85 * load_ratio))

        current_metrics_dict = {
            "avg_current": metrics.avg_current,
            "std_current": metrics.std_current,
            "power_factor": power_factor,
            "avg_temp": metrics.avg_temp,
        }

        baseline_scores = baseline_engine.calculate_baseline_scores(motor_id, current_metrics_dict)
        anomaly_score, is_iforest_anomaly = anomaly_engine.train_and_score_anomaly(
            motor_id, current_metrics_dict
        )

        # 4. Fingerprinting
        current_features = {
            "startup_ramp": metrics.startup_slope,
            "ripple": metrics.std_current,
            "peak_ratio": metrics.peak_to_mean,
            "thermal_rise": round(metrics.max_temp - temperatures[0], 2) if temperatures else 0,
        }
        fingerprint_drift = logic.calculate_drift(context, current_features)

        # Operating Envelope & Output Initialization (Moved up to prevent UnboundLocalError)
        envelope = self._calculate_operating_envelope(
            profile, metrics.avg_current, metrics.max_temp
        )
        analysis_output = self._initialize_output(final_state, fingerprint_drift, envelope)

        # Populate Phase 13 scores into analysis_output
        analysis_output["drift_score"] = baseline_scores["drift_score"]
        analysis_output["deviation_score"] = baseline_scores["deviation_score"]
        analysis_output["trend_score"] = baseline_scores["trend_score"]
        analysis_output["anomaly_score"] = anomaly_score
        analysis_output["voltage"] = profile.get("v_rated", 415.0)
        analysis_output["power_factor"] = power_factor
        analysis_output["temperature_rise"] = (
            round(metrics.max_temp - temperatures[0], 2) if temperatures else 0.0
        )
        analysis_output["baseline_current"] = baseline_scores["current_mean_baseline"]
        analysis_output["baseline_pf"] = baseline_scores["power_factor_baseline"]
        analysis_output["baseline_temperature"] = baseline_scores["temperature_baseline"]
        analysis_output["review_status"] = "NEW" if is_iforest_anomaly else "ACKNOWLEDGED"

        # 5. Pattern Analysis (Shadow AI - No Alerting)
        pattern_data = pattern.pattern_engine.analyze_cycle(context, metrics, np.array(currents))
        analysis_output["shadow_ai"] = pattern_data

        # TinyML Classifier Integration
        tinyml_result = None
        if vibrations and "raw" in vibrations:
            raw_v = vibrations["raw"]
            if len(raw_v) >= 2048:
                try:
                    from src.engines.tinyml_engine import TinyMLEngine

                    if not hasattr(self, "tinyml_engine"):
                        self.tinyml_engine = TinyMLEngine()
                    pred_class, confidence, probs = self.tinyml_engine.predict(
                        np.array(raw_v[:2048])
                    )
                    tinyml_result = {
                        "class": pred_class,
                        "confidence": confidence,
                        "probabilities": probs,
                    }
                except Exception as e:
                    logger.error(f"TinyML inference failed in orchestrator: {e}", exc_info=True)

        # 6. Expert Agent Ensemble
        agent_data = {
            "currents": currents,
            "temperatures": temperatures,
            "avg_current": metrics.avg_current,
            "max_temp": metrics.max_temp,
            "variation_level": metrics.variation_level,
            "baseline": baseline,
            "drifts": drifts,
            "ambient_temperatures": ambient_temperatures,
            "fingerprint_drift": fingerprint_drift,
            "slope": metrics.startup_slope,
            "vib_rms": metrics.vib_rms,
            "vib_peak": metrics.vib_peak,
            "vib_kurtosis": metrics.vib_kurtosis,
            "vib_crest": metrics.vib_crest,
            "tinyml_result": tinyml_result,
        }
        expert_findings = ensemble.get_diagnostics(agent_data)
        best_finding = ensemble.aggregate_findings(expert_findings)

        # 7. Result Synthesis (Weighted Ensemble)
        raw_event, logic_vote, logic_confidence = logic.detect_fault(
            context, metrics, final_state, baseline, trend_type, slope=metrics.startup_slope
        )

        thermal_vote = any(
            f.get("vote") for f in expert_findings if f["agent"] == "Thermal Stress Expert"
        )
        bearing_vote = any(
            f.get("vote") for f in expert_findings if f["agent"] == "Mechanical Health Expert"
        )

        # Confirmation logic incorporating fuzzy confidence
        total_votes = (
            (1 if logic_vote else 0) + (1 if thermal_vote else 0) + (1 if bearing_vote else 0)
        )
        persistence = logic.update_persistence(context, raw_event, best_finding["severity"])

        is_hard_fault = raw_event in ["DRY_RUN", "HARDWARE_ANOMALY"]
        is_confirmed = (
            (total_votes >= 2)
            or (is_hard_fault and logic_vote)
            or (persistence >= 2 and logic_vote)
        )

        if is_confirmed:
            event_verdict = raw_event if raw_event != "NORMAL" else best_finding["event"]
        else:
            event_verdict = "NORMAL"

        stabilized_event = logic.stabilize_event(context, event_verdict)

        # 3-sigma anomaly elevation
        if is_iforest_anomaly and stabilized_event == "NORMAL":
            stabilized_event = "ANOMALY_ALERT"
            best_finding["event"] = "ANOMALY_ALERT"
            best_finding["severity"] = "MEDIUM"
            best_finding["failure_mode"] = "Isolation Forest Drift"
            analysis_output["summary"] = (
                "Isolation Forest detected out-of-bounds anomaly (drift > 3-sigma)."
            )

        if stabilized_event == "NORMAL":
            best_finding["event"] = "NORMAL"
            best_finding["severity"] = "NONE"
            best_finding["failure_mode"] = "NONE"
        else:
            best_finding["event"] = stabilized_event
            if best_finding["severity"] == "NONE":
                best_finding["severity"] = "LOW"
        risk_data = decision.calculate_aging_risk(
            context, metrics.max_temp, metrics.avg_current, best_finding["event"]
        )
        analysis_output["aging_risk"] = risk_data
        analysis_output["remaining_useful_life"] = decision.estimate_rul(context, risk_data)
        analysis_output["edge_ml_flag"] = ml_suspicion

        # Calculate projected time-to-trip for Feature 2
        t_amb = 25.0
        if ambient_temperatures and len(ambient_temperatures) > 0:
            t_amb = ambient_temperatures[-1]
        elif len(temperatures) > 0:
            t_amb = temperatures[0]
        analysis_output["time_to_trip"] = decision.calculate_time_to_trip(
            metrics.avg_current, metrics.max_temp, t_amb, profile
        )

        if best_finding["event"] != "NORMAL":
            self._process_anomalous_cycle(
                context,
                profile,
                best_finding,
                metrics,
                risk_data,
                current_features,
                expert_findings,
                currents,
                temperatures,
                times,
                data_source,
                llm_mode,
                analysis_output,
                baseline,
                drifts,
                final_state,
                is_realtime,
            )
        else:
            self._process_healthy_cycle(
                context,
                motor_id,
                metrics,
                current_features,
                data_source,
                currents,
                temperatures,
                times,
                analysis_output,
                is_realtime,
            )

        # Phase 1.3: Commit industrial checkpoint at end of analysis
        context.persist_if_dirty()

        return analysis_output

    def get_explanation(self, llm_data, mode: str = "On-Premise") -> str:
        if not llm_data:
            return "No anomalies detected."
        simplified_mode = (
            "On-Premise"
            if mode in ["Local Priority", "Local Only", "On-Premise"]
            else "Cloud Backup"
        )
        explanation = dual_explainer.generate_reasoning(llm_data, mode=simplified_mode)
        if explanation.startswith("ERROR:"):
            from src.engines.fallback_engine import generate_deterministic_fallback

            explanation = generate_deterministic_fallback(llm_data)
        return explanation

    def _calculate_operating_envelope(
        self, profile: Dict[str, Any], avg_current: float, max_temp: float
    ) -> EnvelopeMetrics:
        rated_i = profile.get("rated_current", 2.2)
        max_t_limit = profile.get("max_temp_c", 125.0)
        return {
            "current_pct": round(avg_current / rated_i, 2) if rated_i > 0 else 0,
            "temp_pct": round(max_temp / max_t_limit, 2) if max_t_limit > 0 else 0,
        }

    def _initialize_output(
        self, state: str, fingerprint_drift: float, envelope: EnvelopeMetrics
    ) -> AnalysisResult:
        return {
            "event": "NORMAL",
            "severity": "NONE",
            "confidence": 1.0,
            "failure_mode": "NONE",
            "state": state,
            "duration": "0s",
            "persistence": 0,
            "recommendation": "Continue Monitoring",
            "urgency": "LOW",
            "summary": "System operating normally.",
            "llm_data": None,
            "envelope": envelope,
            "fingerprint_drift": fingerprint_drift,
            "aging_risk": None,
            "remaining_useful_life": None,
            "edge_ml_flag": None,
            "root_cause_suspicions": [],
            "shadow_ai": None,
            "time_to_trip": None,
        }

    def _process_anomalous_cycle(
        self,
        context,
        profile,
        best_finding,
        metrics: CycleMetrics,
        risk_data,
        current_features,
        expert_findings,
        currents,
        temperatures,
        times,
        data_source,
        llm_mode,
        analysis_output,
        baseline,
        drifts,
        final_state,
        is_realtime,
    ):
        duration_min = logic.get_event_duration(context)
        confidence = decision.compute_confidence(
            best_finding["severity"],
            context.fault_count,
            drifts.get("current_drift", 0),
            metrics.variation_level,
        )
        action_data = decision.get_decision(
            context,
            best_finding["event"],
            best_finding["severity"],
            best_finding["failure_mode"],
            confidence,
            drifts.get("trend_type", "STABLE"),
        )
        ranked_hypotheses = decision.get_ranked_hypotheses(
            best_finding["event"],
            drifts.get("current_drift", 0),
            drifts.get("temp_drift", 0),
            metrics.variation_level,
            metrics.startup_slope,
        )
        duration_str = llm_input_builder.format_duration(duration_min)
        llm_data = llm_input_builder.build_llm_input(
            best_finding["event"],
            currents[-1],
            temperatures[-1],
            baseline,
            drifts,
            final_state,
            best_finding["severity"],
            context.fault_count,
            duration_min,
            confidence,
            action_data,
            logic.get_previous_summary(context),
            best_finding["failure_mode"],
            metrics.variation_level,
            [h[0] for h in ranked_hypotheses],
            schematics=profile.get("schematics"),
            motor_id=context.motor_id,
        )
        llm_data.update(
            {
                "expert_reasoning": best_finding["reasoning"],
                "agent_name": best_finding["agent"],
                "aging_risk_summary": decision.get_risk_summary(risk_data),
                "fingerprint_drift": analysis_output["fingerprint_drift"],
                "ranked_hypotheses": [h[0] for h in ranked_hypotheses],
                "mcp_spectral_analysis": self._run_spectral_analysis(
                    context.motor_id, currents, profile
                ),
            }
        )
        llm_data["remediation_action"] = ensemble.remediation.analyze(
            {"event": best_finding["event"]}
        )["action"]
        self._apply_kb_enrichment(llm_data, context.motor_id, temperatures[-1])
        analysis_output.update(
            {
                "event": best_finding["event"],
                "severity": best_finding["severity"],
                "confidence": confidence,
                "failure_mode": best_finding["failure_mode"],
                "duration": duration_str,
                "persistence": context.fault_count,
                "recommendation": action_data["action"],
                "urgency": action_data["urgency"],
                "summary": action_data["summary"],
                "llm_data": llm_data,
            }
        )
        self._log_to_evidence_store(
            context.motor_id,
            metrics,
            current_features,
            data_source,
            currents,
            temperatures,
            times,
            analysis_output,
            best_finding,
            risk_data,
            llm_data,
            llm_mode,
            expert_findings,
            baseline,
            is_realtime,
        )

    def _run_spectral_analysis(self, motor_id, currents, profile):
        if cache_currents_for_mcsa(motor_id, currents):
            return analyze_spectral(
                currents,
                synchronous_speed=profile.get("synchronous_speed_rpm", 1500),
                rated_current=profile.get("rated_current_amps", 1.5),
            )
        return {"status": "ERROR", "reason": "Current caching failed"}

    def _apply_kb_enrichment(self, llm_data, motor_id, current_temp):
        specs = get_motor_specs(motor_id)
        if specs:
            llm_data["motor_specs"] = specs
            limit = specs.get("max_temp_c")
            if limit is not None:
                if current_temp > (limit * 0.8):
                    llm_data["expert_reasoning"] += (
                        f" | NOTE: Temperature approaching limit ({limit} deg C)."
                    )
        kb_key = EVENT_TO_KNOWLEDGE.get(llm_data["event"], llm_data["event"])
        fault_info = FAULT_KNOWLEDGE.get(kb_key, FAULT_KNOWLEDGE.get("Overload"))
        if fault_info:
            llm_data["base_text"] = (
                f"Diagnosis: {fault_info.get('diagnosis', 'Unknown')}\nCause: {fault_info.get('cause', 'Unknown')}\nAction: {fault_info.get('action', 'Unknown')}"
            )
        else:
            llm_data["base_text"] = "Diagnosis: Unknown\nCause: Unknown\nAction: Check system specs"

    def _log_to_evidence_store(
        self,
        motor_id,
        metrics,
        features,
        source,
        currents,
        temps,
        times,
        output,
        finding,
        risk_data,
        llm_data,
        mode,
        expert_findings,
        baseline,
        is_realtime,
    ):
        if not is_realtime:
            from src.utils.database import db

            try:
                cycle_id = db.log_cycle(
                    motor_id=motor_id,
                    avg_current=metrics.avg_current,
                    max_temp=metrics.max_temp,
                    duration=metrics.runtime_sec,
                    features=features,
                    data_source=source,
                    times=times,
                    currents=currents,
                    temperatures=temps,
                )
                event_id = db.log_event(cycle_id, output)
                diag_id = db.log_diagnostic(
                    event_id,
                    {
                        "baseline": baseline,
                        "thresholds": {},
                        "reasoning": finding["reasoning"],
                        "llm_explanation": None,
                        "recommendation": output["recommendation"],
                        "urgency": output["urgency"],
                        "aging_risk": risk_data.get("stress_factor", 1.0) if risk_data else 1.0,
                        "version": "1.0.0",
                        "llm_data_json": json.dumps(llm_data),
                        "llm_status": "PENDING",
                        "llm_mode": mode,
                    },
                )
                db.log_agent_findings(diag_id, expert_findings)
            except Exception as e:
                logger.error(f"Failed to log anomalous cycle to Evidence Store: {e}")

    def _process_healthy_cycle(
        self,
        context,
        motor_id,
        metrics,
        features,
        source,
        currents,
        temps,
        times,
        analysis_output,
        is_realtime,
    ):
        logic.stabilize_event(context, "NORMAL")
        logic.update_gold_fingerprint(context, features, is_healthy=True)
        if not is_realtime:
            from src.utils.database import db

            try:
                cycle_id = db.log_cycle(
                    motor_id=motor_id,
                    avg_current=metrics.avg_current,
                    max_temp=metrics.max_temp,
                    duration=metrics.runtime_sec,
                    features=features,
                    data_source=source,
                    times=times,
                    currents=currents,
                    temperatures=temps,
                )
                db.log_event(cycle_id, analysis_output)
            except Exception as e:
                logger.error(f"Failed to log healthy cycle to Evidence Store: {e}")

        # Update Shadow AI Baseline (Self-Supervised Learning)
        if "shadow_ai" in analysis_output:
            feats = analysis_output["shadow_ai"].get("features", {})
            if feats:
                pattern.pattern_engine.update_pattern_baseline(
                    context, feats["entropy"], feats["peak_stability"]
                )

    def _handle_invalid_input(self) -> AnalysisResult:
        return {
            "event": "INVALID_INPUT",
            "severity": "NONE",
            "confidence": 0.0,
            "failure_mode": "NONE",
            "state": "UNKNOWN",
            "duration": "0s",
            "persistence": 0,
            "recommendation": "Check sensors",
            "urgency": "LOW",
            "summary": "Insufficient data.",
            "llm_data": None,
            "envelope": {"current_pct": 0, "temp_pct": 0},
            "fingerprint_drift": 0.0,
            "aging_risk": None,
            "remaining_useful_life": None,
            "edge_ml_flag": None,
            "root_cause_suspicions": [],
            "shadow_ai": None,
        }
