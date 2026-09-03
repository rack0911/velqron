import os
import sqlite3

from src.core.config import CONFIG
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DatabaseConnection:
    """Handles the raw SQLite connection context manager, schemas, and migrations."""

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(CONFIG.DATA_DIR, "velqron.db")
        self.db_path = db_path
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
        except sqlite3.Error:
            pass
        return conn

    def _init_db(self):
        """Initialize the SQLite database with the schemas and compatibility structures."""
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            with self._connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA busy_timeout=30000;")
                cursor = conn.cursor()

                # Table 1: Machine Registry (Nameplate Context)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS machine_registry (
                        motor_id TEXT PRIMARY KEY,
                        asset_name TEXT NOT NULL,
                        location TEXT,
                        rated_voltage REAL,
                        rated_current REAL,
                        rated_power_kw REAL,
                        rated_speed_rpm REAL,
                        insulation_class TEXT,
                        service_factor REAL,
                        installation_date TEXT
                    );
                """)

                # Table 2: Telemetry & Cycle metrics (Fault Dataset)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS fault_dataset (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        motor_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        operating_mode TEXT NOT NULL,
                        voltage REAL,
                        current REAL,
                        power_factor REAL,
                        temperature_rise REAL,
                        baseline_current REAL,
                        baseline_pf REAL,
                        baseline_temperature REAL,
                        drift_score REAL,
                        deviation_score REAL,
                        trend_score REAL,
                        anomaly_score REAL,
                        rule_flags TEXT,
                        rule_confidence REAL,
                        review_status TEXT DEFAULT 'NEW',
                        severity TEXT,
                        duration_sec INTEGER,
                        aging_risk TEXT,
                        data_source TEXT DEFAULT 'PHYSICAL',
                        llm_explanation TEXT,
                        llm_status TEXT DEFAULT 'PENDING',
                        llm_mode TEXT,
                        llm_data_json TEXT,
                        FOREIGN KEY(motor_id) REFERENCES machine_registry(motor_id)
                    );
                """)

                # Table 3: Ground Truth Feedback (Engineer Feedback)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS engineer_feedback (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        motor_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        rule_diagnosis TEXT,
                        actual_root_cause TEXT,
                        is_correct INTEGER,
                        notes TEXT,
                        FOREIGN KEY(motor_id) REFERENCES machine_registry(motor_id)
                    );
                """)

                # Table 4: Maintenance Action & Outcomes
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS maintenance_action (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        motor_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        action_taken TEXT,
                        downtime_minutes INTEGER,
                        resolved INTEGER,
                        FOREIGN KEY(motor_id) REFERENCES machine_registry(motor_id)
                    );
                """)

                # Compatibility Tables
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS calibration (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        motor_id TEXT,
                        zero_offset REAL,
                        noise_floor REAL,
                        rated_current REAL,
                        service_factor REAL,
                        certificate_path TEXT
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS operator_inspections (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        motor_id TEXT,
                        shaft_wobble INTEGER,
                        bearing_grinding INTEGER,
                        stator_clogged INTEGER,
                        oil_leak INTEGER,
                        operator_name TEXT,
                        notes TEXT
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS system_state (
                        motor_id TEXT PRIMARY KEY,
                        state_json TEXT NOT NULL,
                        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS commissioning_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        motor_id TEXT,
                        rated_current REAL,
                        max_temp_c REAL,
                        symmetry_ratio REAL,
                        zero_offset REAL,
                        noise_floor REAL,
                        commissioned_by TEXT,
                        notes TEXT
                    )
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS live_status (
                        motor_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        current REAL NOT NULL,
                        temperature REAL NOT NULL,
                        operating_mode TEXT NOT NULL,
                        voltage REAL,
                        power_factor REAL,
                        drift_score REAL,
                        deviation_score REAL,
                        trend_score REAL,
                        anomaly_score REAL,
                        rule_flags TEXT,
                        rule_confidence REAL,
                        severity TEXT,
                        urgency TEXT,
                        explanation TEXT,
                        recommendation TEXT,
                        data_source TEXT,
                        time_to_trip REAL
                    );
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS audit_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        operator TEXT DEFAULT 'System',
                        action TEXT NOT NULL,
                        details TEXT
                    );
                """)

                # Database migration checks
                try:
                    cursor.execute("ALTER TABLE live_status ADD COLUMN time_to_trip REAL;")
                except sqlite3.OperationalError:
                    pass

                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_fault_dataset_motor_ts ON fault_dataset(motor_id, timestamp);"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_maintenance_action_motor_ts ON maintenance_action(motor_id, timestamp);"
                )

                conn.commit()

            self._seed_default_profile()

        except sqlite3.Error as e:
            logger.critical(f"Database initialization failed: {e}")
            raise

    def _seed_default_profile(self):
        try:
            from src.core.profile_manager import load_profile

            profile = load_profile()
            motor_id = profile.get("motor_id", "SIM_MOTOR_01")
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1 FROM machine_registry WHERE motor_id = ?", (motor_id,))
                if not cursor.fetchone():
                    cursor.execute(
                        """
                        INSERT INTO machine_registry (
                            motor_id, asset_name, location, rated_voltage, rated_current,
                            rated_power_kw, rated_speed_rpm, insulation_class, service_factor, installation_date
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            motor_id,
                            profile.get("motor_name", "Primary Pump A"),
                            profile.get("location", "Central Utility Room"),
                            profile.get("v_rated", 415.0),
                            profile.get("rated_current", 2.2),
                            0.75,
                            profile.get("rpm", 1440.0),
                            profile.get("insulation_class", "F"),
                            profile.get("service_factor", 1.15),
                            profile.get("install_date", "2026-04-13"),
                        ),
                    )
                    conn.commit()
        except Exception as e:
            logger.warning(f"Failed to seed machine_registry with default profile: {e}")
