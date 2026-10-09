#!/usr/bin/env python3
"""Guard: every tracked ``test_*.py`` is actually executed by CI (issue #230).

Run it directly, standard library only, no xschem / ngspice / PDK::

    python3 design/test_ci_test_coverage.py

Why this exists
---------------
Unit tests here are wired into CI by hand, one ``run:`` step per file, and
the omission has happened twice: issue #190 wired tests that "nothing ran",
and issue #217 then found two more that #190's list had missed. A test that
exists but never runs is a silent hole in the evidence chain, so this guard
makes the omission mechanical to catch instead of reactive.

The contract it enforces
------------------------
For every tracked file whose basename matches ``test_*.py`` (``git ls-files``):

* **PR coverage** -- a real ``python3 <repo-relative path>`` command inside a
  ``run:`` step of an unconditional job in ``.github/workflows/ci.yml``
  (PR-blocking), AND the path matches one of ci.yml's positive
  ``on.pull_request.paths`` patterns, so editing the test triggers the job;
* or **nightly coverage** -- the same kind of command in
  ``.github/workflows/pdk-nightly.yml``, with that workflow keeping its
  ``schedule`` (cron) and ``workflow_dispatch`` triggers and the executing
  job's ``if:`` keeping both events eligible (the opt-in ``run-pdk-check``
  PR gate is left alone; no PR paths list is required there);
* or an **exact, justified exemption** in ``EXEMPTIONS`` below.

Additionally, this guard itself must be PR-covered, and ci.yml's PR filters
must match this file and BOTH workflow files, so a wiring edit re-runs the
check even though the nightly stays opt-in on PRs.

What counts as "executed" -- a bounded scanner, not a YAML/shell parser
-----------------------------------------------------------------------
* Only ``run:`` values of job steps are read: plain or quoted scalars and
  ``|`` / ``>`` block scalars (with ``-``/``+`` chomping). YAML comments,
  step names, ``with:`` inputs etc. never count.
* Inside a run script, shell comments are stripped (bash rule: ``#`` at the
  start of a word, outside quotes), the script is tokenised with ``shlex``
  and split into simple commands on ``; && || | & ( )`` and newlines. Only a
  command whose word is ``python``/``python3``/``python3.N`` (after leading
  ``VAR=value`` assignments) counts; its first non-option argument is the
  script, normalised (``./`` stripped) and compared to the FULL repo-relative
  path -- never a basename or substring. ``echo`` strings therefore never
  count, and ``sim/tests/test_x_extra.py`` is not ``sim/tests/test_x.py``.
* Discovery/indirect runners (``pytest``, ``python3 -m pytest|unittest``)
  and non-literal script arguments (``python3 "$t"``, globs) count only
  through an explicit ``INDIRECT_RUNNERS`` entry; otherwise they are
  reported as unsupported. So are heredocs, ``cd`` before a test command,
  ``working-directory``, non-sh ``shell:``, YAML anchors/aliases/tags, flow
  collections where a list is required, explicit block-indentation
  indicators, unterminated quotes, and filter negation / ``paths-ignore`` /
  bracket, brace or ``+`` glob syntax. Unsupported relevant syntax fails
  closed with a diagnostic rather than being guessed at.
* Path-filter globs support the subset this repo uses: literal paths, ``*``
  and ``?`` (never across ``/``), and ``**`` (across ``/``).

The fixture-based controls below exercise both directions -- each defect
must fail naming itself, and each supported form must pass -- using
injected inventory/workflow text only (no dummy tracked files, no edits to
the production workflows).
"""

from __future__ import annotations

import posixpath
import re
import shlex
import subprocess
import sys
import unittest
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

CI_WORKFLOW = ".github/workflows/ci.yml"
NIGHTLY_WORKFLOW = ".github/workflows/pdk-nightly.yml"
GUARD_PATH = "design/test_ci_test_coverage.py"

# ---------------------------------------------------------------------------
# Reviewed exemptions: EXACT tracked file paths only (no globs, no
# directories). An entry that is no longer tracked, or that has gained real
# execution coverage, is reported as stale -- remove it when that happens.
# Standalone stdlib tests must never be added here to make the guard pass;
# wire them into ci.yml instead.
# ---------------------------------------------------------------------------
EXEMPTIONS: dict[str, str] = {
    "digital/tb/cocotb/test_trng_digital_fv.py": (
        "cocotb 2.0 testbench, not a standalone script: it only runs inside "
        "an HDL simulation launched by `klt functional-verification` (cocotb "
        "+ an HDL simulator). Neither ci.yml nor pdk-nightly.yml provisions "
        "that runner, so it has NO CI execution today; adding simulator CI is "
        "out of scope for issue #230 and must be its own change."
    ),
}

# ---------------------------------------------------------------------------
# Explicit mapping for discovery/indirect runners. Key: (workflow path, the
# command's tokens joined by single spaces, e.g. "python3 -m pytest sim/tests").
# Value: the exact tracked test paths that command is known to execute.
# Empty on purpose: every test in this repo is a direct `python3 <path>` step.
# A mapping whose command is no longer present in its workflow is stale.
# ---------------------------------------------------------------------------
INDIRECT_RUNNERS: dict[tuple[str, str], tuple[str, ...]] = {}

ADD_STEP_HINT = (
    "add a step `run: python3 {path}` to the `lint` job in "
    f"{CI_WORKFLOW} (PR-blocking) -- or, for a PDK-gated test, to a "
    f"scheduled job in {NIGHTLY_WORKFLOW} -- and make sure one of ci.yml's "
    "`on.pull_request.paths` patterns matches it"
)


class Unsupported(Exception):
    """Workflow syntax this bounded scanner deliberately does not interpret."""


