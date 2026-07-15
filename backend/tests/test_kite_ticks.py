import struct
from datetime import datetime, timezone

from app.prices.kite_ticks import decode_ticks, update_cache


def _packet(instrument_token: int, ltp_rupees: float, extra_bytes: int = 0) -> bytes:
    """Build one Kite tick packet: instrument_token(4) + ltp-in-paise(4) +
    optional zero-filled padding (simulating the extra fields a "quote"/"full"
    mode packet carries after the first 8 bytes, which the decoder must
    ignore)."""
    return struct.pack(">Ii", instrument_token, round(ltp_rupees * 100)) + b"\x00" * extra_bytes


def _message(*packets: bytes) -> bytes:
    header = struct.pack(">H", len(packets))
    body = b"".join(struct.pack(">H", len(p)) + p for p in packets)
    return header + body


def test_decode_ticks_single_ltp_packet():
    message = _message(_packet(738561, 2500.50))

    ticks = decode_ticks(message)

    assert ticks == [{"instrument_token": 738561, "ltp": 2500.50}]


def test_decode_ticks_multiple_packets():
    message = _message(_packet(738561, 2500.50), _packet(5633, 150.25))

    ticks = decode_ticks(message)

    assert ticks == [
        {"instrument_token": 738561, "ltp": 2500.50},
        {"instrument_token": 5633, "ltp": 150.25},
    ]


def test_decode_ticks_ignores_bytes_past_the_first_eight_in_a_quote_packet():
    # A 44-byte "quote" mode packet -- decoder must still read only the
    # leading instrument_token+ltp and ignore the other 36 bytes.
    message = _message(_packet(738561, 2500.50, extra_bytes=36))

    ticks = decode_ticks(message)

    assert ticks == [{"instrument_token": 738561, "ltp": 2500.50}]


def test_decode_ticks_returns_empty_list_for_too_short_payload():
    assert decode_ticks(b"") == []
    assert decode_ticks(b"\x00") == []


def test_decode_ticks_stops_gracefully_on_truncated_packet():
    # Claims 1 packet of length 8 but only 4 bytes follow.
    truncated = struct.pack(">H", 1) + struct.pack(">H", 8) + b"\x00\x00\x00\x00"

    assert decode_ticks(truncated) == []


def test_update_cache_stores_ltp_and_timestamp():
    cache: dict[int, dict] = {}
    now = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)

    update_cache(cache, [{"instrument_token": 738561, "ltp": 2500.50}], now)

    assert cache[738561] == {"ltp": 2500.50, "as_of": now}


def test_update_cache_overwrites_prior_value_for_same_token():
    cache = {738561: {"ltp": 2400.0, "as_of": datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc)}}
    now = datetime(2026, 7, 15, 9, 30, tzinfo=timezone.utc)

    update_cache(cache, [{"instrument_token": 738561, "ltp": 2500.50}], now)

    assert cache[738561]["ltp"] == 2500.50
    assert cache[738561]["as_of"] == now
