"""Build a top-layer GF pad transition into an inner-layer differential line.

The model intentionally differs from :mod:`gf_gssg_model`: when the selected
line is internal, L1 contains the four isolated GF pads, their local terminal
port bridge, and a ground plane cleared away from every pad.  There is no L1
fanout or topline.  P/N signal vias and solid GND return columns connect the
pads to the inner differential structure and its reference planes.  Two rows
of additional return columns flank the inner traces.  A single two-mode wave
port is placed at the remote end of the inner line.

An optional open radiation region, adaptive setup, and interpolating sweep are
created, but no solve is started.  The module can be called with an existing
``StackupConfig`` or run directly with the shared eight-layer example.
"""

# Developer: 39004628 / Luxshare
# Copyright © 2026 39004628 / Luxshare. All rights reserved.

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import floor
from pathlib import Path

from pyaedt import Desktop, Hfss

try:
    from hfss_stackup_builder import (
        Layer,
        StackupConfig,
        _create_materials,
        _adjacent_dielectric,
        _identifier,
        _nearest_copper,
        _origin_expression_bottom_up,
        _port_reference_conductors,
        _validate,
        create_hfss_analysis,
        eight_layer_example,
        height_variable,
        layer_material_groups,
        set_copper_transparency,
    )
    from gf_gssg_model import (
        GSSGConfig,
        GF_COMMON_IMPEDANCE,
        GF_DIFFERENTIAL_IMPEDANCE,
        GF_PORT_GND_HEIGHT,
        GF_PORT_HEIGHT,
        GF_PORT_TRANSPARENCY,
        GF_PORT_WAVE_WIDTH,
        _layer_colors,
        _set_color,
        _set_transparency,
    )
except ImportError:  # pragma: no cover
    from .hfss_stackup_builder import (
        Layer,
        StackupConfig,
        _create_materials,
        _adjacent_dielectric,
        _identifier,
        _nearest_copper,
        _origin_expression_bottom_up,
        _port_reference_conductors,
        _validate,
        create_hfss_analysis,
        eight_layer_example,
        height_variable,
        layer_material_groups,
        set_copper_transparency,
    )
    from .gf_gssg_model import (
        GSSGConfig,
        GF_COMMON_IMPEDANCE,
        GF_DIFFERENTIAL_IMPEDANCE,
        GF_PORT_GND_HEIGHT,
        GF_PORT_HEIGHT,
        GF_PORT_TRANSPARENCY,
        GF_PORT_WAVE_WIDTH,
        _layer_colors,
        _set_color,
        _set_transparency,
    )


@dataclass
class InnerGFConfig:
    """Parameters specific to the L1-GF to inner-layer transition."""

    gf_layer_name: str = "L1"
    inner_signal_layer_name: str = "L2"
    upper_reference_layer_name: str = ""
    lower_reference_layer_name: str = ""
    via_pad_radius: str = "0.127mm"
    via_column_radius: str = "0.057mm"
    via_antipad_radius: str = "10mil"
    via_antipad_x: str = "10mil"
    layer_antipads: dict[str, dict[str, str]] = field(default_factory=dict)
    mechanical_via_enabled: bool = False
    mechanical_start_layer: str = ""
    mechanical_end_layer: str = ""
    mechanical_column_radius: str = "3mil"
    mechanical_pad_radius: str = "6mil"
    d_via: str = "0.5mm"
    via_x_offset: str = "SIGNAL_PAD_LENGTH/4"
    pad_void_x1: str = "150um"
    pad_void_y: str = "0um"
    pad_void_x2: str = "0um"
    pad_void_end_layer_name: str = ""
    gnd_return_via_count: int = 3
    gnd_return_via_pitch: str = "0.4mm"
    create_open_region: bool = True
    open_region_frequency: str = "60GHz"
    create_setup: bool = True
    create_sweep: bool = True
    sweep_start: str = "0.01GHz"
    sweep_stop: str = "60GHz"
    sweep_points: int = 401

    @classmethod
    def from_dict(cls, data: dict) -> "InnerGFConfig":
        values = {
            name: str(data[name])
            for name in (
                "gf_layer_name",
                "inner_signal_layer_name",
                "upper_reference_layer_name",
                "lower_reference_layer_name",
                "via_pad_radius",
                "via_column_radius",
                "via_antipad_radius",
                "via_antipad_x",
                "mechanical_start_layer",
                "mechanical_end_layer",
                "mechanical_column_radius",
                "mechanical_pad_radius",
                "d_via",
                "via_x_offset",
                "pad_void_x1",
                "pad_void_y",
                "pad_void_x2",
                "pad_void_end_layer_name",
                "gnd_return_via_pitch",
                "open_region_frequency",
                "sweep_start",
                "sweep_stop",
            )
            if name in data
        }
        for name in ("gnd_return_via_count", "sweep_points"):
            if name in data:
                values[name] = int(data[name])
        for name in (
            "mechanical_via_enabled", "create_open_region", "create_setup", "create_sweep"
        ):
            if name in data:
                value = data[name]
                values[name] = value if isinstance(value, bool) else str(value).lower() in {
                    "1", "true", "yes", "on"
                }
        if "layer_antipads" in data and isinstance(data["layer_antipads"], dict):
            values["layer_antipads"] = {
                str(layer): {
                    "radius": str(settings.get("radius", data.get("via_antipad_radius", "10mil"))),
                    "x": str(settings.get("x", data.get("via_antipad_x", "10mil"))),
                }
                for layer, settings in data["layer_antipads"].items()
                if isinstance(settings, dict)
            }
        return cls(**values)

    def to_dict(self) -> dict:
        return asdict(self)


AEDT_VERSION = ""
DESIGN_NAME = "InnerGFTransition"
PROJECT_PATH = Path(__file__).with_name("gf_inner_model.aedt")
KEEP_DESKTOP_OPEN = True
_OPEN_DESKTOPS: list[Desktop] = []


def _require_positive_expression(value: str, field_name: str) -> None:
    """Reject empty/non-positive literal dimensions before AEDT is started."""
    if not value.strip():
        raise ValueError(f"{field_name} is required.")
    # Expressions such as SIGNAL_PAD_LENGTH/4 are intentionally allowed.  The
    # AEDT expression parser performs the final dimensional validation.
    literal = _literal_mm(value)
    try:
        numeric = float(value)
    except ValueError:
        numeric = None
    if (literal is not None and literal <= 0) or (numeric is not None and numeric <= 0):
        raise ValueError(f"{field_name} must be positive.")


def _require_nonnegative_expression(value: str, field_name: str) -> None:
    """Reject empty/negative literal margins while allowing AEDT expressions."""
    if not value.strip():
        raise ValueError(f"{field_name} is required.")
    literal = _literal_mm(value)
    try:
        numeric = float(value)
    except ValueError:
        numeric = None
    if (literal is not None and literal < 0) or (numeric is not None and numeric < 0):
        raise ValueError(f"{field_name} must be non-negative.")


