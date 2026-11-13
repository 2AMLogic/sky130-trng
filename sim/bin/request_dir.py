#!/usr/bin/env python3
"""The one rule for reading a directory of `klt sim` request folders.

A request directory holds one sub-directory per `klt sim` request, each with a
``plan.json`` (what was asked for) and a ``resp.json`` (what came back). A
request that the fleet refused for capacity, that failed, or that was never
submitted leaves ``resp.json`` absent, empty, or without a ``corners`` key --
and the reducer that reads the directory decides what that means for the
record it is about to write.

The rule this module implements is ``ro-array-supply-perturbation/ripple.py``'s
(issue #288's evidence requirement): **a request with no usable response is
returned to the caller, not dropped on the floor.**
:func:`load_request_dir` returns ``(chunks, missing)`` -- never a silently
shortened list -- so each reducer states its own completeness policy in one
place instead of having it fall out of a glob pattern:

* ``ripple.py``  -- carries the missing requests into the record as explicit rows
* ``wakeup.py``  -- records their names under ``requests_without_response``
* ``sensitivity.py`` -- drops them, and the caller's coverage-manifest gate
  refuses to record a partial grid
* ``xor-combining-alternatives/reduce.py`` -- refuses unless all 6 came back
* ``local-mismatch-monte-carlo/reduce.py`` -- refuses to emit a record

Five reducers used to carry five copies of this walk, with five glob patterns
and five different answers for a request with no response. The
local-mismatch copy dropped such a request silently *and* took its
``n_*_requested`` sample counts from the units that came back, so a refused
Monte Carlo chunk shrank the denominator with it: a record could read
"30/30 array" while a third of the requested draws were missing, with no error
and no trace but a short seed list. Issue #469; same consolidation shape as
#133 and #465.

Reading a *committed* corner bundle (``corners/<rid>/*.klt-sim.json.gz``) is a
different job -- the bundle only ever contains responses that arrived -- and
stays with the reducers that replay one.
"""

from __future__ import annotations

import json
import os
import glob as _glob

#: What a request directory with no usable response is called when `klt` left
#: no error message of its own behind.
NO_RESPONSE = "no response: request not submitted or submission did not complete"


def submit_error(reqpath):
    """Why the request directory at ``reqpath`` has no usable response.

    The `klt` error message if the client wrote one, else the tail of whatever
    it did write, else :data:`NO_RESPONSE`. Never raises: this runs on the
    failure path, where any file in the directory may be absent or truncated.
    """
    for fn in ("resp.json", "klt.log"):
        p = os.path.join(reqpath, fn)
        try:
            with open(p) as fh:
                txt = fh.read()
        except OSError:
            continue
        if not txt.strip():
            continue
        try:
            msg = json.loads(txt).get("error", {}).get("message")
            if msg:
                return msg
        except (ValueError, AttributeError):
            pass
        return txt.strip()[-600:]
    return NO_RESPONSE


def _read_json(path):
    """Parsed ``resp.json`` at ``path``, or None if absent, empty or malformed.

    A refused or still-running request leaves a zero-byte ``resp.json``, and a
    submission killed mid-write leaves a truncated one; neither is a usable
    response and neither should abort the walk -- the request comes back in
    ``missing`` instead. The *plan* side cannot be read this way, because a
    plan that reads as None has nowhere to go: see :func:`_read_plan`.
    """
    try:
        if os.path.getsize(path) == 0:
            return None
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _read_plan(path):
    """Parsed ``plan.json`` at ``path``, or None if there is no such file.

    "No file" and "a file I cannot read" are *not* the same answer, and this is
    the one place in the walk where conflating them loses a request:

    * **no file at all** -- the directory is not a request directory (a
      ``notes/`` folder beside the requests), and the walk skips it.
    * **a file that is there but unreadable** -- zero-byte, truncated, not a
      JSON object -- is a *corrupt request*, not a non-request, so it raises
      and names the path. All five hand-rolled walks this module replaced did
      ``json.load(open(plan.json))`` unguarded and so raised here too.

    Skipping the second case would drop the request from *both* of
    :func:`load_request_dir`'s lists, leaving no caller able to state a policy
    about it -- and in the local-mismatch reducer the lost plan would also take
    its requested draws out of the denominator, re-creating the silent
    "20/20 array" headline over 20 of 30 requested draws that issue #469 exists
    to remove (PR #473 review).
    """
    try:
        with open(path) as fh:
            txt = fh.read()
    except FileNotFoundError:
        return None                       # not a request directory
    except OSError as exc:
        raise ValueError(f"unreadable plan.json at {path}: {exc}") from exc
    if not txt.strip():
        raise ValueError(f"unreadable plan.json at {path}: file is empty")
    try:
        plan = json.loads(txt)
    except ValueError as exc:
        raise ValueError(f"unreadable plan.json at {path}: {exc}") from exc
    if not isinstance(plan, dict):
        # Otherwise a plan.json holding `null` would forge the "no such file"
        # sentinel above and vanish just as silently.
        raise ValueError(f"unreadable plan.json at {path}: expected a JSON object, got {type(plan).__name__}")
    return plan


def load_request_dir(reqdir, pattern="*", name_from="dirname", require_corners=True):
    """Read a directory of `klt sim` requests -> ``(chunks, missing)``.

    ``chunks``  = ``[(name, plan, resp)]`` for requests with a usable response.
    ``missing`` = ``[(name, plan, reason)]`` for requests that were refused,
    failed, or never completed -- so the caller can carry them as explicit rows,
    name them in its record, or refuse to write one. Both are sorted by
    directory name, so a reduction over them is deterministic.

    ``pattern``  glob for the request sub-directories, relative to ``reqdir``
                 (e.g. ``"*-*-*"``, ``"det-*"``). A matching path that is not a
                 directory, or a directory with no ``plan.json`` file, is not a
                 request directory and is ignored entirely -- it appears in
                 neither list. A ``plan.json`` that *is* there but cannot be
                 read raises instead of being ignored: see :func:`_read_plan`.
    ``name_from`` ``"dirname"`` to name each request after its directory, or
                 ``"plan"`` to use the plan's own ``name`` field.
    ``require_corners`` treat a parsed response with no ``corners`` key as
                 missing. A `klt` response that reports an error carries no
                 corners, so this is on by default; pass False only if the
                 caller inspects the raw response itself.
    """
    if name_from not in ("dirname", "plan"):
        raise ValueError(f"name_from must be 'dirname' or 'plan', not {name_from!r}")
    chunks, missing = [], []
    for d in sorted(_glob.glob(os.path.join(reqdir, pattern))):
        if not os.path.isdir(d):
            continue                      # a stray file beside the requests
        plan = _read_plan(os.path.join(d, "plan.json"))
        if plan is None:
            continue                      # not a request directory
        name = os.path.basename(d) if name_from == "dirname" else plan["name"]
        resp = _read_json(os.path.join(d, "resp.json"))
        if resp is None or (require_corners and "corners" not in resp):
            missing.append((name, plan, submit_error(d)))
        else:
            chunks.append((name, plan, resp))
    return chunks, missing
