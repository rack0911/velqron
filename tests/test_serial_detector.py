from unittest.mock import MagicMock, patch

from src.utils.serial_detector import find_esp32_port


def test_find_esp32_port_match_cp210():
    mock_port1 = MagicMock()
    mock_port1.description = "Some unknown device"
    mock_port1.device = "/dev/ttyUSB0"

    mock_port2 = MagicMock()
    mock_port2.description = "CP2102 USB to UART Bridge Controller"
    mock_port2.device = "/dev/ttyUSB1"

    with patch("serial.tools.list_ports.comports", return_value=[mock_port1, mock_port2]):
        assert find_esp32_port() == "/dev/ttyUSB1"


def test_find_esp32_port_match_usb():
    mock_port1 = MagicMock()
    mock_port1.description = "USB Serial Device"
    mock_port1.device = "COM3"

    with patch("serial.tools.list_ports.comports", return_value=[mock_port1]):
        assert find_esp32_port() == "COM3"


def test_find_esp32_port_no_match():
    mock_port1 = MagicMock()
    mock_port1.description = "Generic Bluetooth Adapter"
    mock_port1.device = "/dev/ttyS0"

    with patch("serial.tools.list_ports.comports", return_value=[mock_port1]):
        assert find_esp32_port() is None


def test_find_esp32_port_no_ports():
    with patch("serial.tools.list_ports.comports", return_value=[]):
        assert find_esp32_port() is None