def _literal_mm(value: str) -> float | None:
    """Return a literal length in mm, or ``None`` for an AEDT expression."""
    import re
    match = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(mm|mil|um|in)\s*", value, re.I)
    if not match:
        return None
    magnitude = float(match.group(1))
    unit = match.group(2).lower()
    return magnitude * {"mm": 1.0, "mil": 0.0254, "um": 0.001, "in": 25.4}[unit]


def _require_frequency(value: str, field_name: str) -> None:
    """Require a positive literal frequency accepted by AEDT."""
    import re
    match = re.fullmatch(
        r"\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(Hz|kHz|MHz|GHz|THz)\s*",
        value,
        re.IGNORECASE,
    )
    if not match or float(match.group(1)) <= 0:
        raise ValueError(f"{field_name} must be a positive literal frequency.")


def _resolved_via_x_offset_mm(gssg: GSSGConfig, inner: InnerGFConfig) -> float | None:
    """Resolve the pad-center-to-via-center X distance in millimetres."""
    import re
    result = _literal_mm(inner.via_x_offset)
    if result is not None:
        return result
    match = re.fullmatch(
        r"\s*SIGNAL_PAD_LENGTH\s*/\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*",
        inner.via_x_offset,
        re.IGNORECASE,
    )
    signal_pad_mm = _literal_mm(gssg.signal_pad_length)
    if match and signal_pad_mm is not None and float(match.group(1)) > 0:
        return signal_pad_mm / float(match.group(1))
    return None


def _resolved_via_x_position_mm(gssg: GSSGConfig, inner: InnerGFConfig) -> float | None:
    """Resolve the via X position measured from the signal-pad left edge."""
    offset_mm = _resolved_via_x_offset_mm(gssg, inner)
    signal_pad_mm = _literal_mm(gssg.signal_pad_length)
    if offset_mm is None or signal_pad_mm is None:
        return None
    return signal_pad_mm / 2 - offset_mm


def _inner_via_topology(
    stackup: StackupConfig,
    gf_layer: Layer,
    inner_layer: Layer,
    inner: InnerGFConfig,
) -> tuple[list[Layer], list[tuple[Layer, Layer]], tuple[Layer, Layer] | None, dict[str, str]]:
    """Resolve laser segments, optional mechanical span, and pad technology."""
    copper = [layer for layer in stackup.layers if layer.kind == "copper"]
    start_index, end_index = copper.index(gf_layer), copper.index(inner_layer)
    if end_index <= start_index:
        raise ValueError("Inner GF breakout layer must be below L1.")
    path = copper[start_index:end_index + 1]
    if not inner.mechanical_via_enabled:
        return (
            path,
            list(zip(path, path[1:])),
            None,
            {layer.name: "laser" for layer in path},
        )
    if len(path) < 3:
        raise ValueError(
            "Mechanical VIA requires at least one internal copper layer between L1 and breakout."
        )
    path_names = [layer.name for layer in path]
    valid_start_names = path_names[1:-1]
    if inner.mechanical_start_layer not in valid_start_names:
        raise ValueError(
            "mechanical_start_layer must be below L1 and before the breakout layer."
        )
    mechanical_start_index = path_names.index(inner.mechanical_start_layer)
    # A blank endpoint is the legacy JSON behavior: reserve the final copper
    # transition as one laser segment.
    mechanical_end_name = inner.mechanical_end_layer or path_names[-2]
    valid_end_names = path_names[mechanical_start_index + 1:]
    if mechanical_end_name not in valid_end_names:
        raise ValueError(
            "mechanical_end_layer must be after mechanical_start_layer and no deeper "
            "than the breakout layer."
        )
    mechanical_end_index = path_names.index(mechanical_end_name)
    mechanical = (path[mechanical_start_index], path[mechanical_end_index])
    laser_segments = list(
        zip(path[:mechanical_start_index], path[1:mechanical_start_index + 1])
    )
    laser_segments.extend(
        zip(path[mechanical_end_index:-1], path[mechanical_end_index + 1:])
    )
    pad_technology: dict[str, str] = {}
    for first, second in laser_segments:
        pad_technology.setdefault(first.name, "laser")
        pad_technology.setdefault(second.name, "laser")
    pad_technology[mechanical[0].name] = "mechanical"
    pad_technology[mechanical[1].name] = "mechanical"
    return path, laser_segments, mechanical, pad_technology


def _inner_layer_antipad_values(
    inner: InnerGFConfig, layer_name: str
) -> tuple[str, str]:
    override = inner.layer_antipads.get(layer_name, {})
    return (
        str(override.get("radius", inner.via_antipad_radius)),
        str(override.get("x", inner.via_antipad_x)),
    )


def _inner_antipad_variable_names(layer: Layer) -> tuple[str, str]:
    suffix = _identifier(layer.name).upper()
    return f"VIA_ANTIPAD_RADIUS_{suffix}", f"VIA_ANTIPAD_X_{suffix}"


def _selected_reference_layers(
    stackup: StackupConfig,
    inner_signal: Layer,
    inner: InnerGFConfig,
) -> tuple[Layer, Layer]:
    """Resolve the explicitly selected ground references around the signal layer."""
    if not inner.upper_reference_layer_name.strip():
        raise ValueError("upper_reference_layer_name must be explicitly selected.")
    if not inner.lower_reference_layer_name.strip():
        raise ValueError("lower_reference_layer_name must be explicitly selected.")

    def reference(name: str, field_name: str) -> Layer:
        layer = next((item for item in stackup.layers if item.name == name), None)
        if layer is None or layer.kind != "copper":
            raise ValueError(f"{field_name} {name!r} must be a copper layer.")
        if layer.role != "ground":
            raise ValueError(f"{field_name} {name!r} must be a ground copper layer.")
        return layer

    upper = reference(inner.upper_reference_layer_name, "Upper reference layer")
    lower = reference(inner.lower_reference_layer_name, "Lower reference layer")
    upper_index = stackup.layers.index(upper)
    signal_index = stackup.layers.index(inner_signal)
    lower_index = stackup.layers.index(lower)
    if not upper_index < signal_index < lower_index:
        raise ValueError(
            "Reference layers must bracket the inner signal layer in physical order: "
            "upper reference < signal < lower reference."
        )
    return upper, lower