# ===========================================================================
# Minimal block-YAML reader (the subset GitHub workflow files here use)
# ===========================================================================


@dataclass
class Scalar:
    text: str
    line: int
    style: str  # plain | single | double | literal | folded | flow


@dataclass
class _Tok:
    indent: int  # column of the key (or of the scalar for a bare list item)
    line: int
    dash: bool
    dash_col: int
    key: str | None
    value: Scalar | None


_KEY_RE = re.compile(
    r"""^(?P<key>"[^"]*"|'[^']*'|[A-Za-z_][A-Za-z0-9_.\-]*)\s*:(?:\s+(?P<val>.*)|$)"""
)
_BLOCK_RE = re.compile(r"^([|>])([-+]?)$")


def _strip_yaml_comment(s: str) -> str:
    """Drop a trailing `` # comment`` that is outside quotes."""
    quote = None
    for i, ch in enumerate(s):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"" and (i == 0 or s[i - 1] in " \t:[,{"):
            quote = ch
        elif ch == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
    return s.rstrip()


def _decode_scalar(raw: str, line: int, where: str) -> Scalar:
    raw = raw.strip()
    if raw[:1] in ("&", "*", "!") or raw.startswith("<<"):
        raise Unsupported(f"{where}:{line}: YAML anchor/alias/tag `{raw}`")
    if raw[:1] == "'":
        if len(raw) < 2 or not raw.endswith("'"):
            raise Unsupported(f"{where}:{line}: unterminated or multi-line single-quoted scalar")
        return Scalar(raw[1:-1].replace("''", "'"), line, "single")
    if raw[:1] == '"':
        body = raw[1:-1]
        if len(raw) < 2 or not raw.endswith('"') or body.endswith("\\") and not body.endswith("\\\\"):
            raise Unsupported(f"{where}:{line}: unterminated or multi-line double-quoted scalar")
        out, i = [], 0
        while i < len(body):
            ch = body[i]
            if ch == "\\" and i + 1 < len(body):
                nxt = body[i + 1]
                out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/"}.get(nxt, "\\" + nxt))
                i += 2
                continue
            out.append(ch)
            i += 1
        return Scalar("".join(out), line, "double")
    if raw[:1] in ("[", "{"):
        return Scalar(raw, line, "flow")
    return Scalar(raw, line, "plain")


def _fold(lines: list[str]) -> str:
    """YAML folded-scalar folding (simplified, chomping ignored)."""
    out: list[str] = []
    prev_plain = False
    for ln in lines:
        if not ln.strip():
            out.append("\n")
            prev_plain = False
        elif ln[:1] in (" ", "\t"):
            out.append(("\n" if out and not out[-1].endswith("\n") else "") + ln + "\n")
            prev_plain = False
        else:
            out.append((" " if prev_plain else "") + ln)
            prev_plain = True
    return "".join(out)


def _tokenize(text: str, where: str) -> list[_Tok]:
    lines = text.splitlines()
    toks: list[_Tok] = []
    i = 0
    seen_doc = False
    while i < len(lines):
        raw = lines[i]
        lineno = i + 1
        i += 1
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise Unsupported(f"{where}:{lineno}: tab indentation")
        content = _strip_yaml_comment(raw)
        if not content.strip():
            continue
        if content.strip() in ("---", "..."):
            if seen_doc or toks:
                raise Unsupported(f"{where}:{lineno}: multiple YAML documents")
            seen_doc = True
            continue
        indent = len(content) - len(content.lstrip(" "))
        body = content[indent:]
        dash = False
        dash_col = indent
        if body == "-" or body.startswith("- "):
            dash = True
            rest = body[1:].lstrip(" ")
            indent = indent + (len(body) - len(rest))
            body = rest
            if not body:
                raise Unsupported(f"{where}:{lineno}: empty/nested list item form `-` alone")
        m = _KEY_RE.match(body)
        if m:
            key = m.group("key").strip("\"'")
            if key == "<<":
                raise Unsupported(f"{where}:{lineno}: YAML merge key")
            val_raw = (m.group("val") or "").strip()
            value: Scalar | None = None
            if val_raw:
                bm = _BLOCK_RE.match(val_raw)
                if val_raw[:1] in "|>" and not bm:
                    raise Unsupported(
                        f"{where}:{lineno}: block scalar header `{val_raw}` "
                        "(explicit indentation indicators are not supported)"
                    )
                if bm:
                    block: list[str] = []
                    while i < len(lines):
                        nxt = lines[i]
                        if nxt.strip() and len(nxt) - len(nxt.lstrip(" ")) <= indent:
                            break
                        block.append(nxt)
                        i += 1
                    while block and not block[-1].strip():
                        block.pop()
                    nonblank = [b for b in block if b.strip()]
                    base = min((len(b) - len(b.lstrip(" ")) for b in nonblank), default=0)
                    if nonblank and len(nonblank[0]) - len(nonblank[0].lstrip(" ")) != base:
                        raise Unsupported(
                            f"{where}:{lineno}: block scalar whose first line is "
                            "more indented than later lines"
                        )
                    dedented = [b[base:] if b.strip() else "" for b in block]
                    text_val = "\n".join(dedented) if bm.group(1) == "|" else _fold(dedented)
                    value = Scalar(text_val, lineno, "literal" if bm.group(1) == "|" else "folded")
                else:
                    value = _decode_scalar(val_raw, lineno, where)
            toks.append(_Tok(indent, lineno, dash, dash_col, key, value))
        else:
            if not dash:
                raise Unsupported(
                    f"{where}:{lineno}: line `{body}` is neither `key: value` nor a "
                    "list item (multi-line plain scalars are not supported)"
                )
            toks.append(_Tok(indent, lineno, True, dash_col, None, _decode_scalar(body, lineno, where)))
    return toks


