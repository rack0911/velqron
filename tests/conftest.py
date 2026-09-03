import os
import shutil
import sys
import tempfile

import pytest

# Add src to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch):
    """Isolates Velqron data files for testing."""
    test_dir = tempfile.mkdtemp()
    data_dir = os.path.join(test_dir, "data")
    os.makedirs(data_dir, exist_ok=True)

    monkeypatch.setenv("VELQRON_DATA_DIR", data_dir)

    # Mock LLM calls to prevent timeouts/errors during tests
    # Removed global mock to allow specific tests to override or test fallback logic.

    # Also need to re-import or update the CONFIG object in src.core.config
    # Since it was already imported, we might need to manually update it
    from src.core.config import CONFIG

    CONFIG.DATA_DIR = data_dir
    from src.utils.database import db

    db.db_path = os.path.join(data_dir, "velqron.db")
    db._init_db()

    yield test_dir

    # Cleanup
    shutil.rmtree(test_dir)


@pytest.fixture
def motor_context():
    from src.core.motor_context import MotorContext

    return MotorContext("TEST_MOTOR")


@pytest.fixture
def mock_baseline():
    return {"avg_current": 2.0, "avg_temp": 35.0, "avg_runtime": 180.0}