def _validate_inner_config(
    stackup: StackupConfig, gssg: GSSGConfig, inner: InnerGFConfig
) -> tuple[Layer, Layer, Layer, Layer]:
    """Validate the GF, signal, and explicitly selected reference layers."""
    # Inner GF has independent upper/lower reference selectors.  Validate the
    # shared stackup structure here, then validate the Inner-GF references
    # below instead of using the stackup-tab differential selections.
    signal = _validate(stackup, validate_references=False)
    gf = next((layer for layer in stackup.layers if layer.name == inner.gf_layer_name), None)
    if gf is None or gf.kind != "copper":
        raise ValueError(f"GF layer {inner.gf_layer_name!r} must be a copper layer.")
    if stackup.layers.index(gf) != 0 or gf.name != "L1":
        raise ValueError("Inner GF transition requires the top copper layer L1 for GF pads.")
    if gssg.signal_layer_name != gf.name:
        raise ValueError(
            f"GSSG configuration must target {gf.name!r}; got {gssg.signal_layer_name!r}."
        )

    inner_signal = next(
        (layer for layer in stackup.layers if layer.name == inner.inner_signal_layer_name), None
    )
    if inner_signal is None or inner_signal.kind != "copper":
        raise ValueError(
            f"Inner signal layer {inner.inner_signal_layer_name!r} must be a copper layer."
        )
    inner_index = stackup.layers.index(inner_signal)
    copper_layers = [layer for layer in stackup.layers if layer.kind == "copper"]
    if inner_signal in (copper_layers[0], copper_layers[-1]):
        raise ValueError("Inner signal layer must not be an external copper layer.")
    if inner_signal is not signal or inner_signal.role != "signal":
        raise ValueError(
            f"Stackup signal role must identify inner layer {inner_signal.name!r}."
        )
    upper_reference, lower_reference = _selected_reference_layers(
        stackup, inner_signal, inner
    )
    _require_positive_expression(inner.via_pad_radius, "via_pad_radius")
    _require_positive_expression(inner.via_column_radius, "via_column_radius")
    _require_positive_expression(inner.via_antipad_radius, "via_antipad_radius")
    _require_positive_expression(inner.via_antipad_x, "via_antipad_x")
    _require_positive_expression(inner.mechanical_column_radius, "mechanical_column_radius")
    _require_positive_expression(inner.mechanical_pad_radius, "mechanical_pad_radius")
    _require_positive_expression(inner.d_via, "d_via")
    _require_positive_expression(inner.via_x_offset, "via_x_offset")
    _require_positive_expression(inner.gnd_return_via_pitch, "gnd_return_via_pitch")
    if inner.gnd_return_via_count < 1:
        raise ValueError("gnd_return_via_count must be at least 1.")
    if inner.create_open_region:
        _require_frequency(inner.open_region_frequency, "open_region_frequency")
    if inner.create_sweep and not inner.create_setup:
        raise ValueError("create_sweep requires create_setup.")
    if inner.create_setup:
        _require_frequency(inner.sweep_start, "sweep_start")
        _require_frequency(inner.sweep_stop, "sweep_stop")
    if inner.create_sweep:
        if inner.sweep_points < 2:
            raise ValueError("sweep_points must be at least 2.")
    pad_mm = _literal_mm(inner.via_pad_radius)
    column_mm = _literal_mm(inner.via_column_radius)
    antipad_mm = _literal_mm(inner.via_antipad_radius)
    if pad_mm is not None and column_mm is not None and pad_mm <= column_mm:
        raise ValueError("via_pad_radius must be greater than via_column_radius.")
    if antipad_mm is not None and pad_mm is not None and antipad_mm <= pad_mm:
        raise ValueError("via_antipad_radius must be greater than via_pad_radius.")
    if inner.pad_void_end_layer_name:
        _require_positive_expression(inner.pad_void_x1, "pad_void_x1")
        _require_nonnegative_expression(inner.pad_void_y, "pad_void_y")
        _require_nonnegative_expression(inner.pad_void_x2, "pad_void_x2")
        pad_void_x1_mm = _literal_mm(inner.pad_void_x1)
        if pad_void_x1_mm is not None and pad_void_x1_mm < 0.15:
            raise ValueError("pad_void_x1 must be at least 150um.")
        pad_void_end = next(
            (
                layer
                for layer in stackup.layers
                if layer.name == inner.pad_void_end_layer_name
            ),
            None,
        )
        if pad_void_end is None or pad_void_end.kind != "copper":
            raise ValueError("pad_void_end_layer_name must identify a copper layer.")
        if stackup.layers.index(pad_void_end) < stackup.layers.index(gf):
            raise ValueError("Pad underlay clearance must extend downward from L1.")
    mechanical_column_mm = _literal_mm(inner.mechanical_column_radius)
    mechanical_pad_mm = _literal_mm(inner.mechanical_pad_radius)
    if (
        mechanical_column_mm is not None and mechanical_pad_mm is not None
        and mechanical_pad_mm <= mechanical_column_mm
    ):
        raise ValueError(
            "mechanical_pad_radius must be greater than mechanical_column_radius."
        )
    path, _, _, pad_technology = _inner_via_topology(
        stackup, gf, inner_signal, inner
    )
    for layer in path:
        radius_text, x_text = _inner_layer_antipad_values(inner, layer.name)
        _require_positive_expression(radius_text, f"via_antipad_radius_{layer.name}")
        _require_positive_expression(x_text, f"via_antipad_x_{layer.name}")
        radius_mm = _literal_mm(radius_text)
        technology = pad_technology.get(layer.name)
        if technology and radius_mm is not None:
            active_pad_mm = (
                mechanical_pad_mm if technology == "mechanical" else pad_mm
            )
            if active_pad_mm is not None and radius_mm <= active_pad_mm:
                raise ValueError(
                    f"via_antipad_radius_{layer.name} must exceed its {technology} pad radius."
                )
    offset_mm = _resolved_via_x_offset_mm(gssg, inner)
    position_mm = _resolved_via_x_position_mm(gssg, inner)
    pitch_mm = _literal_mm(inner.gnd_return_via_pitch)
    gnd_pad_mm = _literal_mm(gssg.gnd_pad_length)
    if offset_mm is not None and position_mm is not None:
        if position_mm <= 0:
            raise ValueError(
                "via_x_offset must be less than half of SIGNAL_PAD_LENGTH."
            )
        if pad_mm is not None and position_mm < pad_mm:
            raise ValueError(
                "Signal VIA pad must remain inside the signal-pad left edge."
            )
    if None not in (position_mm, pitch_mm, column_mm, gnd_pad_mm):
        last_edge_mm = (
            float(position_mm)
            + (inner.gnd_return_via_count - 1) * float(pitch_mm)
            + float(column_mm)
        )
        if last_edge_mm > float(gnd_pad_mm):
            raise ValueError("GND return vias must remain inside GND_PAD_LENGTH.")
    return gf, inner_signal, upper_reference, lower_reference


def _create_pad(
    hfss: Hfss,
    name: str,
    x: str,
    y: str,
    length: str,
    width: str,
    z_origin: str,
    thickness: str,
    color: tuple[int, int, int],
) -> object:
    pad = hfss.modeler.create_box(
        [x, y, z_origin], [length, width, thickness], name=name, material="copper"
    )
    if not pad:
        raise RuntimeError(f"Unable to create {name}.")
    _set_color(pad, color)
    return pad


def _create_gf_lumped_ports(
    hfss: Hfss,
    signal_z: str,
    p_pad_center_y: str,
    n_pad_center_y: str,
    differential_impedance: float,
    common_impedance: float,
) -> None:
    """Create only the two local GF lumped ports; no surface wave port."""
    m = hfss.modeler
    port_z0 = f"({signal_z})+COPPER_THICKNESS"
    port_x = "SIGNAL_PAD_LENGTH"
    p_y0 = f"({p_pad_center_y})-SIGNAL_PAD_WIDTH/2"
    n_y0 = f"({n_pad_center_y})-SIGNAL_PAD_WIDTH/2"
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

    bridge = m.create_rectangle(
        "YZ", [port_x, "SIDE_MARGIN", port_z0],
        ["2*GND_PAD_WIDTH+2*GS_GAP+2*SIGNAL_PAD_WIDTH+SS_GAP", "GF_PORT_GND_HEIGHT"],
        name="GF_GND_BRIDGE",
    )
    if not bridge:
        raise RuntimeError("Unable to create GF_GND_BRIDGE.")
    clearance = m.create_rectangle(
        "YZ", [port_x, "SIDE_MARGIN+GND_PAD_WIDTH", port_z0],
        ["2*GS_GAP+2*SIGNAL_PAD_WIDTH+SS_GAP", "GF_PORT_HEIGHT"],
        name="GF_GND_BRIDGE_CLEARANCE",
    )
    if not clearance or not m.subtract(bridge, clearance, keep_originals=False):
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


