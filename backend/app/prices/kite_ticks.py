import struct


def decode_ticks(payload: bytes) -> list[dict]:
    """Decode one Kite WebSocket binary message into a list of
    ``{"instrument_token": int, "ltp": float}``.

    Wire format (all big-endian): 2-byte packet count, then per packet a
    2-byte length prefix followed by that many bytes. Every packet mode
    (ltp=8 bytes, quote=44 bytes, full=184 bytes) shares the same first 8
    bytes -- 4-byte instrument_token, then 4-byte last_traded_price in paise
    (divide by 100 for rupees) -- so one decode path reads just those 8
    bytes and ignores anything past them, regardless of packet length.

    Never raises -- a malformed/truncated payload (a dropped byte mid-frame,
    a corrupted relay hop) yields whatever packets parsed cleanly before the
    truncation, matching this codebase's "degrade, don't crash" convention
    for anything on a live external-feed path.
    """
    if len(payload) < 2:
        return []
    num_packets = struct.unpack_from(">H", payload, 0)[0]
    ticks = []
    offset = 2
    for _ in range(num_packets):
        if offset + 2 > len(payload):
            break
        packet_len = struct.unpack_from(">H", payload, offset)[0]
        offset += 2
        if offset + packet_len > len(payload) or packet_len < 8:
            break
        packet = payload[offset:offset + packet_len]
        offset += packet_len
        instrument_token = struct.unpack_from(">I", packet, 0)[0]
        ltp_paise = struct.unpack_from(">i", packet, 4)[0]
        ticks.append({"instrument_token": instrument_token, "ltp": ltp_paise / 100})
    return ticks


def update_cache(cache: dict[int, dict], ticks: list[dict], now) -> None:
    """Write each tick into ``cache`` keyed by instrument_token, overwriting
    any prior value -- the cache only ever holds the latest known price per
    instrument, never a history."""
    for tick in ticks:
        cache[tick["instrument_token"]] = {"ltp": tick["ltp"], "as_of": now}