class _Parser:
    def __init__(self, toks: list[_Tok], where: str):
        self.t = toks
        self.i = 0
        self.where = where

    def parse(self):
        if not self.t:
            return {}
        node = self._block(self.t[0].indent if not self.t[0].dash else self.t[0].dash_col)
        if self.i != len(self.t):
            raise Unsupported(f"{self.where}:{self.t[self.i].line}: unexpected indentation")
        return node

    def _block(self, ind: int):
        tok = self.t[self.i]
        if tok.dash and tok.dash_col == ind:
            return self._seq(ind)
        return self._map(ind)

    def _value_after(self, tok: _Tok, ind: int):
        if tok.value is not None:
            return tok.value
        if self.i < len(self.t):
            nxt = self.t[self.i]
            nxt_col = nxt.dash_col if nxt.dash else nxt.indent
            if nxt_col > ind or (nxt.dash and nxt.dash_col == ind):
                return self._block(nxt_col)
        return None

    def _map(self, ind: int) -> dict:
        out: dict = {}
        out["__line__"] = self.t[self.i].line
        while self.i < len(self.t):
            tok = self.t[self.i]
            if tok.dash or tok.indent != ind:
                if tok.indent > ind and not tok.dash:
                    raise Unsupported(f"{self.where}:{tok.line}: unexpected indentation")
                break
            if tok.key is None:
                raise Unsupported(f"{self.where}:{tok.line}: expected `key:`")
            self.i += 1
            if tok.key in out:
                raise Unsupported(f"{self.where}:{tok.line}: duplicate key `{tok.key}`")
            out[tok.key] = self._value_after(tok, ind)
        return out

    def _seq(self, ind: int) -> list:
        out: list = []
        while self.i < len(self.t):
            tok = self.t[self.i]
            if not (tok.dash and tok.dash_col == ind):
                break
            if tok.key is None:
                self.i += 1
                out.append(tok.value)
                continue
            # `- key: v` starts a mapping whose keys sit at tok.indent
            first = _Tok(tok.indent, tok.line, False, tok.indent, tok.key, tok.value)
            self.t[self.i] = first
            out.append(self._map(tok.indent))
        return out


def parse_yaml(text: str, where: str):
    return _Parser(_tokenize(text, where), where).parse()


# ===========================================================================
# Shell command extraction from a run: script
# ===========================================================================

_PY_RE = re.compile(r"^(?:.*/)?python(?:3(?:\.\d+)?)?$")
_PY_FLAGS_NOARG = set("bBdEhiIOPqsSuvVx")
_PY_FLAGS_ARG = set("WX")
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_NONLITERAL = re.compile(r"[$`*?\[\]~{}]")
# Shell reserved words / prefixes that may precede the command word.
_PREFIX_WORDS = {"if", "then", "elif", "else", "while", "until", "do", "!", "{", "time", "exec", "command"}


def _prepare_shell(script: str) -> str:
    """Strip bash comments and turn unquoted newlines into `;`."""
    out: list[str] = []
    quote = None
    i = 0
    n = len(script)
    while i < n:
        ch = script[i]
        if quote == "'":
            out.append(ch)
            if ch == "'":
                quote = None
        elif quote == '"':
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(script[i + 1])
                i += 1
            elif ch == '"':
                quote = None
        else:
            if ch == "\\" and i + 1 < n:
                if script[i + 1] == "\n":
                    out.append(" ")
                else:
                    out.append(ch + script[i + 1])
                i += 2
                continue
            if ch in "'\"":
                quote = ch
                out.append(ch)
            elif ch == "#" and (i == 0 or script[i - 1] in " \t\n;&|()"):
                while i < n and script[i] != "\n":
                    i += 1
                continue
            elif ch == "\n":
                out.append(" ; ")
            else:
                out.append(ch)
        i += 1
    if quote:
        raise Unsupported("unterminated shell quote")
    return "".join(out)