def _create_inner_signal(
    hfss: Hfss,
    inner: Layer,
    z_origin: str,
    pair_center_y: str,
) -> dict[str, object]:
    """Create inner-layer ground, straight lines, and via-to-line fanouts."""
    m = hfss.modeler
    height = height_variable(inner)
    inner_id = _identifier(inner.name)
    ground = m.create_box(
        ["BOARD_X0", "0mm", z_origin],
        ["BOARD_LENGTH_TOTAL", "BOARD_WIDTH", height],
        name=f"GND_{inner_id}", material="copper",
    )
    if not ground:
        raise RuntimeError(f"Unable to create inner reference ground for {inner.name}.")

    line_p_center = f"({pair_center_y})-(W_LINE+S_LINE)/2"
    line_n_center = f"({pair_center_y})+(W_LINE+S_LINE)/2"
    line_x0 = "BOARD_X0"
    transition_x = "VIA_X_POSITION-FANOUT_LENGTH"
    line_length = "VIA_X_POSITION-FANOUT_LENGTH-BOARD_X0"

    # One formal W/S/G corridor runs continuously to the VIA center.  The VIA
    # slot anti-pad supplies the only additional local clearance; a separate
    # fanout-width clearance would over-open the reference copper.
    trace_clearance = m.create_box(
        [line_x0, f"({pair_center_y})-(S_LINE+2*W_LINE+2*G_LINE)/2", z_origin],
        ["VIA_X_POSITION-BOARD_X0", "S_LINE+2*W_LINE+2*G_LINE", height],
        name=f"INNER_GND_{inner_id}_TRACE_CLEARANCE", material="vacuum",
    )
    if not trace_clearance or not m.subtract(
        ground, trace_clearance, keep_originals=False
    ):
        raise RuntimeError(f"Unable to create inner ground clearance on {inner.name}.")

    traces: dict[str, object] = {}
    for side, center in (("P", line_p_center), ("N", line_n_center)):
        y0 = f"({center})-W_LINE/2"
        trace = m.create_box(
            [line_x0, y0, z_origin], [line_length, "W_LINE", height],
            name=f"INNER_TRACE_{side}", material="copper",
        )
        if not trace:
            raise RuntimeError(f"Unable to create INNER_TRACE_{side}.")
        traces[side] = trace

    via_p_center = f"({pair_center_y})-D_VIA/2"
    via_n_center = f"({pair_center_y})+D_VIA/2"
    for side, via_center, line_center in (
        ("P", via_p_center, line_p_center),
        ("N", via_n_center, line_n_center),
    ):
        line_y0 = f"({line_center})-W_LINE/2"
        line_y1 = f"({line_center})+W_LINE/2"
        via_y0 = f"({via_center})-VIA_PAD_RADIUS"
        via_y1 = f"({via_center})+VIA_PAD_RADIUS"
        fanout = m.create_polyline(
            [
                [transition_x, line_y0, z_origin],
                [transition_x, line_y1, z_origin],
                ["VIA_X_POSITION", via_y1, z_origin],
                ["VIA_X_POSITION", via_y0, z_origin],
            ],
            cover_surface=True,
            close_surface=True,
            name=f"INNER_FANOUT_{side}",
            material="copper",
        )
        if not fanout:
            raise RuntimeError(f"Unable to create INNER_FANOUT_{side}.")
        solid = m.sweep_along_vector(fanout, ["0mm", "0mm", height])
        if not solid:
            raise RuntimeError(f"Unable to sweep INNER_FANOUT_{side}.")
        traces[f"fanout_{side}"] = solid
    traces["ground"] = ground
    return traces


def _create_isolated_l1_ground(
    hfss: Hfss,
    layer: Layer,
    z_origin: str,
    color: tuple[int, int, int],
) -> object:
    """Create L1 ground ending at, but not extending beneath, the GF pads."""
    m = hfss.modeler
    height = height_variable(layer)
    ground = m.create_box(
        ["BOARD_X0", "0mm", z_origin],
        ["-BOARD_X0", "BOARD_WIDTH", height],
        name="GND_L1", material="copper",
    )
    if not ground:
        raise RuntimeError("Unable to create isolated L1 ground plane.")
    _set_color(ground, color)
    return ground


def _create_gnd_pad_return_vias(
    hfss: Hfss,
    inner: InnerGFConfig,
    y_gnd_l: str,
    y_gnd_r: str,
    lower_ref_z: str,
    signal_z: str,
    gf_layer: Layer,
) -> list[object]:
    """Add several pad-connected return columns extending in +X."""
    vias: list[object] = []
    for side, via_y in (
        ("L", f"({y_gnd_l})+GND_PAD_WIDTH/2"),
        ("R", f"({y_gnd_r})+GND_PAD_WIDTH/2"),
    ):
        for index in range(inner.gnd_return_via_count):
            via_x = f"VIA_X_POSITION+{index}*GND_RETURN_VIA_PITCH"
            name = f"GND_VIA_{side}_{index + 1:03d}"
            via = _create_via(
                hfss, name, via_x, via_y, lower_ref_z,
                f"BOARD_THICKNESS-({lower_ref_z})", signal_z,
                height_variable(gf_layer), lower_ref_z, None, create_pads=False,
            )
            _set_color(via["column"], (145, 145, 145))
            vias.append(via["column"])
    return vias


