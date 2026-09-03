# Changelog

All notable changes to the Velqron motor-ai project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-05-19

### Added
- **Core Intelligence Pipeline**
  - Cycle-based analysis engine (`EngineOrchestrator`) coordinating 10 specialized engines.
  - Auto-learning baseline using dual-window EMA (Exponential Moving Average) smoothing.
  - Fault detection for 5 core types: Stable Overload, Degrading Overload, Dry Run, Unstable Load, Long-term Degradation.
  - Anti-flip stability buffer to prevent impossible fault transitions.
  - Persistence tracking to filter out false alarms on first-cycle anomalies.
  - Fingerprint Engine for cycle signature extraction and drift calculation.
  - Aging Risk Engine based on Arrhenius thermal degradation models.
  - Bayesian Hypothesis Engine for probabilistic root-cause ranking.
- **Expert Agent Ensemble**
  - `BearingExpert`: RMS ripple analysis for mechanical friction.
  - `ThermalExpert`: Physics-based Lumped Parameter Thermal Network (LPTN) modeling.
  - `InsulationExpert`: Dielectric stress and leakage tracking.
  - `OperatorChecklistAgent`: Manual operator shift inspection checklist (shaft wobble, bearing grinding, oil leaks).
  - `RemediationAgent`: Autonomous self-healing advice.
- **Reasoning & RAG**
  - Local Ollama and NVIDIA NIM cloud LLM integration (`dual_explainer.py`).
  - Industrial RAG system for nameplate specs and engineering facts grounding.
  - `MCPSpectralClient` for in-process DSP (FFT/envelope) via the Model Context Protocol.
- **Hardware & Firmware**
  - ESP32 C++ firmware (`motor_ai.ino`) with high-fidelity signal chain (10Hz reporting, 1kHz burst sampling).
  - Real-time RMS current & temperature capture with auto-zeroing bias.
  - Hardware-in-the-loop (HIL) fault injection capabilities.
- **Persistence Layer**
  - SQLite Evidence Store (`velqron.db`) for rigorous audit trails of cycles, events, and diagnostics.
  - Raw high-frequency waveform storage (compressed `.csv.gz`) with 30-day rolling purge policy.
- **Dashboard & Tooling**
  - Streamlit dashboard with Expert Console, live charts, and Commissioning Wizard.
  - Maintenance Lifecycle workflows (fault resolution, baseline reset).
  - Robustness audit script and accuracy scorecard generation.
  - GitHub Actions CI pipeline for automated testing and linting.

### Changed
- Refactored `analyzer.py` to route logic through a centralized `EngineOrchestrator`.
- Migrated naive single-prompt LLM scripts to structured context injection (`llm_input_builder.py`) and sanitization.

### Removed
- Legacy files: `explainer.py`, `llm_explainer.py`, and `motor_simulator.py` (replaced by new modular structure).