def shell_commands(script: str) -> list[list[str]]:
    """Split a run script into simple commands (lists of words)."""
    prepared = _prepare_shell(script)
    lex = shlex.shlex(prepared, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = ""
    try:
        tokens = list(lex)
    except ValueError as exc:
        raise Unsupported(f"shell tokenisation failed: {exc}") from None
    cmds: list[list[str]] = []
    cur: list[str] = []
    for tok in tokens:
        if tok and all(c in ";&|()<>" for c in tok):
            if "<<" in tok:
                raise Unsupported("heredoc (`<<`) in a run script")
            if tok in (">", ">>", "<", ">&", "<&", "&>", ">|"):
                cur.append(tok)  # redirection: stays part of the command
                continue
            if cur:
                cmds.append(cur)
            cur = []
        else:
            cur.append(tok)
    if cur:
        cmds.append(cur)
    return cmds


@dataclass
class PyCommand:
    kind: str  # script | indirect | inline | other
    script: str | None
    text: str


def classify(cmd: list[str]) -> PyCommand | None:
    """Classify one simple command; None if it is not a Python/pytest runner."""
    words = list(cmd)
    while words and (_ASSIGN_RE.match(words[0]) or words[0] in _PREFIX_WORDS):
        words.pop(0)
    if not words:
        return None
    text = " ".join(words)
    head = words[0]
    if posixpath.basename(head) in ("pytest", "py.test"):
        return PyCommand("indirect", None, text)
    if not _PY_RE.match(head):
        return None
    j = 1
    while j < len(words):
        w = words[j]
        if w in (">", ">>", "<", ">&", "<&", "&>", ">|"):
            return PyCommand("inline", None, text)  # `python3 < file`: stdin
        if w == "-":
            return PyCommand("inline", None, text)
        if w in ("--version", "--help", "-V", "-h"):
            return PyCommand("inline", None, text)
        if w.startswith("--"):
            raise Unsupported(f"unrecognised python option `{w}` in `{text}`")
        if w.startswith("-") and len(w) > 1:
            flags = w[1:]
            for k, f in enumerate(flags):
                if f == "c":
                    return PyCommand("inline", None, text)
                if f == "m":
                    mod = flags[k + 1:] or (words[j + 1] if j + 1 < len(words) else "")
                    if mod in ("pytest", "unittest"):
                        return PyCommand("indirect", None, text)
                    return PyCommand("other", None, text)
                if f in _PY_FLAGS_ARG:
                    if k == len(flags) - 1:
                        j += 1
                    break
                if f not in _PY_FLAGS_NOARG:
                    raise Unsupported(f"unrecognised python option `-{f}` in `{text}`")
            j += 1
            continue
        if _NONLITERAL.search(w):
            return PyCommand("indirect", None, text)
        path = posixpath.normpath(w)
        return PyCommand("script", path, text)
    return PyCommand("inline", None, text)  # bare `python3`: REPL/stdin


# ===========================================================================
# Workflow model and coverage analysis
# ===========================================================================


@dataclass
class Execution:
    workflow: str
    job: str
    line: int
    counted: bool
    why_not: str = ""


@dataclass
class WorkflowScan:
    path: str
    on: dict = field(default_factory=dict)
    executions: dict[str, list[Execution]] = field(default_factory=dict)
    indirect_seen: set[str] = field(default_factory=set)
    errors: list[str] = field(default_factory=list)


def _truthy(v) -> bool:
    return isinstance(v, Scalar) and v.text.strip().lower() not in ("false", "")


def _norm_expr(expr: str) -> str:
    e = " ".join(expr.split())
    if e.startswith("${{") and e.endswith("}}"):
        e = e[3:-2].strip()
    return e


def _top_level_or(expr: str) -> list[str]:
    parts, depth, quote, cur, i = [], 0, None, [], 0
    while i < len(expr):
        ch = expr[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif depth == 0 and expr.startswith("||", i):
            parts.append("".join(cur).strip())
            cur = []
            i += 2
            continue
        cur.append(ch)
        i += 1
    parts.append("".join(cur).strip())
    return parts


def _strip_parens(s: str) -> str:
    while s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
    return s


def nightly_job_eligible(job_if) -> tuple[bool, str]:
    """Is a job with this `if:` eligible on both schedule and workflow_dispatch?"""
    if job_if is None:
        return True, ""
    if not isinstance(job_if, Scalar):
        return False, "job `if:` is not a scalar"
    disjuncts = {_strip_parens(p) for p in _top_level_or(_norm_expr(job_if.text))}
    missing = [
        ev for ev in ("schedule", "workflow_dispatch")
        if not ({f"github.event_name == '{ev}'", f'github.event_name == "{ev}"'} & disjuncts)
    ]
    if missing:
        return False, (
            "job `if:` does not keep "
            + " / ".join(missing)
            + " eligible as a top-level `github.event_name == '...'` disjunct"
        )
    return True, ""


def scan_workflow(
    path: str,
    text: str,
    role: str,
    tracked: set[str],
    indirect: dict[tuple[str, str], tuple[str, ...]],
) -> WorkflowScan:
    """role: 'pr' (ci.yml) or 'nightly' (pdk-nightly.yml)."""
    scan = WorkflowScan(path)
    try:
        doc = parse_yaml(text, path)
    except Unsupported as exc:
        scan.errors.append(f"UNSUPPORTED {exc}")
        return scan
    if not isinstance(doc, dict):
        scan.errors.append(f"UNSUPPORTED {path}: top level is not a mapping")
        return scan
    on = doc.get("on", doc.get("true"))
    if isinstance(on, Scalar):
        scan.errors.append(
            f"UNSUPPORTED {path}:{on.line}: `on:` must be a block mapping of events, not `{on.text}`"
        )
        on = None
    scan.on = on if isinstance(on, dict) else {}
    defaults = doc.get("defaults")
    if isinstance(defaults, dict) and "run" in defaults:
        scan.errors.append(f"UNSUPPORTED {path}: workflow-level `defaults.run` (working-directory/shell)")
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        scan.errors.append(f"UNSUPPORTED {path}: no `jobs:` mapping")
        return scan
    for job_name, job in jobs.items():
        if job_name == "__line__" or not isinstance(job, dict):
            continue
        job_reason = ""
        if role == "pr":
            if "if" in job:
                job_reason = "the job has an `if:` condition, so it is not unconditionally PR-blocking"
        else:
            ok, why = nightly_job_eligible(job.get("if"))
            if not ok:
                job_reason = why
        if "needs" in job:
            job_reason = job_reason or "the job has `needs:`; dependency eligibility is not analysed"
        if _truthy(job.get("continue-on-error")):
            job_reason = job_reason or "the job has `continue-on-error`"
        if isinstance(job.get("defaults"), dict) and "run" in job["defaults"]:
            scan.errors.append(
                f"UNSUPPORTED {path}: job `{job_name}` sets `defaults.run` (working-directory/shell)"
            )
        if isinstance(job.get("strategy"), dict):
            job_reason = job_reason or "the job uses a `strategy:` matrix"
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict) or "run" not in step:
                continue
            run = step["run"]
            if not isinstance(run, Scalar) or run.style == "flow":
                scan.errors.append(f"UNSUPPORTED {path}: job `{job_name}`: non-scalar `run:` value")
                continue
            step_reason = job_reason
            if "if" in step:
                step_reason = step_reason or "the step has an `if:` condition"
            if _truthy(step.get("continue-on-error")):
                step_reason = step_reason or "the step has `continue-on-error`"
            shell = step.get("shell")
            shell_ok = shell is None or (
                isinstance(shell, Scalar) and shell.text.split()[0] in ("bash", "sh")
            )
            wd = step.get("working-directory")
            try:
                if not shell_ok:
                    if any(t in run.text for t in tracked):
                        raise Unsupported(f"non-sh `shell: {shell.text}` step mentioning a test path")
                    continue
                cmds = shell_commands(run.text)
                changed_dir = False
                for cmd in cmds:
                    words = [w for w in cmd if not (_ASSIGN_RE.match(w) or w in _PREFIX_WORDS)]
                    if words and words[0] in ("cd", "pushd", "popd"):
                        changed_dir = True
                        continue
                    pc = classify(cmd)
                    if pc is None or pc.kind in ("inline", "other"):
                        continue
                    if pc.kind == "indirect":
                        mapped = indirect.get((path, pc.text))
                        if mapped is None:
                            raise Unsupported(
                                f"indirect/discovery runner `{pc.text}` has no explicit "
                                "INDIRECT_RUNNERS mapping -- use a direct "
                                "`python3 <path>` step per test, or map it"
                            )
                        scan.indirect_seen.add(pc.text)
                        for t in mapped:
                            scan.executions.setdefault(t, []).append(
                                Execution(path, job_name, run.line, not step_reason, step_reason)
                            )
                        continue
                    script = pc.script or ""
                    is_test = posixpath.basename(script).startswith("test_") and script.endswith(".py")
                    if is_test and (changed_dir or (wd is not None and wd.text not in (".", "./"))):
                        raise Unsupported(
                            f"`{pc.text}` runs after a directory change "
                            "(cd / working-directory); use a repo-root-relative command"
                        )
                    scan.executions.setdefault(script, []).append(
                        Execution(path, job_name, run.line, not step_reason, step_reason)
                    )
            except Unsupported as exc:
                scan.errors.append(f"UNSUPPORTED {path}:{run.line}: job `{job_name}`: {exc}")
    return scan


def glob_to_regex(pattern: str) -> re.Pattern:
    if not pattern or pattern.startswith("!") or re.search(r"[\[\]{}+\\]", pattern):
        raise Unsupported(
            f"path-filter pattern `{pattern}` uses negation/bracket/brace/`+`/escape "
            "syntax outside the supported subset (literal, `*`, `?`, `**`)"
        )
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def check_coverage(
    tracked_files: list[str],
    workflows: dict[str, str],
    exemptions: dict[str, str] | None = None,
    indirect: dict[tuple[str, str], tuple[str, ...]] | None = None,
) -> list[str]:
    """Return diagnostics (empty list == fully wired)."""
    exemptions = EXEMPTIONS if exemptions is None else exemptions
    indirect = INDIRECT_RUNNERS if indirect is None else indirect
    diags: list[str] = []
    tests = sorted(
        p for p in tracked_files
        if posixpath.basename(p).startswith("test_") and p.endswith(".py")
    )
    tracked = set(tests)

    scans: dict[str, WorkflowScan] = {}
    for path, role in ((CI_WORKFLOW, "pr"), (NIGHTLY_WORKFLOW, "nightly")):
        if path not in workflows:
            diags.append(f"UNSUPPORTED {path}: workflow file missing")
            scans[path] = WorkflowScan(path)
            continue
        scans[path] = scan_workflow(path, workflows[path], role, tracked, indirect)
        diags.extend(scans[path].errors)

    for (wf, cmd) in sorted(indirect):
        if cmd not in scans.get(wf, WorkflowScan(wf)).indirect_seen:
            diags.append(f"STALE-MAPPING INDIRECT_RUNNERS[({wf!r}, {cmd!r})]: command not found in {wf}")

    # --- ci.yml PR trigger + path filters ---------------------------------
    ci = scans[CI_WORKFLOW]
    pr_patterns: list[re.Pattern] | None = None
    pr = ci.on.get("pull_request", "absent") if ci.on else "absent"
    if pr == "absent":
        diags.append(f"TRIGGER {CI_WORKFLOW}: no `on.pull_request` trigger -- nothing in it is PR-blocking")
    else:
        if isinstance(pr, dict):
            if "paths-ignore" in pr:
                diags.append(f"UNSUPPORTED {CI_WORKFLOW}: `pull_request.paths-ignore` is not supported")
            paths = pr.get("paths")
            if paths is not None:
                if not isinstance(paths, list):
                    diags.append(
                        f"UNSUPPORTED {CI_WORKFLOW}: `pull_request.paths` must be a block list"
                    )
                    paths = []
                pr_patterns = []
                for p in paths:
                    if not isinstance(p, Scalar) or p.style == "flow":
                        diags.append(f"UNSUPPORTED {CI_WORKFLOW}: non-scalar paths entry")
                        continue
                    try:
                        pr_patterns.append(glob_to_regex(p.text))
                    except Unsupported as exc:
                        diags.append(f"UNSUPPORTED {CI_WORKFLOW}:{p.line}: {exc}")

    def pr_filtered(p: str) -> bool:
        return pr_patterns is None or any(rx.match(p) for rx in pr_patterns)

    # --- nightly triggers ---------------------------------------------------
    ng = scans[NIGHTLY_WORKFLOW]
    nightly_ok = True
    sched = ng.on.get("schedule") if ng.on else None
    if not (isinstance(sched, list) and any(isinstance(s, dict) and "cron" in s for s in sched)):
        diags.append(f"TRIGGER {NIGHTLY_WORKFLOW}: no `on.schedule` cron trigger")
        nightly_ok = False
    if not ng.on or "workflow_dispatch" not in ng.on:
        diags.append(f"TRIGGER {NIGHTLY_WORKFLOW}: no `on.workflow_dispatch` (manual) trigger")
        nightly_ok = False

    # --- per-test coverage --------------------------------------------------
    for path, reason in sorted(exemptions.items()):
        if re.search(r"[*?\[\]{}]", path) or path.endswith("/") or not (
            posixpath.basename(path).startswith("test_") and path.endswith(".py")
        ):
            diags.append(
                f"BAD-EXEMPTION {path}: exemptions must be one exact tracked test_*.py path "
                "(no globs, no directories)"
            )
        elif path not in tracked:
            diags.append(f"STALE-EXEMPTION {path}: not a tracked test file any more -- remove it from EXEMPTIONS")
        if not reason.strip():
            diags.append(f"BAD-EXEMPTION {path}: no justification recorded")

    for t in tests:
        ci_runs = [e for e in ci.executions.get(t, []) if e.counted]
        ng_runs = [e for e in ng.executions.get(t, []) if e.counted] if nightly_ok else []
        if t in exemptions:
            if ci_runs or ng_runs:
                diags.append(
                    f"STALE-EXEMPTION {t}: it is now executed by CI -- remove it from EXEMPTIONS"
                )
            continue
        if ci_runs:
            if not pr_filtered(t):
                diags.append(
                    f"UNFILTERED {t}: executed in {CI_WORKFLOW} but no `on.pull_request.paths` "
                    "pattern matches it, so editing it does not trigger the job"
                )
            continue
        if t == GUARD_PATH:
            diags.append(f"UNWIRED {t}: the coverage guard itself must run PR-blocking in {CI_WORKFLOW}")
            continue
        if ng_runs:
            continue
        notes = [
            f"{e.workflow} job `{e.job}` (line {e.line}) not counted: {e.why_not}"
            for wf in (ci, ng) for e in wf.executions.get(t, []) if not e.counted
        ]
        if ng.executions.get(t) and not nightly_ok:
            notes.append(f"{NIGHTLY_WORKFLOW} lacks its schedule/manual triggers")
        diags.append(
            f"UNWIRED {t}: no CI step executes it -- " + ADD_STEP_HINT.format(path=t)
            + ("" if not notes else " [" + "; ".join(notes) + "]")
        )

    for p in (GUARD_PATH, CI_WORKFLOW, NIGHTLY_WORKFLOW):
        if not pr_filtered(p):
            diags.append(
                f"UNFILTERED {p}: not matched by {CI_WORKFLOW} `on.pull_request.paths`, so "
                "editing it would not re-run this guard"
            )
    return diags


def repository_inputs(root: Path = REPO_ROOT) -> tuple[list[str], dict[str, str]]:
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True, capture_output=True, text=True,
    ).stdout
    files = [f for f in out.split("\0") if f]
    workflows = {}
    for wf in (CI_WORKFLOW, NIGHTLY_WORKFLOW):
        p = root / wf
        if p.is_file():
            workflows[wf] = p.read_text(encoding="utf-8")
    return files, workflows