def _create_inner_trace_return_vias(
    hfss: Hfss,
    stackup: StackupConfig,
    gssg: GSSGConfig,
    inner: InnerGFConfig,
    inner_layer: Layer,
    upper_reference: Layer,
    lower_reference: Layer,
    bottom_up: list[Layer],
    pair_center_y: str,
) -> list[object]:
    """Create two rows of solid return columns beside the inner traces."""
    if not stackup.return_vias_enabled:
        return []
    trace_mm = _literal_mm(gssg.trace_length)
    fanout_mm = _literal_mm(gssg.fanout_length)
    via_position_mm = _resolved_via_x_position_mm(gssg, inner)
    edge_mm = _literal_mm(stackup.return_via_ground_edge_offset)
    pitch_mm = _literal_mm(stackup.return_via_pitch)
    if None in (trace_mm, fanout_mm, via_position_mm, edge_mm, pitch_mm):
        raise ValueError(
            "Inner return-via span, edge offset, and pitch must resolve to literal lengths."
        )
    span_mm = trace_mm + fanout_mm + via_position_mm
    if span_mm <= 0 or edge_mm < 0 or pitch_mm <= 0:
        raise ValueError("Inner return-via span and pitch must be positive; edge offset cannot be negative.")
    available_mm = span_mm - 2 * edge_mm
    if available_mm < 0:
        raise ValueError("Inner trace is too short for the selected return-via edge offset.")
    count = floor(available_mm / pitch_mm) + 1

    lower_z = _origin_expression_bottom_up(bottom_up, lower_reference.name)
    upper_z = _origin_expression_bottom_up(bottom_up, upper_reference.name)
    via_height = (
        f"({upper_z})+{height_variable(upper_reference)}-({lower_z})"
    )
    y_offset = "S_LINE/2+W_LINE+G_LINE+RETURN_VIA_EDGE_OFFSET"
    m = hfss.modeler
    vias: list[object] = []
    for side, y in (
        ("L", f"({pair_center_y})-({y_offset})"),
        ("R", f"({pair_center_y})+({y_offset})"),
    ):
        for index in range(count):
            x = f"BOARD_X0+RETURN_VIA_EDGE_OFFSET+{index}*RETURN_VIA_PITCH"
            via = m.create_cylinder(
                "Z", [x, y, lower_z], "VIA_COLUMN_RADIUS", via_height,
                name=f"INNER_RETURN_VIA_{side}_{index + 1:03d}_COLUMN", material="copper",
            )
            if not via:
                raise RuntimeError(f"Unable to create inner return via {side}{index + 1}.")
            _set_color(via, (145, 145, 145))
            vias.append(via)
    return vias


def _create_via(
    hfss: Hfss,
    name: str,
    x: str,
    y: str,
    z0: str,
    height: str,
    pad_z: str,
    pad_height: str,
    landing_z: str | None = None,
    landing_height: str | None = None,
    create_pads: bool = True,
) -> dict[str, object]:
    """Create one solid copper column and optional solid landing pads."""
    m = hfss.modeler
    column = m.create_cylinder(
        "Z", [x, y, z0], "VIA_COLUMN_RADIUS", height,
        name=f"{name}_COLUMN", material="copper",
    )
    if not column:
        raise RuntimeError(f"Unable to create {name} column.")
    result = {"column": column}
    if not create_pads:
        return result
    pad = m.create_cylinder(
        "Z", [x, y, pad_z], "VIA_PAD_RADIUS", pad_height,
        name=f"{name}_PAD", material="copper",
    )
    if not pad:
        raise RuntimeError(f"Unable to create {name} top landing pad.")
    result["pad"] = pad
    if landing_z is not None and landing_height is not None:
        landing = m.create_cylinder(
            "Z", [x, y, landing_z], "VIA_PAD_RADIUS", landing_height,
            name=f"{name}_INNER_PAD", material="copper",
        )
        if not landing:
            raise RuntimeError(f"Unable to create {name} landing pad.")
        result["landing"] = landing
    return result


def _unite_coplanar_signal(modeler: object, assignments: list[str], label: str) -> None:
    """Unite same-layer signal metal while explicitly rejecting VIA columns."""
    columns = [name for name in assignments if name.endswith("_COLUMN")]
    if columns:
        raise RuntimeError(
            f"Refusing invalid {label} Unite; VIA columns must remain separate: "
            + ", ".join(columns)
        )
    if not modeler.unite(assignments):
        raise RuntimeError(f"Unable to unite {label}.")


def _subtract_signal_slot_clearance(
    hfss: Hfss,
    records: list[dict[str, object]],
    x: str,
    pair_center_y: str,
    crossed_max_index: int,
) -> None:
    """Cut the shared P/N two-circle plus +/-X slot on every crossed copper."""
    m = hfss.modeler
    for record in records:
        layer = record["layer"]
        if not isinstance(layer, Layer) or layer.kind != "copper":
            continue
        if int(record["config_index"]) > crossed_max_index:
            continue
        body = record.get("body")
        if body is None:
            continue
        radius_name, x_name = _inner_antipad_variable_names(layer)
        prefix = f"SIG_SLOT_ANTIPAD_{_identifier(layer.name)}"
        circle_p = m.create_cylinder(
            "Z", [x, f"({pair_center_y})-D_VIA/2", record["z_origin"]],
            radius_name, height_variable(layer), name=prefix, material="vacuum",
        )
        circle_n = m.create_cylinder(
            "Z", [x, f"({pair_center_y})+D_VIA/2", record["z_origin"]],
            radius_name, height_variable(layer),
            name=f"{prefix}_N_CIRCLE", material="vacuum",
        )
        neck_negative_x = m.create_box(
            [f"({x})-{x_name}", f"({pair_center_y})-D_VIA/2", record["z_origin"]],
            [x_name, "D_VIA", height_variable(layer)],
            name=f"{prefix}_NECK_NEG_X", material="vacuum",
        )
        neck_positive_x = m.create_box(
            [x, f"({pair_center_y})-D_VIA/2", record["z_origin"]],
            [x_name, "D_VIA", height_variable(layer)],
            name=f"{prefix}_NECK_POS_X", material="vacuum",
        )
        if not circle_p or not circle_n or not neck_negative_x or not neck_positive_x:
            raise RuntimeError(f"Unable to create slot anti-pad on {record['name']}.")
        if not m.unite([
            circle_p.name, circle_n.name, neck_negative_x.name, neck_positive_x.name,
        ]):
            raise RuntimeError(f"Unable to unite slot anti-pad on {record['name']}.")
        if not m.subtract(body, circle_p, keep_originals=False):
            raise RuntimeError(f"Unable to subtract slot anti-pad on {record['name']}.")


def _subtract_skipped_reference_clearance(
    hfss: Hfss,
    ground: object,
    layer: Layer,
    z_origin: str,
    pair_center_y: str,
) -> None:
    """Open one W/S/G corridor to the VIA center on a skipped reference layer."""
    m = hfss.modeler
    layer_id = _identifier(layer.name)
    trace_width = "S_LINE+2*W_LINE+2*G_LINE"
    trace = m.create_box(
        ["BOARD_X0", f"({pair_center_y})-({trace_width})/2", z_origin],
        ["VIA_X_POSITION-BOARD_X0", trace_width, height_variable(layer)],
        name=f"SKIPPED_REF_{layer_id}_TRACE_CLEARANCE", material="vacuum",
    )
    if not trace or not m.subtract(ground, trace, keep_originals=False):
        raise RuntimeError(
            f"Unable to create skipped-reference clearance on {layer.name}."
        )


