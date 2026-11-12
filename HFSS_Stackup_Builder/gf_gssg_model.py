"""Reusable GSSG gold-finger geometry builder for PyAEDT.

The module can be run directly for a small three-layer demonstration, or the
``build_gssg_project`` function can be called by the stackup GUI.  In the
latter case the complete stackup is supplied as :class:`StackupConfig`; this
module only adds the selected-layer pads, fan-outs and traces.

The standalone builder also creates the GF pad-side terminal ports, a Perfect
E ground bridge, and one wave port at the far end of the differential traces.
No solve is started; the AEDT desktop is intentionally left open.
"""

# Developer: Yetaikunle
# Copyright © 2026 Yetaikunle. All rights reserved.

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from pyaedt import Desktop, Hfss

try:
    from hfss_stackup_builder import (
        Layer, StackupConfig, _create_materials, _identifier, _origin_expression_bottom_up,
        _adjacent_dielectric, _nearest_copper, _validate, height_variable, layer_material_groups,
        create_hfss_analysis, set_copper_transparency,
    )
except ImportError:  # pragma: no cover
    from .hfss_stackup_builder import (
        Layer, StackupConfig, _create_materials, _identifier, _origin_expression_bottom_up,
        _adjacent_dielectric, _nearest_copper, _validate, height_variable, layer_material_groups,
        create_hfss_analysis, set_copper_transparency,
    )


@dataclass
class GSSGConfig:
    """GSSG geometry and selected stackup-layer settings."""

    signal_layer_name: str = "L1"
    gnd_pad_length: str = "2.316mm"
    signal_pad_length: str = "1.45mm"
    gnd_pad_width: str = "380um"
    signal_pad_width: str = "380um"
    gs_gap: str = "220um"
    ss_gap: str = "220um"
    fanout_length: str = "500um"
    trace_length: str = "1.5mm"
    w_line: str = "100um"
    s_line: str = "100um"
    g_line: str = "40um"
    # Deprecated GUI compatibility fields.  They are not written to AEDT and
    # are excluded from the standalone JSON representation below.
    fanout_pad_width: str = "SIGNAL_PAD_WIDTH"
    fanout_trace_width: str = "W_LINE"
    pad_overlap: str = "5um"
    mark1_x: str = "0um"
    mark1_y: str = "0um"
    mark2_x: str = "0um"
    mark2_y: str = "0um"
    mark3_x: str = "0um"
    mark3_y: str = "0um"
    mark4_x: str = "0um"
    mark4_y: str = "0um"
    model_length: str = "3.5mm"
    side_margin: str = "1mm"
    copper_thickness: str = "35um"
    create_open_region: bool = True
    open_region_frequency: str = "60GHz"
    create_setup: bool = True
    create_sweep: bool = True
    sweep_start: str = "0.01GHz"
    sweep_stop: str = "60GHz"
    sweep_points: int = 401

    @classmethod
    def from_dict(cls, data: dict) -> "GSSGConfig":
        """Load the GSSG portion of a GUI/JSON configuration."""
        values = {name: str(data[name]) for name in (
            "signal_layer_name", "gnd_pad_length", "signal_pad_length", "gnd_pad_width",
            "signal_pad_width", "gs_gap", "ss_gap", "fanout_length", "trace_length",
            "w_line", "s_line", "g_line", "pad_overlap", "mark1_x", "mark1_y", "mark2_x", "mark2_y",
            "mark3_x", "mark3_y", "mark4_x", "mark4_y", "model_length", "side_margin",
            "copper_thickness",
            "open_region_frequency", "sweep_start", "sweep_stop",
        ) if name in data}
        for name in ("create_open_region", "create_setup", "create_sweep"):
            if name in data:
                value = data[name]
                values[name] = value if isinstance(value, bool) else str(value).lower() in {
                    "1", "true", "yes", "on"
                }
        if "sweep_points" in data:
            values["sweep_points"] = int(data["sweep_points"])
        return cls(**values)

    def to_dict(self) -> dict:
        """Serialize only the current GSSG fields for the unified GUI JSON."""
        data = asdict(self)
        data.pop("fanout_pad_width", None)
        data.pop("fanout_trace_width", None)
        return data


