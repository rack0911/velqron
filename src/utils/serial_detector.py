import time
from typing import Any, Dict, Optional

import serial

from src.utils.logger import get_logger

logger = get_logger(__name__)


class ConnectionState:
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING = "RECONNECTING"
    DEGRADED = "DEGRADED"


def find_esp32_port() -> Optional[str]:
    """Autodetects the serial port for the ESP32."""
    ports = list(serial.tools.list_ports.comports())
    for port in ports:
        if any(sig in port.description for sig in ["CP210", "Silicon Labs", "USB", "ACM"]):
            return port.device
    return None


class TelemetryReader:
    def __init__(self, port: Optional[str] = None, baud: int = 115200, timeout: float = 1.0):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.ser: Optional[serial.Serial] = None

        self.state = ConnectionState.CONNECTING
        self.last_valid_packet_ts = time.time()
        self.last_connection_attempt_ts = 0.0
        self.reconnect_delay = 1.0
        self.malformed_packet_count = 0
        self.is_simulated = False

    def _close_handle(self):
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def connect(self) -> bool:
        """Attempts to establish a clean serial connection with fresh port scan."""
        now = time.time()
        if now - self.last_connection_attempt_ts < self.reconnect_delay:
            return False

        self.last_connection_attempt_ts = now
        self.state = ConnectionState.CONNECTING
        self._close_handle()

        actual_port = self.port or find_esp32_port()
        if not actual_port:
            self.is_simulated = True
            logger.warning("No physical ESP32 device found. Falling back to simulator mode.")
            return False

        try:
            self.ser = serial.Serial(actual_port, self.baud, timeout=self.timeout)
            self.state = ConnectionState.CONNECTED
            self.last_valid_packet_ts = time.time()
            self.is_simulated = False
            logger.info(f"Connected to ESP32 on {actual_port}")
            return True
        except (serial.SerialException, OSError) as e:
            logger.warning(f"Connection failed on {actual_port}: {e}. Falling back to simulator.")
            self.is_simulated = True
            return False

    def read_tick(self) -> Dict[str, Any]:
        """Reads a single telemetry tick, falls back to simulator on errors/timeouts."""
        now = time.time()

        # Check watchdog/timeout (> 10 seconds since last valid physical packet)
        if not self.is_simulated and (now - self.last_valid_packet_ts > 10.0):
            logger.warning(
                "No serial telemetry received for over 10 seconds. Falling back to simulator."
            )
            self.is_simulated = True
            self.state = ConnectionState.RECONNECTING

        if self.is_simulated:
            # Try to reconnect occasionally in the background
            if self.state in [ConnectionState.CONNECTING, ConnectionState.RECONNECTING]:
                self.connect()
            if self.is_simulated:
                return self._get_simulated_tick()

        try:
            if not self.ser or not self.ser.is_open:
                self.connect()
                if self.is_simulated:
                    return self._get_simulated_tick()

            line = self.ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                return self._get_simulated_tick() if self.is_simulated else None

            parts = line.split(",")
            if len(parts) >= 3:
                self.last_valid_packet_ts = time.time()
                self.malformed_packet_count = 0

                tick = {
                    "current": float(parts[0]),
                    "temperature": float(parts[1]),
                    "health": int(parts[2]),
                    "data_source": "PHYSICAL",
                    "timestamp": time.time(),
                }
                return tick
            else:
                self.malformed_packet_count += 1
                if self.malformed_packet_count > 5:
                    logger.warning("Too many malformed packets. Forcing serial reconnect.")
                    self.is_simulated = True
                    self.state = ConnectionState.RECONNECTING
                return self._get_simulated_tick() if self.is_simulated else None
        except (serial.SerialException, OSError) as e:
            logger.warning(f"Serial Exception raised: {e}. Switching to simulated fallback.")
            self.is_simulated = True
            self.state = ConnectionState.RECONNECTING

        return self._get_simulated_tick()

    def _get_simulated_tick(self) -> Dict[str, Any]:
        """Generates simulated telemetry using simulator_engine."""
        import random

        # We can simulate normal operation telemetry
        current = 2.2 + random.uniform(-0.05, 0.05)
        temperature = 35.0 + random.uniform(-0.1, 0.1)
        return {
            "current": current,
            "temperature": temperature,
            "ambient_temp": 25.0,
            "health": 3,
            "data_source": "SIMULATED",
            "timestamp": time.time(),
            "reason": "USB Disconnected (Simulated Fallback)",
        }

    def send_command(self, cmd_type: str, value: Any = None) -> bool:
        if self.is_simulated or not self.ser or not self.ser.is_open:
            return False
        try:
            payload = f"{cmd_type}{value if value is not None else ''}"
            self.ser.write(f"{payload}\n".encode("utf-8"))
            self.ser.flush()
            return True
        except Exception:
            return False

    def close(self):
        self._close_handle()
