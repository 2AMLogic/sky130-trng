"""Library half of ``layout/bin/compose-whole.py`` (issue #775): the
PDK-free, ``klayout``-free pure-Python composition logic.

Everything here is text/JSON work -- DEF/RTL/SPICE interface parsing, the
floorplan model and its interface audit, ``klt gen-compose`` request
construction, the response verdict and sanitisation, the combined LVS
reference and its structural check, the interface table / area verdict /
report rendering, and the ``--check`` stable-view diff helpers -- so
``layout/test_compose_whole.py`` exercises it directly on the PR-blocking
CI path with no ``klt``, no PDK and no GDS read. Nothing here imports
``klayout.db`` or ``_gds_geometry`` and nothing runs ``klt``: the
``klayout.db`` geometry audits and the ``klt`` compose/check/DRC driver
stay in the CLI entry point ``layout/bin/compose-whole.py``, which imports
this module by name -- the same seam ``verify_whole_lib.py`` (issue #173,
extended by #495) and ``_gds_geometry.py`` (issue #613) already use, and
the continuation of the ``_klt_common.py`` extraction (#535).

The 32 definitions and their module constants moved verbatim from
``compose-whole.py`` (issue #172): a structural move only -- generated
artifact bytes, error messages and the CLI contract are unchanged.
``BuildError`` / ``load_json`` / ``rel`` come from ``_klt_common``, the
digest helpers from ``_hashing`` (the prefixed ``sha256_file`` /
``sha256_text`` partials moved with the callers that record digests); no
local forks of either.
"""

from __future__ import annotations

import re
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _hashing import sha256_file as _sha256_file, sha256_text as _sha256_text  # noqa: E402
from _klt_common import BuildError, load_json, rel  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

STATUS_PENDING = (
    "composed; physical sign-off pending (#173 DRC/LVS, #174 characterization)"
)

#: Layer number (GDS) -> flat-extraction layer key, met2 and up plus li1/met1.
_LAYER_KEY = {
    (67, 20): "li",
    (68, 20): "m1",
    (69, 20): "m2",
    (70, 20): "m3",
    (71, 20): "m4",
    (72, 20): "m5",
}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


sha256_file = partial(_sha256_file, prefix=True)  # recorded as "sha256:<hex>"
sha256_text = partial(_sha256_text, prefix=True)  # recorded as "sha256:<hex>"