AEDT_VERSION = ""
DESIGN_NAME = "GSSG_GoldFinger"
PROJECT_PATH = Path(__file__).with_name("gssg_gold_finger.aedt")
KEEP_DESKTOP_OPEN = True
_OPEN_DESKTOPS: list[Desktop] = []

# Direct-script configuration aliases.  Applications should prefer
# ``GSSGConfig``; these names make the file easy to edit for a quick run.
GND_PAD_LENGTH = "2.316mm"
SIGNAL_PAD_LENGTH = "1.45mm"
GND_PAD_WIDTH = "380um"
SIGNAL_PAD_WIDTH = "380um"
GS_GAP = "220um"
SS_GAP = "220um"
FANOUT_LENGTH = "500um"
TRACE_LENGTH = "1.5mm"
W_LINE = "100um"
S_LINE = "100um"
G_LINE = "40um"
PAD_OVERLAP = "5um"
MARK1_X = "0um"
MARK1_Y = "0um"
MARK2_X = "0um"
MARK2_Y = "0um"
MARK3_X = "0um"
MARK3_Y = "0um"
MARK4_X = "0um"
MARK4_Y = "0um"
MODEL_LENGTH = "3.5mm"
SIDE_MARGIN = "1mm"
COPPER_THICKNESS = "35um"

# GF port geometry.  These are kept as AEDT expressions so they can be edited
# in the Variables manager after a project has been generated.
GF_PORT_HEIGHT = "5mil"
GF_PORT_GND_HEIGHT = "10mil"
GF_PORT_TRANSPARENCY = 0.6
GF_PORT_WAVE_WIDTH = "S_LINE+4*W_LINE+6*G_LINE"
# Default three-layer stackup alias.  Stackups with another surface signal
# layer replace this alias in ``_build_stackup_and_gssg``.
GF_PORT_WAVE_PP_H = "PP_L1_H"
GF_PORT_WAVE_HEIGHT = "8*PP_L1_H"
GF_DIFFERENTIAL_IMPEDANCE = 93.0
GF_COMMON_IMPEDANCE = "GF_DIFFERENTIAL_IMPEDANCE/4"


def _default_stackup(config: GSSGConfig) -> StackupConfig:
    return StackupConfig(
        design_name=DESIGN_NAME,
        aedt_version=AEDT_VERSION,
        layers=[
            Layer("L1", "copper", config.copper_thickness, role="signal"),
            Layer("PP_L1", "pp", "100um", 3.5, 0.0),
            Layer("L2", "copper", config.copper_thickness, role="ground"),
        ],
    )


def _set_color(obj: object, rgb: tuple[int, int, int]) -> None:
    """Set an AEDT display color, supporting old and new PyAEDT properties."""
    try:
        obj.color = rgb
    except (AttributeError, TypeError, ValueError):
        try:
            obj.color = "(%d %d %d)" % rgb
        except (AttributeError, TypeError, ValueError):
            pass


def _layer_colors(config: StackupConfig) -> dict[str, tuple[int, int, int]]:
    palette = (
        (220, 120, 40), (40, 145, 220), (70, 175, 95), (180, 90, 205),
        (220, 75, 100), (40, 185, 175), (200, 160, 45), (110, 110, 220),
    )
    copper = [layer for layer in config.layers if layer.kind == "copper"]
    return {layer.name: palette[index % len(palette)] for index, layer in enumerate(copper)}


def _create_pad(hfss: Hfss, name: str, x: str, y: str, length: str, width: str,
                z_origin: str, thickness: str, color: tuple[int, int, int]) -> object:
    pad = hfss.modeler.create_box([x, y, z_origin], [length, width, thickness],
                                  name=name, material="copper")
    if not pad:
        raise RuntimeError(f"Unable to create {name}.")
    _set_color(pad, color)
    return pad