# ===========================================================================
# Tests
# ===========================================================================


class RepositoryWiring(unittest.TestCase):
    """The real repository: every tracked test is wired (the guard proper)."""

    def test_repository_is_fully_wired(self):
        files, workflows = repository_inputs()
        diags = check_coverage(files, workflows)
        if diags:
            self.fail(
                "CI test-wiring guard failed (issue #230):\n  " + "\n  ".join(diags)
            )


CI_OK = """\
name: CI
# python3 sim/tests/test_in_yaml_comment.py
on:
  push:
    branches: [main]
  pull_request:
    paths:
      - "design/**"
      - "sim/tests/**"
      - "layout/test_*.py"
      - ".github/workflows/ci.yml"
      - ".github/workflows/pdk-nightly.yml"
  workflow_dispatch: {}
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: design/test_ci_test_coverage.py
        run: python3 design/test_ci_test_coverage.py
      - name: scalar
        run: python3 sim/tests/test_a.py
      - name: multiline
        run: |
          set -euo pipefail
          echo "python3 sim/tests/test_in_echo.py"
          # python3 sim/tests/test_in_shell_comment.py
          FOO=1 python3 -u ./sim/tests/test_b.py && echo done
          python3 \\
            layout/test_new.py
      - name: quoted
        run: "python3 'sim/tests/test_c.py'"
      - name: folded
        run: >-
          python3
          sim/tests/test_d.py
"""