def _subtract_pad_underlay_clearance(
    hfss: Hfss,
    stackup: StackupConfig,
    inner: InnerGFConfig,
    ground_by_layer: dict[str, object],
    bottom_up: list[Layer],
    pair_center_y: str,
) -> None:
    """Project the X1/Y/X2 GF-pad void through copper down to one layer."""
    if not inner.pad_void_end_layer_name:
        return
    copper = [layer for layer in stackup.layers if layer.kind == "copper"]
    end_index = next(
        index
        for index, layer in enumerate(copper)
        if layer.name == inner.pad_void_end_layer_name
    )
    x_size = "PAD_VOID_X2+SIGNAL_PAD_LENGTH+PAD_VOID_X1"
    y_size = "2*SIGNAL_PAD_WIDTH+SS_GAP+2*PAD_VOID_Y"
    y_origin = f"({pair_center_y})-(SIGNAL_PAD_WIDTH+SS_GAP/2+PAD_VOID_Y)"
    for layer in copper[:end_index + 1]:
        ground = ground_by_layer.get(layer.name)
        if ground is None:
            continue
        tool = hfss.modeler.create_box(
            [
                "-PAD_VOID_X2",
                y_origin,
                _origin_expression_bottom_up(bottom_up, layer.name),
            ],
            [x_size, y_size, height_variable(layer)],
            name=f"GF_PAD_UNDERCUT_{_identifier(layer.name)}",
            material="vacuum",
        )
        if not tool or not hfss.modeler.subtract(
            ground, tool, keep_originals=False
        ):
            raise RuntimeError(
                f"Unable to create GF pad underlay clearance on {layer.name}."
            )


def _create_inner_wave_port(
    hfss: Hfss,
    references: list[str],
    z0: str,
    z1: str,
    pair_center_y: str,
) -> None:
    m = hfss.modeler
    hfss["INNER_PORT_Z0"] = z0
    hfss["INNER_PORT_Z1"] = z1
    hfss["INNER_PORT_Z"] = "INNER_PORT_Z1-INNER_PORT_Z0"
    wave = m.create_rectangle(
        "YZ", ["BOARD_X0", f"({pair_center_y})-GF_PORT_WAVE_WIDTH/2", "INNER_PORT_Z0"],
        ["GF_PORT_WAVE_WIDTH", "INNER_PORT_Z"], name="INNER_WAVE_PORT_SHEET",
    )
    if not wave:
        raise RuntimeError("Unable to create INNER_WAVE_PORT_SHEET.")
    if len(references) < 3:
        raise RuntimeError(
            "Inner wave port requires upper, coplanar, and lower reference conductors."
        )
    if not hfss.wave_port(
        wave, reference=references, create_port_sheet=False, modes=2,
        impedance=50, name="INNER_WAVE_PORT", terminals_rename=True,
    ):
        raise RuntimeError("Unable to assign INNER_WAVE_PORT.")


def _inner_port_expressions(
    upper_reference: Layer,
    lower_reference: Layer,
    bottom_up: list[Layer],
) -> tuple[str, str]:
    """Cover both reference conductors from lower outer to upper outer face."""
    lower_origin = _origin_expression_bottom_up(bottom_up, lower_reference.name)
    upper_origin = _origin_expression_bottom_up(bottom_up, upper_reference.name)
    return lower_origin, f"({upper_origin})+{height_variable(upper_reference)}"


def _assign_inner_differential_pair(
    hfss: Hfss,
    differential_impedance: float,
    common_impedance: float,
) -> None:
    candidates = (
        ("INNER_WAVE_PORT_T1", "INNER_WAVE_PORT_T2"),
        ("INNER_WAVE_PORT_1", "INNER_WAVE_PORT_2"),
    )
    for assignment, reference in candidates:
        if hfss.set_differential_pair(
            assignment=assignment,
            reference=reference,
            common_mode="Comm2",
            differential_mode="Diff2",
            common_reference=common_impedance,
            differential_reference=differential_impedance,
            active=True,
            matched=False,
        ):
            return
    raise RuntimeError("Unable to create INNER_WAVE_PORT Diff2/Comm2 pair.")


def _create_analysis_options(hfss: Hfss, inner: InnerGFConfig) -> None:
    """Create the requested radiation region/setup/sweep without solving."""
    create_hfss_analysis(
        hfss,
        create_open_region=inner.create_open_region,
        open_region_frequency=inner.open_region_frequency,
        create_setup=inner.create_setup,
        create_sweep=inner.create_sweep,
        sweep_start=inner.sweep_start,
        sweep_stop=inner.sweep_stop,
        sweep_points=inner.sweep_points,
    )


