#!/usr/bin/env python3
"""Curated-deck DRC coverage audit for the composed whole block (issue #281).

``klt drc`` reports the curated sky130 deck as clean on
``layout/trng_whole/trng_whole.gds``, but it also lists rules it did not run
(``coverage.inapplicable``, reason ``no_applicable_geometry``; the legacy name
of that list is ``rules_skipped``) and stream layer/datatype pairs that no rule
reads (``coverage.layers_in_stream_without_rules``). This module checks klt's
"inapplicable" claim against the stream itself, using inputs it does not take
from that claim, and writes two tables:

1. **Inapplicable rules.** For each rule: its ``check`` kind and the deck
   layers it reads (from ``klt deck rules``), each layer's GDS layer/datatype
   (from the deck's own layer table), the flattened shape count of each layer
   in the composed stream (from ``klt layers --flattened --include-text``),
   klt's reason, and a verdict:

   - ``vacuous-confirmed``: the rule cannot fire because a layer it needs has
     no geometry. Single-layer kinds (``angle``, ``ongrid``, ``width``,
     ``space``) need that one layer to be empty. Two-layer kinds
     (``enclosing``, ``separation``) need at least one of the two to be empty,
     because the check needs both.
   - ``residual``: every layer the rule needs has geometry, yet klt lists the
     rule as inapplicable. This contradicts klt's reason and is a residual
     coverage gap.
   - ``unresolved``: the rule is not in the pinned deck, a layer cannot be
     resolved to one stream layer/datatype, or the check kind (or its layer
     count) is not one this audit understands. Never turned into
     ``vacuous-confirmed``.

2. **Unruled stream layers.** For each ``layers_in_stream_without_rules``
   entry: definition and flattened shape counts, text count, klt's
   ``annotation`` flag, the deck layer name if the deck has one, and a verdict:
   ``present-unruled`` (polygon geometry, no rule reads it) or
   ``text-or-marker-only`` (only text, or klt flags it as annotation). A
   layer klt lists as in the stream but ``klt layers`` cannot find is
   ``unresolved``. No row is labelled "absent".

**Pinning.** The rule-to-layer mapping must come from the deck that produced
the committed ``drc.json``. ``klt deck rules`` must report
``content_hash == drc.json provenance.deck.content_hash``. The layer-name
table (``klayout_tools.decks.get_layer_names``) is read from an importable
``klayout_tools`` whose sky130 deck module hashes to the same value. That
module's sha256 *is* klt's deck ``content_hash``. A mismatch is an
:class:`AuditError` that names both hashes. The audit never substitutes a
different deck silently.

**Counts.** ``flattened_shapes`` is klt's count of instantiated shapes per
layer/datatype under the top cell, and it includes text objects.
``geometry = flattened_shapes - text_count`` is the polygon/box/path count a
DRC rule can act on. Every verdict above is decided on ``geometry``.

This is evidence, not sign-off. It audits klt's own curated deck against
itself and the stream. It is not a foundry runset and adds no antenna,
density, seal-ring or latch-up check.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

SCHEMA_VERSION = 1
DECK = "sky130"

SINGLE_LAYER_KINDS = ("angle", "ongrid", "width", "space")
TWO_LAYER_KINDS = ("enclosing", "separation")

VERDICT_CONDITIONS = {
    "vacuous-confirmed": {
        **{k: "the one layer the rule reads has geometry == 0 in the flattened stream" for k in SINGLE_LAYER_KINDS},
        **{k: "at least one of the two layers the rule reads has geometry == 0 (the check needs both)" for k in TWO_LAYER_KINDS},
    },
    "residual": "every layer the rule reads has geometry > 0, yet klt lists the rule as inapplicable",
    "unresolved": "rule id not in the pinned deck; or a deck layer name not resolvable to exactly one stream "
    "layer/datatype that the pinned DRC run also read (drc.json coverage.deck_layers); or a check kind / "
    "layer count outside the kinds above. Never forced to vacuous-confirmed",
}
UNRULED_CONDITIONS = {
    "present-unruled": "geometry > 0 and klt's annotation flag is false: drawn shapes that no curated rule reads",
    "text-or-marker-only": "flattened_shapes > 0 and (geometry == 0, i.e. text objects only, or klt's annotation flag is true)",
    "unresolved": "listed by klt drc as in the stream but klt layers reports no shapes for it",
}
NOT_SIGNOFF = (
    "Evidence, not sign-off. This audit cross-checks klt's own curated sky130 deck coverage report against the "
    "composed stream. It is not a foundry DRC runset, and it adds no antenna, density, seal-ring, latch-up or "
    "foundry-only rule. No ratified spec value is read or changed."
)


class AuditError(RuntimeError):
    """The audit cannot run on the pinned deck (hash mismatch, missing input)."""


# --------------------------------------------------------------------------
# pinned inputs
# --------------------------------------------------------------------------


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ld_key(layer: int, datatype: int) -> str:
    return f"{layer}/{datatype}"


def pinned_deck_hash(drc_report: dict) -> str:
    try:
        return drc_report["provenance"]["deck"]["content_hash"]
    except (KeyError, TypeError) as exc:
        raise AuditError("drc.json has no provenance.deck.content_hash to pin the audit to") from exc


def require_pinned(got: str | None, pinned: str, what: str) -> None:
    if got != pinned:
        raise AuditError(
            f"{what}: deck content hash {got} does not match the pinned deck {pinned} recorded in "
            "layout/trng_whole/verify/drc.json provenance.deck.content_hash. The audit refuses to map rules "
            "through a different deck; use the klt build that produced drc.json (layout/pdk.json klt_version_pin)."
        )


def load_deck_layer_table() -> tuple[str, dict[tuple[int, int], str]]:
    """The deck's own ``(layer, datatype) -> name`` table and the sha256 of the
    deck module it came from (klt's deck ``content_hash`` is that digest)."""
    try:
        from klayout_tools import decks  # noqa: PLC0415
    except ImportError as exc:
        raise AuditError(
            "klayout_tools is not importable from this interpreter; the deck layer table "
            "(klayout_tools.decks.get_layer_names) is needed to resolve rule layers to stream layer/datatype. "
            "Run with the pinned venv's python."
        ) from exc
    src = decks.deck_source_path(DECK)
    if not src:
        raise AuditError(f"klayout_tools.decks.deck_source_path({DECK!r}) returned nothing")
    digest = "sha256:" + sha256_bytes(Path(src).read_bytes())
    return digest, dict(decks.get_layer_names(DECK))


def layer_counts(layers_doc: dict) -> dict[str, dict]:
    """``klt layers --flattened --include-text`` -> per-``L/D`` counts."""
    out = {}
    for rec in layers_doc.get("layers", []):
        if "flattened_shapes" not in rec:
            raise AuditError("klt layers output has no flattened_shapes (run with --flattened --include-text)")
        flat = int(rec["flattened_shapes"])
        text = int(rec.get("text_count") or 0)
        out[ld_key(rec["layer"], rec["datatype"])] = {
            "definition_shapes": int(rec.get("shapes") or 0),
            "flattened_shapes": flat,
            "text_count": text,
            "geometry": flat - text,
            "annotation": bool(rec.get("annotation")),
        }
    return out


_ZERO = {"definition_shapes": 0, "flattened_shapes": 0, "text_count": 0, "geometry": 0, "annotation": False}


# --------------------------------------------------------------------------
# classification
# --------------------------------------------------------------------------


def audited_rule_ids(coverage: dict) -> list[dict]:
    """Union of ``inapplicable``, legacy ``rules_skipped`` and ``skipped``,
    in deck order of first appearance, with the lists each id appears in."""
    rows: dict[str, dict] = {}
    for entry in coverage.get("inapplicable") or []:
        rows.setdefault(entry["id"], {"lists": [], "reason": None})
        rows[entry["id"]]["lists"].append("inapplicable")
        rows[entry["id"]]["reason"] = entry.get("reason")
    for rid in coverage.get("rules_skipped") or []:
        rows.setdefault(rid, {"lists": [], "reason": None})["lists"].append("rules_skipped")
    for entry in coverage.get("skipped") or []:
        rid = entry["id"] if isinstance(entry, dict) else entry
        rows.setdefault(rid, {"lists": [], "reason": None})["lists"].append("skipped")
        if isinstance(entry, dict) and rows[rid]["reason"] is None:
            rows[rid]["reason"] = entry.get("reason")
    return [{"rule": rid, **info} for rid, info in rows.items()]


def resolve_layer(name: str, name_to_lds: dict[str, list[str]], deck_layers: set[str]) -> tuple[str | None, str | None]:
    """(``L/D`` or None, why-unresolved or None)."""
    lds = name_to_lds.get(name, [])
    if not lds:
        return None, f"deck layer table does not name {name!r}"
    if len(lds) > 1:
        return None, f"deck layer table maps {name!r} to several layer/datatypes {lds}"
    if lds[0] not in deck_layers:
        return None, f"{name!r} -> {lds[0]} is not among the layers the pinned DRC run read (drc.json coverage.deck_layers)"
    return lds[0], None


def classify_rule(entry: dict, rules_by_id: dict[str, dict], name_to_lds: dict[str, list[str]],
                  deck_layers: set[str], counts: dict[str, dict]) -> dict:
    rid = entry["rule"]
    row = {"rule": rid, "check": None, "deck_layers": [], "klt_reason": entry["reason"], "klt_lists": entry["lists"]}
    rule = rules_by_id.get(rid)
    if rule is None:
        return row | {"verdict": "unresolved", "why": "rule id is not in the pinned deck (klt deck rules)"}
    kind, names = rule.get("check"), list(rule.get("layers") or [])
    row["check"] = kind
    problems = []
    for name in names:
        ld, why = resolve_layer(name, name_to_lds, deck_layers)
        c = counts.get(ld, _ZERO) if ld else None
        row["deck_layers"].append({
            "name": name,
            "gds": ld,
            "flattened_shapes": None if c is None else c["flattened_shapes"],
            "text_count": None if c is None else c["text_count"],
            "geometry": None if c is None else c["geometry"],
        })
        if why:
            problems.append(why)
    if kind in SINGLE_LAYER_KINDS:
        want = 1
    elif kind in TWO_LAYER_KINDS:
        want = 2
    else:
        return row | {"verdict": "unresolved", "why": f"check kind {kind!r} is not one this audit understands"}
    if len(names) != want:
        return row | {"verdict": "unresolved", "why": f"check kind {kind!r} reads {len(names)} layers; the audit expects {want}"}
    if problems:
        return row | {"verdict": "unresolved", "why": "; ".join(problems)}
    geoms = [lay["geometry"] for lay in row["deck_layers"]]
    empty = [lay["name"] for lay in row["deck_layers"] if lay["geometry"] == 0]
    if empty:
        return row | {"verdict": "vacuous-confirmed", "why": f"no geometry on {', '.join(empty)}"}
    return row | {"verdict": "residual",
                  "why": f"all required layers have geometry ({', '.join(str(g) for g in geoms)}) but klt lists the rule as inapplicable"}


def classify_unruled(ld: str, counts: dict[str, dict], ld_to_name: dict[str, str]) -> dict:
    c = counts.get(ld)
    row = {"gds": ld, "deck_layer_name": ld_to_name.get(ld)}
    if c is None or c["flattened_shapes"] == 0:
        return row | dict(_ZERO) | {"text_only": None, "verdict": "unresolved",
                                    "why": "klt drc lists it as in the stream; klt layers reports no shapes"}
    text_only = c["geometry"] == 0
    verdict = "text-or-marker-only" if (text_only or c["annotation"]) else "present-unruled"
    return row | c | {"text_only": text_only, "verdict": verdict}


def build_audit(*, drc_report: dict, deck_rules: dict, layer_table: tuple[str, dict[tuple[int, int], str]],
                layers_doc: dict, gds_sha256: str, gds_rel: str, drc_rel: str, top: str) -> dict:
    """Pure: everything the audit reads is passed in. Raises
    :class:`AuditError` when either deck source is not the pinned deck."""
    pinned = pinned_deck_hash(drc_report)
    require_pinned(deck_rules.get("content_hash"), pinned, "klt deck rules --deck sky130")
    table_hash, table = layer_table
    require_pinned(table_hash, pinned, "klayout_tools.decks sky130 layer table (deck module sha256)")
    cov = drc_report["coverage"]
    deck_layers = set(cov.get("deck_layers") or [])
    counts = layer_counts(layers_doc)
    name_to_lds: dict[str, list[str]] = {}
    ld_to_name: dict[str, str] = {}
    for (layer, datatype), name in sorted(table.items()):
        name_to_lds.setdefault(name, []).append(ld_key(layer, datatype))
        ld_to_name[ld_key(layer, datatype)] = name
    rules_by_id = {r["id"]: r for r in deck_rules.get("rules", [])}

    rule_rows = [classify_rule(e, rules_by_id, name_to_lds, deck_layers, counts) for e in audited_rule_ids(cov)]
    unruled_rows = [classify_unruled(ld, counts, ld_to_name) for ld in cov.get("layers_in_stream_without_rules") or []]

    used_names = sorted({lay["name"] for r in rule_rows for lay in r["deck_layers"]})
    layer_map = {n: (name_to_lds.get(n) or [None])[0] if len(name_to_lds.get(n, [])) == 1 else None for n in used_names}
    checked = list(cov.get("layers_checked") or [])
    unruled = list(cov.get("layers_in_stream_without_rules") or [])
    stream = sorted(counts, key=lambda k: tuple(int(x) for x in k.split("/")))

    def tally(rows, key="verdict"):
        out: dict[str, int] = {}
        for r in rows:
            out[r[key]] = out.get(r[key], 0) + 1
        return dict(sorted(out.items()))

    drc_input = (drc_report.get("provenance") or {}).get("input") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "issue": 281,
        "not_signoff": NOT_SIGNOFF,
        "generator": "layout/bin/verify-whole.py audit (layout/bin/drc_coverage_audit.py)",
        "inputs": {
            "gds": gds_rel,
            "gds_sha256": gds_sha256,
            "top": top,
            "drc_report": drc_rel,
            "drc_report_input_content_hash": drc_input.get("content_hash"),
            "drc_report_input_matches_gds": drc_input.get("content_hash") == "sha256:" + gds_sha256,
            "deck": {
                "name": DECK,
                "content_hash": pinned,
                "rules_source": "klt deck rules --deck sky130 --format json (content_hash verified equal to the pin)",
                "layer_table_source": "klayout_tools.decks.get_layer_names('sky130') from a deck module whose "
                "sha256 equals the pin (klt exposes no layer/datatype for rule layers on its CLI)",
            },
            "counts_source": "klt layers <gds> --top <top> --flattened --include-text --format json",
        },
        "count_semantics": "flattened_shapes: klt's instantiated (hierarchy- and transform-flattened) shape count per "
        "layer/datatype under the top cell, text objects included. geometry = flattened_shapes - text_count: the "
        "polygons/boxes/paths a DRC rule can act on. definition_shapes: shapes in cell definitions, not instantiated.",
        "verdict_conditions": VERDICT_CONDITIONS,
        "unruled_conditions": UNRULED_CONDITIONS,
        "summary": {
            "rules_audited": len(rule_rows),
            "rules_by_verdict": tally(rule_rows),
            "unruled_layers": len(unruled_rows),
            "unruled_by_verdict": tally(unruled_rows),
            "stream_layers": len(stream),
            "stream_layers_checked": len([k for k in stream if k in checked]),
            "stream_layers_unruled": len([k for k in stream if k in unruled]),
            "stream_layers_unaccounted": [k for k in stream if k not in checked and k not in unruled],
        },
        "layer_map": layer_map,
        "rules": rule_rows,
        "unruled_layers": unruled_rows,
    }