def _create_surface_fanout_and_trace(
    hfss: Hfss, signal_name: str, pad_center_y: str, route_center_y: str,
    color: tuple[int, int, int], z_origin: str,
) -> None:
    """Create one six-point fan-out and its straight continuation.

    Points 1 and 6 are the fixed-width (``W_LINE``) trace ends.  Points 2 and
    5 are the lower/upper line-to-Pad midpoints, controlled by MARK1 and MARK2;
    points 3 and 4 are the Pad-side endpoints, controlled by MARK3 and MARK4.
    P/N use the same MARK values; only their nominal centerline coordinates
    differ.  No automatic sign change is applied to the Y offsets.
    """
    m = hfss.modeler
    points = _fanout_points(pad_center_y, route_center_y, clearance=False)
    trace_y0 = f"({route_center_y})-W_LINE/2"
    trace_y1 = f"({route_center_y})+W_LINE/2"
    z = z_origin
    fanout = m.create_polyline([[x, y, z] for x, y in points], cover_surface=True,
                               close_surface=True, name=f"FANOUT_{signal_name}", material="copper")
    if not fanout:
        raise RuntimeError(f"Unable to create FANOUT_{signal_name}.")
    solid = m.sweep_along_vector(fanout, ["0mm", "0mm", "COPPER_THICKNESS"])
    if not solid:
        raise RuntimeError(f"Unable to sweep FANOUT_{signal_name}.")
    _set_color(solid, color)
    trace = m.create_polyline([
        ["-FANOUT_LENGTH", trace_y0, z],
        ["-FANOUT_LENGTH-TRACE_LENGTH", trace_y0, z],
        ["-FANOUT_LENGTH-TRACE_LENGTH", trace_y1, z],
        ["-FANOUT_LENGTH", trace_y1, z],
    ], cover_surface=True, close_surface=True, name=f"TRACE_{signal_name}", material="copper")
    if not trace:
        raise RuntimeError(f"Unable to create TRACE_{signal_name}.")
    trace_solid = m.sweep_along_vector(trace, ["0mm", "0mm", "COPPER_THICKNESS"])
    if not trace_solid:
        raise RuntimeError(f"Unable to sweep TRACE_{signal_name}.")
    _set_color(trace_solid, color)
    if not m.unite([f"SIG_PAD_{signal_name}", f"FANOUT_{signal_name}", f"TRACE_{signal_name}"]):
        raise RuntimeError(f"Unable to unite SIG_PAD_{signal_name} fan-out and trace.")
    _set_color(m[f"SIG_PAD_{signal_name}"], color)


def _fanout_points(pad_center_y: str, route_center_y: str, clearance: bool = False) -> list[tuple[str, str]]:
    """Return the six XY points for a fanout or its outer clearance envelope."""
    trace_y0 = f"({route_center_y})-W_LINE/2"
    trace_y1 = f"({route_center_y})+W_LINE/2"
    pad_y0 = f"({pad_center_y})-SIGNAL_PAD_WIDTH/2"
    pad_y1 = f"({pad_center_y})+SIGNAL_PAD_WIDTH/2"
    if clearance:
        lower_pad_y = f"({pad_y0})+MARK3_Y-G_LINE"
        upper_pad_y = f"({pad_y1})+MARK4_Y+G_LINE"
        lower_trace_y = f"({trace_y0})-G_LINE"
        upper_trace_y = f"({trace_y1})+G_LINE"
        lower_mid_y = f"(({trace_y0})+({pad_y0}))/2+MARK1_Y-G_LINE"
        upper_mid_y = f"(({trace_y1})+({pad_y1}))/2+MARK2_Y+G_LINE"
    else:
        lower_pad_y = f"({pad_y0})+MARK3_Y"
        upper_pad_y = f"({pad_y1})+MARK4_Y"
        lower_trace_y, upper_trace_y = trace_y0, trace_y1
        lower_mid_y = f"(({trace_y0})+({pad_y0}))/2+MARK1_Y"
        upper_mid_y = f"(({trace_y1})+({pad_y1}))/2+MARK2_Y"
    midpoint_x = "(-FANOUT_LENGTH+PAD_OVERLAP)/2"
    return [
        ("-FANOUT_LENGTH", lower_trace_y),
        (f"{midpoint_x}+MARK1_X", lower_mid_y),
        ("PAD_OVERLAP+MARK3_X", lower_pad_y),
        ("PAD_OVERLAP+MARK4_X", upper_pad_y),
        (f"{midpoint_x}+MARK2_X", upper_mid_y),
        ("-FANOUT_LENGTH", upper_trace_y),
    ]


