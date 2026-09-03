import time
from typing import Any, Dict, Tuple

import numpy as np
from sklearn.ensemble import IsolationForest

from src.utils.database import db
from src.utils.logger import get_logger

logger = get_logger(__name__)


def train_and_score_anomaly(motor_id: str, current_metrics: Dict[str, Any]) -> Tuple[float, bool]:
    """
    Loads historical healthy cycles, fits IsolationForest, and returns (anomaly_score, is_3_sigma_anomaly).
    """
    history = db.load_recent_cycles(motor_id)

    # 7 to 14 days time window filter
    cutoff_time = time.time() - (14 * 24 * 3600)
    recent_history = []
    for h in history:
        ts_str = h.get("timestamp")
        try:
            if isinstance(ts_str, (float, int)):
                ts = float(ts_str)
            else:
                ts = time.mktime(time.strptime(ts_str.split(".")[0], "%Y-%m-%d %H:%M:%S"))
            if ts >= cutoff_time:
                recent_history.append(h)
        except Exception:
            recent_history.append(h)

    # Use all history if recent history is too thin
    if len(recent_history) < 5:
        recent_history = history

    # Extract healthy features for training
    X = []
    for h in recent_history:
        # Only use healthy/unflagged cycles
        is_healthy = h.get("event") in [None, "NORMAL"]
        if is_healthy:
            curr = h.get("current") or h.get("avg_current") or 0.0
            std_curr = h.get("current_std") or h.get("steady_ripple") or 0.05
            pf = h.get("power_factor") or 0.85
            temp = h.get("temperature_rise") or h.get("max_temp") or h.get("avg_temp") or 30.0
            X.append([curr, std_curr, pf, temp])

    curr_i = current_metrics.get("avg_current", 0.0)
    curr_std = current_metrics.get("std_current", 0.0)
    curr_pf = current_metrics.get("power_factor", 0.85)
    curr_t = current_metrics.get("avg_temp", 30.0)
    current_x = [curr_i, curr_std, curr_pf, curr_t]

    if len(X) < 5:
        # Not enough samples to fit Isolation Forest yet, return nominal
        return 0.0, False

    try:
        X_train_arr = np.array(X)
        clf = IsolationForest(contamination=0.05, random_state=42)
        clf.fit(X_train_arr)

        # Decision function returns higher value for more normal samples, negative for anomaly.
        # We invert it: higher is more abnormal.
        score = float(-clf.decision_function([current_x])[0])

        # 3-sigma out-of-bounds check relative to healthy baseline score distribution
        train_scores = -clf.decision_function(X_train_arr)
        mean_score = np.mean(train_scores)
        std_score = np.std(train_scores)

        # Enforce configurable standard deviation floor to prevent z-score explosions
        from src.core.config import CONFIG

        min_std = 0.02
        if hasattr(CONFIG, "ANOMALY") and hasattr(CONFIG.ANOMALY, "MIN_STD"):
            min_std = CONFIG.ANOMALY.MIN_STD
        else:
            min_std = getattr(CONFIG, "ANOMALY_MIN_STD", 0.02)
        if std_score < min_std:
            std_score = min_std

        is_anomaly = False
        if std_score > 0:
            z_score = (score - mean_score) / std_score
            if z_score > 3.0:
                is_anomaly = True

        return score, is_anomaly
    except Exception as e:
        logger.exception(f"Isolation Forest model training failed: {e}")
        return 0.0, False
