# motor_profiles.py

# CORE MOTOR PARAMETERS
BASE_CURRENT = 2.0
BASE_TEMP_START = 30.0

PROFILES = {
    "NORMAL_OPERATION": {
        "current": {"base": BASE_CURRENT, "noise": 0.05, "pattern": "stable"},
        "temperature": {"start": BASE_TEMP_START, "rise_per_min": 0.8, "plateau": 42.0},
        "expected_detection": "NORMAL",
    },
    "STABLE_OVERLOAD": {
        "current": {
            "base": BASE_CURRENT,
            "increase_percent": 0.20,  # Represents the 15-25% range
            "noise": 0.05,
            "pattern": "stable_high",
        },
        "temperature": {"start": BASE_TEMP_START, "rise_per_min": 1.2, "plateau": 50.0},
        "expected_detection": "STABLE_OVERLOAD",
    },
    "DEGRADING_OVERLOAD": {
        "current": {
            "base": BASE_CURRENT,
            "progressive_increase": 0.08,  # Increased rate (+8% per cycle) for clearer detection
            "noise": 0.05,
        },
        "temperature": {
            "start": BASE_TEMP_START,
            "rise_per_min_base": 1.0,
            "rise_increase_per_cycle": 0.2,  # Increasing rise per cycle
            "plateau_base": 45.0,
            "plateau_increase_per_cycle": 2.0,  # Increasing plateau per cycle
        },
        "expected_detection": "DEGRADING_OVERLOAD",
    },
    "DRY_RUN": {
        "current": {
            "drop_percent": -0.40,  # -40% mid-range
            "unstable": True,
            "noise": 0.10,
        },
        "temperature": {
            "start": BASE_TEMP_START,
            "slow_rise": True,
            "rise_per_min": 0.3,
            "plateau": 35.0,
        },
        "expected_detection": "DRY_RUN",
    },
    "UNSTABLE_LOAD": {
        "current": {
            "base": BASE_CURRENT,
            "fluctuation": 0.20,  # +/- 20%
            "random_spikes": True,
            "noise": 0.05,
        },
        "temperature": {
            "start": BASE_TEMP_START,
            "irregular_rise": True,
            "rise_per_min": 0.9,
            "plateau": 47.0,
        },
        "expected_detection": "UNSTABLE_LOAD",
    },
    "SENSOR_DISCONNECT": {
        "current": {"base": 0.0, "noise": 0.01, "pattern": "flat"},
        "temperature": {
            "start": 25.0,  # Ambient
            "rise_per_min": 0.0,
            "plateau": 25.0,
        },
        "expected_detection": "NORMAL",  # Should not trigger fault
    },
    "SIGNAL_CLIPPING": {
        "current": {
            "base": 30.0,  # Saturated
            "noise": 0.1,
            "pattern": "stable_high",
        },
        "temperature": {"start": BASE_TEMP_START, "rise_per_min": 2.0, "plateau": 60.0},
        "expected_detection": "STABLE_OVERLOAD",  # Saturated is treated as overload
    },
    "COMPOUND_FAULT": {
        "current": {
            "base": BASE_CURRENT,
            "increase_percent": 0.35,  # Severe Overload
            "fluctuation": 0.25,  # High Instability
            "random_spikes": True,
            "noise": 0.08,
        },
        "temperature": {
            "start": BASE_TEMP_START,
            "rise_per_min": 2.5,  # Rapid Heating
            "plateau": 75.0,
        },
        "expected_detection": "STABLE_OVERLOAD",  # Overload should take priority
    },
}
