import json
import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.engines.tinyml_engine import TinyMLEngine


def test_feature_extraction():
    """Verify that feature extraction works and produces 16 features."""
    engine = TinyMLEngine()

    # Generate 2048 samples of a simple sine wave with noise
    t = np.linspace(0, 1.0, 2048)
    signal = np.sin(2 * np.pi * 50 * t) + np.random.normal(0, 0.1, 2048)

    features = engine.extract_features(signal)

    assert isinstance(features, np.ndarray)
    assert features.shape == (16,)
    assert np.all(np.isfinite(features))
    # RMS of sine + noise should be around 0.7
    assert features[0] > 0.0


def test_predict_fallback_when_model_missing():
    """Verify that engine falls back gracefully when model files are missing."""
    # Data directory is isolated tempdir, so models/ does not exist.
    engine = TinyMLEngine()

    assert not engine.is_loaded

    # Run predict on dummy signal
    signal = np.random.normal(0, 0.1, 2048)
    pred_class, confidence, probabilities = engine.predict(signal)

    assert pred_class == "NORMAL"
    assert confidence == 1.0
    assert probabilities["NORMAL"] == 1.0
    assert probabilities["INNER_RACE"] == 0.0


def test_predict_with_mock_onnx():
    """Verify inference pipeline works when model is loaded and mock run is executed."""
    from src.core.config import CONFIG

    # Create mock directories and configuration in the isolated test data dir
    models_dir = os.path.join(CONFIG.DATA_DIR, "models")
    os.makedirs(models_dir, exist_ok=True)

    mock_config = {
        "model_file": "velqron_fault_classifier.onnx",
        "model_type": "Random Forest",
        "accuracy": 0.98,
        "num_features": 16,
        "feature_names": [
            "RMS",
            "Peak",
            "Peak_to_Peak",
            "Crest_Factor",
            "Shape_Factor",
            "Impulse_Factor",
            "Kurtosis",
            "Skewness",
            "Std_Dev",
            "Clearance",
            "Freq_Center",
            "Freq_RMS",
            "FFT_Peak_1",
            "FFT_Peak_2",
            "FFT_Peak_3",
            "FFT_Peak_4",
        ],
        "class_labels": ["NORMAL", "INNER_RACE", "BALL_FAULT", "OUTER_RACE"],
        "sampling_rate": 12000,
        "window_size": 2048,
        "scaler": {"mean": [0.5] * 16, "std": [0.2] * 16},
    }

    config_path = os.path.join(models_dir, "edge_config.json")
    with open(config_path, "w") as f:
        json.dump(mock_config, f)

    model_path = os.path.join(models_dir, "velqron_fault_classifier.onnx")
    # Write a dummy model file so os.path.exists checks pass
    with open(model_path, "w") as f:
        f.write("mock_onnx_bytes")

    # Mock onnxruntime module and InferenceSession
    import sys

    mock_ort = MagicMock()
    mock_session = MagicMock()
    mock_ort.InferenceSession.return_value = mock_session

    # sklearn output format for classifier:
    # Output 0: labels (shape: [batch_size])
    # Output 1: probability dictionary lists: e.g. [{0: 0.1, 1: 0.8, 2: 0.05, 3: 0.05}]
    mock_labels = np.array([1])  # INNER_RACE index
    mock_probs = [{0: 0.1, 1: 0.8, 2: 0.05, 3: 0.05}]

    mock_session.run.return_value = [mock_labels, mock_probs]

    # Mock inputs
    mock_session.get_inputs.return_value = [MagicMock(name="input")]

    with (
        patch.dict(sys.modules, {"onnxruntime": mock_ort}),
        patch("src.engines.tinyml_engine.HAS_ONNXRUNTIME", True),
        patch("src.engines.tinyml_engine.ort", mock_ort),
    ):
        engine = TinyMLEngine(model_path=model_path, config_path=config_path)

        assert engine.is_loaded
        assert engine.scaler_mean is not None
        assert len(engine.scaler_mean) == 16

        # Run prediction
        signal = np.random.normal(0, 0.1, 2048)
        pred_class, confidence, probabilities = engine.predict(signal)

        # Verify predictions map correctly
        assert pred_class == "INNER_RACE"
        assert confidence == 0.8
        assert probabilities["NORMAL"] == 0.1
        assert probabilities["INNER_RACE"] == 0.8
        assert probabilities["BALL_FAULT"] == 0.05
        assert probabilities["OUTER_RACE"] == 0.05

        # Verify session run was called
        mock_session.run.assert_called_once()

        # Check scaling logic: (feature - mean) / std
        # Make sure input data passed to run matches shape (1, 16)
        args, kwargs = mock_session.run.call_args
        inputs = kwargs.get("input_feed") or args[1]
        input_data = inputs[list(inputs.keys())[0]]
        assert input_data.shape == (1, 16)
        assert input_data.dtype == np.float32


def test_real_model_inference_if_present():
    """If the real model files are present in the repo, copy them to isolated config and test actual inference."""
    import shutil

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    real_models_dir = os.path.join(repo_root, "data", "models")
    real_onnx_path = os.path.join(real_models_dir, "velqron_fault_classifier.onnx")
    real_config_path = os.path.join(real_models_dir, "edge_config.json")

    if not (os.path.exists(real_onnx_path) and os.path.exists(real_config_path)):
        pytest.skip("Real model files not found in data/models/")

    from src.core.config import CONFIG

    # Create isolated model dir
    isolated_models_dir = os.path.join(CONFIG.DATA_DIR, "models")
    os.makedirs(isolated_models_dir, exist_ok=True)

    # Copy real files
    shutil.copy(real_onnx_path, os.path.join(isolated_models_dir, "velqron_fault_classifier.onnx"))
    shutil.copy(real_config_path, os.path.join(isolated_models_dir, "edge_config.json"))

    # Now run prediction (try actual onnxruntime, if installed)
    from src.engines.tinyml_engine import HAS_ONNXRUNTIME

    if not HAS_ONNXRUNTIME:
        pytest.skip("onnxruntime is not installed on this system.")

    engine = TinyMLEngine()
    assert engine.is_loaded

    # Test on a dummy signal (normal noise)
    signal = np.random.normal(0, 0.1, 2048)
    pred_class, confidence, probabilities = engine.predict(signal)

    assert pred_class in ["NORMAL", "INNER_RACE", "BALL_FAULT", "OUTER_RACE"]
    assert 0.0 <= confidence <= 1.0
    for label in ["NORMAL", "INNER_RACE", "BALL_FAULT", "OUTER_RACE"]:
        assert label in probabilities
        assert 0.0 <= probabilities[label] <= 1.0
