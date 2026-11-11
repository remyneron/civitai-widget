"""Tiny BlurHash decoder used for image placeholders. No Qt here."""

from __future__ import annotations

import math
from functools import lru_cache

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#$%*+,-.:;=?@[]^_{|}~"
_INDEX = {char: i for i, char in enumerate(_ALPHABET)}


def _decode83(text: str) -> int:
    value = 0
    for char in text:
        value = value * 83 + _INDEX[char]
    return value


def _srgb_to_linear(value: int) -> float:
    v = value / 255.0
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(value: float) -> int:
    v = min(1.0, max(0.0, value))
    if v <= 0.0031308:
        return int(v * 12.92 * 255 + 0.5)
    return int((1.055 * v ** (1 / 2.4) - 0.055) * 255 + 0.5)


def _sign_pow(value: float, exponent: float) -> float:
    return math.copysign(abs(value) ** exponent, value)


@lru_cache(maxsize=256)
def decode(blurhash: str, width: int = 20, height: int = 20) -> bytes | None:
    """Decode to packed RGB888 bytes (`width * height * 3`), or None if the hash is invalid."""
    try:
        if not blurhash or len(blurhash) < 6:
            return None
        size_flag = _decode83(blurhash[0])
        num_y = size_flag // 9 + 1
        num_x = size_flag % 9 + 1
        if len(blurhash) != 4 + 2 * num_x * num_y:
            return None
        max_value = (_decode83(blurhash[1]) + 1) / 166.0

        dc = _decode83(blurhash[2:6])
        colors = [(_srgb_to_linear(dc >> 16), _srgb_to_linear((dc >> 8) & 255), _srgb_to_linear(dc & 255))]
        for i in range(1, num_x * num_y):
            value = _decode83(blurhash[4 + i * 2 : 6 + i * 2])
            colors.append(
                (
                    _sign_pow((value // 361 - 9) / 9.0, 2.0) * max_value,
                    _sign_pow((value // 19 % 19 - 9) / 9.0, 2.0) * max_value,
                    _sign_pow((value % 19 - 9) / 9.0, 2.0) * max_value,
                )
            )
    except (KeyError, TypeError):
        return None

    cos_x = [[math.cos(math.pi * x * i / width) for i in range(num_x)] for x in range(width)]
    cos_y = [[math.cos(math.pi * y * j / height) for j in range(num_y)] for y in range(height)]

    out = bytearray(width * height * 3)
    pos = 0
    for y in range(height):
        row_y = cos_y[y]
        for x in range(width):
            row_x = cos_x[x]
            r = g = b = 0.0
            for j in range(num_y):
                basis_y = row_y[j]
                offset = j * num_x
                for i in range(num_x):
                    basis = row_x[i] * basis_y
                    color = colors[offset + i]
                    r += color[0] * basis
                    g += color[1] * basis
                    b += color[2] * basis
            out[pos] = _linear_to_srgb(r)
            out[pos + 1] = _linear_to_srgb(g)
            out[pos + 2] = _linear_to_srgb(b)
            pos += 3
    return bytes(out)
