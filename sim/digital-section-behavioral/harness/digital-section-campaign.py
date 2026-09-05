#!/usr/bin/env python3
"""Behavioural campaign over the assembled digital section.

Eight experiments against ``digital/model/digital_top.py``, each one a
property the architecture in
``spec/decision-records/DR-0004-sky130-digital-section-architecture.md``
claims and would otherwise be asserting without evidence:

A. a healthy source completes the start-up test at exactly ``STARTUP``
   samples and then produces conditioned words at the designed rate;
B. a stuck source trips the RCT at exactly ``C_RCT`` samples;
C. a strongly biased source trips the APT at the end of its first window;
D. a moderately biased source (`p = 0.75`, inside the design's own `H`
   target) does **not** trip -- the tests are not hair-trigger;
E. a long healthy run raises no alarm at all (an empirical floor under the
   `alpha = 2^-40` false-alarm argument);
F. the raw path keeps delivering while the conditioned path is gated --
   the SP 800-90B invariant this whole two-path design exists to preserve;
G. the latch-and-ungate sequence: ungating requires **both** a
   write-1-to-cleared alarm and a passed start-up test, neither alone;
H. an `OUT_MODE` switch flushes the conditioner and both FIFOs.

**Declared synthetic sources.** No sky130 raw bitstream has been simulated
yet (issue #21), so every bit here comes from a seeded, explicitly-labelled
generator: a fair coin, a stuck value, or a biased coin. These stimuli
exercise the *logic*; they say nothing about the entropy of the real source
and no entropy claim is made from them.

Usage::

    python3 sim/digital-section-behavioral/harness/digital-section-campaign.py
    python3 sim/digital-section-behavioral/harness/digital-section-campaign.py --emit-record
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "digital"))
sys.path.insert(0, str(REPO_ROOT / "sim" / "bin"))

from evidence_record import mint_behavioral_record  # noqa: E402
from model import regmap as rm  # noqa: E402
from model.digital_top import TrngDigital  # noqa: E402
from model.params import (C_APT, C_RCT, COND_BLOCK_BITS, H_DESIGN,  # noqa: E402
                          STARTUP_SAMPLES, W_APT, WORD_BITS)

DEFAULT_SEED = 20260905
RAW_RATE_BPS = 50_000.0


def new_dut(enable: bool = True, conditioned: bool = False) -> TrngDigital:
    dut = TrngDigital()
    ctrl = (rm.CTRL_EN if enable else 0) | (rm.CTRL_OUT_MODE if conditioned else 0)
    dut.write(rm.CTRL, ctrl)
    return dut


def feed(dut: TrngDigital, bits, out_ready: int = 0) -> dict:
    """Feed a bit sequence, returning the first-event indices seen.

    Word production is counted at the point a word is *completed*, not when
    it lands in a FIFO, so a full FIFO (depth 4, no consumer) does not
    silently understate what the datapath produced.
    """
    events = {"startup_done_at": None, "first_alarm_at": None,
              "alarm_word": 0, "cond_words": 0, "raw_words": 0}
    for i, bit in enumerate(bits):
        prev_cond_count = dut.cond.count
        prev_raw_count = dut.raw_count
        gated_before = dut.health.gated
        dut.cycle(raw_bit=bit, raw_valid=1, out_ready=out_ready)
        if (not gated_before and prev_cond_count == COND_BLOCK_BITS - 1
                and dut.cond.count == 0):
            events["cond_words"] += 1
        if prev_raw_count == WORD_BITS - 1 and dut.raw_count == 0:
            events["raw_words"] += 1
        if events["startup_done_at"] is None and dut.health.startup_done:
            events["startup_done_at"] = i + 1
        if events["first_alarm_at"] is None and dut.health.alarm:
            events["first_alarm_at"] = i + 1
            events["alarm_word"] = dut.alarm_word()
    return events


def drain(dut: TrngDigital, addr: int, limit: int = 64) -> list[int]:
    """Read a data register until it stops yielding words."""
    out = []
    for _ in range(limit):
        before = (dut.raw_fifo.level if addr == rm.RAW_DATA else dut.cond_fifo.level)
        if before == 0:
            break
        out.append(dut.read(addr))
    return out


def experiments(seed: int, long_run: int) -> tuple[dict, list[str]]:
    rng = random.Random(seed)
    res: dict = {}
    log: list[str] = []

    def note(line: str) -> None:
        log.append(line)

    # -- A. healthy source ------------------------------------------------
    dut = new_dut()
    n_a = STARTUP_SAMPLES + 8 * COND_BLOCK_BITS
    bits = [rng.getrandbits(1) for _ in range(n_a)]
    ev = feed(dut, bits)
    # words the design should have produced after the gate lifted
    expected_cond = (n_a - STARTUP_SAMPLES) // COND_BLOCK_BITS
    res["A"] = {
        "samples": n_a,
        "startup_done_at": ev["startup_done_at"],
        "alarm": bool(ev["first_alarm_at"]),
        "cond_words_pushed": ev["cond_words"],
        "expected_cond_words": expected_cond,
        "raw_words_pushed": ev["raw_words"],
        "expected_raw_words": n_a // WORD_BITS,
        "ok": (ev["startup_done_at"] == STARTUP_SAMPLES
               and ev["first_alarm_at"] is None
               and ev["cond_words"] == expected_cond
               and ev["raw_words"] == n_a // WORD_BITS),
    }
    note(f"A healthy: startup_done_at={ev['startup_done_at']} "
         f"cond_words={ev['cond_words']}/{expected_cond} raw_words={ev['raw_words']}")

    # -- B. stuck source (RCT) --------------------------------------------
    dut = new_dut()
    ev = feed(dut, [1] * (C_RCT + 32))
    res["B"] = {
        "trip_at": ev["first_alarm_at"],
        "expected_trip_at": C_RCT,
        "alarm_word": ev["alarm_word"],
        "rct_bit_set": bool(ev["alarm_word"] & rm.AL_RCT),
        "detection_latency_ms": (ev["first_alarm_at"] or 0) / RAW_RATE_BPS * 1e3,
        "ok": ev["first_alarm_at"] == C_RCT and bool(ev["alarm_word"] & rm.AL_RCT),
    }
    note(f"B stuck-at-1: trip_at={ev['first_alarm_at']} (expected {C_RCT}) "
         f"alarm=0x{ev['alarm_word']:x}")

    # -- C. strongly biased source (APT) ----------------------------------
    dut = new_dut()
    rng_c = random.Random(seed + 1)
    bias = 0.95
    # a strongly biased stream that never repeats C_RCT times in a row, so the
    # APT is the test that must catch it
    bits_c = []
    run_len = 0
    for _ in range(4 * W_APT):
        bit = 1 if rng_c.random() < bias else 0
        if bit == 1:
            run_len += 1
            if run_len >= C_RCT - 1:
                bit = 0
                run_len = 0
        else:
            run_len = 0
        bits_c.append(bit)
    ev = feed(dut, bits_c)
    res["C"] = {
        "bias": bias,
        "trip_at": ev["first_alarm_at"],
        "alarm_word": ev["alarm_word"],
        "apt_bit_set": bool(ev["alarm_word"] & rm.AL_APT),
        "rct_bit_set": bool(ev["alarm_word"] & rm.AL_RCT),
        "window": W_APT,
        "cutoff": C_APT,
        "ok": (ev["first_alarm_at"] is not None
               and ev["first_alarm_at"] % W_APT == 0
               and bool(ev["alarm_word"] & rm.AL_APT)
               and not bool(ev["alarm_word"] & rm.AL_RCT)),
    }
    note(f"C biased p={bias}: trip_at={ev['first_alarm_at']} alarm=0x{ev['alarm_word']:x}")

    # -- D. moderate bias, should NOT trip --------------------------------
    dut = new_dut()
    rng_d = random.Random(seed + 2)
    bias_d = 0.75  # H = -log2(0.75) = 0.415 bit/sample, below the 0.5 target
    bits_d = [1 if rng_d.random() < bias_d else 0 for _ in range(16 * W_APT)]
    ev = feed(dut, bits_d)
    res["D"] = {
        "bias": bias_d,
        "h_of_source": 0.4150375,
        "windows": 16,
        "tripped": ev["first_alarm_at"] is not None,
        "trip_at": ev["first_alarm_at"],
        "ok": ev["first_alarm_at"] is None,
    }
    note(f"D moderate bias p={bias_d}: tripped={ev['first_alarm_at'] is not None}")

    # -- E. long healthy run, no false alarm -------------------------------
    dut = new_dut()
    rng_e = random.Random(seed + 3)
    ev = feed(dut, [rng_e.getrandbits(1) for _ in range(long_run)])
    res["E"] = {
        "samples": long_run,
        "windows": long_run // W_APT,
        "alarms": 0 if ev["first_alarm_at"] is None else 1,
        "first_alarm_at": ev["first_alarm_at"],
        "wall_clock_equivalent_s": long_run / RAW_RATE_BPS,
        "ok": ev["first_alarm_at"] is None,
    }
    note(f"E long healthy run: {long_run} samples, alarms="
         f"{0 if ev['first_alarm_at'] is None else 1}")

    # -- F. raw is never gated --------------------------------------------
    dut = new_dut()
    feed(dut, [1] * (C_RCT + 4 * WORD_BITS))   # trip, then keep sampling
    gated = dut.health.gated
    raw_words = drain(dut, rm.RAW_DATA)
    data_read = dut.read(rm.DATA)
    res["F"] = {
        "gated": gated,
        "raw_words_readable_while_gated": len(raw_words),
        "data_read_while_gated": data_read,
        "status_gated_bit": bool(dut.read(rm.STATUS) & rm.ST_GATED),
        "ok": gated and len(raw_words) > 0 and data_read == 0,
    }
    note(f"F raw-never-gated: gated={gated} raw_words={len(raw_words)} "
         f"DATA={data_read:#x}")

    # -- G. latch, acknowledge, re-run start-up ----------------------------
    # The ungate condition is a CONJUNCTION: the sticky alarm must be
    # acknowledged AND a full start-up test must have passed since the trip.
    # This experiment shows neither alone is sufficient.
    dut = new_dut()
    feed(dut, [1] * C_RCT)                     # trip exactly on the cutoff
    alarm_before = dut.read(rm.ALARM)
    rng_g = random.Random(seed + 4)
    feed(dut, [rng_g.getrandbits(1) for _ in range(STARTUP_SAMPLES - 1)])
    startup_done_short = dut.health.startup_done          # False
    dut.write(rm.ALARM, rm.AL_MASK)            # acknowledge EARLY
    alarm_after = dut.read(rm.ALARM)                      # 0
    gated_after_early_ack = dut.health.gated              # still gated
    feed(dut, [rng_g.getrandbits(1) for _ in range(1)])   # start-up completes
    gated_after_startup = dut.health.gated                # ungated

    # second trip: the start-up test passes again, but the latched alarm
    # alone holds the gate until software acknowledges it.
    feed(dut, [1] * C_RCT)
    feed(dut, [rng_g.getrandbits(1) for _ in range(STARTUP_SAMPLES)])
    startup_done_second = dut.health.startup_done         # True
    gated_with_latched_alarm = dut.health.gated           # still gated
    dut.write(rm.ALARM, rm.AL_MASK)
    gated_after_ack2 = dut.health.gated                   # ungated

    res["G"] = {
        "alarm_before": alarm_before,
        "startup_done_one_short": startup_done_short,
        "alarm_after_w1c": alarm_after,
        "gated_after_early_ack": gated_after_early_ack,
        "gated_after_startup": gated_after_startup,
        "startup_done_after_second_trip": startup_done_second,
        "gated_with_latched_alarm": gated_with_latched_alarm,
        "gated_after_ack2": gated_after_ack2,
        "ok": (alarm_before != 0 and not startup_done_short
               and alarm_after == 0 and gated_after_early_ack
               and not gated_after_startup and startup_done_second
               and gated_with_latched_alarm and not gated_after_ack2),
    }
    note(f"G latch/ack: alarm_before=0x{alarm_before:x} gated_after_early_ack="
         f"{gated_after_early_ack} gated_after_startup={gated_after_startup} "
         f"gated_with_latched_alarm={gated_with_latched_alarm} "
         f"gated_after_ack2={gated_after_ack2}")

    # -- H. mode-switch flush ---------------------------------------------
    dut = new_dut()
    rng_h = random.Random(seed + 5)
    feed(dut, [rng_h.getrandbits(1) for _ in range(STARTUP_SAMPLES + 3 * COND_BLOCK_BITS)])
    levels_before = (dut.raw_fifo.level, dut.cond_fifo.level, dut.cond.count)
    dut.write(rm.CTRL, rm.CTRL_EN | rm.CTRL_OUT_MODE)   # switch to conditioned
    levels_after = (dut.raw_fifo.level, dut.cond_fifo.level, dut.cond.count)
    res["H"] = {
        "levels_before": list(levels_before),
        "levels_after": list(levels_after),
        "ok": levels_before != (0, 0, 0) and levels_after == (0, 0, 0),
    }
    note(f"H mode-switch flush: before={levels_before} after={levels_after}")

    return res, log


def build_report(res: dict, seed: int, long_run: int) -> str:
    lines: list[str] = []
    a = lines.append
    a("## Configuration")
    a("")
    a(f"- DUT: `digital/model/digital_top.py` at `C_RCT` = {C_RCT}, `C_APT` = {C_APT}, "
      f"`W` = {W_APT}, start-up = {STARTUP_SAMPLES} samples, `K` = 8 ({COND_BLOCK_BITS} raw bits/word)")
    a(f"- cutoffs evaluated at `H` = {H_DESIGN} (design target -- **provisional**, no sky130 `H` measured yet, issue #21)")
    a(f"- sample clock: {RAW_RATE_BPS:,.0f} Hz (DR-0003's measured operating point), used only to convert sample counts to time")
    a(f"- stimulus: **declared synthetic** sources, `random.Random({seed})` and derived streams")
    a("")
    a("## Results")
    a("")
    a("| Experiment | Property under test | Result |")
    a("|---|---|---|")
    a(f"| A | healthy source: start-up completes at exactly {STARTUP_SAMPLES} samples, then one conditioned word per {COND_BLOCK_BITS} raw bits | "
      f"{'**PASS**' if res['A']['ok'] else '**FAIL**'} -- start-up at {res['A']['startup_done_at']}, "
      f"{res['A']['cond_words_pushed']}/{res['A']['expected_cond_words']} conditioned words, "
      f"{res['A']['raw_words_pushed']}/{res['A']['expected_raw_words']} raw words, no alarm |")
    a(f"| B | stuck-at-1 source trips the RCT at exactly `C_RCT` = {C_RCT} samples | "
      f"{'**PASS**' if res['B']['ok'] else '**FAIL**'} -- tripped at sample {res['B']['trip_at']} "
      f"({res['B']['detection_latency_ms']:.2f} ms at 50 kbps) |")
    a(f"| C | strongly biased source (`p` = {res['C']['bias']}, RCT runs suppressed) trips the **APT**, on a window boundary | "
      f"{'**PASS**' if res['C']['ok'] else '**FAIL**'} -- tripped at sample {res['C']['trip_at']}, ALARM = 0x{res['C']['alarm_word']:x} (APT bit only) |")
    a(f"| D | moderately biased source (`p` = {res['D']['bias']}, `H` = {res['D']['h_of_source']:.3f}) does not trip over {res['D']['windows']} windows | "
      f"{'**PASS**' if res['D']['ok'] else '**FAIL**'} -- {'no trip' if not res['D']['tripped'] else f'tripped at {res[chr(39)+chr(39)]}'} |")
    a(f"| E | {res['E']['samples']:,} healthy samples ({res['E']['windows']} APT windows, "
      f"{res['E']['wall_clock_equivalent_s']:.1f} s of real time at 50 kbps) raise no alarm | "
      f"{'**PASS**' if res['E']['ok'] else '**FAIL**'} -- {res['E']['alarms']} alarms |")
    a(f"| F | the **raw** path is readable while the conditioned path is gated | "
      f"{'**PASS**' if res['F']['ok'] else '**FAIL**'} -- gated = {res['F']['gated']}, "
      f"{res['F']['raw_words_readable_while_gated']} raw words read, `DATA` returns 0x{res['F']['data_read_while_gated']:x} |")
    a(f"| G | latch-and-gate: ungating requires **both** a cleared alarm and a passed start-up test, neither alone | "
      f"{'**PASS**' if res['G']['ok'] else '**FAIL**'} -- acknowledged {STARTUP_SAMPLES - 1} samples in: still gated; "
      f"gate lifts on the {STARTUP_SAMPLES}th. After a second trip the start-up test passes again but the latched "
      f"alarm holds the gate until write-1-to-clear |")
    a(f"| H | an `OUT_MODE` switch flushes the conditioner and **both** FIFOs | "
      f"{'**PASS**' if res['H']['ok'] else '**FAIL**'} -- (raw, cond, partial-block) went "
      f"{tuple(res['H']['levels_before'])} -> {tuple(res['H']['levels_after'])} |")
    a("")
    a("## Notes on what each experiment is and is not")
    a("")
    a("- **B and C are logic checks, not entropy measurements.** They confirm")
    a("  the tests fire where the formulas say they should on a source")
    a("  constructed to fail; they say nothing about whether sky130's real")
    a("  entropy source would pass.")
    a("- **E is a floor under the false-alarm argument, not a verification of")
    a(f"  it.** {res['E']['samples']:,} samples is ~2^{math.log2(res['E']['samples']):.1f} -- vanishingly")
    a("  small against a per-sample false-alarm probability of 2^-40, so this")
    a("  run could not have observed a legitimate false alarm. It would have")
    a("  caught a gross implementation error (an off-by-one cutoff, a")
    a("  mis-sized window) that made the tests fire orders of magnitude too")
    a("  often, which is what it is for.")
    a("- **D's source is below the design's own `H` target** (`H` = 0.415 vs the")
    a("  0.5 target) and is still not caught, which is the honest behaviour of")
    a("  an SP 800-90B health test: it detects catastrophic failure, not")
    a("  gradual entropy loss. That is a property of the standard's test")
    a("  design, and it is why the block's entropy claim rests on the source")
    a("  model and (eventually) measured silicon, not on the health tests.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--long-run", type=int, default=1_000_000,
                    help="sample count for experiment E")
    ap.add_argument("--emit-record", action="store_true")
    args = ap.parse_args(argv)

    res, log = experiments(args.seed, args.long_run)
    body = build_report(res, args.seed, args.long_run)
    print(body)

    ok = all(v.get("ok") for v in res.values())
    if not ok:
        print("\nCAMPAIGN FAILED", file=sys.stderr)

    if args.emit_record:
        artifact = Path(tempfile.gettempdir()) / "digital-section-campaign-events.txt"
        artifact.write_text("\n".join(log) + "\n")
        mint_behavioral_record(
            repo_root=REPO_ROOT,
            slug="digital-section-behavioral",
            claim=("the assembled digital section's health tests, start-up "
                   "gate, latch-and-gate failure policy, raw-path invariant "
                   "and mode-switch flush behave as DR-0004 specifies, over "
                   "declared synthetic sources"),
            body_md=body,
            summary={"ok": ok, "seed": args.seed, "long_run": args.long_run,
                     "experiments": res},
            level="behavioral",
            seeds={"python_random": args.seed,
                   "derived_streams": [args.seed + i for i in range(1, 6)]},
            artifacts=[artifact],
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
