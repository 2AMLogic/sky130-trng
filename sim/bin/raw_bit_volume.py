"""Read and verify packed bitstreams from raw-bit volume campaign records."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "layout" / "bin"))
from _hashing import sha256_bytes, sha256_text  # noqa: E402

VOLUME_SLUG = "raw-bit-volume-campaign"


class VolumeInputError(ValueError):
    """A volume-record stream is missing, malformed, truncated or mismatched."""


_HEX_RE = re.compile(r"[0-9a-f]*")


def decode_packed_hex(text: str) -> list[int]:
    """Decode packed lowercase hex, MSB of each byte first (as `pack_hex`)."""
    if len(text) % 2 or not _HEX_RE.fullmatch(text):
        raise VolumeInputError("not an even-length lowercase hex string")
    return [int(c) for byte in bytes.fromhex(text) for c in f"{byte:08b}"]


def load_stream(path: Path, n: int, sha256_hex: str) -> list[int]:
    """Read one packed-hex stream file and verify declared n and hash.

    The source hashes the hex characters without the writer's single
    trailing newline (not the decoded bytes).
    """
    try:
        raw = path.read_text()
    except OSError as exc:
        raise VolumeInputError(f"cannot read {path}: {exc}") from exc
    text = raw[:-1] if raw.endswith("\n") else raw
    digest = sha256_text(text)
    if digest != sha256_hex:
        raise VolumeInputError(
            f"{path.name}: sha256 mismatch (declared {sha256_hex}, got {digest})"
        )
    try:
        bits = decode_packed_hex(text)
    except VolumeInputError as exc:
        raise VolumeInputError(f"{path.name}: {exc}") from exc
    if len(bits) != n:
        raise VolumeInputError(
            f"{path.name}: length mismatch (declared n={n}, decoded {len(bits)})"
        )
    return bits


def load_volume_source(source_json: Path) -> tuple[dict, list[tuple[dict, list[int]]], str]:
    """Return (source record, [(manifest row, bits)], sha256 of source JSON)."""
    source_json = Path(source_json)
    try:
        raw = source_json.read_bytes()
        rec = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise VolumeInputError(f"cannot read source record {source_json}: {exc}") from exc
    for key in ("record_id", "slug", "level", "streams"):
        if key not in rec:
            raise VolumeInputError(f"source record lacks `{key}`")
    if rec["slug"] != VOLUME_SLUG:
        raise VolumeInputError(f"source slug {rec['slug']!r} is not {VOLUME_SLUG!r}")
    if source_json.stem != rec["record_id"]:
        raise VolumeInputError("source file name does not match its record_id")
    if not rec["streams"]:
        raise VolumeInputError("source record has an empty stream manifest")
    runs_dir = source_json.parent.parent / "runs" / rec["record_id"]
    streams = []
    for row in rec["streams"]:
        for key in (
            "corner",
            "temp_c",
            "vdd_v",
            "ts_s",
            "ts_name",
            "seed",
            "file",
            "n",
            "sha256_hex",
        ):
            if key not in row:
                raise VolumeInputError(f"manifest row lacks `{key}`: {row.get('file')}")
        if Path(row["file"]).name != row["file"]:
            raise VolumeInputError(f"manifest file {row['file']!r} is not a bare name")
        streams.append((row, load_stream(runs_dir / row["file"], row["n"], row["sha256_hex"])))
    return rec, streams, sha256_bytes(raw)