def _build_inner_stack(
    hfss: Hfss,
    stackup: StackupConfig,
    gssg: GSSGConfig,
    inner: InnerGFConfig,
) -> None:
    gf_layer, inner_layer, upper_reference, lower_reference = _validate_inner_config(
        stackup, gssg, inner
    )
    via_path, laser_segments, mechanical_segment, pad_technology = _inner_via_topology(
        stackup, gf_layer, inner_layer, inner
    )
    bottom_up = list(reversed(stackup.layers))
    mapping = layer_material_groups(stackup)
    _create_materials(hfss, stackup, mapping)
    colors = _layer_colors(stackup)
    modeler = hfss.modeler
    modeler.model_units = "mm"

    for name, value in {
        "GND_PAD_LENGTH": gssg.gnd_pad_length,
        "SIGNAL_PAD_LENGTH": gssg.signal_pad_length,
        "GND_PAD_WIDTH": gssg.gnd_pad_width,
        "SIGNAL_PAD_WIDTH": gssg.signal_pad_width,
        "GS_GAP": gssg.gs_gap,
        "SS_GAP": gssg.ss_gap,
        "FANOUT_LENGTH": gssg.fanout_length,
        "TRACE_LENGTH": gssg.trace_length,
        "W_LINE": gssg.w_line,
        "S_LINE": gssg.s_line,
        "G_LINE": gssg.g_line,
        "PAD_OVERLAP": gssg.pad_overlap,
        "SIDE_MARGIN": gssg.side_margin,
        "MODEL_LENGTH": gssg.model_length,
        "VIA_PAD_RADIUS": inner.via_pad_radius,
        "VIA_COLUMN_RADIUS": inner.via_column_radius,
        "VIA_ANTIPAD_RADIUS": inner.via_antipad_radius,
        "VIA_ANTIPAD_X": inner.via_antipad_x,
        "MECHANICAL_VIA_COLUMN_RADIUS": inner.mechanical_column_radius,
        "MECHANICAL_VIA_PAD_RADIUS": inner.mechanical_pad_radius,
        "D_VIA": inner.d_via,
        "VIA_X_OFFSET": inner.via_x_offset,
        "VIA_X_POSITION": "SIGNAL_PAD_LENGTH/2-VIA_X_OFFSET",
        "PAD_VOID_X1": inner.pad_void_x1,
        "PAD_VOID_Y": inner.pad_void_y,
        "PAD_VOID_X2": inner.pad_void_x2,
        "GND_RETURN_VIA_PITCH": inner.gnd_return_via_pitch,
        "RETURN_VIA_EDGE_OFFSET": stackup.return_via_ground_edge_offset,
        "RETURN_VIA_PITCH": stackup.return_via_pitch,
        # Store the selected copper-layer ordinal as a dimensionless value.
        # AEDT design variables cannot evaluate a layer name as a string.
        "INNER_SIGNAL_LAYER": str(
            [layer for layer in stackup.layers if layer.kind == "copper"].index(inner_layer) + 1
        ),
        "UPPER_REFERENCE_LAYER": str(
            [layer for layer in stackup.layers if layer.kind == "copper"].index(upper_reference) + 1
        ),
        "LOWER_REFERENCE_LAYER": str(
            [layer for layer in stackup.layers if layer.kind == "copper"].index(lower_reference) + 1
        ),
    }.items():
        hfss[name] = value
    for layer in (item for item in stackup.layers if item.kind == "copper"):
        radius_name, x_name = _inner_antipad_variable_names(layer)
        radius_value, x_value = _inner_layer_antipad_values(inner, layer.name)
        hfss[radius_name] = radius_value
        hfss[x_name] = x_value
    for name, value in (
        ("MARK1_X", gssg.mark1_x), ("MARK1_Y", gssg.mark1_y),
        ("MARK2_X", gssg.mark2_x), ("MARK2_Y", gssg.mark2_y),
        ("MARK3_X", gssg.mark3_x), ("MARK3_Y", gssg.mark3_y),
        ("MARK4_X", gssg.mark4_x), ("MARK4_Y", gssg.mark4_y),
    ):
        hfss[name] = value
    for layer in stackup.layers:
        hfss[height_variable(layer)] = layer.thickness

    hfss["COPPER_THICKNESS"] = height_variable(gf_layer)
    hfss["BOARD_WIDTH"] = "2*SIDE_MARGIN+2*GND_PAD_WIDTH+2*SIGNAL_PAD_WIDTH+2*GS_GAP+SS_GAP"
    hfss["BOARD_LENGTH_TOTAL"] = "MODEL_LENGTH+FANOUT_LENGTH+TRACE_LENGTH"
    hfss["BOARD_X0"] = "-(FANOUT_LENGTH+TRACE_LENGTH)"
    hfss["BOARD_THICKNESS"] = "+".join(height_variable(x) for x in bottom_up)
    hfss["GF_PORT_HEIGHT"] = GF_PORT_HEIGHT
    hfss["GF_PORT_GND_HEIGHT"] = GF_PORT_GND_HEIGHT
    hfss["GF_PORT_WAVE_WIDTH"] = GF_PORT_WAVE_WIDTH
    # Kept for compatibility with the GF variable set.  This model has no
    # surface wave port, but the value remains tied to the dielectric adjacent
    # to the fixed top-layer GF pads.
    hfss["GF_PORT_WAVE_PP_H"] = height_variable(_adjacent_dielectric(stackup, 0))
    hfss["GF_PORT_WAVE_HEIGHT"] = "8*GF_PORT_WAVE_PP_H"
    hfss["GF_PORT_WAVE_Z0"] = _origin_expression_bottom_up(
        bottom_up, _nearest_copper(stackup, 0, 1).name
    )
    hfss["GF_DIFFERENTIAL_IMPEDANCE"] = str(stackup.differential_impedance)
    hfss["GF_COMMON_IMPEDANCE"] = str(stackup.common_impedance)

    # Record every actual copper body and its Z origin for wave references and
    # via anti-pad operations.  L1 deliberately has no full-sheet body.
    records: list[dict[str, object]] = []
    ground_by_layer: dict[str, object] = {}
    z_origin = "0mm"
    inner_geometry: dict[str, object] = {}
    inner_index = stackup.layers.index(inner_layer)
    pair_center = "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP/2"
    for actual_layer in bottom_up:
        config_index = stackup.layers.index(actual_layer)
        if actual_layer.kind in {"pp", "core"}:
            dielectric = modeler.create_box(
                ["BOARD_X0", "0mm", z_origin],
                ["BOARD_LENGTH_TOTAL", "BOARD_WIDTH", height_variable(actual_layer)],
                name=_identifier(actual_layer.name), material=mapping[actual_layer.name],
            )
            if not dielectric:
                raise RuntimeError(f"Unable to create {actual_layer.name}.")
            dielectric.display_wireframe = True
        elif actual_layer.name == gf_layer.name:
            # L1 carries a real reference plane, but every GF pad sits inside
            # its own clearance and therefore remains electrically isolated.
            ground = _create_isolated_l1_ground(
                hfss, actual_layer, z_origin, colors[actual_layer.name]
            )
            ground_by_layer[actual_layer.name] = ground
        elif actual_layer.name == inner_layer.name:
            inner_geometry = _create_inner_signal(hfss, actual_layer, z_origin, pair_center)
            ground = inner_geometry["ground"]
            ground_by_layer[actual_layer.name] = ground
            records.append({
                "layer": actual_layer, "config_index": config_index,
                "z_origin": z_origin, "name": ground.name, "body": ground,
            })
        else:
            ground = modeler.create_box(
                ["BOARD_X0", "0mm", z_origin],
                ["BOARD_LENGTH_TOTAL", "BOARD_WIDTH", height_variable(actual_layer)],
                name=f"GND_{_identifier(actual_layer.name)}", material="copper",
            )
            if not ground:
                raise RuntimeError(f"Unable to create {actual_layer.name} copper.")
            _set_color(ground, colors[actual_layer.name])
            ground_by_layer[actual_layer.name] = ground
            records.append({
                "layer": actual_layer, "config_index": config_index,
                "z_origin": z_origin, "name": ground.name, "body": ground,
            })
        z_origin = f"({z_origin})+{height_variable(actual_layer)}"

    _subtract_pad_underlay_clearance(
        hfss, stackup, inner, ground_by_layer, bottom_up, pair_center
    )

    upper_index = stackup.layers.index(upper_reference)
    lower_index = stackup.layers.index(lower_reference)
    for record in records:
        record_index = int(record["config_index"])
        if (
            upper_index < record_index < inner_index
            or inner_index < record_index < lower_index
        ):
            _subtract_skipped_reference_clearance(
                hfss,
                record["body"],
                record["layer"],
                record["z_origin"],
                pair_center,
            )

    _create_inner_trace_return_vias(
        hfss, stackup, gssg, inner, inner_layer,
        upper_reference, lower_reference, bottom_up, pair_center,
    )

    signal_z = _origin_expression_bottom_up(bottom_up, gf_layer.name)
    inner_z = _origin_expression_bottom_up(bottom_up, inner_layer.name)
    gf_color = colors[gf_layer.name]
    y_gnd_l = "SIDE_MARGIN"
    y_sig_p = "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP"
    y_sig_n = "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP"
    y_gnd_r = "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP+SIGNAL_PAD_WIDTH+GS_GAP"
    p_center = "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH/2"
    n_center = "SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP+SIGNAL_PAD_WIDTH/2"
    _create_pad(hfss, "GND_PAD_L", "0mm", y_gnd_l, "GND_PAD_LENGTH", "GND_PAD_WIDTH", signal_z, height_variable(gf_layer), gf_color)
    _create_pad(hfss, "SIG_PAD_P", "0mm", y_sig_p, "SIGNAL_PAD_LENGTH", "SIGNAL_PAD_WIDTH", signal_z, height_variable(gf_layer), gf_color)
    _create_pad(hfss, "SIG_PAD_N", "0mm", y_sig_n, "SIGNAL_PAD_LENGTH", "SIGNAL_PAD_WIDTH", signal_z, height_variable(gf_layer), gf_color)
    _create_pad(hfss, "GND_PAD_R", "0mm", y_gnd_r, "GND_PAD_LENGTH", "GND_PAD_WIDTH", signal_z, height_variable(gf_layer), gf_color)
    # P/N signal vias land on the inner fanout endpoints.
    via_y_p = "(SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP/2)-D_VIA/2"
    via_y_n = "(SIDE_MARGIN+GND_PAD_WIDTH+GS_GAP+SIGNAL_PAD_WIDTH+SS_GAP/2)+D_VIA/2"
    _subtract_signal_slot_clearance(
        hfss, records, "VIA_X_POSITION", pair_center, inner_index
    )
    record_by_name = {
        record["layer"].name: record
        for record in records
        if isinstance(record.get("layer"), Layer)
    }
    for side, via_y in (("P", via_y_p), ("N", via_y_n)):
        for first, second in laser_segments:
            shallow, deep = sorted((first, second), key=stackup.layers.index)
            shallow_origin = _origin_expression_bottom_up(bottom_up, shallow.name)
            deep_origin = _origin_expression_bottom_up(bottom_up, deep.name)
            column_height = (
                f"({shallow_origin})+{height_variable(shallow)}-({deep_origin})"
            )
            column_name = (
                f"SIG_VIA_{side}_LASER_{_identifier(first.name)}_"
                f"{_identifier(second.name)}_COLUMN"
            )
            column = modeler.create_cylinder(
                "Z", ["VIA_X_POSITION", via_y, deep_origin],
                "VIA_COLUMN_RADIUS", column_height,
                name=column_name, material="copper",
            )
            if not column:
                raise RuntimeError(f"Unable to create laser VIA column {column_name}.")
            _set_color(column, gf_color)

        if mechanical_segment is not None:
            first, second = mechanical_segment
            shallow, deep = sorted((first, second), key=stackup.layers.index)
            shallow_origin = _origin_expression_bottom_up(bottom_up, shallow.name)
            deep_origin = _origin_expression_bottom_up(bottom_up, deep.name)
            column_height = (
                f"({shallow_origin})+{height_variable(shallow)}-({deep_origin})"
            )
            column_name = (
                f"SIG_VIA_{side}_MECHANICAL_{_identifier(first.name)}_"
                f"{_identifier(second.name)}_COLUMN"
            )
            column = modeler.create_cylinder(
                "Z", ["VIA_X_POSITION", via_y, deep_origin],
                "MECHANICAL_VIA_COLUMN_RADIUS", column_height,
                name=column_name, material="copper",
            )
            if not column:
                raise RuntimeError(
                    f"Unable to create mechanical VIA column {column_name}."
                )
            _set_color(column, gf_color)

        for layer in via_path:
            technology = pad_technology.get(layer.name)
            if technology is None:
                continue
            if layer is gf_layer:
                pad_name = f"SIG_VIA_{side}_PAD"
                pad_z = signal_z
            elif layer is inner_layer:
                pad_name = f"SIG_VIA_{side}_INNER_PAD"
                pad_z = inner_z
            else:
                pad_name = (
                    f"SIG_VIA_{side}_{_identifier(layer.name)}_"
                    f"{technology.upper()}_PAD"
                )
                pad_z = record_by_name[layer.name]["z_origin"]
            radius = (
                "MECHANICAL_VIA_PAD_RADIUS"
                if technology == "mechanical" else "VIA_PAD_RADIUS"
            )
            pad = modeler.create_cylinder(
                "Z", ["VIA_X_POSITION", via_y, pad_z], radius,
                height_variable(layer), name=pad_name, material="copper",
            )
            if not pad:
                raise RuntimeError(f"Unable to create {technology} VIA pad {pad_name}.")
            _set_color(pad, gf_color)

        # Every vertical column and intermediate landing stays independent.
        # Only the actual breakout-layer trace, fanout, and landing pad unite.
        inner_path = [
            f"INNER_TRACE_{side}",
            f"INNER_FANOUT_{side}",
            f"SIG_VIA_{side}_INNER_PAD",
        ]
        _unite_coplanar_signal(
            modeler, inner_path, f"inner-side {side} trace/fanout/landing"
        )

    # GF-pad GND return vias terminate at the explicitly selected lower
    # reference plane, which may be separated from the signal layer.
    upper_ref_z = _origin_expression_bottom_up(bottom_up, upper_reference.name)
    lower_ref_z = _origin_expression_bottom_up(bottom_up, lower_reference.name)
    # GND vias intentionally have no anti-pad or landing pad.  Multiple
    # columns extend from the front of each GND pad toward its rear (+X).
    _create_gnd_pad_return_vias(
        hfss, inner, y_gnd_l, y_gnd_r, lower_ref_z, signal_z, gf_layer
    )
    hfss["UPPER_REF_Z"] = upper_ref_z
    hfss["LOWER_REF_Z"] = lower_ref_z

    # Assign ports only after the complete P/N conductive paths exist, so the
    # later Boolean Unite does not invalidate terminal attachment geometry.
    _create_gf_lumped_ports(
        hfss, signal_z, p_center, n_center,
        stackup.differential_impedance, stackup.common_impedance,
    )

    z0, z1 = _inner_port_expressions(upper_reference, lower_reference, bottom_up)
    port_references = _port_reference_conductors(
        stackup, inner_layer, upper_reference, lower_reference, ground_by_layer
    )
    _create_inner_wave_port(hfss, port_references, z0, z1, pair_center)
    _assign_inner_differential_pair(
        hfss, stackup.differential_impedance, stackup.common_impedance
    )
    _create_analysis_options(hfss, inner)


