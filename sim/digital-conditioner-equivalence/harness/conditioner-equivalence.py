#!/usr/bin/env python3
"""Equivalence testbench for the CRC-32 LFSR conditioner.

The conditioner is the one block in the digital section where "it looks
right" is not evidence: a wrong bit order or a wrong tap set still produces
plausible-looking 32-bit words. So the model is checked against **two
independently-constructed references** plus the standard library's own
CRC-32:

* **Reference B** -- GF(2) polynomial long division on Python integers
  (``state = (M(x)*x^32 + I(x)*x^n) mod G(x)``). Shares no loop structure
  with the LFSR.
* **Reference C** -- :func:`zlib.crc32`. The reflected CRC-32 with the same
  generator; feeding the LFSR the bit-reversed message and
  reversing/complementing its output must reproduce it exactly. This is what
  makes "the polynomial really is CRC-32" a checked claim.
* **Flush/blocking behaviour** -- each conditioned word must depend on
  exactly its own 256 raw bits and nothing else, which is checked by
  perturbing bits inside and outside the block.

Declared synthetic source: no sky130 raw bitstream exists yet (issue #21), so
every bit here comes from a seeded :mod:`random` stream and is labelled as
such. The conditioner is a deterministic function of its input, so this
costs the equivalence claim nothing -- it would cost an *entropy* claim
everything, and no entropy claim is made here.

Usage::

    python3 sim/digital-conditioner-equivalence/harness/conditioner-equivalence.py
    python3 sim/digital-conditioner-equivalence/harness/conditioner-equivalence.py --emit-record
"""

from __future__ import annotations

import argparse
import random
import sys
import zlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "digital"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

from evidence_record import mint_behavioral_record  # noqa: E402
from model.conditioner import (Crc32Conditioner, bit_reverse32,  # noqa: E402
                               crc32_polynomial_remainder, lfsr_over_bits)
from model.params import COND_BLOCK_BITS, CRC32_INIT, CRC32_POLY  # noqa: E402

DEFAULT_SEED = 20260905
DEFAULT_BLOCKS = 256


def model_words(bits: list[int]) -> list[int]:
    cond = Crc32Conditioner()
    out = []
    for bit in bits:
        word = cond.push(bit)
        if word is not None:
            out.append(word)
    return out