def _create_surface_ground(
    hfss: Hfss, color: tuple[int, int, int], z_origin: str,
    p_pad_center_y: str, p_route_center_y: str,
    n_pad_center_y: str, n_route_center_y: str, ground_name: str,
) -> None:
    """Create full L1 copper and subtract straight and fanout clearances."""
    m = hfss.modeler
    pair_center = "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP/2"
    ground = m.create_box(
        ["BOARD_X0", "0mm", z_origin],
        ["BOARD_LENGTH_TOTAL", "BOARD_WIDTH", "COPPER_THICKNESS"],
        name=ground_name, material="copper",
    )
    if not ground:
        raise RuntimeError(f"Unable to create {ground_name}.")
    _set_color(ground, color)

    # Remove the complete Pad-side part of the plane first.  The resulting
    # L1 ground still starts as one full copper sheet, but never overlaps the
    # four Pad bodies that begin at X=0.
    pad_region = m.create_box(
        ["0mm", "0mm", z_origin],
        ["MODEL_LENGTH", "BOARD_WIDTH", "COPPER_THICKNESS"],
        name="GND_PAD_REGION_CLEARANCE", material="vacuum",
    )
    if not pad_region or not m.subtract(ground, pad_region, keep_originals=False):
        raise RuntimeError("Unable to remove the Pad-side ground region.")

    # Straight CPWG opening: S + 2W + 2G, from the trace end to fanout start.
    straight = m.create_box(
        ["BOARD_X0", f"({pair_center})-(S_LINE+2*W_LINE+2*G_LINE)/2", z_origin],
        ["TRACE_LENGTH", "S_LINE+2*W_LINE+2*G_LINE", "COPPER_THICKNESS"],
        name="GND_STRAIGHT_CLEARANCE", material="vacuum",
    )
    if not straight or not m.subtract(ground, straight, keep_originals=False):
        raise RuntimeError("Unable to subtract straight surface-ground clearance.")

    # Fanout opening: P lower contour followed by N upper contour.  This is
    # an outer envelope, so the full L1 plane remains on both outer sides.
    p_points = _fanout_points(p_pad_center_y, p_route_center_y, clearance=True)
    n_points = _fanout_points(n_pad_center_y, n_route_center_y, clearance=True)
    envelope = [p_points[0], p_points[1], p_points[2], n_points[3], n_points[4], n_points[5]]
    sheet = m.create_polyline([[x, y, z_origin] for x, y in envelope], cover_surface=True,
                              close_surface=True, name="GND_FANOUT_CLEARANCE", material="vacuum")
    if not sheet:
        raise RuntimeError("Unable to create fanout surface-ground clearance.")
    clearance_solid = m.sweep_along_vector(sheet, ["0mm", "0mm", "COPPER_THICKNESS"])
    if not clearance_solid or not m.subtract(ground, clearance_solid, keep_originals=False):
        raise RuntimeError("Unable to subtract fanout surface-ground clearance.")
    _set_color(m[ground_name], color)


def _set_transparency(obj: object, value: float) -> None:
    """Set display transparency while tolerating PyAEDT object variants."""
    try:
        obj.transparency = value
    except (AttributeError, TypeError, ValueError):
        pass


