"""Throwaway age X25519 key pair for tests, in pure Python (no age-keygen needed).

X25519 per RFC 7748, bech32 per BIP 173 (age uses plain bech32, not bech32m).
For tests only: the key never leaves the test's temp directory.
"""
import os

P = 2 ** 255 - 19
A24 = 121665
CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"


def _x25519(k: bytes, u: int) -> bytes:
    k = bytearray(k)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    s = int.from_bytes(k, "little")
    x1, x2, z2, x3, z3, swap = u, 1, 0, u, 1, 0
    for t in reversed(range(255)):
        bit = (s >> t) & 1
        swap ^= bit
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = bit
        a, b = (x2 + z2) % P, (x2 - z2) % P
        aa, bb = a * a % P, b * b % P
        e = (aa - bb) % P
        c, d = (x3 + z3) % P, (x3 - z3) % P
        da, cb = d * a % P, c * b % P
        x3 = (da + cb) ** 2 % P
        z3 = x1 * (da - cb) ** 2 % P
        x2 = aa * bb % P
        z2 = e * (aa + A24 * e) % P
    if swap:
        x2, z2 = x3, z3
    return (x2 * pow(z2, P - 2, P) % P).to_bytes(32, "little")


def _polymod(values):
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        b = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((b >> i) & 1) else 0
    return chk


def _bech32(hrp: str, data: bytes) -> str:
    acc, bits, five = 0, 0, []
    for byte in data:
        acc = (acc << 8) | byte
        bits += 8
        while bits >= 5:
            bits -= 5
            five.append((acc >> bits) & 31)
    if bits:
        five.append((acc << (5 - bits)) & 31)
    expand = [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp]
    pm = _polymod(expand + five + [0] * 6) ^ 1
    check = [(pm >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + "1" + "".join(CHARSET[d] for d in five + check)


def keypair():
    """-> (identity line for a keys.txt, recipient string)."""
    sk = os.urandom(32)
    pk = _x25519(sk, 9)
    return _bech32("age-secret-key-", sk).upper(), _bech32("age", pk)