def run(seed: int, blocks: int) -> tuple[str, dict, list[str]]:
    rng = random.Random(seed)
    bits = [rng.getrandbits(1) for _ in range(blocks * COND_BLOCK_BITS)]

    # -- check 1: model vs GF(2) long division, block by block --------------
    words = model_words(bits)
    ref_b = [crc32_polynomial_remainder(bits[i * COND_BLOCK_BITS:(i + 1) * COND_BLOCK_BITS])
             for i in range(blocks)]
    mismatches_b = [i for i, (a, b) in enumerate(zip(words, ref_b)) if a != b]

    # -- check 2: the polynomial really is CRC-32 (zlib) --------------------
    zlib_cases = []
    zlib_bad = 0
    for n_bytes in (0, 1, 2, 3, 15, 16, 17, 64, 255):
        data = bytes(rng.getrandbits(8) for _ in range(n_bytes))
        reflected_bits = [(byte >> i) & 1 for byte in data for i in range(8)]
        got = bit_reverse32(lfsr_over_bits(reflected_bits)) ^ 0xFFFFFFFF
        want = zlib.crc32(data) & 0xFFFFFFFF
        zlib_cases.append({"n_bytes": n_bytes, "got": got, "want": want,
                           "ok": got == want})
        zlib_bad += (got != want)

    # -- check 3: block independence ---------------------------------------
    # Flipping one bit inside block k must change word k and only word k.
    flip_index = COND_BLOCK_BITS + 137  # somewhere inside block 1
    perturbed = list(bits)
    perturbed[flip_index] ^= 1
    words_p = model_words(perturbed)
    changed = [i for i, (a, b) in enumerate(zip(words, words_p)) if a != b]
    block_independence_ok = changed == [1]

    # -- check 4: avalanche, as a sanity floor on the mixing ----------------
    # Not an entropy claim: a CRC is linear, and a linear map cannot be an
    # entropy amplifier. This only catches a conditioner that is barely
    # mixing at all (e.g. a stuck feedback tap).
    ham = []
    for _ in range(64):
        base = [rng.getrandbits(1) for _ in range(COND_BLOCK_BITS)]
        j = rng.randrange(COND_BLOCK_BITS)
        alt = list(base)
        alt[j] ^= 1
        w0 = model_words(base)[0]
        w1 = model_words(alt)[0]
        ham.append(bin(w0 ^ w1).count("1"))
    mean_hamming = sum(ham) / len(ham)

    # -- check 5: the all-zero and all-one degenerate inputs ---------------
    zero_word = model_words([0] * COND_BLOCK_BITS)[0]
    one_word = model_words([1] * COND_BLOCK_BITS)[0]
    degenerate_distinct = zero_word != one_word

    # -- check 6: flush ------------------------------------------------------
    cond = Crc32Conditioner()
    for bit in bits[:100]:
        cond.push(bit)
    cond.reset()
    flushed = [cond.push(b) for b in bits[:COND_BLOCK_BITS]]
    flush_word = [w for w in flushed if w is not None]
    flush_ok = (len(flush_word) == 1 and flush_word[0] == words[0])

    ok = (not mismatches_b and zlib_bad == 0 and block_independence_ok
          and degenerate_distinct and flush_ok)

    lines: list[str] = []
    a = lines.append
    a("## Configuration")
    a("")
    a(f"- polynomial: `0x{CRC32_POLY:08X}` (CRC-32, non-reflected), init `0x{CRC32_INIT:08X}`")
    a(f"- block size: {COND_BLOCK_BITS} raw bits in -> one 32-bit word out (`K = 8`)")
    a(f"- stimulus: **declared synthetic** -- `random.Random({seed})`, {blocks} blocks "
      f"({blocks * COND_BLOCK_BITS} raw bits). No sky130 raw bitstream exists yet (issue #21).")
    a("")
    a("## Results")
    a("")
    a("| # | Check | Result |")
    a("|---|---|---|")
    a(f"| 1 | {blocks} conditioned words vs. GF(2) polynomial long division (independent implementation) | "
      f"{'**PASS** -- all words identical' if not mismatches_b else f'**FAIL** -- {len(mismatches_b)} mismatched words'} |")
    a(f"| 2 | LFSR core vs. `zlib.crc32` over {len(zlib_cases)} message lengths (0-255 bytes), reflected convention | "
      f"{'**PASS**' if zlib_bad == 0 else f'**FAIL** -- {zlib_bad} mismatches'} |")
    a(f"| 3 | one flipped raw bit changes exactly its own block's word | "
      f"{'**PASS**' if block_independence_ok else f'**FAIL** -- changed words {changed}'} |")
    a(f"| 4 | mean output Hamming distance for a single flipped input bit | {mean_hamming:.2f} / 32 bits |")
    a(f"| 5 | all-zero and all-one blocks produce distinct words | "
      f"{'**PASS**' if degenerate_distinct else '**FAIL**'} (`0x{zero_word:08X}` vs `0x{one_word:08X}`) |")
    a(f"| 6 | `reset()` discards a partial block (a flush leaves no residue) | "
      f"{'**PASS**' if flush_ok else '**FAIL**'} |")
    a("")
    a("### Check 2 detail")
    a("")
    a("| message bytes | LFSR (reflected + complemented) | `zlib.crc32` | |")
    a("|---|---|---|---|")
    for case in zlib_cases:
        a(f"| {case['n_bytes']} | `0x{case['got']:08X}` | `0x{case['want']:08X}` | "
          f"{'ok' if case['ok'] else '**MISMATCH**'} |")
    a("")
    a("## What this record does and does not establish")
    a("")
    a("- It **does** establish that the committed conditioner computes CRC-32")
    a("  as specified, that each output word depends on exactly its own 256")
    a("  raw bits, and that a flush leaves no residue across a gate or a mode")
    a("  switch.")
    a("- Check 4 is a **sanity floor, not an entropy claim.** A CRC is a")
    a("  linear map over GF(2); it redistributes entropy, it cannot create")
    a("  any. Per SP 800-90B this is a *non-vetted* conditioner, so the")
    a("  block's entropy accounting is stated at the raw tap and never at the")
    a("  conditioner output (DR-0004 §3.3).")
    a("- It says nothing about the *entropy* of the input bits: the stimulus")
    a("  is a declared synthetic pseudorandom source, and the real one has")
    a("  not been simulated (issue #21).")

    summary = {
        "ok": ok,
        "seed": seed,
        "blocks": blocks,
        "raw_bits": blocks * COND_BLOCK_BITS,
        "poly": f"0x{CRC32_POLY:08X}",
        "init": f"0x{CRC32_INIT:08X}",
        "gf2_mismatches": len(mismatches_b),
        "zlib_mismatches": zlib_bad,
        "block_independence_ok": block_independence_ok,
        "mean_hamming_single_bit_flip": mean_hamming,
        "all_zero_word": f"0x{zero_word:08X}",
        "all_one_word": f"0x{one_word:08X}",
        "flush_ok": flush_ok,
        "first_word": f"0x{words[0]:08X}",
        "last_word": f"0x{words[-1]:08X}",
    }
    return "\n".join(lines), summary, []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--blocks", type=int, default=DEFAULT_BLOCKS)
    ap.add_argument("--emit-record", action="store_true")
    args = ap.parse_args(argv)

    body, summary, artifacts = run(args.seed, args.blocks)
    print(body)
    if not summary["ok"]:
        print("\nEQUIVALENCE FAILED", file=sys.stderr)

    if args.emit_record:
        mint_behavioral_record(
            repo_root=REPO_ROOT,
            slug="digital-conditioner-equivalence",
            claim=("the committed CRC-32/LFSR conditioner model is bit-exact "
                   "against two independently-constructed references, and each "
                   "conditioned word depends on exactly its own 256 raw bits"),
            body_md=body,
            summary=summary,
            level="behavioral",
            seeds={"python_random": args.seed},
            artifacts=[Path(p) for p in artifacts],
        )
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