def build_inner_gf_project(
    stackup_config: StackupConfig,
    gssg_config: GSSGConfig,
    inner_config: InnerGFConfig,
    project_path: str | Path,
    keep_desktop_open: bool = True,
    log_callback=None,
) -> Path:
    """Build and save the inner-line/GF transition project."""
    _validate_inner_config(stackup_config, gssg_config, inner_config)
    project_path = Path(project_path)
    if project_path.exists():
        raise FileExistsError(f"Output project already exists: {project_path}")
    desktop = None
    try:
        version = stackup_config.aedt_version.strip() or None
        desktop = Desktop(version=version, non_graphical=False, new_desktop=False, close_on_exit=False)
        if keep_desktop_open:
            _OPEN_DESKTOPS.append(desktop)
        hfss = Hfss(
            project=str(project_path), design=stackup_config.design_name,
            solution_type="Terminal", version=version, new_desktop=False, close_on_exit=False,
            aedt_process_id=desktop.aedt_process_id,
        )
        _build_inner_stack(hfss, stackup_config, gssg_config, inner_config)
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
    """Build the default eight-layer L1-GF to L2 transition model."""
    stackup = eight_layer_example()
    stackup.design_name = DESIGN_NAME
    stackup.aedt_version = AEDT_VERSION
    gssg = GSSGConfig(signal_layer_name="L1")
    return build_inner_gf_project(
        stackup,
        gssg,
        InnerGFConfig(
            upper_reference_layer_name="L1",
            lower_reference_layer_name="L3",
        ),
        PROJECT_PATH,
        KEEP_DESKTOP_OPEN,
    )


if __name__ == "__main__":
    build_project()
