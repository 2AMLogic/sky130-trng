#!/usr/bin/env python3
"""CRC-32 LFSR conditioner (non-vetted), bit-exact behavioural model.

``K = 8``: 256 raw bits are absorbed into a 32-bit CRC register, and the
register value is emitted as one conditioned word. The register is re-seeded
to :data:`~digital.model.params.CRC32_INIT` at every block boundary, so each
output word depends on exactly 256 raw bits and no bits from any other block
-- see ``spec/decision-records/DR-0004-sky130-digital-section-architecture.md``
§3.2 for why the bounded, non-overlapping dependency was chosen over a
free-running register.

Structure (bit order, polynomial, initial value) is the non-reflected CRC-32
LFSR::

    fb    = state[31] XOR raw_bit
    state = (state << 1) XOR (POLY if fb else 0)

This is a **non-vetted** conditioner in SP 800-90B terms: it makes no
full-entropy claim, and the block's entropy accounting is stated at the raw
tap, never at the conditioner output (DR-0004 §3.3).
"""

from __future__ import annotations

from .params import COND_BLOCK_BITS, CRC32_INIT, CRC32_POLY


class Crc32Conditioner:
    """256-raw-bits-in / one-32-bit-word-out CRC-32 LFSR."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Flush: drop the partial block and re-seed the register.

        Called on reset, on a health-test gate, and on an ``OUT_MODE`` switch
        (DR-0004 §4.3) -- a flush must never leave half a block of pre-event
        bits to be mixed into a post-event word.
        """
        self.state = CRC32_INIT
        self.count = 0

    def push(self, bit: int) -> int | None:
        """Absorb one raw bit; return a conditioned word at a block boundary."""
        fb = ((self.state >> 31) & 1) ^ (bit & 1)
        self.state = ((self.state << 1) & 0xFFFFFFFF) ^ (CRC32_POLY if fb else 0)
        self.count += 1
        if self.count == COND_BLOCK_BITS:
            word = self.state
            self.state = CRC32_INIT
            self.count = 0
            return word
        return None


# --------------------------------------------------------------------------
# Independent references -- used only by the equivalence testbench, never by
# the DUT model. Each is written from a *different* construction so that a
# shared mistake is unlikely (``sim/digital-conditioner-equivalence/``).
# --------------------------------------------------------------------------

def crc32_polynomial_remainder(bits: list[int]) -> int:
    """Reference B: GF(2) polynomial long division, no LFSR anywhere.

    For a message ``M(x)`` of ``n`` bits (first bit = highest degree) and an
    initial register value ``I(x)``, the MSB-first CRC register after ``n``
    shifts is, by linearity of the shift register over GF(2)::

        state(x) = ( M(x)*x^32 + I(x)*x^n )  mod  G(x)

    This computes that remainder directly by long division on Python
    integers. It shares no code path and no loop structure with
    :class:`Crc32Conditioner`, so agreement between the two is evidence
    about the implementation rather than a tautology.
    """
    gen = (1 << 32) | CRC32_POLY
    n = len(bits)
    message = 0
    for bit in bits:
        message = (message << 1) | (bit & 1)
    value = (message << 32) ^ (CRC32_INIT << n)
    for shift in range(value.bit_length() - 1, 31, -1):
        if (value >> shift) & 1:
            value ^= gen << (shift - 32)
    return value & 0xFFFFFFFF


def bit_reverse32(value: int) -> int:
    out = 0
    for i in range(32):
        out = (out << 1) | ((value >> i) & 1)
    return out


def lfsr_over_bits(bits: list[int]) -> int:
    """Run the raw LFSR core over an arbitrary-length bit list (no blocking)."""
    state = CRC32_INIT
    for bit in bits:
        fb = ((state >> 31) & 1) ^ (bit & 1)
        state = ((state << 1) & 0xFFFFFFFF) ^ (CRC32_POLY if fb else 0)
    return state
