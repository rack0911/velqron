import hashlib
import hmac
import logging
import time
from typing import Any, Dict, Optional

import serial

from src.utils.serial_detector import ConnectionState, TelemetryReader

logger = logging.getLogger(__name__)


class LinkManager(TelemetryReader):
    """
    Unified Industrial Link Manager.
    Sole owner of Serial I/O and Watchdog State Machine.
    Integrates TelemetryReader's 10s simulation fallback.
    """

    SHARED_SECRET = b"VELQRON_INDUSTRIAL_2026"

    def __init__(self, port: Optional[str] = None, baud: int = 115200, timeout: float = 1.0):
        super().__init__(port, baud, timeout)
        self.malformed_packet_count = 0
        self.MALFORMED_THRESHOLD = 5

    def read_tick(self) -> Dict[str, Any]:
        """Reads a single telemetry tick and manages watchdog with 10s fallback."""
        now = time.time()

        # Check watchdog/timeout (> 10 seconds since last valid physical packet)
        if not self.is_simulated and (now - self.last_valid_packet_ts > 10.0):
            logger.warning(
                "No serial telemetry received for over 10 seconds. Falling back to simulator."
            )
            self.is_simulated = True
            self.state = ConnectionState.RECONNECTING

        if self.is_simulated:
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

            # Handle Binary Packet Prefix
            if line.startswith("BIN_PKT:"):
                hex_data = line.split(":")[1]
                return self._parse_binary_packet(hex_data)

            if line.startswith("SYS_MSG:"):
                self.last_valid_packet_ts = time.time()
                return {"type": "SYSTEM_MSG", "message": line, "data_source": "PHYSICAL"}

            if line.startswith("SYN_DATA:"):
                self.last_valid_packet_ts = time.time()
                return {"type": "SYNC_DATA", "message": line, "data_source": "PHYSICAL"}

            parts = line.split(",")
            if len(parts) >= 3:
                self.last_valid_packet_ts = time.time()
                self.malformed_packet_count = 0
                if self.state == ConnectionState.DEGRADED:
                    self.state = ConnectionState.CONNECTED

                tick = {
                    "current": float(parts[0]),
                    "temperature": float(parts[1]),
                    "health": int(parts[2]),
                    "data_source": "PHYSICAL",
                    "timestamp": time.time(),
                }

                # Optional stats (Backwards compatible)
                if len(parts) >= 7:
                    tick["mean_deviation"] = float(parts[4])
                    tick["peak_centered"] = float(parts[5])
                    tick["crest_factor"] = float(parts[6])

                # Vibration stats (New in Tier 2)
                if len(parts) >= 11:
                    tick["vib_rms"] = float(parts[7])
                    tick["vib_peak"] = float(parts[8])
                    tick["vib_kurtosis"] = float(parts[9])
                    tick["vib_crest"] = float(parts[10])

                return tick
            else:
                self._handle_malformed()
                return self._get_simulated_tick() if self.is_simulated else None
        except (serial.SerialException, OSError) as e:
            logger.warning(f"Link error during read: {e}. Switching to simulated fallback.")
            self.is_simulated = True
            self.state = ConnectionState.RECONNECTING

        return self._get_simulated_tick()

    def _handle_malformed(self):
        self.malformed_packet_count += 1
        if self.malformed_packet_count > self.MALFORMED_THRESHOLD:
            self.state = ConnectionState.DEGRADED
        if self.malformed_packet_count > self.MALFORMED_THRESHOLD * 2:
            self.state = ConnectionState.RECONNECTING
            self.is_simulated = True

    def _parse_binary_packet(self, hex_str: str) -> Dict[str, Any]:
        """Parses the dense 8-byte binary schema into a standard tick dict."""
        try:
            data = bytes.fromhex(hex_str)
            if len(data) != 8:
                return self._get_simulated_tick()

            # XOR Checksum Validation
            chk = 0
            for i in range(7):
                chk ^= data[i]
            if chk != data[7]:
                logger.warning("Binary checksum mismatch")
                return self._get_simulated_tick()

            current = ((data[0] << 8) | data[1]) / 100.0
            temp = ((data[2] << 8) | data[3]) / 10.0
            health = data[4]
            crest = data[5] / 10.0
            flags = data[6]

            is_tripped = bool(flags & (1 << 7))
            is_overloaded = bool(flags & (1 << 6))

            self.last_valid_packet_ts = time.time()
            return {
                "current": current,
                "temperature": temp,
                "health": health,
                "crest_factor": crest,
                "is_tripped": is_tripped,
                "is_overloaded": is_overloaded,
                "data_source": "PHYSICAL",
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Binary parse error: {e}")
            return self._get_simulated_tick()

    def _sign_command(self, cmd_type: str, value: Any = None) -> str:
        """Signs a command using HMAC-SHA256 for firmware verification."""
        payload = f"{cmd_type}:{value if value is not None else ''}"
        signature = hmac.new(self.SHARED_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:4]
        return f"{payload}:{signature}"

    def send_command(self, cmd_type: str, value: Any = None) -> bool:
        if self.is_simulated or not self.ser or not self.ser.is_open:
            return False

        if cmd_type in ["B", "C", "S", "U"]:
            payload = self._sign_command(cmd_type, value)
        else:
            payload = f"{cmd_type}{value if value is not None else ''}"

        try:
            self.ser.write(f"{payload}\n".encode("utf-8"))
            self.ser.flush()
            logger.info(f"Sent command: {payload}")
            return True
        except Exception as e:
            logger.error(f"Failed to send command {cmd_type}: {e}")
            return False
