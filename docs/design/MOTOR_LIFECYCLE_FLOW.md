# Velqron Life-Cycle: From Startup to Shutdown

This document provides a technical flowchart of every event and decision point that occurs in the Velqron system during a single motor operating cycle.

## 1. End-to-End Operation Flow

```mermaid
flowchart TD
    subgraph HW ["HARDWARE LAYER (ESP32 / S3)"]
        S1["Motor Switch ON"] --> S2["Zero-Crossing Sync Sampling"]
        S2 --> S3["Telemetry Packet Emitted<br/>(Fused: Current + Temp + Vib)"]
    end

    subgraph ING ["INGESTION LAYER (reader.py / dashboard.py)"]
        S3 --> L1["LinkManager.read_tick()"]
        L1 --> L1A{"Binary Packet?"}
        L1A -- YES --> L1B["Unpack 8-Byte Schema"]
        L1A -- NO --> L1C["Parse CSV Line"]

        L1B & L1C --> L2{"HMAC Verified?"}
        L2 -- NO --> L3["Discard / Security Log"]
        L2 -- YES --> L4{"Watchdog OK?"}

        L4 -- YES --> L8["Buffer Multi-Modal Tick"]
    end

    subgraph ORC ["ORCHESTRATION LAYER (orchestrator.py)"]
        L8 --> O1["_preprocess_cycle()<br/>(Calculate 40 Stats + Vib Kurtosis)"]
        O1 --> O2["Load MotorContext<br/>(System State Checkpoint)"]

        subgraph CORE ["INTELLIGENCE CORE"]
            O2 --> E1["Fuzzy Logic Controller:<br/>Sigmoid Confidence?"]
            O2 --> E2["Thermal Expert Guardrail:<br/>Physics Residual (ODE)?"]
            O2 --> E3["Bearing Expert Fusion:<br/>Vibration + Drift?"]
            O2 --> E4["Shadow AI Observer:<br/>Pattern Entropy Shift?"]
        end

        E1 & E2 & E3 & E4 --> O4["Weighted Ensemble Synthesis"]
        O4 --> O5{"Confirmed Fault?"}

        O5 -- YES --> O6["Decision Engine:<br/>Calc Aging Risk + Action"]
        O5 -- NO --> O7["Status: NORMAL"]
    end

    subgraph PERS ["PERSISTENCE LAYER (SQLite)"]
        O6 --> P1["Update persistence count"]
        O7 --> P1
        P1 --> P2["persist_if_dirty()<br/>(Save Industrial Checkpoint)"]

        S4["Motor Switch OFF"] --> P3["reader.py detects current < Noise Floor"]
        P3 --> P4["log_cycle()<br/>(Commit full cycle stats to DB)"]
        P4 --> P5["Reset persistence & trends"]
    end

    subgraph UI ["PRESENTATION LAYER (dashboard.py)"]
        O6 --> U1["Render Alert + LLM Explanation"]
        O7 --> U2["Render Green Status"]
        P2 --> U3["Update Trend Charts"]
    end
```

## 2. Key Stage Details

### Stage 1: The "Hardware Integrity Gate"
Before any analysis occurs, the `LinkManager` and `reader.py` verify that the data is trustworthy. If the ESP32 has rebooted or a sensor has failed, the logic engines are immediately bypassed.

### Stage 2: The "Ensemble Verdict"
Instead of relying on a single rule, the system requires a **Voting Majority**.
* **Logic Engine**: Checks hard thresholds.
* **Thermal Expert**: Checks physics (LPTN model).
* **Bearing Expert**: Checks mechanical patterns (Signature drift).
* **Result**: If 2 out of 3 agree, the severity escalates.

### Stage 3: The "Industrial Checkpoint"
On every tick, if the diagnostic state has changed, a minimal JSON blob is saved to the `system_state` table. This ensures that if the power is cut at any point between "Startup" and "Shutdown," the system remembers exactly where it was in the diagnostic process.

### Stage 4: The "Cycle Commit"
Only when the motor current drops below the **Noise Floor (1.5A)** is the entire run considered a "Cycle." At this point, the average current, max temp, and runtime are calculated and written to the `cycles` table for long-term reporting.

---
*Reference: docs/governance/ARCHITECTURE.md*
