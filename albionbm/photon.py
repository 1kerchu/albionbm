"""Decodificador del protocolo de red Photon (Protocol18) que usa Albion Online.

Es una adaptación a Python del parser del cliente oficial de Albion Online Data Project
(https://github.com/ao-data/albiondata-client, carpeta client/photon), que a su vez porta
PhotonParser.cs de https://github.com/JPCodeCraft/AlbionDataAvalonia.

Solo LEE paquetes que ya llegan a tu ordenador: no envía nada ni modifica el juego.
"""
from __future__ import annotations

import io
import struct
from typing import Any, Callable, Dict, Optional

PHOTON_HEADER_LENGTH = 12
COMMAND_HEADER_LENGTH = 12
FRAGMENT_HEADER_LENGTH = 20
MAX_PENDING_SEGMENTS = 64
MAX_SEGMENT_TOTAL_LENGTH = 8 << 20

CMD_DISCONNECT = 4
CMD_SEND_RELIABLE = 6
CMD_SEND_UNRELIABLE = 7
CMD_SEND_FRAGMENT = 8

MSG_REQUEST = 2
MSG_RESPONSE = 3
MSG_EVENT = 4
MSG_RESPONSE_ALT = 7
MSG_ENCRYPTED = 131

FLAG_ENCRYPTED = 1
FLAG_CRC_ENABLED = 0xCC
CRC_FIELD_LENGTH = 4

# Códigos de tipo de Protocol18
T_UNKNOWN, T_BOOLEAN, T_BYTE, T_SHORT, T_FLOAT, T_DOUBLE, T_STRING, T_NULL = 0, 2, 3, 4, 5, 6, 7, 8
T_CINT, T_CLONG = 9, 10
T_INT1, T_INT1N, T_INT2, T_INT2N = 11, 12, 13, 14
T_LONG1, T_LONG1N, T_LONG2, T_LONG2N = 15, 16, 17, 18
T_CUSTOM, T_DICT, T_HASHTABLE, T_OBJARRAY = 19, 20, 21, 23
T_OPREQ, T_OPRESP, T_EVENT = 24, 25, 26
T_FALSE, T_TRUE = 27, 28
T_SHORT0, T_INT0, T_LONG0, T_FLOAT0, T_DOUBLE0, T_BYTE0 = 29, 30, 31, 32, 33, 34
T_ARRAY = 0x40
T_CUSTOM_SLIM = 0x80


class StringArray(list):
    """Lista de strings tipada (Protocol18 typed string array)."""


# ---------------------------------------------------------------- lectores básicos

def _read_byte(buf: io.BytesIO) -> Optional[int]:
    b = buf.read(1)
    return b[0] if b else None


def _remaining(buf: io.BytesIO) -> int:
    return len(buf.getbuffer()) - buf.tell()


def _read_fmt(buf: io.BytesIO, fmt: str, size: int, default=0):
    b = buf.read(size)
    if len(b) < size:
        return default
    return struct.unpack(fmt, b)[0]


def _read_cuint(buf: io.BytesIO, max_shift: int = 35) -> int:
    value, shift = 0, 0
    while True:
        b = _read_byte(buf)
        if b is None:
            return 0
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value
        shift += 7
        if shift >= max_shift:
            return 0


def _zigzag(v: int) -> int:
    return (v >> 1) ^ -(v & 1)


def _read_string(buf: io.BytesIO) -> str:
    length = _read_cuint(buf)
    if length <= 0 or length > _remaining(buf):
        return ""
    return buf.read(length).decode("utf-8", errors="replace")


# ---------------------------------------------------------------- deserializador

def read_parameter_table(buf: io.BytesIO) -> Dict[int, Any]:
    count = _read_cuint(buf)
    params: Dict[int, Any] = {}
    for _ in range(count):
        if _remaining(buf) <= 0:
            break
        key = _read_byte(buf)
        tc = _read_byte(buf)
        if key is None or tc is None:
            break
        params[key] = deserialize(buf, tc)
    return params