NIGHTLY_OK = """\
name: PDK nightly
on:
  schedule:
    - cron: "41 6 * * *"
  workflow_dispatch: {}
  pull_request:
    types: [opened, synchronize, reopened, labeled]
jobs:
  netlist-check:
    runs-on: ubuntu-latest
    if: >-
      github.event_name == 'schedule' ||
      github.event_name == 'workflow_dispatch' ||
      (github.event_name == 'pull_request' &&
       contains(github.event.pull_request.labels.*.name, 'run-pdk-check'))
    steps:
      - name: Resolve
        run: |
          version="$(python3 -c "import json; print(json.load(open('design/pdk.json'))['v'])")"
      - name: design/test_netlist_erc.py (ERC regression fixture)
        run: python3 design/test_netlist_erc.py
"""

BASE_TESTS = [
    GUARD_PATH,
    "sim/tests/test_a.py",
    "sim/tests/test_b.py",
    "sim/tests/test_c.py",
    "sim/tests/test_d.py",
    "layout/test_new.py",
    "design/test_netlist_erc.py",
    "digital/tb/cocotb/test_trng_digital_fv.py",
    "design/_test_check.py",  # not test_*.py: never inventoried
]


def run_fixture(tracked=None, ci=CI_OK, nightly=NIGHTLY_OK, exemptions=None, indirect=None):
    return check_coverage(
        BASE_TESTS if tracked is None else tracked,
        {CI_WORKFLOW: ci, NIGHTLY_WORKFLOW: nightly},
        exemptions=exemptions,
        indirect=indirect or {},
    )