def drift(committed: dict, fresh: dict) -> list[str]:
    """Human-readable differences between two audit documents (empty: none)."""
    out = []
    for key in sorted(set(committed) | set(fresh)):
        if committed.get(key) == fresh.get(key):
            continue
        if key == "rules":
            a = {r["rule"]: r for r in committed.get("rules", [])}
            b = {r["rule"]: r for r in fresh.get("rules", [])}
            for rid in sorted(set(a) | set(b)):
                if a.get(rid) != b.get(rid):
                    out.append(f"rules[{rid}]: {_brief(a.get(rid))} -> {_brief(b.get(rid))}")
        elif key == "unruled_layers":
            a = {r["gds"]: r for r in committed.get("unruled_layers", [])}
            b = {r["gds"]: r for r in fresh.get("unruled_layers", [])}
            for ld in sorted(set(a) | set(b)):
                if a.get(ld) != b.get(ld):
                    out.append(f"unruled_layers[{ld}]: {_brief_u(a.get(ld))} -> {_brief_u(b.get(ld))}")
        elif key == "layer_map":
            a, b = committed.get(key) or {}, fresh.get(key) or {}
            for n in sorted(set(a) | set(b)):
                if a.get(n) != b.get(n):
                    out.append(f"layer_map[{n}]: {a.get(n)} -> {b.get(n)}")
        else:
            out.append(f"{key} differs")
    return out