def _create_gf_ports(
    hfss: Hfss,
    signal_z: str,
    ground_name: str,
    reference_ground_names: list[str],
    p_pad_center_y: str,
    n_pad_center_y: str,
    pair_center_y: str,
    differential_impedance: float,
    common_impedance: float,
    wave_z0: str = "0mm",
) -> None:
    """Create GF terminal ports, the recorded PEC bridge, and a wave port."""
    m = hfss.modeler
    port_z0 = f"({signal_z})+COPPER_THICKNESS"
    port_x = "SIGNAL_PAD_LENGTH"
    p_y0 = f"({p_pad_center_y})-SIGNAL_PAD_WIDTH/2"
    n_y0 = f"({n_pad_center_y})-SIGNAL_PAD_WIDTH/2"

    # For a YZ rectangle PyAEDT maps sizes[0] to YSize and sizes[1] to ZSize.
    # Therefore the signal-pad width must be passed first and the 5 mil height
    # second.
    port_p = m.create_rectangle(
        "YZ", [port_x, p_y0, port_z0],
        ["SIGNAL_PAD_WIDTH", "GF_PORT_HEIGHT"], name="PORT_P_SHEET",
    )
    port_n = m.create_rectangle(
        "YZ", [port_x, n_y0, port_z0],
        ["SIGNAL_PAD_WIDTH", "GF_PORT_HEIGHT"], name="PORT_N_SHEET",
    )
    if not port_p or not port_n:
        raise RuntimeError("Unable to create GF pad-side port sheets.")

    # Build one 10-mil-high YZ bridge from the inner edge of the left GND Pad
    # to the inner edge of the right GND Pad.  The central subtracting sheet
    # reproduces Rectangle4 from GF_lumped.py and leaves only the two side
    # regions connected to the GND pads.
    bridge_x = port_x
    bridge_y0 = "SIDE_MARGIN"
    # Include both GND pad widths: the bridge runs from the outer edge of the
    # left GND pad to the inner edge of the right GND pad, matching Rectangle1
    # in GF_lumped.py (default span: 2.18 mm).
    bridge = m.create_rectangle(
        "YZ", [bridge_x, bridge_y0, port_z0],
        ["2*GND_PAD_WIDTH+2*GS_GAP+2*SIGNAL_PAD_WIDTH+SS_GAP", "GF_PORT_GND_HEIGHT"],
        name="GF_GND_BRIDGE",
    )
    if not bridge:
        raise RuntimeError("Unable to create GF_GND_BRIDGE.")
    central_clearance = m.create_rectangle(
        "YZ", [bridge_x, "SIDE_MARGIN+GND_PAD_WIDTH", port_z0],
        # This is the temporary Boolean tool for the signal opening; it is
        # only as tall as the signal terminal sheet, not the full ground
        # bridge.
        ["2*GS_GAP+2*SIGNAL_PAD_WIDTH+SS_GAP", "GF_PORT_HEIGHT"],
        name="GF_GND_BRIDGE_CLEARANCE",
    )
    if not central_clearance or not m.subtract(bridge, central_clearance, keep_originals=False):
        raise RuntimeError("Unable to cut the central signal opening from GF_GND_BRIDGE.")
    _set_color(bridge, (128, 255, 255))
    _set_transparency(bridge, GF_PORT_TRANSPARENCY)
    if not hfss.assign_perfect_e("GF_GND_BRIDGE", name="GF_GND_BRIDGE_PEC"):
        raise RuntimeError("Unable to assign Perfect E to GF ground bridge.")

    if not hfss.lumped_port(
        port_p, reference=bridge, create_port_sheet=False,
        impedance=50, name="GF_PORT_P", terminals_rename=True,
    ):
        raise RuntimeError("Unable to assign GF_PORT_P lumped port.")
    if not hfss.lumped_port(
        port_n, reference=bridge, create_port_sheet=False,
        impedance=50, name="GF_PORT_N", terminals_rename=True,
    ):
        raise RuntimeError("Unable to assign GF_PORT_N lumped port.")

    # One wave port is placed at the remote end of the two traces.  For this
    # surface-line geometry its Z extent is eight times the adjacent PP/Core
    # thickness, rather than the complete stackup height.
    wave = m.create_rectangle(
        "YZ", ["BOARD_X0", f"({pair_center_y})-GF_PORT_WAVE_WIDTH/2", wave_z0],
        ["GF_PORT_WAVE_WIDTH", "GF_PORT_WAVE_HEIGHT"], name="GF_WAVE_PORT_SHEET",
    )
    if not wave:
        raise RuntimeError("Unable to create GF wave-port sheet.")
    refs = list(dict.fromkeys([ground_name, *reference_ground_names]))
    refs = [name for name in refs if name and name in m.object_names]
    if not refs:
        raise RuntimeError("No reference ground objects available for GF wave port.")
    if not hfss.wave_port(
        wave, reference=refs, create_port_sheet=False, modes=2,
        impedance=50, name="GF_WAVE_PORT", terminals_rename=True,
    ):
        raise RuntimeError("Unable to assign GF_WAVE_PORT wave port.")

    # Terminal P/N ports form the local differential pair.  Newer AEDT
    # versions expose terminal suffixes; retain a fallback for versions that
    # keep the boundary names unchanged.
    pair_candidates = (("GF_PORT_P_T1", "GF_PORT_N_T1"), ("GF_PORT_P", "GF_PORT_N"))
    for assignment, reference in pair_candidates:
        if hfss.set_differential_pair(
            assignment=assignment, reference=reference,
            common_mode="Comm1", differential_mode="Diff1",
            common_reference=common_impedance,
            differential_reference=differential_impedance,
            active=True, matched=False,
        ):
            break
    else:
        raise RuntimeError("Unable to create GF Diff1/Comm1 differential pair.")