def read_text(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError as exc:
        raise BuildError(f"missing input: {path}") from exc


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise BuildError(f"missing input: {path}")
    return path


def mirror_point(orientation: str, origin: dict, x: float, y: float):
    """Macro-local (x, y) -> composed frame, per klt gen-compose semantics.

    ``mirror_x`` is (x, y) -> (-x, y) about the block's own local origin,
    applied BEFORE the block is translated by ``origin``; ``none`` is the
    identity. Only these two orientations are used by this floorplan.
    """
    if orientation == "mirror_x":
        return round(origin["x"] - x, 6), round(origin["y"] + y, 6)
    if orientation == "none":
        return round(origin["x"] + x, 6), round(origin["y"] + y, 6)
    raise BuildError(f"unsupported orientation {orientation!r} in floorplan")


# --------------------------------------------------------------------------
# digital macro interface: DEF pins, GDS labels, RTL ports
# --------------------------------------------------------------------------

_DEF_UNITS = re.compile(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)")
_DEF_LAYER = re.compile(
    r"\+\s*LAYER\s+(\w+)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)"
)
_DEF_PLACE = re.compile(r"\+\s*(PLACED|FIXED)\s*\(\s*(-?\d+)\s+(-?\d+)\s*\)\s*(\w+)")
_METAL_GDS = {"li1": 67, "met1": 68, "met2": 69, "met3": 70, "met4": 71, "met5": 72}


def parse_def_pins(def_text: str) -> list[dict]:
    """Physical pins from a DEF ``PINS`` section.

    Returns one dict per pin: ``name`` (the pin name = the GDS label),
    ``net``, ``direction``, ``use``, ``layer`` (DEF name), ``layer_gds``
    ((layer, 20)), and ``rects_um`` -- absolute ``(x0, y0, x1, y1)`` boxes
    (the DEF stores each LAYER box relative to the pin's PLACED/FIXED point).
    """
    units = _DEF_UNITS.search(def_text)
    if not units:
        raise BuildError("DEF has no UNITS DISTANCE MICRONS")
    dbu = int(units.group(1))
    section = re.search(r"^PINS\s+\d+\s*;(.*?)^END PINS", def_text, re.S | re.M)
    if not section:
        raise BuildError("DEF has no PINS section")
    pins = []
    for chunk in re.split(r"\n\s*- ", "\n" + section.group(1))[1:]:
        head = re.match(
            r"(\S+)\s*\+\s*NET\s+(\S+)(?:\s*\+\s*SPECIAL)?\s*\+\s*DIRECTION\s+(\w+)"
            r"\s*\+\s*USE\s+(\w+)",
            chunk,
        )
        if not head:
            raise BuildError(f"unparseable DEF pin: {chunk[:80]!r}")
        place = _DEF_PLACE.search(chunk)
        if not place:
            raise BuildError(f"DEF pin {head.group(1)} has no PLACED/FIXED point")
        if place.group(4) != "N":
            raise BuildError(
                f"DEF pin {head.group(1)} is oriented {place.group(4)}, only N is handled"
            )
        px, py = int(place.group(2)), int(place.group(3))
        layers = _DEF_LAYER.findall(chunk)
        if not layers:
            raise BuildError(f"DEF pin {head.group(1)} has no LAYER box")
        names = {name for name, *_ in layers}
        if len(names) != 1:
            raise BuildError(f"DEF pin {head.group(1)} spans layers {sorted(names)}")
        layer = layers[0][0]
        if layer not in _METAL_GDS:
            raise BuildError(f"DEF pin {head.group(1)} on unknown layer {layer}")
        rects = [
            (
                (px + int(x0)) / dbu,
                (py + int(y0)) / dbu,
                (px + int(x1)) / dbu,
                (py + int(y1)) / dbu,
            )
            for _, x0, y0, x1, y1 in layers
        ]
        pins.append(
            {
                "name": head.group(1),
                "net": head.group(2),
                "direction": head.group(3).lower(),
                "use": head.group(4).lower(),
                "layer": layer,
                "layer_gds": [_METAL_GDS[layer], 20],
                "rects_um": rects,
            }
        )
    return pins


def pin_center(pin: dict) -> tuple[float, float]:
    """Centre of the pin's first rectangle (signal pins have exactly one)."""
    x0, y0, x1, y1 = pin["rects_um"][0]
    return round((x0 + x1) / 2, 6), round((y0 + y1) / 2, 6)


def pin_width(pin: dict) -> float:
    x0, y0, x1, y1 = pin["rects_um"][0]
    return round(min(x1 - x0, y1 - y0), 6)


def pin_edge_direction(pin: dict, die_um: tuple[float, float]) -> int:
    """Outward direction of a boundary pin: 180 (west), 270 (south), ..."""
    cx, cy = pin_center(pin)
    dists = {180: cx, 0: die_um[0] - cx, 270: cy, 90: die_um[1] - cy}
    return min(dists, key=dists.get)


def parse_rtl_ports(rtl_text: str) -> list[dict]:
    """Top-module ports ``[{name, direction, msb, lsb}]`` of trng_digital.v."""
    header = re.search(r"module\s+trng_digital\b.*?\)\s*\(\s*(.*?)\)\s*;", rtl_text, re.S)
    if not header:
        raise BuildError("trng_digital.v: module header not found")
    ports = []
    for line in header.group(1).splitlines():
        line = line.split("//")[0].strip().rstrip(",")
        match = re.match(
            r"(input|output)\s+wire\s*(?:\[(\d+):(\d+)\])?\s*(\w+)$", line
        )
        if match:
            msb = int(match.group(2)) if match.group(2) is not None else None
            lsb = int(match.group(3)) if match.group(3) is not None else None
            ports.append(
                {
                    "name": match.group(4),
                    "direction": match.group(1),
                    "msb": msb,
                    "lsb": lsb,
                }
            )
    if not ports:
        raise BuildError("trng_digital.v: no ports parsed")
    return ports


def expand_rtl_bits(ports: list[dict]) -> list[dict]:
    """One row per scalar bit, LSB first for buses: ``bus_addr[0]`` .. ``[3]``."""
    bits = []
    for port in ports:
        if port["msb"] is None:
            bits.append({"name": port["name"], "direction": port["direction"],
                         "base": port["name"], "index": None})
            continue
        low, high = sorted((port["msb"], port["lsb"]))
        for index in range(low, high + 1):
            bits.append(
                {
                    "name": f"{port['name']}[{index}]",
                    "direction": port["direction"],
                    "base": port["name"],
                    "index": index,
                    "width": high - low + 1,
                }
            )
    return bits


def parse_spice_pins(spice_text: str, subckt: str) -> list[dict]:
    """Ports + directions of one ``.subckt`` in an xschem-generated netlist.

    Directions come from the ``*.ipin`` / ``*.opin`` / ``*.iopin`` comment
    lines xschem emits inside the subckt body (the netlist's own record of
    the schematic's pin types); the order is the ``.subckt`` header order.
    """
    lines = spice_text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(rf"^\.subckt\s+{re.escape(subckt)}\b", line, re.I):
            start = index
            break
    if start is None:
        raise BuildError(f".subckt {subckt} not found in the analog reference")
    header = lines[start].split()[2:]
    index = start + 1
    while index < len(lines) and lines[index].startswith("+"):
        header += lines[index][1:].split()
        index += 1
    dirs = {}
    for line in lines[index:]:
        if line.startswith(".ends"):
            break
        match = re.match(r"^\*\.(ipin|opin|iopin)\s+(\S+)", line)
        if match:
            dirs[match.group(2)] = {"ipin": "input", "opin": "output",
                                    "iopin": "inout"}[match.group(1)]
    missing = [name for name in header if name not in dirs]
    if missing:
        raise BuildError(f".subckt {subckt}: no pin-type comment for {missing}")
    return [{"name": name, "direction": dirs[name]} for name in header]


# --------------------------------------------------------------------------
# the model: macros, ports, nets, pads
# --------------------------------------------------------------------------


class Model:
    """Everything derived from floorplan.json + the committed macro artifacts."""

    def __init__(self, fp: dict, spec_dir: Path):
        self.fp = fp
        self.spec_dir = spec_dir
        macros = fp["macros"]
        self.dig = macros["digital"]
        self.ana = macros["analog"]
        self.path = {
            "dig_gds": require_file(spec_dir / self.dig["gds"]),
            "dig_def": require_file(spec_dir / self.dig["def"]),
            "dig_rtl": require_file(spec_dir / self.dig["rtl"]),
            "dig_routed_v": require_file(spec_dir / self.dig["routed_verilog"]),
            "dig_abstract": require_file(spec_dir / self.dig["abstract_spice"]),
            "ana_gds": require_file(spec_dir / self.ana["gds"]),
            "ana_resp": require_file(spec_dir / self.ana["compose_response"]),
            "ana_recipe": require_file(spec_dir / self.ana["compose_recipe"]),
            "ana_spice": require_file(spec_dir / self.ana["reference"]),
        }
        self.pins = parse_def_pins(read_text(self.path["dig_def"]))
        self.rtl_bits = expand_rtl_bits(parse_rtl_ports(read_text(self.path["dig_rtl"])))
        self.ana_pins = parse_spice_pins(
            read_text(self.path["ana_spice"]), self.ana["reference_subckt"]
        )
        die = re.search(r"DIEAREA\s*\(\s*0\s+0\s*\)\s*\(\s*(\d+)\s+(\d+)\s*\)",
                        read_text(self.path["dig_def"]))
        units = int(_DEF_UNITS.search(read_text(self.path["dig_def"])).group(1))
        self.die_um = (int(die.group(1)) / units, int(die.group(2)) / units)
        self.dig_by_name = {pin["name"]: pin for pin in self.pins}
        self.net_by_name = {net["name"]: net for net in fp["nets"]}
        self.shared_digital = {
            net["digital"]
            for net in fp["nets"]
            if net.get("digital") and net["class"] in ("inter_macro", "shared_input")
        }
        self.supply_pins = {"VPWR", "VGND"}
        self.external_digital = [
            bit["name"]
            for bit in self.rtl_bits
            if bit["name"] not in self.shared_digital
        ]

    # -- coordinates --------------------------------------------------

    def dig_xy(self, x: float, y: float):
        return mirror_point(self.dig["orientation"], self.dig["origin_um"], x, y)

    def ana_xy(self, x: float, y: float):
        return mirror_point(self.ana["orientation"], self.ana["origin_um"], x, y)

    def ana_port_global(self, name: str):
        port = self.fp["analog_ports"][name]
        return self.ana_xy(port["x_um"], port["y_um"])

    def pad_global(self, net_name: str):
        """Pad centre: directly above the analog lane it serves."""
        x, _ = self.ana_port_global(self.net_by_name[net_name]["analog"])
        return x, self.fp["pad_row"]["y_um"]

    def dig_port_local(self, rtl_name: str):
        """Digital pin port (macro-local) for the compose request."""
        pin = self.dig_by_name[rtl_name]
        x, y = pin_center(pin)
        return {
            "name": rtl_name,
            "x_um": x,
            "y_um": y,
            "layer": {"layer": pin["layer_gds"][0], "datatype": 20},
            "width_um": pin_width(pin),
            "direction_deg": pin_edge_direction(pin, self.die_um),
        }

    def supply_port_local(self, name: str):
        port = self.fp["digital_supply_ports"][name]
        return {
            "name": name,
            "x_um": port["x_um"],
            "y_um": port["y_um"],
            "layer": {"layer": port["layer"][0], "datatype": port["layer"][1]},
            "width_um": port["width_um"],
            "direction_deg": port["direction_deg"],
        }

    def ana_port_local(self, name: str):
        port = self.fp["analog_ports"][name]
        return {
            "name": name,
            "x_um": port["x_um"],
            "y_um": port["y_um"],
            "layer": {"layer": port["layer"][0], "datatype": port["layer"][1]},
            "width_um": port["width_um"],
            "direction_deg": 90,
        }

    def pad_names(self) -> list[str]:
        return [net["name"] for net in self.fp["nets"] if net.get("pad")]


# --------------------------------------------------------------------------
# interface / coverage audits (pure python)
# --------------------------------------------------------------------------


def audit_interface(model: Model) -> dict:
    """Port coverage, bus-bit mapping and alias consistency.

    Raises BuildError on: a digital RTL bit with no physical pin (or the
    reverse), a duplicate pin, a net that names an analog or digital pin that
    does not exist, a pin claimed by two nets, a missing analog pin, a
    direction conflict between the two macros on a shared net, or conflicting
    aliases (the same whole-block net name given to two nets).
    """
    errors = []
    names = [net["name"] for net in model.fp["nets"]]
    for name in sorted({n for n in names if names.count(n) > 1}):
        errors.append(f"duplicate whole-block net name {name!r}")

    # -- digital: RTL bits <-> DEF pins <-> GDS labels ------------------
    dig_names = [pin["name"] for pin in model.pins]
    for name in sorted({n for n in dig_names if dig_names.count(n) > 1}):
        errors.append(f"duplicate digital physical pin {name!r}")
    rtl_names = [bit["name"] for bit in model.rtl_bits]
    rtl_dups = sorted({n for n in rtl_names if rtl_names.count(n) > 1})
    if rtl_dups:
        errors.append(f"duplicate RTL port bits {rtl_dups}")
    missing_phys = sorted(set(rtl_names) - set(dig_names))
    extra_phys = sorted(set(dig_names) - set(rtl_names) - model.supply_pins)
    if missing_phys:
        errors.append(f"RTL bits without a physical DEF pin: {missing_phys}")
    if extra_phys:
        errors.append(f"DEF pins without an RTL port: {extra_phys}")
    missing_supply = sorted(model.supply_pins - set(dig_names))
    if missing_supply:
        errors.append(f"DEF has no supply pin {missing_supply}")
    dir_of = {bit["name"]: bit["direction"] for bit in model.rtl_bits}
    for pin in model.pins:
        if pin["name"] in dir_of and pin["direction"] != dir_of[pin["name"]]:
            errors.append(
                f"direction conflict on digital pin {pin['name']}: DEF "
                f"{pin['direction']} vs RTL {dir_of[pin['name']]}"
            )

    # -- analog: every .subckt pin accounted for exactly once -------------
    ana_names = [pin["name"] for pin in model.ana_pins]
    ana_dir = {pin["name"]: pin["direction"] for pin in model.ana_pins}
    claimed_ana: dict[str, str] = {}
    claimed_dig: dict[str, str] = {}
    for net in model.fp["nets"]:
        analog = net.get("analog")
        if analog:
            if analog not in ana_dir:
                errors.append(f"net {net['name']}: analog pin {analog!r} does not exist")
            if analog in claimed_ana:
                errors.append(
                    f"analog pin {analog!r} claimed by both {claimed_ana[analog]!r} "
                    f"and {net['name']!r}"
                )
            claimed_ana[analog] = net["name"]
            if analog not in model.fp["analog_ports"]:
                errors.append(f"net {net['name']}: no analog_ports entry for {analog!r}")
        digital = net.get("digital")
        if digital:
            if digital not in dig_names:
                errors.append(f"net {net['name']}: digital pin {digital!r} does not exist")
            if digital in claimed_dig:
                errors.append(
                    f"digital pin {digital!r} claimed by both {claimed_dig[digital]!r} "
                    f"and {net['name']!r}"
                )
            claimed_dig[digital] = net["name"]
            if digital not in model.supply_pins and digital not in dir_of:
                errors.append(f"net {net['name']}: {digital!r} is not an RTL port")
        # alias consistency: a shared net must not rename the analog pin
        if analog and digital and digital not in model.supply_pins:
            if analog != digital or net["name"] != digital:
                errors.append(
                    f"net {net['name']}: conflicting aliases analog {analog!r} / "
                    f"digital {digital!r} (this block keeps one name per shared net)"
                )
        # direction conflict across the two macros on one net
        if analog and digital and digital not in model.supply_pins:
            if ana_dir.get(analog) == "output" and dir_of.get(digital) != "input":
                errors.append(f"net {net['name']}: analog output drives digital non-input")
            if ana_dir.get(analog) == "input" and dir_of.get(digital) != "input":
                errors.append(f"net {net['name']}: both macros drive/receive inconsistently")
    unclaimed_ana = sorted(set(ana_names) - set(claimed_ana))
    if unclaimed_ana:
        errors.append(f"analog trng_top pins not covered by any net: {unclaimed_ana}")
    extra_ana_ports = sorted(set(model.fp["analog_ports"]) - set(claimed_ana))
    if extra_ana_ports:
        errors.append(f"analog_ports entries used by no net: {extra_ana_ports}")
    # every digital signal pin is either a shared net pin or external
    for name in sorted(model.shared_digital):
        if name not in dig_names:
            errors.append(f"shared digital pin {name!r} has no physical pin")
    if model.supply_pins - set(claimed_dig):
        errors.append(
            f"digital supply pins not tied to a net: {sorted(model.supply_pins - set(claimed_dig))}"
        )
    # external digital pins must not collide with whole-block net names
    clash = sorted(set(model.external_digital) & set(names))
    if clash:
        errors.append(f"external digital pin names collide with net names: {clash}")
    if errors:
        raise BuildError("interface audit failed:\n  " + "\n  ".join(errors))
    return {
        "digital_physical_pins": len(model.pins),
        "digital_signal_bits": len(rtl_names),
        "digital_shared_pins": sorted(model.shared_digital),
        "digital_external_pins": len(model.external_digital),
        "analog_pins": len(ana_names),
        "whole_block_nets": len(names),
        "errors": 0,
    }


# --------------------------------------------------------------------------
# the gen-compose request
# --------------------------------------------------------------------------


def vpwr_waypoints(model: Model) -> list[list[float]]:
    """VPWR -> analog vdd: escape west of the digital bbox, run the gap lane."""
    esc = model.fp["vpwr_escape"]
    port = model.fp["digital_supply_ports"]["VPWR"]
    _, port_y = model.dig_xy(port["x_um"], port["y_um"])
    ax, _ = model.ana_port_global("vdd")
    return [
        [esc["lane_x_um"], port_y],
        [esc["lane_x_um"], esc["gap_lane_y_um"]],
        [ax, esc["gap_lane_y_um"]],
    ]


def build_connectivity(model: Model) -> list[dict]:
    """One connectivity[] entry per whole-block net.

    2-pin nets are plain; a net with a boundary pad, or the supplies (digital
    + analog + pad), is a 3-pin bundle whose legs[] are spelled out so the
    tool cannot choose a different spanning tree (and so the VPWR escape and
    the nested-L inter-macro routes are exactly what the floorplan says).
    """
    conn = []

    def pin(block: str, port: str) -> dict:
        return {"block": block, "port": port}

    for net in model.fp["nets"]:
        name = net["name"]
        analog = net["analog"]
        digital = net.get("digital")
        pins, legs = [], []
        if digital:
            pins.append(pin("dig", digital))
        pins.append(pin("ana", analog))
        if net.get("pad"):
            pins.append(pin("pads", f"pad_{name}"))
        if digital and net["class"] in ("inter_macro", "shared_input"):
            ax, _ = model.ana_port_global(analog)
            _, py = model.dig_xy(*pin_center(model.dig_by_name[digital]))
            legs.append({"from_pin": pin("dig", digital), "to_pin": pin("ana", analog),
                         "waypoints_um": [[ax, py]]})
        elif digital in model.supply_pins:
            leg = {"from_pin": pin("dig", digital), "to_pin": pin("ana", analog)}
            if digital == "VPWR":
                leg["waypoints_um"] = vpwr_waypoints(model)
            legs.append(leg)
        if net.get("pad"):
            legs.append({"from_pin": pin("ana", analog), "to_pin": pin("pads", f"pad_{name}")})
        entry = {"net": name, "pins": pins}
        if len(pins) > 2:
            entry["legs"] = legs
        elif legs and "waypoints_um" in legs[0]:
            entry["waypoints_um"] = legs[0]["waypoints_um"]
        conn.append(entry)
    return conn


def pad_draw_params(model: Model) -> dict:
    pr = model.fp["pad_row"]
    half = pr["size_um"] / 2
    shapes = []
    for name in model.pad_names():
        x, y = model.pad_global(name)
        shapes.append(
            {
                "layer": list(pr["layer"]),
                "rect_um": [round(x - half, 6), round(y - half, 6),
                            round(x + half, 6), round(y + half, 6)],
            }
        )
    return {"shapes": shapes}


def build_request(model: Model, *, absolute_inputs: bool) -> dict:
    """The single klt gen-compose request. Paths are repo-relative unless
    ``absolute_inputs`` (the temp-dir rebuild, where relative paths dangle)."""
    pr = model.fp["pad_row"]

    def gds(entry: dict) -> str:
        path = model.spec_dir / entry["gds"]
        return str(path.resolve()) if absolute_inputs else entry["gds"]

    dports = [model.dig_port_local(name) for name in
              sorted(model.shared_digital - model.supply_pins) + model.external_digital]
    dports += [model.supply_port_local(name) for name in sorted(model.supply_pins)]
    aports = [model.ana_port_local(name) for name in model.fp["analog_ports"]]
    pad_ports = []
    for name in model.pad_names():
        x, y = model.pad_global(name)
        pad_ports.append(
            {
                "name": f"pad_{name}",
                "x_um": x,
                "y_um": y,
                "layer": {"layer": pr["layer"][0], "datatype": pr["layer"][1]},
                "width_um": pr["size_um"],
                "direction_deg": 270,
            }
        )
    blocks = [
        {"id": "dig", "orientation": model.dig["orientation"],
         "cell": {"gds_path": gds(model.dig), "cell_name": model.dig["cell_name"], "ports": dports}},
        {"id": "ana", "orientation": model.ana["orientation"],
         "cell": {"gds_path": gds(model.ana), "cell_name": model.ana["cell_name"], "ports": aports}},
        {"id": "pads", "orientation": "none",
         "cell": {"gds_path": f"{pr['cell_name']}.gds", "cell_name": pr["cell_name"], "ports": pad_ports}},
    ]
    pins = [{"net": name, "block": "dig", "port": name} for name in model.external_digital]
    return {
        "pdk": {"variant": "sky130A"},
        "blocks": blocks,
        "placement": {
            "strategy": "explicit",
            "order": ["dig", "ana", "pads"],
            "origins_um": {
                "dig": dict(model.dig["origin_um"]),
                "ana": dict(model.ana["origin_um"]),
                "pads": {"x": 0.0, "y": 0.0},
            },
        },
        "routing": {"layer_role": model.fp["routing"]["layer_role"],
                    "width_um": model.fp["routing"]["width_um"]},
        "connectivity": build_connectivity(model),
        "pins": pins,
        "options": {"cell_name": model.fp["top_cell"], "output": f"{model.fp['top_cell']}.gds"},
    }


# --------------------------------------------------------------------------
# the tool verdict -- errors AND routing verdicts
# --------------------------------------------------------------------------


def verify_compose_response(response: dict, request: dict) -> dict:
    """Reject anything short of a complete routing.

    ``run_klt`` accepts exit 3 / a partial composition on purpose (a single
    unrouted net is "ran fine, here is the bad news" in the body). For a whole
    block that is a failure: every connectivity net must be ``routed`` with
    every leg routed, no leg reason, ``landed_on_block`` true; the tool's own
    ``unrouted_nets`` must be empty; every requested ``pins[]`` promotion must
    be reported; both macros must sit where the floorplan put them.
    """
    problems = []
    if "error" in response:
        problems.append(f"tool error: {response['error'].get('message')}")
    expected = {entry["net"] for entry in request["connectivity"]}
    got = {net["net"] for net in response.get("nets", [])}
    if expected - got:
        problems.append(f"nets missing from the response: {sorted(expected - got)}")
    if got - expected:
        problems.append(f"unexpected nets in the response: {sorted(got - expected)}")
    if response.get("unrouted_nets"):
        problems.append(f"unrouted_nets: {response['unrouted_nets']}")
    for net in response.get("nets", []):
        if net.get("status") != "routed" or not net.get("routed"):
            problems.append(f"net {net['net']}: status {net.get('status')!r}")
        if net.get("landed_on_block") is not True:
            problems.append(f"net {net['net']}: landed_on_block {net.get('landed_on_block')!r}")
        for leg in net.get("legs", []):
            if not leg.get("routed") or leg.get("reason"):
                problems.append(f"net {net['net']}: leg {leg.get('pins')} not routed: {leg.get('reason')}")
            if leg.get("landed_on_block") is not True:
                problems.append(f"net {net['net']}: leg landed_on_block {leg.get('landed_on_block')!r}")
    want_pins = {pin["net"] for pin in request["pins"]}
    got_pins = {pin.get("net") for pin in response.get("pins", [])}
    if want_pins - got_pins:
        problems.append(f"{len(want_pins - got_pins)} pins[] promotions not reported, e.g. {sorted(want_pins - got_pins)[:3]}")
    blocks = {block["id"]: block for block in response.get("blocks", [])}
    for entry in request["blocks"]:
        block = blocks.get(entry["id"])
        want_origin = request["placement"]["origins_um"][entry["id"]]
        if not block:
            problems.append(f"block {entry['id']} missing from the response")
            continue
        if block.get("orientation") != entry["orientation"]:
            problems.append(f"block {entry['id']}: orientation {block.get('orientation')!r}")
        got_origin = block.get("offset_um") or {}
        if (abs(got_origin.get("x", 1e9) - want_origin["x"]) > 1e-6
                or abs(got_origin.get("y", 1e9) - want_origin["y"]) > 1e-6):
            problems.append(f"block {entry['id']}: placed at {got_origin}, floorplan says {want_origin}")
    if problems:
        raise BuildError("composition did not complete:\n  " + "\n  ".join(problems))
    return {
        "nets": len(got),
        "legs": sum(len(net["legs"]) for net in response["nets"]),
        "pins_promoted": len(got_pins),
        "warnings": list(response.get("warnings", [])),
    }


def sanitize_response(response: dict, model: Model) -> None:
    """Replace each block's absolute ``source_path`` with its repo-relative spelling.

    klt resolves every input to an absolute path in its response; committing
    that would leak the builder's home directory into the evidence (the leak
    ``klt env-provenance --scan`` exists to catch) and make --check always
    differ. The stream content is pinned by ``source_digest`` anyway.
    """
    canonical = {
        model.dig["cell_name"]: rel(model.path["dig_gds"]),
        model.ana["cell_name"]: rel(model.path["ana_gds"]),
        model.fp["pad_row"]["cell_name"]: rel(model.spec_dir / f"{model.fp['pad_row']['cell_name']}.gds"),
    }
    for block in response.get("blocks", []):
        if block.get("cell_name") in canonical and "source_path" in block:
            block["source_path"] = canonical[block["cell_name"]]


# --------------------------------------------------------------------------
# post-compose connectivity: per-net terminals in the composed frame
# --------------------------------------------------------------------------


def composed_terminals(model: Model) -> dict[str, list[dict]]:
    """Every terminal of every whole-block net, in the composed frame."""
    terms: dict[str, list[dict]] = {}
    for net in model.fp["nets"]:
        name = net["name"]
        rows = []
        analog = net["analog"]
        port = model.fp["analog_ports"][analog]
        x, y = model.ana_xy(port["x_um"], port["y_um"])
        rows.append({"kind": "analog_port", "name": analog, "x": x, "y": y,
                     "layer": _LAYER_KEY[tuple(port["layer"])]})
        digital = net.get("digital")
        if digital in model.supply_pins:
            sp = model.fp["digital_supply_ports"][digital]
            dx, dy = model.dig_xy(sp["x_um"], sp["y_um"])
            rows.append({"kind": "digital_supply", "name": digital, "x": dx, "y": dy, "layer": "m5"})
        elif digital:
            pin = model.dig_by_name[digital]
            dx, dy = model.dig_xy(*pin_center(pin))
            rows.append({"kind": "digital_pin", "name": digital, "x": dx, "y": dy,
                         "layer": _LAYER_KEY[tuple(pin["layer_gds"])]})
        if net.get("pad"):
            px, py = model.pad_global(name)
            rows.append({"kind": "pad", "name": f"pad_{name}", "x": px, "y": py, "layer": "m5"})
        terms[name] = rows
    return terms


# --------------------------------------------------------------------------
# generated text artifacts
# --------------------------------------------------------------------------


def whole_ports(model: Model) -> list[dict]:
    """Ordered whole-block port list for the reference netlist / table."""
    ports = []
    order = ["vdd", "vss", "clk", "rst_n", "en1", "en2", "en3", "en4",
             "vddr1", "vddr2", "vddr3", "vddr4",
             "ring_bit1", "ring_bit2", "ring_bit3", "ring_bit4"]
    for name in order:
        net = model.net_by_name[name]
        direction = {"external_to_both": "input", "external_to_analog": "input",
                     "analog_to_external": "output"}[net["direction"]]
        if net["class"] in ("logic_supply", "logic_ground", "ring_supply"):
            direction = "inout"
        ports.append({"name": name, "direction": direction, "origin": "analog/shared"})
    for bit in model.rtl_bits:
        if bit["name"] in model.external_digital:
            ports.append({"name": bit["name"], "direction": bit["direction"], "origin": "digital"})
    return ports


def digital_blackbox_ports(model: Model) -> list[str]:
    return ["VPWR", "VGND"] + [bit["name"] for bit in model.rtl_bits]


def build_reference(model: Model) -> str:
    ana_text = read_text(model.path["ana_spice"]).rstrip("\n")
    top = whole_ports(model)
    dig_ports = digital_blackbox_ports(model)
    inst_nets = []
    for name in dig_ports:
        if name == "VPWR":
            inst_nets.append("vdd")
        elif name == "VGND":
            inst_nets.append("vss")
        else:
            inst_nets.append(name)
    ana_args = [pin["name"] for pin in model.ana_pins]
    lines = [
        "* trng_whole -- combined whole-block LVS reference, GENERATED by",
        "* layout/bin/compose-whole.py (issue #172). Do not edit by hand;",
        "* `compose-whole.py --check` fails if this file and its inputs disagree.",
        "*",
        "* Contents: (1) design/trng_top.spice VERBATIM -- the generated analog",
        "* wrapper trng_top (one sampler_core instance) and the transistor-level",
        "* hierarchy under it, unmodified; (2) a BLACK-BOX .subckt trng_digital for",
        "* the standard-cell digital macro; (3) the top .subckt trng_whole that",
        "* instantiates both and names every shared net.",
        "*",
        "* STANDARD-CELL ABSTRACTION. trng_digital is a placed-and-routed",
        "* sky130_fd_sc_hd macro (layout/trng_digital/); its committed layout",
        "* abstract netlist has 0 devices (the standard cells are black boxes to",
        "* klt extract), so the body below is EMPTY. Whole-block LVS (#173) must",
        "* either supply a cell-level digital reference or compare the digital",
        "* instance as a black box; this file does not decide that.",
        "* Port names are the RTL/GDS pin names: bus_rdata[N] is the pin label of",
        "* net bus_rdata_r[N] and startup_done of startup_done_r inside the macro.",
        "*",
        "* SUPPLY / WELL ALIASES. trng_digital's VPWR is whole-block `vdd`, VGND is",
        "* `vss`; its standard-cell VPB/VNB wells are tied to VPWR/VGND inside the",
        "* macro (tap cells), so they are not separate ports here. The four ring",
        "* supplies vddr1..vddr4 reach only the analog macro and stay four nets.",
        "*",
        "* Boundary connectivity: raw_bit / raw_valid (analog outputs) -> digital",
        "* inputs; clk and rst_n are common to both macros; ring enables en1..en4,",
        "* the four ring-bit monitors ring_bit1..ring_bit4 and vddr1..vddr4 are",
        "* analog-only external pins; every other digital port is external.",
        "",
        ana_text,
        "",
        "* digital macro (black box; see STANDARD-CELL ABSTRACTION above)",
        f".subckt trng_digital {' '.join(dig_ports)}",
        ".ends trng_digital",
        "",
        f".subckt trng_whole {' '.join(p['name'] for p in top)}",
        f"xan {' '.join(ana_args)} trng_top",
        f"xdg {' '.join(inst_nets)} trng_digital",
        ".ends trng_whole",
        "",
    ]
    return "\n".join(lines)


def parse_spice_hierarchy(text: str) -> dict[str, dict]:
    """``{subckt: {ports, instances: [(name, nets, callee)]}}`` of a SPICE text.

    A deliberately small structural reader (continuation lines, ``.subckt`` /
    ``.ends``, ``x`` instance cards, ``key=value`` parameters stripped). The
    reference carries xschem parameter expressions (``'cld'``, ``'int(..)'``)
    that klayout's own SPICE reader rejects, so this checks *structure* only:
    hierarchy, port counts and net names -- it does not evaluate devices.
    """
    cards: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+") and cards:
            cards[-1] += " " + line[1:].strip()
        else:
            cards.append(line.strip())
    circuits: dict[str, dict] = {}
    current = None
    for card in cards:
        low = card.lower()
        if low.startswith(".subckt"):
            tokens = [t for t in card.split()[1:] if "=" not in t]
            current = tokens[0].lower()
            if current in circuits:
                raise BuildError(f"reference defines .subckt {current} twice")
            circuits[current] = {"ports": tokens[1:], "instances": []}
        elif low.startswith(".ends"):
            current = None
        elif current and card[0] == "x":  # lower-case x = hierarchy; XM.. = PDK devices
            tokens = [t for t in card.split() if "=" not in t]
            circuits[current]["instances"].append(
                (tokens[0], tokens[1:-1], tokens[-1].lower())
            )
    return circuits


def check_reference_structure(path: Path, model: Model) -> dict:
    """Structural audit of the generated combined reference."""
    circuits = parse_spice_hierarchy(path.read_text())
    errors = []
    for name, circuit in circuits.items():
        for inst, nets, callee in circuit["instances"]:
            if callee not in circuits:
                errors.append(f"{name}.{inst}: undefined subckt {callee}")
            elif len(nets) != len(circuits[callee]["ports"]):
                errors.append(f"{name}.{inst}: {len(nets)} nets for {callee}'s "
                              f"{len(circuits[callee]['ports'])} ports")
    top = circuits.get("trng_whole")
    if top is None:
        raise BuildError("combined reference has no trng_whole subckt")
    if top["ports"] != [p["name"] for p in whole_ports(model)]:
        errors.append("trng_whole port list differs from the interface table")
    if sorted(c for _, _, c in top["instances"]) != ["trng_digital", "trng_top"]:
        errors.append("trng_whole must instantiate exactly trng_top and trng_digital")
    dig = circuits.get("trng_digital")
    if dig is None or dig["ports"] != digital_blackbox_ports(model):
        errors.append("trng_digital black-box ports differ from VPWR/VGND + RTL bits")
    xdg = next((i for i in top["instances"] if i[0] == "xdg"), None)
    if xdg:
        nets = dict(zip(circuits["trng_digital"]["ports"], xdg[1]))
        if nets.get("VPWR") != "vdd" or nets.get("VGND") != "vss":
            errors.append("trng_digital VPWR/VGND must alias vdd/vss")
        for shared in model.shared_digital:
            if nets.get(shared) != shared:
                errors.append(f"digital {shared} not wired to net {shared}")
        for name in model.external_digital:
            if nets.get(name) != name:
                errors.append(f"digital {name} not wired to a same-named top port")
    xan = next((i for i in top["instances"] if i[0] == "xan"), None)
    if xan:
        for pin, net in zip(circuits["trng_top"]["ports"], xan[1]):
            if pin != net:
                errors.append(f"analog pin {pin} wired to net {net}")
    if errors:
        raise BuildError("combined reference audit failed:\n  " + "\n  ".join(errors))
    internal = sorted(
        (set(xdg[1]) | set(xan[1])) - set(top["ports"])
    ) if xdg and xan else []
    return {
        "subckts": sorted(circuits),
        "top_ports": len(top["ports"]),
        "internal_nets": internal,
        "digital_blackbox_devices": 0,
    }


def interface_rows(model: Model) -> dict:
    """Machine-readable interface table (interface.json)."""
    pr = model.fp["pad_row"]
    rows = []
    for net in model.fp["nets"]:
        name = net["name"]
        analog = net["analog"]
        ax, ay = model.ana_port_global(analog)
        port = model.fp["analog_ports"][analog]
        row = {
            "whole_block_pin": name,
            "class": net["class"],
            "direction": net["direction"],
            "analog_pin": analog,
            "analog_port_local_um": {"x": port["x_um"], "y": port["y_um"]},
            "analog_port_composed_um": {"x": ax, "y": ay},
            "analog_port_layer": port["layer"],
            "digital_pin": net.get("digital"),
        }
        digital = net.get("digital")
        if digital in model.supply_pins:
            sp = model.fp["digital_supply_ports"][digital]
            dx, dy = model.dig_xy(sp["x_um"], sp["y_um"])
            row["digital_port_composed_um"] = {"x": dx, "y": dy}
            row["digital_port_layer"] = sp["layer"]
        elif digital:
            pin = model.dig_by_name[digital]
            dx, dy = model.dig_xy(*pin_center(pin))
            row["digital_port_composed_um"] = {"x": dx, "y": dy}
            row["digital_port_layer"] = pin["layer_gds"]
        if net.get("pad"):
            px, py = model.pad_global(name)
            row["boundary_pad"] = {
                "kind": "met5 pad (klt draw)", "x_um": px, "y_um": py,
                "size_um": pr["size_um"], "layer": pr["layer"],
            }
        else:
            row["boundary_pad"] = None
        rows.append(row)
    dig_rows = []
    for bit in model.rtl_bits:
        pin = model.dig_by_name[bit["name"]]
        gx, gy = model.dig_xy(*pin_center(pin))
        is_shared = bit["name"] in model.shared_digital
        dig_rows.append(
            {
                "pin": bit["name"],
                "bus_base": bit["base"],
                "bus_index": bit["index"],
                "direction": bit["direction"],
                "def_net": pin["net"],
                "layer": pin["layer_gds"],
                "macro_local_um": {"x": pin_center(pin)[0], "y": pin_center(pin)[1]},
                "composed_um": {"x": gx, "y": gy},
                "disposition": "shared net with analog macro" if is_shared
                               else "whole-block external pin (label-only promotion)",
            }
        )
    return {
        "schema_version": 1,
        "top_cell": model.fp["top_cell"],
        "analog_trng_top_pins": [
            {"name": p["name"], "direction": p["direction"]} for p in model.ana_pins
        ],
        "whole_block_nets": rows,
        "digital_pins": dig_rows,
        "supply_aliases": {"VPWR": "vdd", "VGND": "vss",
                           "VPB": "VPWR (tap cells inside trng_digital)",
                           "VNB": "VGND (tap cells inside trng_digital)"},
        "analog_macro_has_pin_shapes": False,
        "notes": [
            "sampler_core.gds carries no top-level pin shapes or labels; each analog "
            "boundary connection is a declared port on existing conductor (analog_port_*), "
            "audited against an extraction of the analog GDS.",
            "Whole-block external pins: the 16 boundary pads (pad shapes, label on the "
            "routed net) and the 107 digital pins (label on the digital macro's own pin shape).",
            "raw_bit and raw_valid are macro-to-macro nets with no boundary pin.",
            "Bus bit order: bus_addr[3:0], bus_wdata/bus_rdata/out_data[31:0]; names "
            "are the GDS pin labels (bus index in brackets, bit 0 = LSB).",
        ],
    }


def interface_markdown(table: dict, area: dict) -> str:
    out = [
        "# trng_whole interface table",
        "",
        "GENERATED by `layout/bin/compose-whole.py` from `floorplan.json` and the",
        "committed macro artifacts -- do not edit by hand. Coordinates are",
        "micrometres in the composed (`trng_whole`) frame; `local` columns are in the",
        "macro's own frame. Provisional: composition only, no DRC/LVS (#173) and no",
        "characterization (#174).",
        "",
        "## Whole-block nets served by the analog macro (18 `trng_top` pins)",
        "",
        "| Whole-block pin | Class | Direction | Analog port (local x, y; layer) | Analog port (composed x, y) | Digital pin | Boundary pad (x, y) |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in table["whole_block_nets"]:
        pad = row["boundary_pad"]
        out.append(
            "| `{n}` | {c} | {d} | ({lx}, {ly}); {lay} | ({cx}, {cy}) | {dp} | {pad} |".format(
                n=row["whole_block_pin"], c=row["class"], d=row["direction"],
                lx=row["analog_port_local_um"]["x"], ly=row["analog_port_local_um"]["y"],
                lay="/".join(str(v) for v in row["analog_port_layer"]),
                cx=row["analog_port_composed_um"]["x"], cy=row["analog_port_composed_um"]["y"],
                dp=f"`{row['digital_pin']}`" if row["digital_pin"] else "-",
                pad=f"({pad['x_um']}, {pad['y_um']})" if pad else "- (internal net)",
            )
        )
    out += [
        "",
        "## trng_digital pins (113 physical pins: 111 signals + VPWR/VGND)",
        "",
        "Bit order is the pin label: `bus_addr[0]` is the LSB. A pin that shares a net",
        "with the analog macro is listed above; every other signal pin is a",
        "whole-block external pin of the same name, promoted label-only on the digital",
        "macro's own pin shape.",
        "",
        "| Pin | Dir | Layer | Composed (x, y) | Disposition |",
        "|---|---|---|---|---|",
    ]
    for row in table["digital_pins"]:
        out.append(
            "| `{p}` | {d} | {lay} | ({x}, {y}) | {disp} |".format(
                p=row["pin"], d=row["direction"],
                lay="/".join(str(v) for v in row["layer"]),
                x=row["composed_um"]["x"], y=row["composed_um"]["y"], disp=row["disposition"],
            )
        )
    out += [
        "",
        "## Supply aliases",
        "",
        "`trng_digital.VPWR` = `vdd`, `trng_digital.VGND` = `vss` (also reached by the analog",
        "macro's `vdd`/`vss`); VPB/VNB are tied to VPWR/VGND by tap cells inside the digital",
        "macro. `vddr1`..`vddr4` reach only the analog macro and are four distinct nets.",
        "",
        f"Combined drawn bbox: {area['width_um']} x {area['height_um']} um = "
        f"{area['area_mm2']} mm2 against the unchanged {area['target_mm2']} mm2 target: "
        f"**{area['result']}**.",
        "",
    ]
    return "\n".join(out)


def area_verdict(model: Model, bbox: dict, ana_bbox: dict, dig_bbox: dict) -> dict:
    width = round(bbox["x1"] - bbox["x0"], 6)
    height = round(bbox["y1"] - bbox["y0"], 6)
    area_um2 = round(width * height, 3)
    area_mm2 = round(area_um2 / 1e6, 6)
    target = model.fp["area_target_mm2"]

    def mm2(box: dict) -> float:
        return round((box["x1"] - box["x0"]) * (box["y1"] - box["y0"]) / 1e6, 6)

    return {
        "basis": "axis-aligned bounding box of all drawn (non-text) geometry of the composed top "
                 "cell, routing and pads included, no keep-out/halo/seal ring, vs the README "
                 "'Area < 0.05 mm2' target (unchanged)",
        "bbox_um": bbox,
        "width_um": width,
        "height_um": height,
        "area_um2": area_um2,
        "area_mm2": area_mm2,
        "target_mm2": target,
        "ratio_to_target": round(area_mm2 / target, 3),
        "result": "Met" if area_mm2 < target else "Unmet",
        "macro_bbox_mm2": {"trng_digital": mm2(dig_bbox), "sampler_core": mm2(ana_bbox),
                           "sum": round(mm2(dig_bbox) + mm2(ana_bbox), 6)},
        "note": "trng_digital alone is already "
                f"{mm2(dig_bbox)} mm2 (target {target} mm2): no placement of these two unchanged "
                "macros can meet the target.",
    }


#: The analog macro's committed evidence files whose provenance names the klt
#: build that produced them (compose/DRC/extract/LVS come from one
#: compose-cell.py run; erc.json is a separate `klt erc` read).
ANALOG_EVIDENCE = ("compose.response.json", "drc.json", "extract.json", "lvs.json", "erc.json")


def analog_macro_klt() -> str:
    """Per-artifact klt builds recorded in layout/sampler_core/*.json.

    Read from each committed file's own ``provenance.klt_version`` rather
    than hardcoded, so regenerating the macro (issue #181) can never leave
    this report describing an older build than the one that produced it.
    """
    macro_dir = REPO_ROOT / "layout/sampler_core"
    parts = []
    for name in ANALOG_EVIDENCE:
        provenance = load_json(require_file(macro_dir / name)).get("provenance") or {}
        parts.append(f"{name} {provenance.get('klt_version', 'unrecorded')}")
    return "committed layout/sampler_core/* evidence: " + "; ".join(parts)


def input_hashes(model: Model) -> dict[str, str]:
    paths = {
        "floorplan": model.spec_dir / "floorplan.json",
        **{key: path for key, path in model.path.items()},
        "design_trng_top_sch": REPO_ROOT / "design/xschem/trng_top.sch",
        "digital_tool_pins": REPO_ROOT / "digital/flow/place-and-route/tool-pins.json",
        "layout_pdk": REPO_ROOT / "layout/pdk.json",
    }
    return {rel(p): sha256_file(require_file(p)) for p in paths.values()}


def stable_view(report: dict) -> dict:
    """The fields --check diffs: everything except the tool string, the
    request hash (the temp rebuild feeds absolute input paths) and the binary
    GDS hashes (compared separately, with a timestamp-only allowance)."""
    view = {k: v for k, v in report.items() if k not in ("tool", "request_sha256")}
    view["outputs"] = {
        name: {k: v for k, v in info.items() if not (name.endswith(".gds") and k == "sha256")}
        for name, info in report["outputs"].items()
    }
    return view


def diff_dict(a, b, path="") -> list[str]:
    out = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: only in rebuilt")
            elif key not in b:
                out.append(f"{path}.{key}: only in committed")
            else:
                out += diff_dict(a[key], b[key], f"{path}.{key}")
    elif a != b:
        out.append(f"{path}: committed={a!r} rebuilt={b!r}")
    return out


#: Artifacts a successful build publishes into layout/trng_whole/.
def published_names(fp: dict) -> list[str]:
    top, cell = fp["top_cell"], fp["pad_row"]["cell_name"]
    return [
        f"{top}.gds", f"{cell}.gds", "compose.request.json", "compose.response.json",
        "pins.draw.request.json", "pins.draw.response.json", f"{top}.ref.spice",
        "interface.json", "interface.md", "report.json",
    ]
