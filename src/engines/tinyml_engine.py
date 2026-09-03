import json
import os
from typing import Dict, Optional, Tuple

import numpy as np
from scipy import stats as sp_stats

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Try to import onnxruntime for TinyML inference
try:
    import onnxruntime as ort

    HAS_ONNXRUNTIME = True
except ImportError:
    ort = None
    HAS_ONNXRUNTIME = False
    logger.warning("onnxruntime is not installed. TinyML inference will run in fallback mock mode.")


class TinyMLEngine:
    """
    TinyML Inference Engine for Velqron.
    Loads exported ONNX model and edge_config.json, extracts features from
    vibration signals, normalizes them, and performs fault classification.
    """

    def __init__(self, model_path: Optional[str] = None, config_path: Optional[str] = None):
        from src.core.config import CONFIG

        # Default paths if not specified
        self.model_path = model_path or os.path.join(
            CONFIG.DATA_DIR, "models", "velqron_fault_classifier.onnx"
        )
        self.config_path = config_path or os.path.join(
            CONFIG.DATA_DIR, "models", "edge_config.json"
        )

        self.session = None
        self.config = {}
        self.scaler_mean = None
        self.scaler_std = None
        self.class_labels = ["NORMAL", "INNER_RACE", "BALL_FAULT", "OUTER_RACE"]
        self.sampling_rate = 12000
        self.window_size = 2048
        self.is_loaded = False

        self.load_model()

    def load_model(self) -> bool:
        """Loads ONNX model session and scaler configurations."""
        if not HAS_ONNXRUNTIME:
            logger.warning("Cannot load ONNX model: onnxruntime not installed.")
            return False

        if not os.path.exists(self.model_path) or not os.path.exists(self.config_path):
            logger.info(
                f"TinyML model or config files not found at {self.model_path}. Running in standby."
            )
            return False

        try:
            # Load Configuration
            with open(self.config_path, "r") as f:
                self.config = json.load(f)

            self.class_labels = self.config.get("class_labels", self.class_labels)
            self.sampling_rate = self.config.get("sampling_rate", self.sampling_rate)
            self.window_size = self.config.get("window_size", self.window_size)

            # Load Scaler
            scaler_info = self.config.get("scaler", {})
            self.scaler_mean = np.array(scaler_info.get("mean", []))
            self.scaler_std = np.array(scaler_info.get("std", []))

            # Load ONNX Session
            self.session = ort.InferenceSession(self.model_path)
            self.is_loaded = True
            logger.info(f"TinyML Engine successfully loaded model '{self.model_path}'")
            return True

        except Exception as e:
            logger.error(f"Failed to load TinyML model/config: {e}", exc_info=True)
            self.is_loaded = False
            return False

    def extract_features(self, window: np.ndarray) -> np.ndarray:
        """
        Extract 16 physics-based features from a single vibration window.
        Must match the training feature extraction exactly.
        """
        abs_window = np.abs(window)
        mean_abs = np.mean(abs_window)

        rms = np.sqrt(np.mean(window**2))
        peak = np.max(abs_window)
        peak_to_peak = np.max(window) - np.min(window)

        # Protect against division by zero
        crest_factor = peak / rms if rms > 1e-10 else 0.0
        shape_factor = rms / mean_abs if mean_abs > 1e-10 else 0.0
        impulse_factor = peak / mean_abs if mean_abs > 1e-10 else 0.0

        kurtosis = sp_stats.kurtosis(window)
        skewness = sp_stats.skew(window)
        std_dev = np.std(window)

        sqrt_mean = np.mean(np.sqrt(abs_window))
        clearance = peak / (sqrt_mean**2) if sqrt_mean > 1e-10 else 0.0

        # Frequency-domain features
        fft_vals = np.abs(np.fft.rfft(window))
        fft_freqs = np.fft.rfftfreq(len(window), d=1.0 / self.sampling_rate)

        # Spectral centroid (weighted average frequency)
        total_energy = np.sum(fft_vals)
        freq_center = np.sum(fft_freqs * fft_vals) / total_energy if total_energy > 0 else 0.0

        # Spectral spread (RMS bandwidth)
        freq_rms = (
            np.sqrt(np.sum(((fft_freqs - freq_center) ** 2) * fft_vals) / total_energy)
            if total_energy > 0
            else 0.0
        )

        # Top 4 FFT peak magnitudes (sorted descending)
        top_4_indices = np.argsort(fft_vals)[-4:][::-1]
        top_fft = fft_vals[top_4_indices]

        return np.array(
            [
                rms,
                peak,
                peak_to_peak,
                crest_factor,
                shape_factor,
                impulse_factor,
                kurtosis,
                skewness,
                std_dev,
                clearance,
                freq_center,
                freq_rms,
                top_fft[0],
                top_fft[1],
                top_fft[2],
                top_fft[3],
            ]
        )

    def predict(self, vibration_window: np.ndarray) -> Tuple[str, float, Dict[str, float]]:
        """
        Predicts motor health from a raw vibration window.
        Returns:
            predicted_class: str (e.g., 'NORMAL', 'INNER_RACE')
            confidence: float (0.0 to 1.0)
            class_probabilities: dict mapping class label -> probability
        """
        # If engine not loaded or onnxruntime not available, fallback to mock/safe response
        if not self.is_loaded or self.session is None:
            # Log warning occasionally or when first attempting inference
            return (
                "NORMAL",
                1.0,
                {label: (1.0 if label == "NORMAL" else 0.0) for label in self.class_labels},
            )

        try:
            # 1. Feature Extraction
            features = self.extract_features(vibration_window)

            # 2. Scaling (Zero mean, Unit variance)
            if self.scaler_mean is not None and self.scaler_std is not None:
                scaled_features = (features - self.scaler_mean) / self.scaler_std
            else:
                scaled_features = features

            # Reshape for ONNX input (batch size 1, num_features)
            input_data = np.expand_dims(scaled_features, axis=0).astype(np.float32)

            # 3. ONNX Session Run
            # Get input/output names
            input_name = self.session.get_inputs()[0].name

            # Run session
            outputs = self.session.run(None, {input_name: input_data})

            # Handle classification predictions:
            # sklearn wrapper models exported to ONNX output [label, probabilities]
            # label shape: [batch], probabilities shape: [batch] of dicts or array
            pred_label_idx = int(outputs[0][0])

            # Map index to label
            pred_class = self.class_labels[pred_label_idx]

            probabilities = {}
            confidence = 1.0

            if len(outputs) > 1:
                # Typically, outputs[1] is a list of dictionaries with prob/score mappings
                prob_out = outputs[1]
                if (
                    isinstance(prob_out, list)
                    and len(prob_out) > 0
                    and isinstance(prob_out[0], dict)
                ):
                    # Mapping may have integer or string keys
                    prob_dict = prob_out[0]
                    for key, val in prob_dict.items():
                        # Map back to string label
                        label_name = self.class_labels[key] if isinstance(key, int) else key
                        probabilities[label_name] = float(val)
                    confidence = probabilities.get(pred_class, 1.0)
                elif isinstance(prob_out, np.ndarray):
                    # Array of probabilities
                    probs = prob_out[0]
                    for idx, val in enumerate(probs):
                        probabilities[self.class_labels[idx]] = float(val)
                    confidence = float(probs[pred_label_idx])

            if not probabilities:
                probabilities = {
                    label: (1.0 if label == pred_class else 0.0) for label in self.class_labels
                }

            return pred_class, confidence, probabilities

        except Exception as e:
            logger.error(f"Error during TinyML inference: {e}", exc_info=True)
            return (
                "NORMAL",
                1.0,
                {label: (1.0 if label == "NORMAL" else 0.0) for label in self.class_labels},
            )
