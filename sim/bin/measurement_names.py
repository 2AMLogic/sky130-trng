"""Corner-measurement name-uniqueness guard (issue #670; failure mode of #548).

A ``klt sim`` response carries each corner's measurements as a LIST of
{name, value} entries.  Reducers deduplicate that list into a name-keyed
dict, and a repeated name silently displaces the entry it duplicates: the
displaced measurement's check is simply never made while the entry-count
bookkeeping stays honest, so a corner can lose a check and still report a
pass.

Guarded callers are the reducers whose campaign generator lifts measurement
names verbatim out of a committed template deck (a regex pass-through with
no uniqueness property of its own):

* ``sim/raw-bit-volume-campaign/derive-combining.py`` (combining deck lifts
  ``sim/ro-array-core-combining/testbench/tb_ro_array_core.spice``),
* ``sim/ro-vth-drift-sensitivity/analysis/sensitivity.py`` (the array deck
  lifts the same template; the ring5 deck's names are structural),
* ``sim/post-layout-ro-ring5-assembled-181/derive.py`` (lifts
  ``sim/post-layout-ro-ring5-assembled/testbench/
  tb_post_layout_ro_ring5_assembled.spice``).

The other reducers named in #670 are fed by generators that build names
structurally -- f-strings over ``range()`` indices and disjoint literal
names -- and were measured duplicate-free instead of guarded; see the #670
PR's per-campaign evidence.

The whole-block analysis scripts (``sim/post-layout-whole-block/analysis/
compare-gate-model.py`` and, via its re-export, ``reduce-whole-block.py``,
issues #642/#690) call :func:`duplicate_measurement_names` directly rather
than :func:`measurements_by_name`: they act on the returned list (raising
``SystemExit`` with ``plan.json`` context or scoring the 12-point corner
``UNMET`` without aborting the remaining corners).

Uniqueness is judged over the FULL measurements list, BEFORE any
``value is not None`` filtering: a repeated name is a deck/report defect
whether or not the displaced entry happened to carry a value, and which of
two same-named entries survives a value filter depends on list order.

Standard library only.
"""
from __future__ import annotations

from collections import Counter


class DuplicateMeasurementName(RuntimeError):
    """A corner's measurements repeat a name; refusing to deduplicate."""

    def __init__(self, corner, duplicates, n_entries):
        self.corner = corner
        self.duplicates = tuple(sorted(duplicates))
        self.n_entries = n_entries
        super().__init__(
            f"corner {corner}: measurement name(s) {list(self.duplicates)} repeat "
            f"across {n_entries} entries: a repeated name displaces the entry it "
            f"duplicates, refusing to deduplicate")


def _corner_label(corner):
    parts = []
    for key in ("corner_id", "process", "corner", "temperature_c", "monte_carlo"):
        if corner.get(key) is not None:
            parts.append(f"{key}={corner[key]}")
    return " ".join(parts) if parts else "<corner without identity fields>"


def duplicate_measurement_names(measurements) -> list[str]:
    """Sorted names that appear more than once in a corner's measurements list."""
    counts = Counter(m["name"] for m in measurements or [])
    return sorted(name for name, n in counts.items() if n > 1)


def measurements_by_name(corner, *, keep_none=False, label=None) -> dict:
    """Deduplicate ``corner["measurements"]`` into ``{name: value}``, loudly.

    Raises :class:`DuplicateMeasurementName` -- naming the corner (an
    explicit ``label`` wins over the identity fields ``corner_id`` /
    ``process`` / ``corner`` / ``temperature_c`` / ``monte_carlo``) and the
    repeated names -- instead of silently keeping the last entry.

    With ``keep_none=False`` (the default) entries whose value is ``None``
    are dropped from the returned dict, matching the
    ``if x.get("value") is not None`` reducers; the uniqueness guard itself
    always counts them (see the module docstring).  An absent or empty
    measurements list gives ``{}``.
    """
    entries = corner.get("measurements") or []
    duplicates = duplicate_measurement_names(entries)
    if duplicates:
        raise DuplicateMeasurementName(label or _corner_label(corner), duplicates, len(entries))
    if keep_none:
        return {m["name"]: m["value"] for m in entries}
    return {m["name"]: m["value"] for m in entries if m.get("value") is not None}
