from typing import Any, Dict, List

import numpy as np

from src.utils.database import db


def compute_ema(values: List[float], alpha: float) -> List[float]:
    if not values:
        return []
    ema = [values[0]]
    for val in values[1:]:
        ema.append(alpha * val + (1 - alpha) * ema[-1])
    return ema


def compute_dema(values: List[float], alpha: float) -> float:
    if not values:
        return 0.0
    ema1 = compute_ema(values, alpha)
    ema2 = compute_ema(ema1, alpha)
    return 2 * ema1[-1] - ema2[-1]


def calculate_baseline_scores(motor_id: str, current_metrics: Dict[str, Any]) -> Dict[str, float]:
    """
    Calculates drift_score, deviation_score, and trend_score based on EMA/Dual-EMA.
    """
    # Fetch historical cycles from SQLite
    history = db.load_recent_cycles(motor_id)

    curr_i = current_metrics.get("avg_current", 0.0)
    curr_std = current_metrics.get("std_current", 0.0)
    curr_pf = current_metrics.get("power_factor", 0.85)
    curr_t = current_metrics.get("avg_temp", 30.0)

    if not history:
        return {
            "drift_score": 0.0,
            "deviation_score": 0.0,
            "trend_score": 0.0,
            "current_mean_baseline": curr_i,
            "current_std_baseline": curr_std,
            "power_factor_baseline": curr_pf,
            "temperature_baseline": curr_t,
        }

    def get_history_vals(key, default_val):
        vals = []
        for h in history:
            val = h.get(key)
            if val is None:
                if key == "current":
                    val = h.get("avg_current")
                elif key == "current_std":
                    val = h.get("std_current") or h.get("steady_ripple")
                elif key == "power_factor":
                    val = h.get("power_factor")
                elif key == "temperature_rise":
                    val = h.get("max_temp") or h.get("avg_temp")
            vals.append(float(val) if val is not None else default_val)
        return vals

    currents = get_history_vals("current", 2.2)
    stds = get_history_vals("current_std", 0.05)
    pfs = get_history_vals("power_factor", 0.85)
    temps = get_history_vals("temperature_rise", 30.0)

    currents.append(curr_i)
    stds.append(curr_std)
    pfs.append(curr_pf)
    temps.append(curr_t)

    alpha = 0.05
    dema_i = compute_dema(currents, alpha)
    dema_std = compute_dema(stds, alpha)
    dema_pf = compute_dema(pfs, alpha)
    dema_t = compute_dema(temps, alpha)

    # 1. Drift Score: Absolute difference between running average and long-term average
    mean_i = np.mean(currents[:-1]) if len(currents) > 1 else curr_i
    mean_std = np.mean(stds[:-1]) if len(stds) > 1 else curr_std
    mean_pf = np.mean(pfs[:-1]) if len(pfs) > 1 else curr_pf
    mean_t = np.mean(temps[:-1]) if len(temps) > 1 else curr_t

    drift_i = abs(dema_i - mean_i) / mean_i if mean_i > 0 else 0.0
    drift_std = abs(dema_std - mean_std) / mean_std if mean_std > 0 else 0.0
    drift_pf = abs(dema_pf - mean_pf) / mean_pf if mean_pf > 0 else 0.0
    drift_t = abs(dema_t - mean_t) / mean_t if mean_t > 0 else 0.0

    drift_score = float(np.mean([drift_i, drift_std, drift_pf, drift_t]))

    # 2. Deviation Score: Current value Z-score relative to running window (last 10 cycles)
    window_size = min(10, len(currents))
    win_i = currents[-window_size:]
    win_std = stds[-window_size:]
    win_pf = pfs[-window_size:]
    win_t = temps[-window_size:]

    def z_score(val, window):
        if len(window) < 2:
            return 0.0
        std = np.std(window[:-1])
        if std == 0:
            return abs(val - np.mean(window[:-1])) / 0.01
        return abs(val - np.mean(window[:-1])) / std

    dev_i = z_score(curr_i, win_i)
    dev_std = z_score(curr_std, win_std)
    dev_pf = z_score(curr_pf, win_pf)
    dev_t = z_score(curr_t, win_t)

    deviation_score = float(np.mean([dev_i, dev_std, dev_pf, dev_t]))

    # 3. Trend Score: Linear slope of parameters over recent 5 cycles
    trend_window = min(5, len(currents))

    def get_slope(win):
        if len(win) < 2:
            return 0.0
        x = np.arange(len(win))
        slope, _ = np.polyfit(x, win, 1)
        mean_val = np.mean(win)
        return slope / mean_val if mean_val > 0 else 0.0

    slope_i = get_slope(currents[-trend_window:])
    slope_std = get_slope(stds[-trend_window:])
    slope_pf = get_slope(pfs[-trend_window:])
    slope_t = get_slope(temps[-trend_window:])

    trend_score = float(np.mean([slope_i, slope_std, slope_pf, slope_t]))

    return {
        "drift_score": round(drift_score, 4),
        "deviation_score": round(deviation_score, 4),
        "trend_score": round(trend_score, 4),
        "current_mean_baseline": dema_i,
        "current_std_baseline": dema_std,
        "power_factor_baseline": dema_pf,
        "temperature_baseline": dema_t,
    }