def _brief(r: dict | None) -> str:
    if r is None:
        return "absent"
    lays = ",".join(f"{lay['name']}={lay['gds']}:{lay['geometry']}" for lay in r["deck_layers"])
    return f"{r['verdict']} [{lays}]"


def _brief_u(r: dict | None) -> str:
    if r is None:
        return "absent"
    return f"{r['verdict']} flat={r['flattened_shapes']} text={r['text_count']}"


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------


def markdown(doc: dict) -> str:
    s, inp = doc["summary"], doc["inputs"]
    lines = [
        "# Whole-block DRC coverage audit: inapplicable rules and unruled layers",
        "",
        f"Generated by `{doc['generator']}` (issue #281). Do not edit by hand; `verify-whole.py check` "
        "regenerates it and fails on drift. **" + doc["not_signoff"] + "**",
        "",
        f"- Stream: `{inp['gds']}` `sha256:{inp['gds_sha256'][:12]}…`, top `{inp['top']}`.",
        f"- DRC report audited: `{inp['drc_report']}` (its input hash matches the stream: "
        f"{'yes' if inp['drc_report_input_matches_gds'] else '**NO**'}).",
        f"- Deck: curated `{inp['deck']['name']}` `{inp['deck']['content_hash']}`, the pin in `drc.json` "
        "`provenance.deck.content_hash`. Rule kinds and layers come from `klt deck rules`, layer/datatype "
        "from the deck's own layer table, and both must hash to the pin.",
        f"- Counts: {doc['count_semantics']}",
        "",
        f"**{s['rules_audited']} inapplicable rules:** "
        + ", ".join(f"{n} {v}" for v, n in s["rules_by_verdict"].items())
        + f". **{s['unruled_layers']} unruled stream layers:** "
        + ", ".join(f"{n} {v}" for v, n in s["unruled_by_verdict"].items())
        + f". Stream accounting: {s['stream_layers']} layer/datatype pairs = {s['stream_layers_checked']} read by "
        f"a curated rule + {s['stream_layers_unruled']} unruled"
        + (f", **unaccounted: {s['stream_layers_unaccounted']}**" if s["stream_layers_unaccounted"] else "")
        + ".",
        "",
        "## Verdict conditions",
        "",
    ]
    vc = doc["verdict_conditions"]
    for kind, cond in vc["vacuous-confirmed"].items():
        lines.append(f"- `vacuous-confirmed` for `{kind}`: {cond}.")
    lines += [f"- `residual`: {vc['residual']}.", f"- `unresolved`: {vc['unresolved']}."]
    for v, cond in doc["unruled_conditions"].items():
        lines.append(f"- unruled `{v}`: {cond}.")
    lines += [
        "",
        "## Table 1: rules klt reports as inapplicable",
        "",
        "| rule | check | deck layers | GDS shape count per layer (geometry / flattened) | klt reason | verdict |",
        "|---|---|---|---|---|---|",
    ]
    for r in doc["rules"]:
        names = ", ".join(f"`{lay['name']}`" for lay in r["deck_layers"]) or "-"
        counts = ", ".join(
            f"`{lay['gds']}`: {lay['geometry']} / {lay['flattened_shapes']}" if lay["gds"] else f"`{lay['name']}`: unmapped"
            for lay in r["deck_layers"]
        ) or "-"
        verdict = r["verdict"] if r["verdict"] == "vacuous-confirmed" else f"**{r['verdict']}** ({r['why']})"
        lines.append(f"| `{r['rule']}` | {r['check'] or '-'} | {names} | {counts} | {r['klt_reason'] or '-'} | {verdict} |")
    lines += [
        "",
        "## Table 2: stream layers no curated rule reads",
        "",
        "| layer/datatype | shapes (definition) | shapes (flattened) | text objects | geometry | text-only? | annotation | deck layer name | verdict |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for u in doc["unruled_layers"]:
        to = "-" if u["text_only"] is None else ("yes" if u["text_only"] else "no")
        lines.append(
            f"| `{u['gds']}` | {u['definition_shapes']} | {u['flattened_shapes']} | {u['text_count']} | {u['geometry']} | "
            f"{to} | {'yes' if u['annotation'] else 'no'} | {u['deck_layer_name'] or '-'} | {u['verdict']} |"
        )
    lines += [
        "",
        "`present-unruled` is a residual gap by definition: these shapes are in the stream and no curated rule "
        "checks them. The curated deck's layer table names none of these layer/datatypes, and the audit does not "
        "guess their purpose.",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# controls (synthetic fixtures; run by `verify-whole.py audit-controls` with
# klt, and with stubbed counts by layout/test_verify_whole.py without klt)
# --------------------------------------------------------------------------

CONTROL_TOP = "audit_ctl"


def control_specs() -> list[dict]:
    """Each control: fixture shapes per ``L/D`` (boxes; ``texts`` for text
    objects), the coverage lists klt is pretended to have reported, optional
    stub deck rules, and the expected verdict per audited rule / unruled layer."""
    return [
        {
            "id": "1-absent-layer-vacuous",
            "intent": "single-layer rule whose layer has no shapes -> vacuous-confirmed",
            "boxes": {"68/20": 2},
            "inapplicable": ["dnwell.angle.1"],
            "expect": {"dnwell.angle.1": "vacuous-confirmed"},
        },
        {
            "id": "2-present-layer-residual",
            "intent": "single-layer rule whose layer HAS shapes but klt lists it inapplicable -> residual",
            "boxes": {"64/18": 1, "68/20": 1},
            "inapplicable": ["dnwell.angle.1"],
            "expect": {"dnwell.angle.1": "residual"},
        },
        {
            "id": "2b-text-only-layer-is-not-geometry",
            "intent": "a layer carrying only text objects has geometry 0: rule vacuous, unruled layer text-or-marker-only",
            "boxes": {"68/20": 1},
            "texts": {"64/18": 2, "68/5": 3},
            "inapplicable": ["dnwell.angle.1"],
            "unruled": ["68/5"],
            "expect": {"dnwell.angle.1": "vacuous-confirmed", "68/5": "text-or-marker-only"},
        },
        {
            "id": "3a-rule-not-in-pinned-deck",
            "intent": "rule id absent from the pinned deck -> unresolved",
            "boxes": {"68/20": 1},
            "inapplicable": ["nosuch.width.1"],
            "expect": {"nosuch.width.1": "unresolved"},
        },
        {
            "id": "3b-unmappable-layer",
            "intent": "rule layer the deck layer table cannot resolve -> unresolved even though nothing is drawn",
            "boxes": {"68/20": 1},
            "inapplicable": ["ctl.width.unmapped"],
            "stub_rules": [{"id": "ctl.width.unmapped", "check": "width", "layers": ["nolayer.drawing"]}],
            "expect": {"ctl.width.unmapped": "unresolved"},
        },
        {
            "id": "3c-unsupported-check-kind",
            "intent": "check kind the audit does not understand -> unresolved even though its layer is empty",
            "boxes": {"68/20": 1},
            "inapplicable": ["ctl.density.dnwell"],
            "stub_rules": [{"id": "ctl.density.dnwell", "check": "density", "layers": ["dnwell.drawing"]}],
            "expect": {"ctl.density.dnwell": "unresolved"},
        },
        {
            "id": "4a-two-layer-one-absent",
            "intent": "two-layer enclosing rule, via3 present and capm absent -> vacuous-confirmed",
            "boxes": {"70/44": 3, "70/20": 1},
            "inapplicable": ["capm.enclosing.via3.1", "met3.enclosing.capm.1"],
            "expect": {"capm.enclosing.via3.1": "vacuous-confirmed", "met3.enclosing.capm.1": "vacuous-confirmed"},
        },
        {
            "id": "4b-two-layer-both-present",
            "intent": "two-layer enclosing rule, via3 and capm both present but klt lists it inapplicable -> residual",
            "boxes": {"70/44": 3, "89/44": 1},
            "inapplicable": ["capm.enclosing.via3.1"],
            "expect": {"capm.enclosing.via3.1": "residual"},
        },
        {
            "id": "unruled-present",
            "intent": "an unruled layer with drawn geometry -> present-unruled",
            "boxes": {"68/20": 1, "236/0": 2},
            "inapplicable": [],
            "unruled": ["236/0"],
            "expect": {"236/0": "present-unruled"},
        },
    ]


DRIFT_BASE = {
    "id": "5-drift-base",
    "boxes": {"70/44": 2, "236/0": 1},
    "inapplicable": ["capm.enclosing.via3.1", "dnwell.angle.1"],
    "unruled": ["236/0"],
}


def stub_layers_doc(spec: dict, extra_boxes: dict[str, int] | None = None) -> dict:
    """What ``klt layers --flattened --include-text`` reports for a fixture
    with only top-level shapes (definition == flattened)."""
    boxes = dict(spec.get("boxes") or {})
    for k, n in (extra_boxes or {}).items():
        boxes[k] = boxes.get(k, 0) + n
    texts = spec.get("texts") or {}
    recs = []
    for k in sorted(set(boxes) | set(texts), key=lambda s: tuple(int(x) for x in s.split("/"))):
        n = boxes.get(k, 0) + texts.get(k, 0)
        lay, dt = (int(x) for x in k.split("/"))
        recs.append({"layer": lay, "datatype": dt, "shapes": n, "annotation": False,
                     "flattened_shapes": n, "text_count": texts.get(k, 0)})
    return {"schema_version": 1, "layers": recs}


def write_fixture(path: Path, spec: dict, extra_boxes: dict[str, int] | None = None) -> None:
    import klayout.db as db  # noqa: PLC0415

    ly = db.Layout()
    ly.dbu = 0.001
    top = ly.create_cell(CONTROL_TOP)
    boxes = dict(spec.get("boxes") or {})
    for k, n in (extra_boxes or {}).items():
        boxes[k] = boxes.get(k, 0) + n
    for k, n in boxes.items():
        li = ly.layer(*(int(x) for x in k.split("/")))
        for i in range(n):
            top.shapes(li).insert(db.Box(i * 2000, 0, i * 2000 + 1000, 1000))
    for k, n in (spec.get("texts") or {}).items():
        li = ly.layer(*(int(x) for x in k.split("/")))
        for i in range(n):
            top.shapes(li).insert(db.Text(f"t{i}", db.Trans(db.Point(i * 500, 5000))))
    ly.write(str(path))


def fixture_drc_report(spec: dict, real_drc: dict) -> dict:
    """The committed drc.json, with the coverage lists replaced by the control's."""
    rep = copy.deepcopy(real_drc)
    cov = rep["coverage"]
    cov["inapplicable"] = [{"id": r, "reason": "no_applicable_geometry"} for r in spec.get("inapplicable", [])]
    cov["rules_skipped"] = list(spec.get("inapplicable", []))
    cov["skipped"] = []
    cov["layers_in_stream_without_rules"] = list(spec.get("unruled", []))
    rep["provenance"]["input"] = {"content_hash": "sha256:fixture", "role": "layout"}
    return rep


def fixture_deck_rules(spec: dict, real_rules: dict) -> dict:
    rules = copy.deepcopy(real_rules)
    if spec.get("stub_rules"):
        rules["rules"] = rules["rules"] + copy.deepcopy(spec["stub_rules"])
    return rules


def _audit_fixture(spec, *, real_drc, real_rules, table, layers_doc) -> dict:
    return build_audit(
        drc_report=fixture_drc_report(spec, real_drc), deck_rules=fixture_deck_rules(spec, real_rules),
        layer_table=table, layers_doc=layers_doc, gds_sha256="fixture", gds_rel=f"<fixture {spec['id']}>",
        drc_rel="<fixture coverage>", top=CONTROL_TOP,
    )


def run_controls(*, real_drc: dict, real_rules: dict, table: tuple[str, dict], count_fn) -> dict:
    """Run controls 1-5. *count_fn(spec, extra_boxes)* returns a ``klt
    layers`` document for the fixture (real klt on a written GDS, or the stub)."""
    results = []
    for spec in control_specs():
        doc = _audit_fixture(spec, real_drc=real_drc, real_rules=real_rules, table=table, layers_doc=count_fn(spec, None))
        got = {r["rule"]: r["verdict"] for r in doc["rules"]} | {u["gds"]: u["verdict"] for u in doc["unruled_layers"]}
        ok = all(got.get(k) == v for k, v in spec["expect"].items())
        results.append({"id": spec["id"], "intent": spec["intent"], "fixture": {"boxes": spec.get("boxes", {}),
                        "texts": spec.get("texts", {})}, "expected": spec["expect"],
                        "observed": {k: got.get(k) for k in spec["expect"]}, "passed": ok})

    # control 5: drift. A committed-style document from the base fixture, then
    # one change at a time; each must be caught by the same check `verify-whole.py check` runs.
    base_layers = count_fn(DRIFT_BASE, None)
    committed = _audit_fixture(DRIFT_BASE, real_drc=real_drc, real_rules=real_rules, table=table, layers_doc=base_layers)
    same = drift(committed, _audit_fixture(DRIFT_BASE, real_drc=real_drc, real_rules=real_rules, table=table, layers_doc=base_layers))
    cases = []

    edited = _audit_fixture(DRIFT_BASE, real_drc=real_drc, real_rules=real_rules, table=table,
                            layers_doc=count_fn(DRIFT_BASE, {"236/0": 1}))
    d = drift(committed, edited)
    cases.append({"change": "one polygon added on 236/0 (an unruled layer) in the stream", "caught": bool(d), "drift": d})

    t_hash, t_map = table
    moved = {k: v for k, v in t_map.items() if v != "capm.drawing"}
    moved[(97, 44)] = "capm.drawing"  # plausible-looking wrong mapping (capm2's layer/datatype)
    remapped = _audit_fixture(DRIFT_BASE, real_drc=real_drc, real_rules=real_rules, table=(t_hash, moved), layers_doc=base_layers)
    d = drift(committed, remapped)
    cases.append({"change": "layer map: capm.drawing remapped 89/44 -> 97/44", "caught": bool(d), "drift": d})

    other_rules = copy.deepcopy(real_rules)
    other_rules["content_hash"] = "sha256:" + "0" * 64
    try:
        _audit_fixture(DRIFT_BASE, real_drc=real_drc, real_rules=other_rules, table=table, layers_doc=base_layers)
        msg, caught = "audit ran on a different deck hash", False
    except AuditError as exc:
        msg = str(exc)
        caught = other_rules["content_hash"] in msg and pinned_deck_hash(real_drc) in msg
    cases.append({"change": "klt deck rules reports a different deck content_hash", "caught": caught, "drift": [msg]})

    try:
        _audit_fixture(DRIFT_BASE, real_drc=real_drc, real_rules=real_rules, table=("sha256:" + "1" * 64, t_map), layers_doc=base_layers)
        msg, caught = "audit ran on a different layer-table deck hash", False
    except AuditError as exc:
        msg = str(exc)
        caught = ("sha256:" + "1" * 64) in msg and pinned_deck_hash(real_drc) in msg
    cases.append({"change": "deck layer table comes from a deck module with a different hash", "caught": caught, "drift": [msg]})

    results.append({
        "id": "5-drift",
        "intent": "the drift check must fail on a stream edit, a mapping change, and a deck-hash change, and pass unchanged",
        "fixture": {"boxes": DRIFT_BASE["boxes"], "texts": {}},
        "unchanged_inputs_reproduce": not same,
        "cases": cases,
        "passed": not same and all(c["caught"] for c in cases),
    })
    return {
        "schema_version": SCHEMA_VERSION,
        "issue": 281,
        "not_signoff": NOT_SIGNOFF,
        "deck_content_hash": pinned_deck_hash(real_drc),
        "all_passed": all(r["passed"] for r in results),
        "controls": results,
    }


def controls_markdown(summary: dict, counts_from: str) -> str:
    lines = [
        "# DRC coverage audit controls (issue #281)",
        "",
        summary["not_signoff"],
        "",
        f"Synthetic fixtures (top cell `{CONTROL_TOP}`, boxes and texts only) are audited with the real pinned deck "
        f"(`{summary['deck_content_hash']}`) and its layer table. Coverage lists are stubbed per control, and so are "
        f"deck rules where stated. Shape counts: {counts_from}.",
        "",
        "| control | intent | expected | observed | passed |",
        "|---|---|---|---|---|",
    ]
    for r in summary["controls"]:
        if r["id"] == "5-drift":
            exp = "drift caught for every change; none when unchanged"
            obs = "; ".join(f"{c['change']}: {'caught' if c['caught'] else '**MISSED**'}" for c in r["cases"])
            obs += "; unchanged: " + ("reproduces" if r["unchanged_inputs_reproduce"] else "**DRIFTS**")
        else:
            exp = ", ".join(f"`{k}` {v}" for k, v in r["expected"].items())
            obs = ", ".join(f"`{k}` {v}" for k, v in r["observed"].items())
        lines.append(f"| `{r['id']}` | {r['intent']} | {exp} | {obs} | {'yes' if r['passed'] else '**NO**'} |")
    lines += ["", f"All passed: **{'yes' if summary['all_passed'] else 'NO'}**."]
    return "\n".join(lines) + "\n"


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2) + "\n"