def deserialize(buf: io.BytesIO, tc: int) -> Any:
    if tc >= T_CUSTOM_SLIM:
        return _custom(buf, tc)
    if tc in (T_UNKNOWN, T_NULL):
        return None
    if tc == T_BOOLEAN:
        return (_read_byte(buf) or 0) != 0
    if tc == T_BYTE:
        return _read_byte(buf) or 0
    if tc == T_SHORT:
        return _read_fmt(buf, "<h", 2)
    if tc == T_FLOAT:
        return _read_fmt(buf, "<f", 4, 0.0)
    if tc == T_DOUBLE:
        return _read_fmt(buf, "<d", 8, 0.0)
    if tc == T_STRING:
        return _read_string(buf)
    if tc == T_CINT:
        return _zigzag(_read_cuint(buf))
    if tc == T_CLONG:
        return _zigzag(_read_cuint(buf, 70))
    if tc in (T_INT1, T_LONG1):
        return _read_byte(buf) or 0
    if tc in (T_INT1N, T_LONG1N):
        return -(_read_byte(buf) or 0)
    if tc in (T_INT2, T_LONG2):
        return _read_fmt(buf, "<H", 2)
    if tc in (T_INT2N, T_LONG2N):
        return -_read_fmt(buf, "<H", 2)
    if tc == T_CUSTOM:
        return _custom(buf, 0)
    if tc in (T_DICT, T_HASHTABLE):
        return _dictionary(buf)
    if tc == T_OBJARRAY:
        out = []
        for _ in range(_read_cuint(buf)):
            t = _read_byte(buf)
            if t is None:
                break
            out.append(deserialize(buf, t))
        return out
    if tc == T_OPREQ:
        op = _read_byte(buf)
        return {"operationCode": op, "parameters": read_parameter_table(buf)}
    if tc == T_OPRESP:
        if _remaining(buf) < 3:
            return None
        op = _read_byte(buf)
        rc = _read_fmt(buf, "<h", 2)
        dbg = ""
        if _remaining(buf) > 0:
            v = deserialize(buf, _read_byte(buf))
            dbg = v if isinstance(v, str) else ""
        return {"operationCode": op, "returnCode": rc, "debugMessage": dbg, "parameters": read_parameter_table(buf)}
    if tc == T_EVENT:
        code = _read_byte(buf)
        return {"code": code, "parameters": read_parameter_table(buf)}
    if tc == T_FALSE:
        return False
    if tc == T_TRUE:
        return True
    if tc in (T_SHORT0, T_INT0, T_LONG0, T_BYTE0):
        return 0
    if tc in (T_FLOAT0, T_DOUBLE0):
        return 0.0
    if tc == T_ARRAY:
        size = _read_cuint(buf)
        t = _read_byte(buf)
        if t is None:
            return None
        return [deserialize(buf, t) for _ in range(size)]
    if tc & T_ARRAY == T_ARRAY:
        return _typed_array(buf, tc & ~T_ARRAY)
    return f"ERROR - unknown type 0x{tc:02X}"


