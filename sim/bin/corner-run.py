#!/usr/bin/env python3
"""PVT corner runner for sim/ ngspice testbenches.

    sim/bin/corner-run.py --print-env
    sim/bin/corner-run.py \\
        sim/ro-stage-noise-mechanism-check/testbench/tb_ro_stage_noise.spice \\
        --slug ro-stage-noise-mechanism-check \\
        --claim "spec/decision-records/DR-0001 mechanism check: .noise on ro_stage" \\
        --corners tt,ss,ff

Adapted from the sibling repo `2AMLogic/sky130-bandgap`'s
`sim/bin/corner-run.py` (same PDK-resolution order, same
``<YYYYMMDD>-<HHMMSS>-<shortsha>`` record-id scheme, same append-only
refuse-to-overwrite discipline) for this repo's simpler netlist layout:
sky130-bandgap netlists an xschem testbench sheet through xschem itself on
every run, where this repo's ``design/netlist.py`` already produces
committed, ``--check``-guarded ``.include``-style subcircuit libraries
(``design/*.spice``) ahead of time -- see ``design/README.md`` §
"Regenerating the netlists". So this runner has no xschem step: it takes an
already-authored ngspice deck **template** (placeholders below), substitutes
the resolved PDK library + requested corner into it, and drives ngspice
directly.

Template placeholders a testbench may use (see
``sim/ro-stage-noise-mechanism-check/testbench/tb_ro_stage_noise.spice`` for
a worked example):

``@@PDK_LIB@@``
    Absolute path to the pinned sky130 combined ngspice corner library
    (``sim/pdk.json``'s ``ngspice_lib``, resolved under the located PDK).
``@@CORNER@@``
    The process-corner section name being run (``tt``/``ss``/``ff``/...).
``@@RO_RING5@@``
    Absolute path to the committed ``design/ro_ring5.spice`` -- the
    ``.include``-style library this repo's testbenches draw device
    subcircuits from. Substituted unconditionally; a testbench that does
    not reference it simply never uses the token.
``@@OUT_ONOISE@@``
    Per-(record, corner) scratch path a deck can ``wrdata`` an
    ``onoise_spectrum`` trace to. If present in the template, the runner
    reads it back after the run and records a spread check (max/min ratio)
    confirming the trace is neither flat nor degenerate -- the "not zero,
    not NaN, not flat" acceptance bar issue #9 sets for the mechanism
    check.
``@@TEMP@@`` / ``@@VDD@@``
    The temperature (degC, ``--temp``, default 27.0) / supply (V, ``--vdd``,
    default 1.8) axes of the {process x temp x supply} PVT grid -- issue #9's
    ``@@CORNER@@`` covers the process axis only. A testbench references
    these to build ``.temp @@TEMP@@`` / a supply source at ``@@VDD@@`` and
    sweep the other two PVT axes across separate runner invocations (one
    process-corner *bundle* per (temp, vdd) point, matching how ``--corners``
    already bundles the process axis into one record). Always recorded in
    the record's own PVT point even for a testbench that does not reference
    either token, so every record states what temperature/supply it ran at.
``@@SEED@@``
    ``--seed``'s value, for a stochastic (``tran-noise``) testbench that
    writes ``.option seed=@@SEED@@`` itself. A deterministic ``.noise``/
    ``.tf`` deck never references this token, in which case ``--seed``'s
    default (a descriptive "N/A..." string, not a number) only ever reaches
    the record's own ``Seed`` field, never a netlist.

Any ``NAME = VALUE`` line ngspice's own ``print`` command writes to stdout
(e.g. ``v(a) = 7.681062e-01``, ``onoise_total = 3.712448e-03``) is captured
as a named measurement and checked for being a finite, parseable number --
this is what "not NaN" actually verifies, deck-generically, without this
script needing to know what any particular deck is measuring.

Exit status: ``0`` all requested corners passed and a record was written,
``2`` a record was written but at least one corner failed its checks,
``1`` harness/setup error (no record written).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SIM_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SIM_DIR.parent
PDK_PIN_FILE = SIM_DIR / "pdk.json"
DEFAULT_RO_RING5 = REPO_ROOT / "design" / "ro_ring5.spice"

MEASUREMENT_RE = re.compile(
    r"^\s*([A-Za-z_][\w().]*)\s*=\s*([+-]?[0-9][0-9.eE+\-]*)\s*$"
)


class HarnessError(RuntimeError):
    """A problem the operator has to fix; never produces a record."""


# --------------------------------------------------------------------------
# PDK resolution -- mirrors design/netlist.py's find_pdk(), reading
# sim/pdk.json (and the git-ignored sim/pdk.local.json override) instead of
# design/pdk.json, per issue #9's own test-plan requirement that this
# harness resolve the PDK the same way: env var -> PDK_ROOT/PDK ->
# sim/pdk.json -> built-in search roots.
# --------------------------------------------------------------------------

BUILTIN_SEARCH_ROOTS = (
    "~/.volare",
    "~/.ciel",
    "/usr/share/pdk",
    "/usr/local/share/pdk",
    "~/share/pdk",
    "/opt/pdk",
)


@dataclass(frozen=True)
class Pdk:
    pin: dict
    path: Path  # .../sky130A
    variant: str
    source: str  # how it was found, for provenance
    lib_file: Path

    @property
    def installed_commit(self) -> str:
        sources = self.path / "SOURCES"
        if sources.is_file():
            for line in sources.read_text().splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "open_pdks":
                    return parts[1]
        return "unknown"

    @property
    def matches_pin(self) -> bool:
        return self.installed_commit == self.pin["open_pdks_commit"]


def load_pin() -> dict:
    if not PDK_PIN_FILE.exists():
        raise HarnessError(f"missing PDK pin file: {PDK_PIN_FILE}")
    try:
        return json.loads(PDK_PIN_FILE.read_text())
    except json.JSONDecodeError as exc:
        raise HarnessError(f"{PDK_PIN_FILE} is not valid JSON: {exc}") from exc


def _is_variant_dir(path: Path) -> bool:
    return (path / "libs.tech" / "combined").is_dir()


def volare_path() -> Path | None:
    exe = shutil.which("volare")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "path"], capture_output=True, text=True, timeout=60, check=True
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return None
    return Path(out) if out else None


def resolve_pdk(pin: dict) -> Pdk:
    """Locate a sky130 install. First hit wins, matching design/netlist.py:

    1. ``SKY130_PDK_PATH`` -- absolute path to the *variant* directory.
    2. ``PDK_ROOT`` (+ ``PDK``) -- the conventional open_pdks environment.
    3. ``sim/pdk.local.json`` -- machine-local override, git-ignored.
    4. ``sim/pdk.json`` (already loaded as *pin*) -- committed defaults.
    5. ``volare path`` / built-in search roots.
    """
    local_file = SIM_DIR / "pdk.local.json"
    local: dict = {}
    if local_file.is_file():
        try:
            local = json.loads(local_file.read_text())
        except json.JSONDecodeError as exc:
            raise HarnessError(f"{local_file} is not valid JSON: {exc}") from exc

    variant = os.environ.get("PDK") or local.get("variant") or pin["variant"]

    explicit = os.environ.get("SKY130_PDK_PATH")
    if explicit:
        path = Path(explicit).expanduser().resolve()
        if not _is_variant_dir(path):
            raise HarnessError(
                f"SKY130_PDK_PATH={explicit} has no libs.tech/combined directory"
            )
        return _make_pdk(pin, path, path.name, "SKY130_PDK_PATH")

    pdk_root = os.environ.get("PDK_ROOT")
    if pdk_root:
        path = (Path(pdk_root).expanduser() / variant).resolve()
        if _is_variant_dir(path):
            return _make_pdk(pin, path, variant, "PDK_ROOT")

    roots = list(local.get("search_roots") or ())
    roots += list(pin.get("search_roots") or ())
    vp = volare_path()
    if vp:
        roots.append(str(vp))
    roots += [pin.get("default_pdk_root", "~/.volare")]
    roots += list(BUILTIN_SEARCH_ROOTS)
    for root in roots:
        path = (Path(root).expanduser() / variant).resolve()
        if _is_variant_dir(path):
            return _make_pdk(pin, path, variant, str(root))

    raise HarnessError(
        "sky130 PDK not found.\n"
        f"  install the pinned version with: {pin['install_command']}\n"
        "  (or set SKY130_PDK_PATH / PDK_ROOT+PDK to an existing install)"
    )


def _make_pdk(pin: dict, path: Path, variant: str, source: str) -> Pdk:
    lib_file = path / pin["ngspice_lib"]
    if not lib_file.is_file():
        raise HarnessError(f"no ngspice model library at {lib_file}")
    return Pdk(pin=pin, path=path, variant=variant, source=source, lib_file=lib_file)


def print_env(pdk: Pdk) -> None:
    print(f"export PDK_ROOT={pdk.path.parent}")
    print(f"export PDK={pdk.variant}")
    print(f"export SKY130_NGSPICE_LIB={pdk.lib_file}")


# --------------------------------------------------------------------------
# tool / repo provenance
# --------------------------------------------------------------------------


def first_line(cmd: list[str]) -> str:
    """First non-decorative line of *cmd*'s output.

    ngspice's own ``--version`` banner opens with a bare ``******`` divider
    line before the actual ``** ngspice-47 : ...`` version line, so "first
    line" has to skip pure-punctuation banner lines rather than always
    taking line 0.
    """
    exe = shutil.which(cmd[0])
    if not exe:
        return "not found"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError) as exc:  # pragma: no cover
        return f"error: {exc}"
    text = (proc.stdout or proc.stderr).strip()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and stripped.strip("*").strip():
            return stripped
    return "unknown"


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=30
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def repo_state() -> dict:
    sha = git("rev-parse", "--short", "HEAD") or "unknown"
    branch = git("rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    dirty = bool(git("status", "--porcelain"))
    return {"sha": sha, "branch": branch, "dirty": dirty}


def default_author() -> str:
    return git("config", "user.email") or os.environ.get("USER", "unknown")


# --------------------------------------------------------------------------
# one corner's ngspice run
# --------------------------------------------------------------------------

PLACEHOLDER_RE = re.compile(r"@@([A-Z0-9_]+)@@")


@dataclass
class CornerResult:
    corner: str
    ok: bool
    returncode: int
    deck_path: Path
    log_path: Path
    measurements: dict[str, float] = field(default_factory=dict)
    onoise_spread: float | None = None
    onoise_min: float | None = None
    onoise_max: float | None = None
    problems: list[str] = field(default_factory=list)


def render_deck(template_text: str, substitutions: dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key not in substitutions:
            raise HarnessError(
                f"testbench references @@{key}@@ with no substitution provided "
                f"(known: {', '.join(sorted(substitutions))})"
            )
        return substitutions[key]

    return PLACEHOLDER_RE.sub(repl, template_text)


def parse_measurements(stdout: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in stdout.splitlines():
        m = MEASUREMENT_RE.match(line)
        if not m:
            continue
        name, value = m.group(1), m.group(2)
        try:
            out[name] = float(value)
        except ValueError:
            out[name] = float("nan")
    return out


def spread(values: list[float]) -> tuple[float, float, float] | None:
    """(min, max, max/min) over positive finite values, or None."""
    finite = [v for v in values if v == v and v not in (float("inf"), float("-inf"))]
    positive = [v for v in finite if v > 0]
    if not positive:
        return None
    lo, hi = min(positive), max(positive)
    ratio = hi / lo if lo > 0 else float("inf")
    return lo, hi, ratio


def run_corner(
    *,
    corner: str,
    template_text: str,
    pdk: Pdk,
    ro_ring5: Path,
    scratch_dir: Path,
    ngspice_exe: str,
    timeout: int,
    not_flat_ratio_min: float,
    temp_c: float,
    vdd_v: float,
    seed: str,
) -> CornerResult:
    scratch_dir.mkdir(parents=True, exist_ok=True)
    onoise_path = scratch_dir / f"{corner}.onoise.txt"
    substitutions = {
        "PDK_LIB": str(pdk.lib_file),
        "CORNER": corner,
        "RO_RING5": str(ro_ring5),
        "OUT_ONOISE": str(onoise_path),
        # Temperature/supply axis, added for issue #10's PVT-grid jitter
        # characterization campaign: sim/bin/corner-run.py's process-only
        # @@CORNER@@ substitution (issue #9 scope) covers one axis of the
        # {process x temp x supply} grid sim/README.md's "PVT grid" section
        # documents; a testbench that also sweeps temperature/supply
        # references these two tokens and gets them from --temp/--vdd
        # (defaults: 27 C / 1.8 V, sky130-trng's nominal 1.8 V core point).
        "TEMP": str(temp_c),
        "VDD": str(vdd_v),
        # Only meaningful for a stochastic (tran-noise) testbench that
        # itself writes `.option seed=@@SEED@@` -- a deterministic .noise/
        # .tf deck simply never references this token. Falls back to
        # whatever --seed was passed (default: the descriptive "N/A..."
        # text used for the record's own Seed field, which no numeric
        # `.option seed=` line should ever be built from -- a testbench
        # that references @@SEED@@ must be invoked with a real --seed).
        "SEED": str(seed),
    }
    deck_text = render_deck(template_text, substitutions)
    deck_path = scratch_dir / f"{corner}.spice"
    deck_path.write_text(deck_text)

    log_path = scratch_dir / f"{corner}.log"
    problems: list[str] = []
    try:
        proc = subprocess.run(
            [ngspice_exe, "-b", str(deck_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=scratch_dir,
        )
    except subprocess.TimeoutExpired:
        log_path.write_text(f"|{deck_text}\n\nTIMEOUT after {timeout}s\n")
        return CornerResult(
            corner=corner,
            ok=False,
            returncode=-1,
            deck_path=deck_path,
            log_path=log_path,
            problems=[f"ngspice timed out after {timeout}s"],
        )

    log_path.write_text(
        "|" + deck_text.replace("\n", "\n|") + "\n\n"
        "----- stdout -----\n" + proc.stdout + "\n"
        "----- stderr -----\n" + proc.stderr + "\n"
    )

    if proc.returncode != 0:
        problems.append(f"ngspice exited {proc.returncode}")

    measurements = parse_measurements(proc.stdout)
    if not measurements:
        problems.append("no 'name = value' measurements found in ngspice output")
    for name, value in measurements.items():
        if value != value:  # NaN
            problems.append(f"measurement {name} is NaN")

    onoise_min = onoise_max = onoise_ratio = None
    if onoise_path.is_file():
        values = []
        for line in onoise_path.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                try:
                    values.append(float(parts[1]))
                except ValueError:
                    continue
        s = spread(values)
        if s is None:
            problems.append("onoise_spectrum trace has no positive finite samples")
        else:
            onoise_min, onoise_max, onoise_ratio = s
            if onoise_ratio < not_flat_ratio_min:
                problems.append(
                    f"onoise_spectrum spread ratio {onoise_ratio:.2f}x < "
                    f"{not_flat_ratio_min}x -- looks flat"
                )
    elif "@@OUT_ONOISE@@" in template_text:
        problems.append(f"expected onoise trace not written: {onoise_path}")

    result = CornerResult(
        corner=corner,
        ok=(proc.returncode == 0 and not problems),
        returncode=proc.returncode,
        deck_path=deck_path,
        log_path=log_path,
        measurements=measurements,
        onoise_spread=onoise_ratio,
        onoise_min=onoise_min,
        onoise_max=onoise_max,
        problems=problems,
    )
    return result


# --------------------------------------------------------------------------
# record writing
# --------------------------------------------------------------------------


def record_id() -> str:
    now = datetime.now(timezone.utc)
    sha = git("rev-parse", "--short", "HEAD") or "nogit"
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{sha}"


def write_record(
    *,
    rid: str,
    slug: str,
    claim: str,
    level: str,
    seed: str,
    testbench: Path,
    pdk: Pdk,
    results: list[CornerResult],
    author: str,
    subset_reason: str | None,
    supersedes: str | None,
    temp_c: float,
    vdd_v: float,
) -> tuple[Path, bool]:
    # Layout: sim/<slug>/{corners/<rid>/, records/<rid>.md, records/<rid>.json}
    # -- one directory per experiment slug, matching the sibling sky130-bandgap
    # repo's convention (and this repo's own pre-existing .gitignore rule,
    # `!sim/*/corners/**/*.log`, which already anticipates it).
    slug_dir = SIM_DIR / slug
    records_dir = slug_dir / "records"
    corners_dir = slug_dir / "corners" / rid
    record_md = records_dir / f"{rid}.md"
    record_json = records_dir / f"{rid}.json"
    if corners_dir.exists() or record_md.exists() or record_json.exists():
        raise HarnessError(
            f"record {rid} already exists under {slug_dir} -- refusing to overwrite"
        )
    corners_dir.mkdir(parents=True)
    records_dir.mkdir(parents=True, exist_ok=True)

    overall_ok = all(r.ok for r in results)
    state = repo_state()

    for r in results:
        (corners_dir / r.log_path.name).write_text(r.log_path.read_text())
        onoise_src = r.deck_path.parent / f"{r.corner}.onoise.txt"
        if onoise_src.is_file():
            (corners_dir / onoise_src.name).write_text(onoise_src.read_text())

    json_record = {
        "record_id": rid,
        "slug": slug,
        "claim": claim,
        "level": level,
        "seed": seed,
        "pvt": {"temp_c": temp_c, "vdd_v": vdd_v},
        "testbench": str(testbench.relative_to(REPO_ROOT)),
        "pdk": {
            "variant": pdk.variant,
            "installed_commit": pdk.installed_commit,
            "pin_commit": pdk.pin["open_pdks_commit"],
            "matches_pin": pdk.matches_pin,
            "lib_file": str(pdk.lib_file),
        },
        "tools": {
            "ngspice": first_line(["ngspice", "--version"]),
            "python": platform.python_version(),
            "os": platform.platform(),
        },
        "repo_state": state,
        "corners": [
            {
                "corner": r.corner,
                "ok": r.ok,
                "returncode": r.returncode,
                "measurements": r.measurements,
                "onoise_min": r.onoise_min,
                "onoise_max": r.onoise_max,
                "onoise_spread_ratio": r.onoise_spread,
                "problems": r.problems,
                "log": f"corners/{r.log_path.name}",
            }
            for r in results
        ],
        "overall": "PASS" if overall_ok else "FAIL",
        "subset_reason": subset_reason,
        "supersedes": supersedes or "(none)",
        "author": author,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
    }
    record_json.write_text(json.dumps(json_record, indent=2) + "\n")

    lines = [
        f"# {rid} -- {slug}",
        "",
        f"**Claim**: {claim}",
        "",
        f"**Level**: {level}",
        f"**Seed**: {seed}",
        f"**PVT point**: {temp_c:g} degC, {vdd_v:g} V supply (process axis per-corner below)",
        f"**Testbench**: `{testbench.relative_to(REPO_ROOT)}`",
        "",
        "## PDK",
        "",
        f"- variant: `{pdk.variant}`",
        f"- installed open_pdks commit: `{pdk.installed_commit}`",
        f"- pinned open_pdks commit (`sim/pdk.json`): `{pdk.pin['open_pdks_commit']}`",
        f"- matches pin: {'yes' if pdk.matches_pin else '**NO -- record run against a mismatched PDK**'}",
        f"- ngspice model library: `{pdk.lib_file}`",
        "",
        "## Tools",
        "",
        f"- ngspice: {first_line(['ngspice', '--version'])}",
        f"- python: {platform.python_version()}",
        f"- OS: {platform.platform()}",
        "",
        "## Repo state",
        "",
        f"- commit: `{state['sha']}`{' (dirty working tree)' if state['dirty'] else ''}",
        f"- branch: `{state['branch']}`",
        "",
        "## Corner matrix run",
        "",
        "| Corner | Verdict | Measurements | onoise spread (max/min) | Problems |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        meas = ", ".join(f"{k}={v:.6g}" for k, v in sorted(r.measurements.items()))
        spread_txt = f"{r.onoise_spread:.2f}x" if r.onoise_spread is not None else "n/a"
        problems_txt = "; ".join(r.problems) if r.problems else "(none)"
        lines.append(
            f"| `{r.corner}` | {'PASS' if r.ok else 'FAIL'} | {meas} | {spread_txt} | {problems_txt} |"
        )
    lines += [
        "",
        f"## Result: **{'PASS' if overall_ok else 'FAIL'}**",
        "",
        (
            "Overall verdict is PASS only if every corner above individually "
            "passed (ngspice exited 0, every parsed `name = value` "
            "measurement was a finite number, and -- where the deck writes "
            "an `onoise_spectrum` trace -- its max/min ratio cleared the "
            "not-flat threshold)."
        ),
        "",
        "## Links",
        "",
        f"- Testbench: `{testbench.relative_to(REPO_ROOT)}`",
        "- Runner: `sim/bin/corner-run.py`",
        f"- Raw per-corner logs: `sim/{slug}/corners/{rid}/`",
        f"- JSON record: `sim/{slug}/records/{rid}.json`",
        "",
        f"- Author: {author}",
        f"- Timestamp (UTC): {json_record['timestamp_utc']}",
        f"- Subset reason: {subset_reason or '(full requested corner set run)'}",
        f"- Supersedes: {supersedes or '(none)'}",
        "",
    ]
    record_md.write_text("\n".join(lines))

    return records_dir, overall_ok


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "testbench",
        nargs="?",
        type=Path,
        help="ngspice deck template (see module docstring for placeholders)",
    )
    parser.add_argument(
        "--corners",
        default=None,
        help="comma-separated corner list (default: sim/pdk.json default_corners)",
    )
    parser.add_argument(
        "--slug",
        default=None,
        help="record slug (required unless --print-env/--dry-run)",
    )
    parser.add_argument(
        "--claim",
        default=None,
        help="one-line claim this record substantiates (required unless --print-env/--dry-run)",
    )
    parser.add_argument(
        "--level",
        default="transistor",
        choices=["transistor", "behavioral", "gate", "gate-simulation"],
    )
    parser.add_argument(
        "--seed",
        default="N/A (deterministic small-signal .noise analysis, not Monte Carlo)",
    )
    parser.add_argument(
        "--ro-ring5",
        type=Path,
        default=DEFAULT_RO_RING5,
        help="path substituted for @@RO_RING5@@",
    )
    parser.add_argument(
        "--temp",
        type=float,
        default=27.0,
        help="temperature (degC) substituted for @@TEMP@@; also recorded as the "
        "record's PVT point even if the testbench does not reference @@TEMP@@",
    )
    parser.add_argument(
        "--vdd",
        type=float,
        default=1.8,
        help="supply (V) substituted for @@VDD@@; also recorded as the record's "
        "PVT point even if the testbench does not reference @@VDD@@ (default: "
        "1.8 V, sky130-trng's nominal 1.8 V core supply)",
    )
    parser.add_argument(
        "--not-flat-ratio-min",
        type=float,
        default=5.0,
        help="min max/min ratio for an onoise trace to count as 'not flat'",
    )
    parser.add_argument("--author", default=None)
    parser.add_argument(
        "--timeout", type=int, default=120, help="per-corner ngspice timeout, seconds"
    )
    parser.add_argument(
        "--subset-reason",
        default=None,
        help="required if --corners is a subset of sim/pdk.json's default_corners",
    )
    parser.add_argument(
        "--supersedes", default=None, help="record id this run corrects/replaces"
    )
    parser.add_argument("--allow-pdk-mismatch", action="store_true")
    parser.add_argument("--print-env", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="resolve PDK + render corner 0's deck, print it, write nothing",
    )
    args = parser.parse_args(argv)

    try:
        pin = load_pin()
        pdk = resolve_pdk(pin)
    except HarnessError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.print_env:
        print_env(pdk)
        return 0

    if not pdk.matches_pin and not args.allow_pdk_mismatch:
        print(
            f"error: installed PDK ({pdk.installed_commit}) does not match "
            f"sim/pdk.json's pin ({pdk.pin['open_pdks_commit']}). "
            "Pass --allow-pdk-mismatch to run anyway (the record will flag it).",
            file=sys.stderr,
        )
        return 1

    if args.testbench is None:
        print(
            "error: a testbench template path is required (see --help)", file=sys.stderr
        )
        return 1
    args.testbench = args.testbench.resolve()
    if not args.testbench.is_file():
        print(f"error: no such testbench: {args.testbench}", file=sys.stderr)
        return 1
    args.ro_ring5 = args.ro_ring5.resolve()

    default_corners = pin.get("default_corners") or ["tt", "ss", "ff"]
    requested = (
        [c.strip() for c in args.corners.split(",")]
        if args.corners
        else list(default_corners)
    )
    unknown = [c for c in requested if c not in pin.get("process_corners", [])]
    if unknown:
        print(
            f"error: corner(s) not in sim/pdk.json process_corners: {', '.join(unknown)}",
            file=sys.stderr,
        )
        return 1

    is_subset = set(requested) < set(default_corners)
    if is_subset and not args.subset_reason:
        print(
            "error: --corners is a subset of the default set; --subset-reason is required",
            file=sys.stderr,
        )
        return 1

    ngspice_exe = shutil.which("ngspice")
    if not ngspice_exe:
        print("error: ngspice not found on PATH", file=sys.stderr)
        return 1

    template_text = args.testbench.read_text()

    if args.dry_run:
        deck = render_deck(
            template_text,
            {
                "PDK_LIB": str(pdk.lib_file),
                "CORNER": requested[0],
                "RO_RING5": str(args.ro_ring5),
                "OUT_ONOISE": "/tmp/dry-run-onoise.txt",
                "TEMP": str(args.temp),
                "VDD": str(args.vdd),
                "SEED": str(args.seed),
            },
        )
        print(f"# corners: {', '.join(requested)}")
        print(deck)
        return 0

    if not args.slug or not args.claim:
        print("error: --slug and --claim are required for a real run", file=sys.stderr)
        return 1

    rid = record_id()
    scratch_root = tempfile.mkdtemp(prefix=f"sim-corner-run-{rid}-")
    scratch_dir = Path(scratch_root)
    results = []
    for corner in requested:
        results.append(
            run_corner(
                corner=corner,
                template_text=template_text,
                pdk=pdk,
                ro_ring5=args.ro_ring5,
                scratch_dir=scratch_dir,
                ngspice_exe=ngspice_exe,
                timeout=args.timeout,
                not_flat_ratio_min=args.not_flat_ratio_min,
                temp_c=args.temp,
                vdd_v=args.vdd,
                seed=args.seed,
            )
        )

    author = args.author or default_author()
    try:
        records_dir, overall_ok = write_record(
            rid=rid,
            slug=args.slug,
            claim=args.claim,
            level=args.level,
            seed=args.seed,
            testbench=args.testbench,
            pdk=pdk,
            results=results,
            author=author,
            subset_reason=args.subset_reason,
            supersedes=args.supersedes,
            temp_c=args.temp,
            vdd_v=args.vdd,
        )
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    print(f"record written: {(records_dir / f'{rid}.md').relative_to(REPO_ROOT)}")
    for r in results:
        print(
            f"  {r.corner}: {'PASS' if r.ok else 'FAIL'}"
            + (f" -- {'; '.join(r.problems)}" if r.problems else "")
        )
    print(f"overall: {'PASS' if overall_ok else 'FAIL'}")

    return 0 if overall_ok else 2


if __name__ == "__main__":
    sys.exit(main())
