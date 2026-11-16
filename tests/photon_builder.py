"""Construye paquetes Photon (Protocol18) sintéticos para los tests."""
import struct


def cuint(v: int) -> bytes:
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def string(s: str) -> bytes:
    b = s.encode("utf-8")
    return cuint(len(b)) + b


class IntList(list):
    """Lista de enteros que se codifica como array tipado de enteros largos comprimidos."""


def value(v) -> bytes:
    """Devuelve type code + valor."""
    if isinstance(v, IntList):
        return bytes([0x40 | 10]) + cuint(len(v)) + b"".join(cuint((x << 1) ^ (x >> 63)) for x in v)
    if isinstance(v, bool):
        return bytes([28 if v else 27])
    if isinstance(v, int):
        z = (v << 1) ^ (v >> 63)
        if abs(v) >= 2 ** 31:
            return bytes([10]) + cuint(z)
        return bytes([9]) + cuint(z & 0xFFFFFFFF)
    if isinstance(v, str):
        return bytes([7]) + string(v)
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return bytes([0x40 | 7]) + cuint(len(v)) + b"".join(string(x) for x in v)
    raise TypeError(v)


def param_table(params: dict) -> bytes:
    return cuint(len(params)) + b"".join(bytes([k]) + value(v) for k, v in params.items())


def response(op: int, params: dict, return_code: int = 0, debug_slot=None) -> bytes:
    body = bytes([op]) + struct.pack("<h", return_code)
    if debug_slot is not None:
        body += value(debug_slot)
        if not isinstance(debug_slot, list):
            body += param_table(params)
    else:
        body += bytes([8]) + param_table(params)  # debug = null
    return body


def request(op: int, params: dict) -> bytes:
    return bytes([op]) + param_table(params)


def reliable(msg_type: int, body: bytes) -> bytes:
    data = bytes([0xF3, msg_type]) + body
    return bytes([6, 0, 0, 0]) + struct.pack(">I", 12 + len(data)) + struct.pack(">I", 1) + data


def fragments(msg_type: int, body: bytes, size: int, start_seq: int = 77):
    data = bytes([0xF3, msg_type]) + body
    parts = [data[i:i + size] for i in range(0, len(data), size)]
    cmds = []
    for n, p in enumerate(parts):
        frag = struct.pack(">IIIII", start_seq, len(parts), n, len(data), n * size) + p
        cmds.append(bytes([8, 0, 0, 0]) + struct.pack(">I", 12 + len(frag)) + struct.pack(">I", start_seq + n) + frag)
    return cmds


def packet(*commands: bytes, flags: int = 0, peer: int = 1, challenge: int = 1234) -> bytes:
    header = struct.pack(">hBBIi", peer, flags, len(commands), 0, challenge)
    return header + b"".join(commands)