def _build_stackup_and_gssg(hfss: Hfss, stackup: StackupConfig, gssg: GSSGConfig) -> None:
    signal = next((x for x in stackup.layers if x.name == gssg.signal_layer_name and x.kind == "copper"), None)
    if signal is None:
        raise ValueError(f"GSSG signal layer {gssg.signal_layer_name!r} is not a copper layer.")
    bottom_up = list(reversed(stackup.layers))
    mapping = layer_material_groups(stackup)
    _create_materials(hfss, stackup, mapping)
    colors = _layer_colors(stackup)
    modeler = hfss.modeler
    modeler.model_units = "mm"
    for name, value in {
        "GND_PAD_LENGTH": gssg.gnd_pad_length, "SIGNAL_PAD_LENGTH": gssg.signal_pad_length,
        "GND_PAD_WIDTH": gssg.gnd_pad_width, "SIGNAL_PAD_WIDTH": gssg.signal_pad_width,
        "GS_GAP": gssg.gs_gap, "SS_GAP": gssg.ss_gap, "FANOUT_LENGTH": gssg.fanout_length,
        "TRACE_LENGTH": gssg.trace_length, "W_LINE": gssg.w_line, "S_LINE": gssg.s_line, "G_LINE": gssg.g_line,
        "PAD_OVERLAP": gssg.pad_overlap, "SIDE_MARGIN": gssg.side_margin, "MODEL_LENGTH": gssg.model_length,
    }.items():
        hfss[name] = value
    for name, value in (("MARK1_X", gssg.mark1_x), ("MARK1_Y", gssg.mark1_y),
                        ("MARK2_X", gssg.mark2_x), ("MARK2_Y", gssg.mark2_y),
                        ("MARK3_X", gssg.mark3_x), ("MARK3_Y", gssg.mark3_y),
                        ("MARK4_X", gssg.mark4_x), ("MARK4_Y", gssg.mark4_y)):
        hfss[name] = value
    for layer in stackup.layers:
        hfss[height_variable(layer)] = layer.thickness
    # Fan-out/trace sweeps use one common name.  In stackup mode the actual
    # copper thickness is stored as L1_H/L2_H/etc., so expose a stable alias
    # that always follows the selected GSSG copper layer.
    hfss["COPPER_THICKNESS"] = height_variable(signal)
    hfss["BOARD_WIDTH"] = "2*SIDE_MARGIN+2*GND_PAD_WIDTH+2*SIGNAL_PAD_WIDTH+2*GS_GAP+SS_GAP"
    hfss["BOARD_LENGTH_TOTAL"] = "MODEL_LENGTH+FANOUT_LENGTH+TRACE_LENGTH"
    hfss["BOARD_X0"] = "-(FANOUT_LENGTH+TRACE_LENGTH)"
    hfss["BOARD_THICKNESS"] = "+".join(height_variable(x) for x in bottom_up)
    hfss["GF_PORT_HEIGHT"] = GF_PORT_HEIGHT
    hfss["GF_PORT_GND_HEIGHT"] = GF_PORT_GND_HEIGHT
    hfss["GF_PORT_WAVE_WIDTH"] = GF_PORT_WAVE_WIDTH
    # The selected GSSG layer is an external (surface) line.  Keep the wave
    # port's vertical size tied to the adjacent PP/Core thickness instead of
    # spanning the complete imported stackup.  The default L1 stackup keeps
    # the documented literal ``8*PP_L1_H``; other surface layers use the
    # stable PP-height alias.
    wave_dielectric = _adjacent_dielectric(stackup, stackup.layers.index(signal))
    wave_pp_height = height_variable(wave_dielectric)
    hfss["GF_PORT_WAVE_PP_H"] = wave_pp_height
    hfss["GF_PORT_WAVE_HEIGHT"] = (
        GF_PORT_WAVE_HEIGHT if wave_pp_height == GF_PORT_WAVE_PP_H
        else "8*GF_PORT_WAVE_PP_H"
    )
    # For GF+topline, the wave port starts at the lower face of the inward
    # reference copper (normally L2) and extends upward through the PP and
    # top-line region.  In the default three-layer stackup this expression is
    # simply 0mm because L2 is the bottom layer.
    signal_index = stackup.layers.index(signal)
    reference_direction = 1 if signal_index == 0 else -1
    wave_reference = _nearest_copper(stackup, signal_index, reference_direction)
    wave_z0 = _origin_expression_bottom_up(bottom_up, wave_reference.name)
    hfss["GF_PORT_WAVE_Z0"] = wave_z0
    hfss["GF_DIFFERENTIAL_IMPEDANCE"] = str(stackup.differential_impedance)
    hfss["GF_COMMON_IMPEDANCE"] = str(stackup.common_impedance)

    z_origin = "0mm"
    reference_ground_names: list[str] = []
    for layer in bottom_up:
        h = height_variable(layer)
        if layer.kind in {"pp", "core"}:
            obj = modeler.create_box(["BOARD_X0", "0mm", z_origin], ["BOARD_LENGTH_TOTAL", "BOARD_WIDTH", h],
                                     name=_identifier(layer.name), material=mapping[layer.name])
            if not obj:
                raise RuntimeError(f"Unable to create {layer.name}.")
            obj.display_wireframe = True
        elif layer.name != signal.name:
            # Keep the original standalone object's stable name while using
            # layer-specific names for a full imported stackup.
            ground_name = "REFERENCE_GND" if len(stackup.layers) == 3 else f"GND_{_identifier(layer.name)}"
            obj = modeler.create_box(["BOARD_X0", "0mm", z_origin], ["BOARD_LENGTH_TOTAL", "BOARD_WIDTH", h],
                                     name=ground_name, material="copper")
            if not obj:
                raise RuntimeError(f"Unable to create {layer.name} copper.")
            _set_color(obj, colors[layer.name])
            reference_ground_names.append(ground_name)
        z_origin = f"({z_origin})+{h}"

    signal_z = _origin_expression_bottom_up(bottom_up, signal.name)
    color = colors[signal.name]
    y_gnd_l = "SIDE_MARGIN"
    y_sig_p = "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP"
    y_sig_n = "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP"
    y_gnd_r = "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP+SIGNAL_PAD_WIDTH+GS_GAP"
    thickness = height_variable(signal)
    _create_pad(hfss, "GND_PAD_L", "0mm", y_gnd_l, "GND_PAD_LENGTH", "GND_PAD_WIDTH", signal_z, thickness, color)
    _create_pad(hfss, "SIG_PAD_P", "0mm", y_sig_p, "SIGNAL_PAD_LENGTH", "SIGNAL_PAD_WIDTH", signal_z, thickness, color)
    _create_pad(hfss, "SIG_PAD_N", "0mm", y_sig_n, "SIGNAL_PAD_LENGTH", "SIGNAL_PAD_WIDTH", signal_z, thickness, color)
    _create_pad(hfss, "GND_PAD_R", "0mm", y_gnd_r, "GND_PAD_LENGTH", "GND_PAD_WIDTH", signal_z, thickness, color)
    pair_center = "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP/2"
    _create_surface_fanout_and_trace(hfss, "P", "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH/2",
                                      f"({pair_center})-(W_LINE+S_LINE)/2", color, signal_z)
    _create_surface_fanout_and_trace(hfss, "N", "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP+SIGNAL_PAD_WIDTH/2",
                                      f"({pair_center})+(W_LINE+S_LINE)/2", color, signal_z)
    ground_name = "GND_L1" if signal.name == "L1" else f"GND_{_identifier(signal.name)}"
    _create_surface_ground(
        hfss, color, signal_z,
        "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH/2",
        f"({pair_center})-(W_LINE+S_LINE)/2",
        "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP+SIGNAL_PAD_WIDTH/2",
        f"({pair_center})+(W_LINE+S_LINE)/2", ground_name,
    )
    _create_gf_ports(
        hfss, signal_z, ground_name, reference_ground_names,
        "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH/2",
        "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP+SIGNAL_PAD_WIDTH/2",
        pair_center,
        stackup.differential_impedance,
        stackup.common_impedance,
        wave_z0,
    )