class PositiveControls(unittest.TestCase):
    def test_baseline_fixture_passes(self):
        # scalar, `|` block with env prefix/flags/./ prefix/backslash
        # continuation, YAML-quoted scalar with a shell-quoted path, `>-`
        # folded block, layout glob, exact cocotb exemption, nightly ERC.
        self.assertEqual(run_fixture(), [])

    def test_layout_glob_covers_future_sibling(self):
        ci = CI_OK.replace(
            "      - name: scalar\n",
            "      - name: sib\n        run: python3 layout/test_future.py\n      - name: scalar\n",
        )
        self.assertEqual(run_fixture(BASE_TESTS + ["layout/test_future.py"], ci=ci), [])

    def test_double_star_crosses_directories(self):
        ci = CI_OK.replace(
            "      - name: scalar\n",
            "      - name: deep\n        run: python3 design/a/b/test_deep.py\n      - name: scalar\n",
        )
        self.assertEqual(run_fixture(BASE_TESTS + ["design/a/b/test_deep.py"], ci=ci), [])

    def test_explicit_indirect_mapping_counts(self):
        ci = CI_OK.replace(
            "      - name: scalar\n        run: python3 sim/tests/test_a.py\n",
            "      - name: discover\n        run: python3 -m unittest discover sim/tests\n",
        )
        mapping = {(CI_WORKFLOW, "python3 -m unittest discover sim/tests"): ("sim/tests/test_a.py",)}
        self.assertEqual(run_fixture(ci=ci, indirect=mapping), [])

    def test_shell_tokenisation(self):
        self.assertEqual(
            shell_commands("a 'x y' && b\n# c\nd \\\n e # f\necho a#b"),
            [["a", "x y"], ["b"], ["d", "e"], ["echo", "a#b"]],
        )

    def test_glob_semantics(self):
        self.assertTrue(glob_to_regex("layout/test_*.py").match("layout/test_x.py"))
        self.assertFalse(glob_to_regex("layout/test_*.py").match("layout/sub/test_x.py"))
        self.assertFalse(glob_to_regex("sim/*").match("sim/tests/test_x.py"))
        self.assertTrue(glob_to_regex("sim/**").match("sim/tests/test_x.py"))
        self.assertTrue(glob_to_regex("a/**/b.py").match("a/b.py"))
        self.assertFalse(glob_to_regex("a?b").match("a/b"))


