import json
import logging
import os
from typing import Any, Dict, List, Optional

from src.core.config import CONFIG

logger = logging.getLogger(__name__)


class MotorContext:
    """
    Encapsulates all state (in-memory and persistent) for a single motor.
    Provides industrial-grade continuity across reboots.
    """

    def __init__(self, motor_id: str):
        self.motor_id = motor_id

        # 1. CORE MEMORY (Mandatory Persistence)
        self.active_event: Optional[str] = None
        self.fault_count: int = 0
        self.first_seen_ts: Optional[float] = None
        self.cycle_start_ts: Optional[float] = None

        # 2. SMOOTHING & TRENDS (Reconstructible from history)
        self.event_history: List[str] = []
        self.severity_history: List[str] = []
        self.trend_buffer: List[float] = []

        # 3. TRANSIENT STATE (In-memory only)
        self.state_buffer: List[float] = []
        self.last_state: str = "OFF"
        self.persistence_data: Optional[Dict[str, Any]] = (
            None  # Deprecated: unified into Core Memory
        )
        self.fingerprint_cache: Optional[Dict[str, Any]] = None
        self.pattern_baseline: Dict[str, float] = {}  # Shadow AI Pattern Baseline

        # Persistence Metadata
        self._last_saved_state: str = ""
        self.data_dir = os.path.join(CONFIG.DATA_DIR, "motors", motor_id)
        os.makedirs(self.data_dir, exist_ok=True)

    def load_persistent_state(self):
        """Hydrates context from industrial checkpoint and history reconstruction."""
        from src.utils.database import db

        # 1. Load the core checkpoint
        state = db.get_system_state(self.motor_id)
        if state and state.get("v") == 1:
            self.active_event = state.get("eid")
            self.fault_count = state.get("cnt", 0)
            self.first_seen_ts = state.get("fts")
            self.cycle_start_ts = state.get("cts")
            self.pattern_baseline = state.get("pbl", {})
            self._last_saved_state = json.dumps(state)
            logger.info(f"Context restored for {self.motor_id} (Fault Count: {self.fault_count})")

        # 2. Reconstruct smoothing/trends
        self.reconstruct_from_history()

    def reconstruct_from_history(self):
        """Rebuilds transient buffers from the Evidence Store."""
        from src.utils.database import db

        self.event_history = db.get_last_event_types(self.motor_id, limit=3)
        self.trend_buffer = db.get_last_current_averages(self.motor_id, limit=5)
        logger.debug(
            f"History reconstructed for {self.motor_id} ({len(self.event_history)} events)"
        )

    def persist_if_dirty(self):
        """Atomic write to SQLite only if state has changed since last save."""
        current_state = {
            "v": 1,
            "eid": self.active_event,
            "cnt": self.fault_count,
            "fts": self.first_seen_ts,
            "cts": self.cycle_start_ts,
            "pbl": self.pattern_baseline,
        }

        state_str = json.dumps(current_state)
        if state_str != self._last_saved_state:
            from src.utils.database import db

            if db.save_system_state(self.motor_id, state_str):
                self._last_saved_state = state_str
                logger.debug(f"State checkpoint saved for {self.motor_id}")

    def record_event(self, event: str):
        """Track last 3 events for anti-flip and smoothing."""
        self.event_history.append(event)
        if len(self.event_history) > 3:
            self.event_history = self.event_history[-3:]

    def reset_state(self):
        """Resets all state for this motor (Manual Reset)."""
        self.active_event = None
        self.fault_count = 0
        self.first_seen_ts = None
        self.cycle_start_ts = None
        self.event_history = []
        self.severity_history = []
        self.state_buffer = []
        self.last_state = "OFF"
        self.trend_buffer = []
        self.persistence_data = None
        self.fingerprint_cache = None
        self._last_saved_state = ""

        from src.utils.database import db

        db.save_system_state(self.motor_id, json.dumps({}))

    def __repr__(self):
        return f"<MotorContext motor_id={self.motor_id} state={self.last_state}>"