def build_gssg_project(stackup_config: StackupConfig, gssg_config: GSSGConfig,
                       project_path: str | Path, keep_desktop_open: bool = True,
                       log_callback=None) -> Path:
    """Build GSSG geometry on ``gssg_config.signal_layer_name``."""
    # Surface GF owns its own reference/port construction.  The reference
    # selectors on the stackup-differential tab must not gate this builder.
    _validate(stackup_config, validate_references=False)
    project_path = Path(project_path)
    if project_path.exists():
        raise FileExistsError(f"Output project already exists: {project_path}")
    desktop = None
    try:
        version = stackup_config.aedt_version.strip() or None
        desktop = Desktop(version=version, non_graphical=False, new_desktop=False, close_on_exit=False)
        if keep_desktop_open:
            _OPEN_DESKTOPS.append(desktop)
        hfss = Hfss(project=str(project_path), design=stackup_config.design_name,
                    solution_type="Terminal", version=version, new_desktop=False, close_on_exit=False,
                    aedt_process_id=desktop.aedt_process_id)
        _build_stackup_and_gssg(hfss, stackup_config, gssg_config)
        create_hfss_analysis(
            hfss,
            create_open_region=gssg_config.create_open_region,
            open_region_frequency=gssg_config.open_region_frequency,
            create_setup=gssg_config.create_setup,
            create_sweep=gssg_config.create_sweep,
            sweep_start=gssg_config.sweep_start,
            sweep_stop=gssg_config.sweep_stop,
            sweep_points=gssg_config.sweep_points,
        )
        set_copper_transparency(hfss)
        if not hfss.save_project(project_path, overwrite=False):
            raise RuntimeError(f"Unable to save project: {project_path}")
        hfss.modeler.fit_all()
        if log_callback:
            log_callback(f"Project created: {project_path}")
        return project_path
    finally:
        if desktop and not keep_desktop_open:
            desktop.release_desktop(close_projects=False, close_on_exit=False)


def build_project() -> Path:
    """Backward-compatible direct entry point using a minimal stackup."""
    config = GSSGConfig(
        gnd_pad_length=GND_PAD_LENGTH, signal_pad_length=SIGNAL_PAD_LENGTH,
        gnd_pad_width=GND_PAD_WIDTH, signal_pad_width=SIGNAL_PAD_WIDTH,
        gs_gap=GS_GAP, ss_gap=SS_GAP, fanout_length=FANOUT_LENGTH,
        trace_length=TRACE_LENGTH, w_line=W_LINE, s_line=S_LINE,
        g_line=G_LINE,
        pad_overlap=PAD_OVERLAP, mark1_x=MARK1_X, mark1_y=MARK1_Y,
        mark2_x=MARK2_X, mark2_y=MARK2_Y, mark3_x=MARK3_X, mark3_y=MARK3_Y,
        mark4_x=MARK4_X, mark4_y=MARK4_Y, model_length=MODEL_LENGTH,
        side_margin=SIDE_MARGIN, copper_thickness=COPPER_THICKNESS,
    )
    return build_gssg_project(_default_stackup(config), config, PROJECT_PATH, KEEP_DESKTOP_OPEN)


if __name__ == "__main__":
    build_project()