def _typed_array(buf: io.BytesIO, elem: int) -> Any:
    size = _read_cuint(buf)
    if elem == T_BOOLEAN:
        packed = buf.read((size + 7) // 8)
        return [bool(packed[i // 8] & (1 << (i % 8))) if i // 8 < len(packed) else False for i in range(size)]
    if elem == T_BYTE:
        return buf.read(size)
    if elem == T_STRING:
        return StringArray(_read_string(buf) for _ in range(size))
    if elem == T_CUSTOM:
        cid = _read_byte(buf) or 0
        return [_custom_payload(buf, cid, False) for _ in range(size)]
    if elem in (T_DICT, T_HASHTABLE):
        return [_dictionary(buf) for _ in range(size)]
    return [deserialize(buf, elem) for _ in range(size)]


def _dictionary(buf: io.BytesIO) -> dict:
    ktc = _read_byte(buf) or 0
    vtc = _read_byte(buf) or 0
    out = {}
    for i in range(_read_cuint(buf)):
        if _remaining(buf) <= 0:
            break
        kt = (_read_byte(buf) or 0) if ktc == 0 else ktc
        vt = (_read_byte(buf) or 0) if vtc == 0 else vtc
        k = deserialize(buf, kt)
        v = deserialize(buf, vt)
        try:
            hash(k)
        except TypeError:
            k = f"UNHASHABLE_{i}"
        out[k] = v
    return out


def _custom(buf: io.BytesIO, gp: int) -> Any:
    slim = gp >= T_CUSTOM_SLIM
    cid = gp & 0x7F if slim else (_read_byte(buf) or 0)
    return _custom_payload(buf, cid, slim)


def _custom_payload(buf: io.BytesIO, cid: int, slim: bool) -> Any:
    size = _read_cuint(buf)
    if size < 0 or size > _remaining(buf):
        if slim:
            return {"type": cid, "data": buf.read()}
        return None
    return {"type": cid, "data": buf.read(size)}


# ---------------------------------------------------------------- CRC de Photon

def calculate_crc(data: bytes) -> int:
    key, result = 3988292384, 0xFFFFFFFF
    for b in data:
        result ^= b
        for _ in range(8):
            result = (result >> 1) ^ key if result & 1 else result >> 1
    return result


# ---------------------------------------------------------------- parser de paquetes

class PhotonParser:
    """Recibe payloads UDP/TCP crudos y llama a los callbacks por cada mensaje decodificado."""

    def __init__(
        self,
        on_request: Optional[Callable[[int, Dict[int, Any]], None]] = None,
        on_response: Optional[Callable[[int, int, str, Dict[int, Any]], None]] = None,
        on_event: Optional[Callable[[int, Dict[int, Any]], None]] = None,
        on_encrypted: Optional[Callable[[], None]] = None,
    ):
        self.on_request = on_request
        self.on_response = on_response
        self.on_event = on_event
        self.on_encrypted = on_encrypted
        self._segments: Dict[int, dict] = {}
        self._segment_order: list = []

    # -- entrada principal
    def receive_packet(self, payload: bytes) -> bool:
        if len(payload) < PHOTON_HEADER_LENGTH:
            return False
        ident = _identity(payload, 0)
        first = _packet_length(payload, 0)
        if ident is None or first is None:
            return False
        first_len, terminal = first
        if terminal or first_len == len(payload):
            return self._receive_single(payload)

        ranges = [(0, first_len)]
        off, framing_ok = first_len, True
        while off < len(payload):
            if _identity(payload, off) != ident:
                framing_ok = False
                break
            pl = _packet_length(payload, off)
            if pl is None:
                framing_ok = False
                break
            ranges.append((off, pl[0]))
            off += pl[0]
            if pl[1]:
                break
        ok = framing_ok
        for o, ln in ranges:
            if not self._receive_single(payload[o:o + ln]):
                ok = False
        return ok

    def _receive_single(self, payload: bytes) -> bool:
        if len(payload) < PHOTON_HEADER_LENGTH:
            return False
        flags = payload[2]
        command_count = payload[3]
        offset = PHOTON_HEADER_LENGTH
        if flags == FLAG_ENCRYPTED:
            if self.on_encrypted:
                self.on_encrypted()
            return False
        if flags == FLAG_CRC_ENABLED:
            if len(payload) < offset + CRC_FIELD_LENGTH:
                return False
            crc = struct.unpack_from(">I", payload, offset)[0]
            offset += CRC_FIELD_LENGTH
            zeroed = bytearray(payload)
            zeroed[PHOTON_HEADER_LENGTH:PHOTON_HEADER_LENGTH + CRC_FIELD_LENGTH] = b"\0\0\0\0"
            if crc != calculate_crc(bytes(zeroed)):
                return False
        for _ in range(command_count):
            res = self._handle_command(payload, offset)
            if res is None:
                return False
            offset = res
        return offset == len(payload)

    def _handle_command(self, src: bytes, offset: int) -> Optional[int]:
        if len(src) - offset < COMMAND_HEADER_LENGTH:
            return None
        cmd_type = src[offset]
        cmd_len = struct.unpack_from(">I", src, offset + 4)[0] - COMMAND_HEADER_LENGTH
        offset += COMMAND_HEADER_LENGTH
        if cmd_len < 0 or len(src) - offset < cmd_len:
            return None
        if cmd_type == CMD_DISCONNECT:
            return offset + cmd_len
        if cmd_type == CMD_SEND_UNRELIABLE:
            if cmd_len < 4:
                return None
            self._handle_reliable(src, offset + 4, cmd_len - 4)
            return offset + cmd_len
        if cmd_type == CMD_SEND_RELIABLE:
            self._handle_reliable(src, offset, cmd_len)
            return offset + cmd_len
        if cmd_type == CMD_SEND_FRAGMENT:
            self._handle_fragment(src, offset, cmd_len)
            return offset + cmd_len
        return offset + cmd_len

    def _handle_reliable(self, src: bytes, offset: int, cmd_len: int) -> None:
        if cmd_len < 2 or len(src) - offset < cmd_len:
            return
        msg_type = src[offset + 1]
        data = src[offset + 2: offset + cmd_len]
        if msg_type == MSG_ENCRYPTED:
            if self.on_encrypted:
                self.on_encrypted()
            return
        try:
            if msg_type == MSG_REQUEST:
                self._dispatch_request(data)
            elif msg_type in (MSG_RESPONSE, MSG_RESPONSE_ALT):
                self._dispatch_response(data)
            elif msg_type == MSG_EVENT:
                self._dispatch_event(data)
        except Exception:  # un mensaje corrupto no debe parar la captura
            pass

    def _dispatch_request(self, data: bytes) -> None:
        if len(data) < 1:
            return
        params = read_parameter_table(io.BytesIO(data[1:]))
        if self.on_request:
            self.on_request(data[0], params)

    def _dispatch_response(self, data: bytes) -> None:
        if len(data) < 3:
            return
        op_code = data[0]
        return_code = struct.unpack_from("<h", data, 1)[0]
        buf = io.BytesIO(data[3:])
        debug = ""
        if _remaining(buf) > 0:
            tc = _read_byte(buf)
            val = deserialize(buf, tc)
            if isinstance(val, str):
                debug = val
            elif isinstance(val, StringArray):
                # Albion mete las órdenes de mercado como array de strings en el hueco del mensaje de debug.
                if self.on_response:
                    self.on_response(op_code, return_code, "", {0: list(val)})
                return
        params = read_parameter_table(buf)
        if self.on_response:
            self.on_response(op_code, return_code, debug, params)

    def _dispatch_event(self, data: bytes) -> None:
        if len(data) < 1:
            return
        params = read_parameter_table(io.BytesIO(data[1:]))
        if self.on_event:
            self.on_event(data[0], params)

    def _handle_fragment(self, src: bytes, offset: int, cmd_len: int) -> None:
        if cmd_len < FRAGMENT_HEADER_LENGTH or len(src) - offset < FRAGMENT_HEADER_LENGTH:
            return
        start_seq, _count, _num, total_len, frag_off = struct.unpack_from(">IIIII", src, offset)
        offset += FRAGMENT_HEADER_LENGTH
        frag_len = cmd_len - FRAGMENT_HEADER_LENGTH
        if frag_len < 0 or len(src) - offset < frag_len:
            return
        seg = self._segments.get(start_seq)
        if seg is None:
            if total_len <= 0 or total_len > MAX_SEGMENT_TOTAL_LENGTH:
                return
            if len(self._segments) >= MAX_PENDING_SEGMENTS:
                self._evict_oldest()
            seg = {"total": total_len, "written": 0, "payload": bytearray(total_len)}
            self._segments[start_seq] = seg
            self._segment_order.append(start_seq)
        end = frag_off + frag_len
        if end <= len(seg["payload"]):
            seg["payload"][frag_off:end] = src[offset:offset + frag_len]
        seg["written"] += frag_len
        if seg["written"] >= seg["total"]:
            del self._segments[start_seq]
            p = bytes(seg["payload"])
            self._handle_reliable(p, 0, len(p))

    def _evict_oldest(self) -> None:
        while self._segment_order:
            oldest = self._segment_order.pop(0)
            if oldest in self._segments:
                del self._segments[oldest]
                return


def _identity(payload: bytes, offset: int):
    if len(payload) - offset < PHOTON_HEADER_LENGTH:
        return None
    peer = struct.unpack_from(">h", payload, offset)[0]
    challenge = struct.unpack_from(">i", payload, offset + 8)[0]
    return peer, challenge


def _packet_length(payload: bytes, offset: int):
    """Devuelve (longitud, es_cifrado_terminal) o None si no es válido."""
    if len(payload) - offset < PHOTON_HEADER_LENGTH:
        return None
    flags = payload[offset + 2]
    if flags == FLAG_ENCRYPTED:
        return len(payload) - offset, True
    header_len = PHOTON_HEADER_LENGTH + (CRC_FIELD_LENGTH if flags == FLAG_CRC_ENABLED else 0)
    if len(payload) - offset < header_len:
        return None
    count = payload[offset + 3]
    if count == 0:
        return None
    cmd = offset + header_len
    for _ in range(count):
        if len(payload) - cmd < COMMAND_HEADER_LENGTH:
            return None
        ln = struct.unpack_from(">I", payload, cmd + 4)[0]
        if ln < COMMAND_HEADER_LENGTH or len(payload) - cmd < ln:
            return None
        cmd += ln
    return cmd - offset, False
