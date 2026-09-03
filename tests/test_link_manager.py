from src.utils.link_manager import LinkManager


def test_parse_binary_packet_success():
    lm = LinkManager(port=None)
    # Construct a valid hex string
    # Bytes: 01 02 03 04 05 06 07
    # Checksum: 01^02^03^04^05^06^07 = 00
    # Bytes in hex: "0102030405060700"

    # Calculate checksum dynamically just to be safe
    data = bytes.fromhex("01020304050607")
    chk = 0
    for b in data:
        chk ^= b
    full_hex = "01020304050607" + f"{chk:02x}"

    res = lm._parse_binary_packet(full_hex)
    assert res["data_source"] == "PHYSICAL"
    # current = ((0x01 << 8) | 0x02) / 100.0 = 258 / 100.0 = 2.58
    assert res["current"] == 2.58
    # temp = ((0x03 << 8) | 0x04) / 10.0 = 772 / 10.0 = 77.2
    assert res["temperature"] == 77.2
    assert res["health"] == 0x05
    assert res["crest_factor"] == 0x06 / 10.0
    # flags = 0x07 (binary: 00000111), so bit 7 and 6 are 0
    assert res["is_tripped"] is False
    assert res["is_overloaded"] is False


def test_parse_binary_packet_wrong_length():
    lm = LinkManager(port=None)
    lm.is_simulated = True  # to return simulated tick

    # Length != 8
    res = lm._parse_binary_packet("010203")  # 3 bytes
    assert res["data_source"] == "SIMULATED"


def test_parse_binary_packet_checksum_mismatch():
    lm = LinkManager(port=None)
    lm.is_simulated = True  # to return simulated tick

    # Valid length (8 bytes) but wrong checksum
    res = lm._parse_binary_packet("01020304050607FF")
    assert res["data_source"] == "SIMULATED"


def test_parse_binary_packet_invalid_hex():
    lm = LinkManager(port=None)
    lm.is_simulated = True  # to return simulated tick

    # Pass non-hex characters which triggers ValueError in bytes.fromhex
    # This hits the 'except Exception as e:' block.
    res = lm._parse_binary_packet("INVALID_HEX_STRING_NOT_HEX")
    assert res["data_source"] == "SIMULATED"
