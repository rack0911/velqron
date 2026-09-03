# dsp.py — Synchronous Spectral Analysis (FFT + Hilbert Envelope)
import logging
import os

logger = logging.getLogger(__name__)


def analyze_spectral(currents, synchronous_speed=1500, rated_current=1.5):
    """
    Runs synchronous, in-process spectral analysis using numpy and scipy.
    Performs FFT and Hilbert-envelope analysis to detect sideband frequencies.

    Args:
        currents: List of float current samples (raw stator current waveform).
        synchronous_speed: Motor synchronous speed in RPM (used to infer supply frequency).
        rated_current: Motor rated current in Amps.

    Returns:
        Dict with 'status' and 'spectral_data' keys on success, or 'status' and 'reason' on error.
    """
    if not currents or len(currents) < 64:
        return {
            "status": "ERROR",
            "reason": f"Insufficient data points for spectral analysis (got {len(currents) if currents else 0}).",
        }

    try:
        import numpy as np
        import scipy.signal as signal

        # Convert to numpy array
        data = np.array(currents, dtype=float)
        n_samples = len(data)

        # Assume a sample rate of 1000 Hz or estimate based on typical dataset size & cycle duration
        fs = 1000.0  # Sampling frequency in Hz

        # De-trend / remove DC component
        detrended = data - np.mean(data)

        # 1. FFT
        fft_vals = np.fft.rfft(detrended)
        fft_freqs = np.fft.rfftfreq(n_samples, d=1 / fs)
        fft_amps = np.abs(fft_vals) / n_samples

        # Find peaks in spectrum
        peaks, properties = signal.find_peaks(
            fft_amps,
            prominence=0.01 * (np.max(fft_amps) if len(fft_amps) > 0 else 1.0),
        )
        peak_freqs = fft_freqs[peaks].tolist()
        peak_amps = fft_amps[peaks].tolist()

        # Sort peaks by amplitude descending
        sorted_peak_indices = np.argsort(peak_amps)[::-1]
        top_peaks = [
            {
                "frequency": round(float(peak_freqs[i]), 2),
                "amplitude": round(float(peak_amps[i]), 4),
            }
            for i in sorted_peak_indices[:5]
        ]

        # 2. Envelope analysis (Hilbert transform)
        analytic_signal = signal.hilbert(detrended)
        amplitude_envelope = np.abs(analytic_signal)
        envelope_detrended = amplitude_envelope - np.mean(amplitude_envelope)
        env_fft_vals = np.fft.rfft(envelope_detrended)
        env_fft_amps = np.abs(env_fft_vals) / n_samples

        env_peaks, env_properties = signal.find_peaks(
            env_fft_amps,
            prominence=0.01 * (np.max(env_fft_amps) if len(env_fft_amps) > 0 else 1.0),
        )
        env_peak_freqs = fft_freqs[env_peaks].tolist()
        env_peak_amps = env_fft_amps[env_peaks].tolist()
        sorted_env_indices = np.argsort(env_peak_amps)[::-1]
        top_env_peaks = [
            {
                "frequency": round(float(env_peak_freqs[i]), 2),
                "amplitude": round(float(env_peak_amps[i]), 4),
            }
            for i in sorted_env_indices[:5]
        ]

        # Estimate main supply frequency and slip
        f_s = 50.0 if synchronous_speed in [1500, 3000] else 60.0

        # Calculate Total Harmonic Distortion (THD) approximation
        fundamental_idx = np.argmin(np.abs(fft_freqs - f_s))
        fundamental_amp = (
            fft_amps[fundamental_idx] if fundamental_idx < len(fft_amps) else np.max(fft_amps)
        )
        if fundamental_amp > 0:
            harmonics_sum = np.sum(fft_amps**2) - fundamental_amp**2
            thd = float(np.sqrt(np.abs(harmonics_sum)) / fundamental_amp)
        else:
            thd = 0.0

        # Detect rotor sideband frequencies around supply frequency
        sideband_list = []
        for peak in top_peaks:
            freq = peak["frequency"]
            if 5.0 < abs(freq - f_s) < 20.0:
                sideband_list.append(peak)

        result = {
            "status": "SUCCESS",
            "spectral_data": {
                "peak_frequencies": top_peaks,
                "envelope_peaks": top_env_peaks,
                "sidebands": sideband_list,
                "thd": round(thd, 4),
                "supply_frequency": f_s,
            },
        }
        logger.info("Spectral signature analysis completed successfully.")
        return result
    except Exception as e:
        logger.error(f"Spectral analysis failure: {e}", exc_info=True)
        return {
            "status": "ERROR",
            "reason": f"Spectral analysis exception: {e}",
        }


def cache_currents_for_mcsa(motor_id, currents):
    """
    Persists raw stator currents to ~/.mcsa_data/{motor_id}_current.csv for
    auditing and offline signal inspection.
    """
    try:
        data_dir = os.path.expanduser("~/.mcsa_data")
        os.makedirs(data_dir, exist_ok=True)
        csv_path = os.path.join(data_dir, f"{motor_id}_current.csv")

        with open(csv_path, mode="w", encoding="utf-8", newline="") as f:
            f.write("current\n")  # Expected header
            for val in currents:
                f.write(f"{round(val, 4)}\n")
        logger.info(f"Cached {len(currents)} currents to {csv_path} for MCSA integration.")
    except Exception as e:
        logger.warning(f"Failed to cache currents for MCSA integration: {e}")