class NegativeControls(unittest.TestCase):
    def assertDiag(self, diags, prefix, name):
        hits = [d for d in diags if d.startswith(prefix) and name in d]
        self.assertTrue(hits, f"expected {prefix} naming {name}, got:\n" + "\n".join(diags))

    def test_unwired_tracked_test(self):
        d = run_fixture(BASE_TESTS + ["sim/tests/test_dummy.py"])
        self.assertDiag(d, "UNWIRED", "sim/tests/test_dummy.py")
        self.assertEqual(len(d), 1, d)
        self.assertIn("add a step `run: python3 sim/tests/test_dummy.py`", d[0])

    def test_reference_only_in_yaml_comment(self):
        self.assertDiag(run_fixture(BASE_TESTS + ["sim/tests/test_in_yaml_comment.py"]),
                        "UNWIRED", "sim/tests/test_in_yaml_comment.py")

    def test_reference_only_in_step_name(self):
        ci = CI_OK.replace("- name: scalar", "- name: python3 sim/tests/test_in_name.py")
        self.assertDiag(run_fixture(BASE_TESTS + ["sim/tests/test_in_name.py"], ci=ci),
                        "UNWIRED", "sim/tests/test_in_name.py")

    def test_reference_only_in_shell_comment(self):
        self.assertDiag(run_fixture(BASE_TESTS + ["sim/tests/test_in_shell_comment.py"]),
                        "UNWIRED", "sim/tests/test_in_shell_comment.py")

    def test_reference_only_in_echo(self):
        self.assertDiag(run_fixture(BASE_TESTS + ["sim/tests/test_in_echo.py"]),
                        "UNWIRED", "sim/tests/test_in_echo.py")

    def test_similarly_named_file_does_not_count(self):
        ci = CI_OK.replace("sim/tests/test_a.py", "sim/tests/test_a_extra.py")
        self.assertDiag(run_fixture(ci=ci), "UNWIRED", "sim/tests/test_a.py")
        ci = CI_OK.replace("python3 sim/tests/test_a.py", "python3 other/sim/tests/test_a.py")
        self.assertDiag(run_fixture(ci=ci), "UNWIRED", "sim/tests/test_a.py")

    def test_executed_but_excluded_by_pr_filter(self):
        ci = CI_OK.replace('      - "sim/tests/**"\n', '      - "sim/*"\n')
        self.assertDiag(run_fixture(ci=ci), "UNFILTERED", "sim/tests/test_a.py")

    def test_ci_workflow_excluded_by_filter(self):
        ci = CI_OK.replace('      - ".github/workflows/ci.yml"\n', "")
        self.assertDiag(run_fixture(ci=ci), "UNFILTERED", CI_WORKFLOW)

    def test_nightly_workflow_excluded_by_filter(self):
        ci = CI_OK.replace('      - ".github/workflows/pdk-nightly.yml"\n', "")
        self.assertDiag(run_fixture(ci=ci), "UNFILTERED", NIGHTLY_WORKFLOW)

    def test_guard_not_wired(self):
        ci = CI_OK.replace("run: python3 design/test_ci_test_coverage.py", "run: echo skip")
        self.assertDiag(run_fixture(ci=ci), "UNWIRED", GUARD_PATH)

    def test_removed_nightly_command(self):
        ng = NIGHTLY_OK.replace("run: python3 design/test_netlist_erc.py", "run: echo gone")
        self.assertDiag(run_fixture(nightly=ng), "UNWIRED", "design/test_netlist_erc.py")

    def test_removed_nightly_schedule(self):
        ng = NIGHTLY_OK.replace('  schedule:\n    - cron: "41 6 * * *"\n', "")
        d = run_fixture(nightly=ng)
        self.assertDiag(d, "TRIGGER", "schedule")
        self.assertDiag(d, "UNWIRED", "design/test_netlist_erc.py")

    def test_removed_nightly_dispatch(self):
        ng = NIGHTLY_OK.replace("  workflow_dispatch: {}\n", "")
        d = run_fixture(nightly=ng)
        self.assertDiag(d, "TRIGGER", "workflow_dispatch")
        self.assertDiag(d, "UNWIRED", "design/test_netlist_erc.py")

    def test_nightly_job_no_longer_schedule_eligible(self):
        ng = NIGHTLY_OK.replace("      github.event_name == 'schedule' ||\n", "")
        self.assertDiag(run_fixture(nightly=ng), "UNWIRED", "design/test_netlist_erc.py")

    def test_stale_exemption_untracked(self):
        ex = dict(EXEMPTIONS, **{"sim/tests/test_gone.py": "was removed"})
        self.assertDiag(run_fixture(exemptions=ex), "STALE-EXEMPTION", "sim/tests/test_gone.py")

    def test_stale_exemption_now_executed(self):
        ex = dict(EXEMPTIONS, **{"sim/tests/test_a.py": "pretend"})
        self.assertDiag(run_fixture(exemptions=ex), "STALE-EXEMPTION", "sim/tests/test_a.py")

    def test_directory_exemption_rejected(self):
        ex = dict(EXEMPTIONS, **{"sim/tests/": "everything", "sim/tests/test_*.py": "glob"})
        d = run_fixture(exemptions=ex)
        self.assertDiag(d, "BAD-EXEMPTION", "sim/tests/")
        self.assertDiag(d, "BAD-EXEMPTION", "sim/tests/test_*.py")

    def test_cocotb_without_exemption_is_unwired(self):
        self.assertDiag(run_fixture(exemptions={}), "UNWIRED", "digital/tb/cocotb/test_trng_digital_fv.py")

    def test_unmapped_discovery_runner(self):
        ci = CI_OK.replace("run: python3 sim/tests/test_a.py", "run: python3 -m pytest sim/tests")
        d = run_fixture(ci=ci)
        self.assertDiag(d, "UNSUPPORTED", "python3 -m pytest sim/tests")
        self.assertDiag(d, "UNWIRED", "sim/tests/test_a.py")

    def test_non_literal_script(self):
        ci = CI_OK.replace("run: python3 sim/tests/test_a.py", 'run: for t in sim/tests/test_*.py; do python3 "$t"; done')
        self.assertDiag(run_fixture(ci=ci), "UNSUPPORTED", 'python3 $t')

    def test_stale_indirect_mapping(self):
        d = run_fixture(indirect={(CI_WORKFLOW, "pytest gone"): ("sim/tests/test_a.py",)})
        self.assertDiag(d, "STALE-MAPPING", "pytest gone")

    def test_unsupported_filter_syntax(self):
        ci = CI_OK.replace('      - "design/**"\n', '      - "design/**"\n      - "!design/x/**"\n')
        self.assertDiag(run_fixture(ci=ci), "UNSUPPORTED", "!design/x/**")
        ci = CI_OK.replace("    paths:\n", "    paths-ignore: [docs/**]\n    paths:\n")
        self.assertDiag(run_fixture(ci=ci), "UNSUPPORTED", "paths-ignore")

    def test_unsupported_yaml_and_shell(self):
        cases = {
            "explicit indentation": CI_OK.replace("run: |\n", "run: |2\n"),
            "unterminated": CI_OK.replace('run: "python3', 'run: "python3 x\n'),
            "directory change": CI_OK.replace(
                "run: python3 sim/tests/test_a.py", "run: cd sim/tests && python3 test_a.py"),
            "heredoc": CI_OK.replace("run: python3 sim/tests/test_a.py", "run: python3 - <<EOF"),
            "anchor": CI_OK.replace("run: python3 sim/tests/test_a.py", "run: *cmd"),
            "multi-line plain": CI_OK.replace(
                "run: python3 sim/tests/test_a.py", "run: python3\n          sim/tests/test_a.py"),
        }
        for label, ci in cases.items():
            with self.subTest(label):
                d = run_fixture(ci=ci)
                self.assertTrue(any(x.startswith("UNSUPPORTED") for x in d), f"{label}: {d}")
                self.assertTrue(d)

    def test_conditional_ci_step_not_counted(self):
        ci = CI_OK.replace(
            "        run: python3 sim/tests/test_a.py\n",
            "        if: false\n        run: python3 sim/tests/test_a.py\n",
        )
        self.assertDiag(run_fixture(ci=ci), "UNWIRED", "sim/tests/test_a.py")


if __name__ == "__main__":
    unittest.main(verbosity=1)
