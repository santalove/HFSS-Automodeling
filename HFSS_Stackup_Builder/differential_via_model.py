"""Build a single-stage differential line-to-via-to-line HFSS model.

The electrical route runs from a configurable copper layer on the negative-X
side through a P/N transition to another copper layer on the positive-X side.
The transition can be an all-laser stack (pad on every copper layer), or a
laser/mechanical/laser stack whose mechanical span has pads only at its ends.
Both line ends have independent W/S/G, trace length, and fanout length.

No solve is started and existing projects are never overwritten.
"""

# Developer: 39004628 / Luxshare
# Copyright © 2026 39004628 / Luxshare. All rights reserved.

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import atan2, ceil, cos, floor, hypot, pi, sin
from pathlib import Path
import re
from typing import Callable

from pyaedt import Desktop, Hfss

try:
    from hfss_stackup_builder import (
        Layer,
        StackupConfig,
        _create_materials,
        _identifier,
        _nearest_copper,
        _origin_expression_bottom_up,
        _port_reference_conductors,
        _resolve_reference_layers,
        _set_object_color,
        copper_layer_colors,
        create_hfss_analysis,
        eight_layer_example,
        height_variable,
        layer_material_groups,
        set_copper_transparency,
    )
except ImportError:  # pragma: no cover
    from .hfss_stackup_builder import (
        Layer,
        StackupConfig,
        _create_materials,
        _identifier,
        _nearest_copper,
        _origin_expression_bottom_up,
        _port_reference_conductors,
        _resolve_reference_layers,
        _set_object_color,
        copper_layer_colors,
        create_hfss_analysis,
        eight_layer_example,
        height_variable,
        layer_material_groups,
        set_copper_transparency,
    )


@dataclass
class DifferentialLineEndConfig:
    """Independent geometry for one remote differential-line end."""

    trace_length: str = "1.5mm"
    fanout_length: str = "0.5mm"
    w_line: str = "100um"
    s_line: str = "100um"
    g_line: str = "40um"
    upper_reference_layer_name: str = ""
    lower_reference_layer_name: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "DifferentialLineEndConfig":
        return cls(**{
            name: str(data[name])
            for name in (
                "trace_length", "fanout_length", "w_line", "s_line", "g_line",
                "upper_reference_layer_name", "lower_reference_layer_name",
            )
            if name in data
        })

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DifferentialViaConfig:
    """Configuration for one P/N via stage between two route layers."""

    route_layers: list[str] = field(default_factory=lambda: ["L2", "L4"])
    start_line: DifferentialLineEndConfig = field(default_factory=lambda: DifferentialLineEndConfig(
        upper_reference_layer_name="L1", lower_reference_layer_name="L3"
    ))
    end_line: DifferentialLineEndConfig = field(default_factory=lambda: DifferentialLineEndConfig(
        upper_reference_layer_name="L3", lower_reference_layer_name="L5"
    ))
    d_via: str = "0.5mm"
    via_column_radius: str = "0.057mm"
    via_pad_radius: str = "0.127mm"
    via_antipad_radius: str = "10mil"
    via_antipad_x: str = "10mil"
    layer_antipads: dict[str, dict[str, str]] = field(default_factory=dict)
    mechanical_via_enabled: bool = False
    mechanical_start_layer: str = ""
    mechanical_end_layer: str = ""
    mechanical_column_radius: str = "3mil"
    mechanical_pad_radius: str = "6mil"
    return_column_radius: str = "0.057mm"
    line_return_pitch: str = "5mil"
    line_return_edge_offset: str = "5mil"
    local_return_pitch: str = "10mil"
    local_return_clearance: str = "2mil"
    side_margin: str = "1mm"
    create_open_region: bool = True
    open_region_frequency: str = "60GHz"
    create_setup: bool = True
    create_sweep: bool = True
    sweep_start: str = "0.01GHz"
    sweep_stop: str = "60GHz"
    sweep_points: int = 401

    @classmethod
    def from_dict(cls, data: dict) -> "DifferentialViaConfig":
        values = {
            name: str(data[name])
            for name in (
                "d_via", "via_column_radius", "via_pad_radius", "via_antipad_radius",
                "via_antipad_x",
                "mechanical_start_layer", "mechanical_end_layer",
                "mechanical_column_radius", "mechanical_pad_radius",
                "return_column_radius", "line_return_pitch", "line_return_edge_offset",
                "local_return_pitch", "local_return_clearance", "side_margin",
                "open_region_frequency", "sweep_start", "sweep_stop",
            )
            if name in data
        }
        for name in (
            "mechanical_via_enabled", "create_open_region", "create_setup", "create_sweep"
        ):
            if name in data:
                value = data[name]
                values[name] = value if isinstance(value, bool) else str(value).lower() in {
                    "1", "true", "yes", "on"
                }
        if "sweep_points" in data:
            values["sweep_points"] = int(data["sweep_points"])
        if "route_layers" in data:
            values["route_layers"] = [str(item) for item in data["route_layers"]]
        if "layer_antipads" in data and isinstance(data["layer_antipads"], dict):
            values["layer_antipads"] = {
                str(layer): {
                    "radius": str(settings.get("radius", data.get("via_antipad_radius", "10mil"))),
                    "x": str(settings.get("x", data.get("via_antipad_x", "10mil"))),
                }
                for layer, settings in data["layer_antipads"].items()
                if isinstance(settings, dict)
            }
        if "start_line" in data:
            values["start_line"] = DifferentialLineEndConfig.from_dict(data["start_line"])
        if "end_line" in data:
            values["end_line"] = DifferentialLineEndConfig.from_dict(data["end_line"])
        return cls(**values)

    def to_dict(self) -> dict:
        return asdict(self)


AEDT_VERSION = ""
DESIGN_NAME = "DifferentialViaTransition"
PROJECT_PATH = Path(__file__).with_name("differential_via_model.aedt")
KEEP_DESKTOP_OPEN = True
_OPEN_DESKTOPS: list[Desktop] = []


def _literal_mm(value: str, field_name: str) -> float:
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(mm|mil|um|in)\s*",
        value,
        re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"{field_name} must be a literal length with unit mm, mil, um, or in.")
    magnitude = float(match.group(1))
    factors = {"mm": 1.0, "mil": 0.0254, "um": 0.001, "in": 25.4}
    return magnitude * factors[match.group(2).lower()]


def _mm(value: float) -> str:
    text = f"{value:.9f}".rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        text = "0"
    return f"{text}mm"


def _validate_stackup(stackup: StackupConfig) -> None:
    if len(stackup.layers) < 3:
        raise ValueError("At least three stackup layers are required.")
    if len({layer.name for layer in stackup.layers}) != len(stackup.layers):
        raise ValueError("Layer names must be unique.")
    if stackup.differential_impedance <= 0:
        raise ValueError("Differential-mode impedance must be positive.")
    if stackup.common_impedance <= 0:
        raise ValueError("Common-mode impedance must be positive.")
    for layer in stackup.layers:
        if layer.kind not in {"copper", "pp", "core"}:
            raise ValueError(f"{layer.name}: invalid layer kind {layer.kind!r}.")
        if not layer.thickness.strip():
            raise ValueError(f"{layer.name}: thickness is required.")
        if layer.kind in {"pp", "core"} and (layer.dk is None or layer.df is None):
            raise ValueError(f"{layer.name}: PP/Core layers require DK and DF.")


def _route_copper_path(stackup: StackupConfig, start: Layer, end: Layer) -> list[Layer]:
    """Return all copper layers from electrical start to electrical end."""
    copper = [layer for layer in stackup.layers if layer.kind == "copper"]
    start_index, end_index = copper.index(start), copper.index(end)
    step = 1 if end_index > start_index else -1
    return copper[start_index:end_index + step:step]


def _via_topology(
    stackup: StackupConfig,
    start: Layer,
    end: Layer,
    config: DifferentialViaConfig,
) -> tuple[list[Layer], list[tuple[Layer, Layer]], tuple[Layer, Layer] | None, dict[str, str]]:
    """Resolve laser stacks, optional mechanical span, and pad technology."""
    path = _route_copper_path(stackup, start, end)
    if not config.mechanical_via_enabled:
        laser_segments = list(zip(path, path[1:]))
        return path, laser_segments, None, {layer.name: "laser" for layer in path}

    if len(path) < 3:
        raise ValueError(
            "Mechanical VIA requires at least one internal copper layer between route layers."
        )
    start_names = [layer.name for layer in path]
    if config.mechanical_start_layer not in start_names[1:-1]:
        raise ValueError(
            "mechanical_start_layer must be an internal copper layer before the end route layer."
        )
    mechanical_start_index = start_names.index(config.mechanical_start_layer)
    # Preserve older JSON files, which omitted the endpoint and implicitly
    # reserved the final transition for a laser VIA.
    mechanical_end_name = config.mechanical_end_layer or start_names[-2]
    if mechanical_end_name not in start_names[mechanical_start_index + 1:]:
        raise ValueError(
            "mechanical_end_layer must be after mechanical_start_layer along the "
            "electrical route and no farther than the end route layer."
        )
    mechanical_end_index = start_names.index(mechanical_end_name)
    mechanical = (path[mechanical_start_index], path[mechanical_end_index])
    laser_segments = list(zip(path[:mechanical_start_index], path[1:mechanical_start_index + 1]))
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


def _layer_antipad_values(
    config: DifferentialViaConfig, layer_name: str
) -> tuple[str, str]:
    override = config.layer_antipads.get(layer_name, {})
    return (
        str(override.get("radius", config.via_antipad_radius)),
        str(override.get("x", config.via_antipad_x)),
    )


def _antipad_variable_names(layer: Layer) -> tuple[str, str]:
    suffix = _identifier(layer.name).upper()
    return f"VIA_ANTIPAD_RADIUS_{suffix}", f"VIA_ANTIPAD_X_{suffix}"


def _validate_config(
    stackup: StackupConfig, config: DifferentialViaConfig
) -> tuple[Layer, Layer, dict[str, float]]:
    _validate_stackup(stackup)
    if len(config.route_layers) != 2:
        raise ValueError("Single-stage version requires exactly two route_layers.")
    if config.route_layers[0] == config.route_layers[1]:
        raise ValueError("The start and end route layers must be different.")
    selected: list[Layer] = []
    for name in config.route_layers:
        matches = [layer for layer in stackup.layers if layer.name == name]
        if not matches or matches[0].kind != "copper":
            raise ValueError(f"Route layer {name!r} must be a copper layer.")
        selected.append(matches[0])

    copper = [layer for layer in stackup.layers if layer.kind == "copper"]
    if len(copper) < 2:
        raise ValueError("At least two copper layers are required.")
    for prefix, layer, line in (
        ("start", selected[0], config.start_line),
        ("end", selected[1], config.end_line),
    ):
        _line_reference_layers(stackup, layer, line, prefix)

    dimensions: dict[str, float] = {}
    for prefix, line in (("start", config.start_line), ("end", config.end_line)):
        for field_name in ("trace_length", "fanout_length", "w_line", "s_line", "g_line"):
            key = f"{prefix}_{field_name}"
            dimensions[key] = _literal_mm(str(getattr(line, field_name)), key)
    for field_name in (
        "d_via", "via_column_radius", "via_pad_radius", "via_antipad_radius",
        "via_antipad_x",
        "mechanical_column_radius", "mechanical_pad_radius",
        "return_column_radius", "line_return_pitch", "line_return_edge_offset",
        "local_return_pitch", "local_return_clearance", "side_margin",
    ):
        dimensions[field_name] = _literal_mm(str(getattr(config, field_name)), field_name)
    nonnegative = {"line_return_edge_offset", "local_return_clearance"}
    for name, value in dimensions.items():
        if value < 0 or (value == 0 and name not in nonnegative):
            raise ValueError(f"{name} must be {'non-negative' if name in nonnegative else 'positive'}.")
    if dimensions["via_pad_radius"] <= dimensions["via_column_radius"]:
        raise ValueError("via_pad_radius must be greater than via_column_radius.")
    if dimensions["via_antipad_radius"] <= dimensions["via_pad_radius"]:
        raise ValueError("via_antipad_radius must be greater than via_pad_radius.")
    if dimensions["mechanical_pad_radius"] <= dimensions["mechanical_column_radius"]:
        raise ValueError(
            "mechanical_pad_radius must be greater than mechanical_column_radius."
        )

    path, _, mechanical, pad_technology = _via_topology(
        stackup, selected[0], selected[1], config
    )
    layer_radii: list[float] = []
    layer_x_values: list[float] = []
    for layer in path:
        radius_text, x_text = _layer_antipad_values(config, layer.name)
        radius = _literal_mm(radius_text, f"via_antipad_radius_{layer.name}")
        x_value = _literal_mm(x_text, f"via_antipad_x_{layer.name}")
        if radius <= 0 or x_value <= 0:
            raise ValueError(f"{layer.name} anti-pad radius and X must be positive.")
        pad_kind = pad_technology.get(layer.name)
        if pad_kind:
            pad_radius = dimensions[
                "mechanical_pad_radius" if pad_kind == "mechanical" else "via_pad_radius"
            ]
            if radius <= pad_radius:
                raise ValueError(
                    f"via_antipad_radius_{layer.name} must exceed its {pad_kind} pad radius."
                )
        dimensions[f"via_antipad_radius_{layer.name}"] = radius
        dimensions[f"via_antipad_x_{layer.name}"] = x_value
        layer_radii.append(radius)
        layer_x_values.append(x_value)
    dimensions["transition_via_antipad_radius"] = max(layer_radii)
    dimensions["transition_via_antipad_x"] = max(layer_x_values)
    return selected[0], selected[1], dimensions


def _line_reference_layers(
    stackup: StackupConfig,
    layer: Layer,
    line: DifferentialLineEndConfig,
    prefix: str,
) -> tuple[Layer | None, Layer | None]:
    """Resolve one line end's explicit upper/lower reference copper."""
    return _resolve_reference_layers(
        stackup,
        layer,
        line.upper_reference_layer_name,
        line.lower_reference_layer_name,
        require_ground_role=False,
        field_prefix=prefix,
    )


def _adjacent_dielectric(stackup: StackupConfig, layer: Layer, direction: int) -> Layer:
    index = stackup.layers.index(layer) + direction
    while 0 <= index < len(stackup.layers):
        candidate = stackup.layers[index]
        if candidate.kind in {"pp", "core"}:
            return candidate
        index += direction
    raise ValueError(f"External route layer {layer.name} has no adjacent dielectric.")


def _reference_span(
    stackup: StackupConfig,
    layer: Layer,
    upper_reference: Layer | None,
    lower_reference: Layer | None,
    bottom_up: list[Layer],
) -> tuple[str, str]:
    """Return the outer Z faces of the references relevant to one line."""
    layer_origin = _origin_expression_bottom_up(bottom_up, layer.name)
    lower_origin = (
        _origin_expression_bottom_up(bottom_up, lower_reference.name)
        if lower_reference else layer_origin
    )
    upper = upper_reference or layer
    upper_origin = _origin_expression_bottom_up(bottom_up, upper.name)
    return lower_origin, f"({upper_origin})+{height_variable(upper)}"


def _port_span(
    stackup: StackupConfig,
    layer: Layer,
    upper_reference: Layer | None,
    lower_reference: Layer | None,
    bottom_up: list[Layer],
) -> tuple[str, str]:
    """Return an internal full-reference span or an external CPWG span."""
    copper = [item for item in stackup.layers if item.kind == "copper"]
    copper_index = copper.index(layer)
    layer_index = stackup.layers.index(layer)
    if copper_index == 0:
        if lower_reference is None:
            raise ValueError(f"External route layer {layer.name} requires a lower reference.")
        dielectric = _adjacent_dielectric(stackup, layer, 1)
        # Keep the established surface-CPWG rule: start at the lower face of
        # the inward reference copper and make the complete sheet 8*PP high.
        z0 = _origin_expression_bottom_up(bottom_up, lower_reference.name)
        layer_origin = _origin_expression_bottom_up(bottom_up, layer.name)
        layer_top = f"({layer_origin})+{height_variable(layer)}"
        z1 = f"({layer_top})+8*{height_variable(dielectric)}"
        return z0, z1
    if copper_index == len(copper) - 1:
        if upper_reference is None:
            raise ValueError(f"External route layer {layer.name} requires an upper reference.")
        dielectric = _adjacent_dielectric(stackup, layer, -1)
        inward_origin = _origin_expression_bottom_up(bottom_up, upper_reference.name)
        z1 = f"({inward_origin})+{height_variable(upper_reference)}"
        z0 = f"({z1})-8*{height_variable(dielectric)}"
        return z0, z1
    return _reference_span(
        stackup, layer, upper_reference, lower_reference, bottom_up
    )


def _transition_reference_span(
    stackup: StackupConfig,
    start_layer: Layer,
    end_layer: Layer,
    start_references: tuple[Layer | None, Layer | None],
    end_references: tuple[Layer | None, Layer | None],
    bottom_up: list[Layer],
) -> tuple[str, str]:
    """Return the outermost ground span enclosing the complete transition."""
    copper = [layer for layer in stackup.layers if layer.kind == "copper"]
    enclosing = [
        layer for layer in (
            start_layer, end_layer, *start_references, *end_references
        ) if layer is not None
    ]
    upper = min(enclosing, key=stackup.layers.index)
    lower = max(enclosing, key=stackup.layers.index)
    lower_origin = _origin_expression_bottom_up(bottom_up, lower.name)
    upper_origin = _origin_expression_bottom_up(bottom_up, upper.name)
    return lower_origin, f"({upper_origin})+{height_variable(upper)}"


def _create_fanout_polygon(
    hfss: Hfss,
    name: str,
    x_line: str,
    x_via: str,
    line_center: str,
    via_center: str,
    width_variable: str,
    z_origin: str,
    height: str,
    material: str = "copper",
) -> object:
    points = [
        [x_line, f"({line_center})-{width_variable}/2", z_origin],
        [x_line, f"({line_center})+{width_variable}/2", z_origin],
        [x_via, f"({via_center})+VIA_PAD_RADIUS", z_origin],
        [x_via, f"({via_center})-VIA_PAD_RADIUS", z_origin],
    ]
    sheet = hfss.modeler.create_polyline(
        points, cover_surface=True, close_surface=True, name=name, material=material
    )
    if not sheet:
        raise RuntimeError(f"Unable to create {name}.")
    solid = hfss.modeler.sweep_along_vector(sheet, ["0mm", "0mm", height])
    if not solid:
        raise RuntimeError(f"Unable to sweep {name}.")
    return solid


def _create_route_layer_clearance(
    hfss: Hfss,
    ground: object,
    prefix: str,
    direction: int,
    z_origin: str,
    height: str,
    antipad_radius_variable: str,
    name_suffix: str = "",
) -> None:
    p = prefix.upper()
    object_prefix = f"{p}{name_suffix}"
    x_line = f"-{p}_FANOUT_LENGTH" if direction < 0 else f"{p}_FANOUT_LENGTH"
    x_trace = "BOARD_X0" if direction < 0 else x_line
    trace_length = f"{p}_TRACE_LENGTH"
    straight = hfss.modeler.create_box(
        [x_trace, f"BOARD_CENTER_Y-({p}_S_LINE+2*{p}_W_LINE+2*{p}_G_LINE)/2", z_origin],
        [trace_length, f"{p}_S_LINE+2*{p}_W_LINE+2*{p}_G_LINE", height],
        name=f"{object_prefix}_TRACE_CLEARANCE", material="vacuum",
    )
    if not straight or not hfss.modeler.subtract(ground, straight, keep_originals=False):
        raise RuntimeError(f"Unable to create {p} trace clearance.")
    line_half = f"({p}_S_LINE+2*{p}_W_LINE+2*{p}_G_LINE)/2"
    # Keep the sum grouped before applying +/- around BOARD_CENTER_Y. Without
    # these parentheses the negative side becomes ``-D_VIA/2 + radius``, can
    # cross the center line, and Parasolid rejects the closed polyline with
    # PK_ERROR_crossing_edge.
    via_half = f"(D_VIA/2+{antipad_radius_variable})"
    # Use two explicit center-line halves.  Although a single symmetric
    # quadrilateral is mathematically equivalent, AEDT can retain only one
    # half after sequential overlapping clearance booleans.  Subtracting the
    # +Y shape and its exact -Y mirror guarantees clearance on both sides.
    fanout_halves = (
        (
            f"{object_prefix}_FANOUT_CLEARANCE",
            [
                [x_line, "BOARD_CENTER_Y", z_origin],
                [x_line, f"BOARD_CENTER_Y+{line_half}", z_origin],
                ["0mm", f"BOARD_CENTER_Y+{via_half}", z_origin],
                ["0mm", "BOARD_CENTER_Y", z_origin],
            ],
        ),
        (
            f"{object_prefix}_FANOUT_CLEARANCE_MIRROR",
            [
                [x_line, "BOARD_CENTER_Y", z_origin],
                [x_line, f"BOARD_CENTER_Y-{line_half}", z_origin],
                ["0mm", f"BOARD_CENTER_Y-{via_half}", z_origin],
                ["0mm", "BOARD_CENTER_Y", z_origin],
            ],
        ),
    )
    for name, points in fanout_halves:
        sheet = hfss.modeler.create_polyline(
            points, cover_surface=True, close_surface=True,
            name=name, material="vacuum",
        )
        if not sheet:
            raise RuntimeError(f"Unable to create {name}.")
        tool = hfss.modeler.sweep_along_vector(sheet, ["0mm", "0mm", height])
        if not tool or not hfss.modeler.subtract(ground, tool, keep_originals=False):
            raise RuntimeError(f"Unable to subtract {name}.")


def _subtract_line_reference_clearances(
    hfss: Hfss,
    stackup: StackupConfig,
    line_layer: Layer,
    references: tuple[Layer | None, Layer | None],
    records: list[dict[str, object]],
    prefix: str,
    direction: int,
) -> None:
    """Open trace/fanout corridors on reference-separated copper layers."""
    signal_index = stackup.layers.index(line_layer)
    upper, lower = references
    upper_index = stackup.layers.index(upper) if upper else signal_index
    lower_index = stackup.layers.index(lower) if lower else signal_index
    for record in records:
        record_index = int(record["config_index"])
        if not (
            upper_index < record_index < signal_index
            or signal_index < record_index < lower_index
        ):
            continue
        layer = record["layer"]
        radius_name, _ = _antipad_variable_names(layer)
        _create_route_layer_clearance(
            hfss,
            record["ground"],
            prefix,
            direction,
            record["z_origin"],
            height_variable(layer),
            radius_name,
            name_suffix=f"_SKIPPED_REF_{_identifier(layer.name)}",
        )


def _create_slot_antipad(
    hfss: Hfss,
    ground: object,
    layer_name: str,
    z_origin: str,
    height: str,
    radius_variable: str,
    x_variable: str,
) -> object:
    """Subtract two anti-pad circles plus +/-X center-line rectangles."""
    m = hfss.modeler
    prefix = f"{_identifier(layer_name)}_SIG_SLOT_ANTIPAD"
    circle_p = m.create_cylinder(
        "Z", ["0mm", "BOARD_CENTER_Y-D_VIA/2", z_origin],
        radius_variable, height,
        name=prefix, material="vacuum",
    )
    circle_n = m.create_cylinder(
        "Z", ["0mm", "BOARD_CENTER_Y+D_VIA/2", z_origin],
        radius_variable, height,
        name=f"{prefix}_N_CIRCLE", material="vacuum",
    )
    neck_negative_x = m.create_box(
        [f"-{x_variable}", "BOARD_CENTER_Y-D_VIA/2", z_origin],
        [x_variable, "D_VIA", height],
        name=f"{prefix}_NECK_NEG_X", material="vacuum",
    )
    neck_positive_x = m.create_box(
        ["0mm", "BOARD_CENTER_Y-D_VIA/2", z_origin],
        [x_variable, "D_VIA", height],
        name=f"{prefix}_NECK_POS_X", material="vacuum",
    )
    if not circle_p or not circle_n or not neck_negative_x or not neck_positive_x:
        raise RuntimeError(f"Unable to create slot anti-pad on {layer_name}.")
    parts = [
        circle_p.name, circle_n.name,
        neck_negative_x.name, neck_positive_x.name,
    ]
    if not m.unite(parts):
        raise RuntimeError(f"Unable to unite slot anti-pad on {layer_name}.")
    if not m.subtract(ground, circle_p, keep_originals=False):
        raise RuntimeError(f"Unable to subtract slot anti-pad on {layer_name}.")
    return circle_p


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


def _create_line_objects(
    hfss: Hfss,
    prefix: str,
    direction: int,
    z_origin: str,
    height: str,
    color: tuple[int, int, int],
) -> dict[str, object]:
    p = prefix.upper()
    line_centers = {
        "P": f"BOARD_CENTER_Y-({p}_W_LINE+{p}_S_LINE)/2",
        "N": f"BOARD_CENTER_Y+({p}_W_LINE+{p}_S_LINE)/2",
    }
    via_centers = {
        "P": "BOARD_CENTER_Y-D_VIA/2",
        "N": "BOARD_CENTER_Y+D_VIA/2",
    }
    result: dict[str, object] = {}
    for side in ("P", "N"):
        trace_x = "BOARD_X0" if direction < 0 else f"{p}_FANOUT_LENGTH"
        trace = hfss.modeler.create_box(
            [trace_x, f"({line_centers[side]})-{p}_W_LINE/2", z_origin],
            [f"{p}_TRACE_LENGTH", f"{p}_W_LINE", height],
            name=f"{p}_TRACE_{side}", material="copper",
        )
        if not trace:
            raise RuntimeError(f"Unable to create {p}_TRACE_{side}.")
        x_line = f"-{p}_FANOUT_LENGTH" if direction < 0 else f"{p}_FANOUT_LENGTH"
        fanout = _create_fanout_polygon(
            hfss, f"{p}_FANOUT_{side}", x_line, "0mm",
            line_centers[side], via_centers[side], f"{p}_W_LINE", z_origin, height,
        )
        _set_object_color(trace, color)
        _set_object_color(fanout, color)
        result[f"trace_{side}"] = trace
        result[f"fanout_{side}"] = fanout
    return result


def _slot_return_points(
    d_via_mm: float,
    antipad_radius_mm: float,
    antipad_x_mm: float,
    return_radius_mm: float,
    clearance_mm: float,
    pitch_mm: float,
) -> list[tuple[float, float]]:
    """Evenly sample the clearance contour of two circles plus a wide neck.

    The physical anti-pad is the union of two radius-R circles and a centered
    rectangle pair extending ``antipad_x_mm`` in both +/-X directions from
    the P/N center line. Return-column centers follow that union expanded by
    the requested copper clearance plus the return-column radius.
    """
    expansion = clearance_mm + return_radius_mm
    circle_radius = antipad_radius_mm + expansion
    half_neck_x = antipad_x_mm
    half_pair_y = d_via_mm / 2

    def inside_expanded_slot(x: float, y: float) -> bool:
        if hypot(x, y - half_pair_y) <= circle_radius:
            return True
        if hypot(x, y + half_pair_y) <= circle_radius:
            return True
        dx = max(abs(x) - half_neck_x, 0.0)
        dy = max(abs(y) - half_pair_y, 0.0)
        return hypot(dx, dy) <= expansion

    # The connected slot is star-shaped around the pair midpoint.  Find its
    # radial boundary densely, then resample the closed contour by arc length.
    dense_count = 1440
    outer = max(
        half_pair_y + circle_radius,
        half_neck_x + expansion,
    ) * 1.25

    def boundary_on_angle(theta: float) -> tuple[float, float]:
        ux, uy = cos(theta), sin(theta)
        low, high = 0.0, outer
        while inside_expanded_slot(high * ux, high * uy):
            high *= 2
        for _ in range(48):
            middle = (low + high) / 2
            if inside_expanded_slot(middle * ux, middle * uy):
                low = middle
            else:
                high = middle
        return low * ux, low * uy

    dense: list[tuple[float, float]] = []
    for index in range(dense_count):
        theta = 2 * pi * index / dense_count
        dense.append(boundary_on_angle(theta))

    segment_lengths = [
        hypot(
            dense[(index + 1) % dense_count][0] - dense[index][0],
            dense[(index + 1) % dense_count][1] - dense[index][1],
        )
        for index in range(dense_count)
    ]
    perimeter = sum(segment_lengths)
    count = max(4, ceil(perimeter / pitch_mm))
    spacing = perimeter / count
    points: list[tuple[float, float]] = []
    segment_index = 0
    traversed = 0.0
    for point_index in range(count):
        target = point_index * spacing
        while traversed + segment_lengths[segment_index] < target:
            traversed += segment_lengths[segment_index]
            segment_index += 1
        start = dense[segment_index]
        end = dense[(segment_index + 1) % dense_count]
        length = segment_lengths[segment_index]
        fraction = 0.0 if length == 0 else (target - traversed) / length
        interpolated = (
            start[0] + fraction * (end[0] - start[0]),
            start[1] + fraction * (end[1] - start[1]),
        )
        # Chord interpolation lies microscopically inside convex arcs. Project
        # it back to the exact radial clearance contour before placing a via.
        points.append(boundary_on_angle(atan2(interpolated[1], interpolated[0])))
    return points


def _distance_to_rectangle(
    point: tuple[float, float], x0: float, x1: float, y0: float, y1: float
) -> float:
    dx = max(min(x0, x1) - point[0], 0.0, point[0] - max(x0, x1))
    dy = max(min(y0, y1) - point[1], 0.0, point[1] - max(y0, y1))
    return hypot(dx, dy)


def _distance_to_segment(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    if not length2:
        return hypot(point[0] - start[0], point[1] - start[1])
    fraction = max(
        0.0,
        min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2),
    )
    return hypot(
        point[0] - (start[0] + fraction * dx),
        point[1] - (start[1] + fraction * dy),
    )


def _distance_to_polygon(
    point: tuple[float, float], vertices: list[tuple[float, float]]
) -> float:
    inside = False
    previous = vertices[-1]
    for current in vertices:
        if (
            (current[1] > point[1]) != (previous[1] > point[1])
            and point[0]
            < (previous[0] - current[0]) * (point[1] - current[1])
            / (previous[1] - current[1])
            + current[0]
        ):
            inside = not inside
        previous = current
    if inside:
        return 0.0
    return min(
        _distance_to_segment(point, vertices[index - 1], vertices[index])
        for index in range(len(vertices))
    )


def _return_disk_intersects_slot(
    point: tuple[float, float], via_x: float, d_via: float,
    antipad_radius: float, antipad_x: float, return_radius: float,
) -> bool:
    half_pair = d_via / 2
    return (
        hypot(point[0] - via_x, point[1] - half_pair) < antipad_radius + return_radius
        or hypot(point[0] - via_x, point[1] + half_pair) < antipad_radius + return_radius
        or _distance_to_rectangle(
            point, via_x - antipad_x, via_x + antipad_x, -half_pair, half_pair
        ) < return_radius
    )


def _return_disk_intersects_route(
    point: tuple[float, float], dimensions: dict[str, float], prefix: str,
    direction: int, via_x: float, d_via: float, antipad_radius: float,
) -> bool:
    """Check a complete return-column disk against straight and fanout voids."""
    return_radius = dimensions["return_column_radius"]
    trace_half = (
        dimensions[f"{prefix}_s_line"]
        + 2 * dimensions[f"{prefix}_w_line"]
        + 2 * dimensions[f"{prefix}_g_line"]
    ) / 2
    line_x = via_x + direction * dimensions[f"{prefix}_fanout_length"]
    remote_x = line_x + direction * dimensions[f"{prefix}_trace_length"]
    if _distance_to_rectangle(
        point, line_x, remote_x, -trace_half, trace_half
    ) < return_radius:
        return True
    via_half = d_via / 2 + antipad_radius
    fanout = [
        (line_x, -trace_half),
        (line_x, trace_half),
        (via_x, via_half),
        (via_x, -via_half),
    ]
    return _distance_to_polygon(point, fanout) < return_radius


def _single_stage_return_point_allowed(
    point: tuple[float, float], dimensions: dict[str, float],
    start_layer_name: str, end_layer_name: str,
) -> bool:
    """Reject return columns whose full cross-section touches any copper void."""
    return_radius = dimensions["return_column_radius"]
    if _return_disk_intersects_slot(
        point, 0.0, dimensions["d_via"],
        dimensions["transition_via_antipad_radius"],
        dimensions["transition_via_antipad_x"], return_radius,
    ):
        return False
    return not (
        _return_disk_intersects_route(
            point, dimensions, "start", -1, 0.0, dimensions["d_via"],
            dimensions[f"via_antipad_radius_{start_layer_name}"],
        )
        or _return_disk_intersects_route(
            point, dimensions, "end", 1, 0.0, dimensions["d_via"],
            dimensions[f"via_antipad_radius_{end_layer_name}"],
        )
    )


def _create_line_return_rows(
    hfss: Hfss,
    prefix: str,
    direction: int,
    z0: str,
    z1: str,
    dimensions: dict[str, float],
    point_allowed: Callable[[tuple[float, float]], bool] | None = None,
) -> list[object]:
    p = prefix.upper()
    ring_radius = (
        max(
            dimensions["transition_via_antipad_radius"],
            dimensions["transition_via_antipad_x"],
        )
        + dimensions["local_return_clearance"]
        + dimensions["return_column_radius"]
    )
    trace = dimensions[f"{prefix}_trace_length"]
    fanout = dimensions[f"{prefix}_fanout_length"]
    edge = dimensions["line_return_edge_offset"]
    pitch = dimensions["line_return_pitch"]
    span = trace + fanout - ring_radius - edge
    if span < 0:
        raise ValueError(f"{prefix} line is too short to connect its return-via rows to the local fence.")
    count = floor(span / pitch) + 1
    y_offset = f"{p}_S_LINE/2+{p}_W_LINE+{p}_G_LINE+LINE_RETURN_EDGE_OFFSET"
    vias: list[object] = []
    for side, y in (
        ("L", f"BOARD_CENTER_Y-({y_offset})"),
        ("R", f"BOARD_CENTER_Y+({y_offset})"),
    ):
        numeric_y = (
            dimensions[f"{prefix}_s_line"] / 2
            + dimensions[f"{prefix}_w_line"]
            + dimensions[f"{prefix}_g_line"]
            + edge
        ) * (-1 if side == "L" else 1)
        accepted_index = 0
        for index in range(count):
            if direction < 0:
                x = f"BOARD_X0+LINE_RETURN_EDGE_OFFSET+{index}*LINE_RETURN_PITCH"
                numeric_x = -(trace + fanout) + edge + index * pitch
            else:
                x = f"BOARD_X1-LINE_RETURN_EDGE_OFFSET-{index}*LINE_RETURN_PITCH"
                numeric_x = (
                    dimensions.get("stage2_x", 0.0)
                    + trace + fanout - edge - index * pitch
                )
            if point_allowed is not None and not point_allowed((numeric_x, numeric_y)):
                continue
            accepted_index += 1
            via = hfss.modeler.create_cylinder(
                "Z", [x, y, z0], "RETURN_COLUMN_RADIUS", f"({z1})-({z0})",
                name=f"{p}_RETURN_VIA_{side}_{accepted_index:03d}_COLUMN", material="copper",
            )
            if not via:
                raise RuntimeError(f"Unable to create {p} return via {side}{index + 1}.")
            _set_object_color(via, (145, 145, 145))
            vias.append(via)
    return vias


def _create_local_return_fence(
    hfss: Hfss,
    z0: str,
    z1: str,
    dimensions: dict[str, float],
    point_allowed: Callable[[tuple[float, float]], bool] | None = None,
) -> list[object]:
    points = _slot_return_points(
        dimensions["d_via"], dimensions["transition_via_antipad_radius"],
        dimensions["transition_via_antipad_x"],
        dimensions["return_column_radius"], dimensions["local_return_clearance"],
        dimensions["local_return_pitch"],
    )
    vias: list[object] = []
    for x, y in points:
        if point_allowed is not None and not point_allowed((x, y)):
            continue
        index = len(vias) + 1
        via = hfss.modeler.create_cylinder(
            "Z", [_mm(x), f"BOARD_CENTER_Y+({_mm(y)})", z0],
            "RETURN_COLUMN_RADIUS", f"({z1})-({z0})",
            name=f"LOCAL_RETURN_VIA_{index:03d}_COLUMN", material="copper",
        )
        if not via:
            raise RuntimeError(f"Unable to create local return via {index}.")
        _set_object_color(via, (145, 145, 145))
        vias.append(via)
    return vias


def _references_for_port(ground_objects: list[object], port_sheet: object) -> list[str]:
    port_box = port_sheet.bounding_box
    tolerance = 1e-9
    names: list[str] = []
    for ground in ground_objects:
        box = ground.bounding_box
        x_overlap = box[0] <= port_box[3] + tolerance and box[3] >= port_box[0] - tolerance
        z_overlap = box[2] <= port_box[5] + tolerance and box[5] >= port_box[2] - tolerance
        if x_overlap and z_overlap:
            names.append(ground.name)
    if not names:
        raise RuntimeError(f"No reference ground intersects port sheet {port_sheet.name}.")
    return names


def _create_wave_port(
    hfss: Hfss,
    prefix: str,
    x: str,
    z0: str,
    z1: str,
    port_width: str,
    references: list[str],
    pair_index: int,
    differential_impedance: float,
    common_impedance: float,
) -> None:
    p = prefix.upper()
    hfss[f"{p}_PORT_Z0"] = z0
    hfss[f"{p}_PORT_Z1"] = z1
    hfss[f"{p}_PORT_Z"] = f"{p}_PORT_Z1-{p}_PORT_Z0"
    sheet = hfss.modeler.create_rectangle(
        "YZ", [x, f"BOARD_CENTER_Y-({port_width})/2", f"{p}_PORT_Z0"],
        [port_width, f"{p}_PORT_Z"], name=f"{p}_WAVE_PORT_SHEET",
    )
    if not sheet:
        raise RuntimeError(f"Unable to create {p} wave-port sheet.")
    port_name = f"{p}_WAVE_PORT"
    if not hfss.wave_port(
        sheet, reference=references, create_port_sheet=False, modes=2,
        impedance=50, name=port_name, terminals_rename=True,
    ):
        raise RuntimeError(f"Unable to assign {port_name}.")
    candidates = (
        (f"{port_name}_T1", f"{port_name}_T2"),
        (f"{port_name}_1", f"{port_name}_2"),
    )
    for assignment, reference in candidates:
        if hfss.set_differential_pair(
            assignment=assignment, reference=reference,
            common_mode=f"Comm{pair_index}", differential_mode=f"Diff{pair_index}",
            common_reference=common_impedance,
            differential_reference=differential_impedance,
            active=True, matched=False,
        ):
            return
    raise RuntimeError(f"Unable to create Diff{pair_index}/Comm{pair_index}.")


def _build_geometry(
    hfss: Hfss,
    stackup: StackupConfig,
    config: DifferentialViaConfig,
) -> None:
    start_layer, end_layer, dimensions = _validate_config(stackup, config)
    start_references = _line_reference_layers(
        stackup, start_layer, config.start_line, "start"
    )
    end_references = _line_reference_layers(
        stackup, end_layer, config.end_line, "end"
    )
    via_path, laser_segments, mechanical_segment, pad_technology = _via_topology(
        stackup, start_layer, end_layer, config
    )
    bottom_up = list(reversed(stackup.layers))
    mapping = layer_material_groups(stackup)
    _create_materials(hfss, stackup, mapping)
    colors = copper_layer_colors(stackup)
    m = hfss.modeler
    m.model_units = "mm"

    variable_values = {
        "START_TRACE_LENGTH": config.start_line.trace_length,
        "START_FANOUT_LENGTH": config.start_line.fanout_length,
        "START_W_LINE": config.start_line.w_line,
        "START_S_LINE": config.start_line.s_line,
        "START_G_LINE": config.start_line.g_line,
        "END_TRACE_LENGTH": config.end_line.trace_length,
        "END_FANOUT_LENGTH": config.end_line.fanout_length,
        "END_W_LINE": config.end_line.w_line,
        "END_S_LINE": config.end_line.s_line,
        "END_G_LINE": config.end_line.g_line,
        "D_VIA": config.d_via,
        "VIA_COLUMN_RADIUS": config.via_column_radius,
        "VIA_PAD_RADIUS": config.via_pad_radius,
        "VIA_ANTIPAD_RADIUS": config.via_antipad_radius,
        "VIA_ANTIPAD_X": config.via_antipad_x,
        "MECHANICAL_VIA_COLUMN_RADIUS": config.mechanical_column_radius,
        "MECHANICAL_VIA_PAD_RADIUS": config.mechanical_pad_radius,
        "RETURN_COLUMN_RADIUS": config.return_column_radius,
        "LINE_RETURN_PITCH": config.line_return_pitch,
        "LINE_RETURN_EDGE_OFFSET": config.line_return_edge_offset,
        "LOCAL_RETURN_PITCH": config.local_return_pitch,
        "LOCAL_RETURN_CLEARANCE": config.local_return_clearance,
        "SIDE_MARGIN": config.side_margin,
    }
    for name, value in variable_values.items():
        hfss[name] = value
    copper = [layer for layer in stackup.layers if layer.kind == "copper"]
    for prefix, references in (
        ("START", start_references), ("END", end_references)
    ):
        upper, lower = references
        hfss[f"{prefix}_UPPER_REFERENCE_LAYER"] = (
            str(copper.index(upper) + 1) if upper else "0"
        )
        hfss[f"{prefix}_LOWER_REFERENCE_LAYER"] = (
            str(copper.index(lower) + 1) if lower else "0"
        )
    for layer in (item for item in stackup.layers if item.kind == "copper"):
        radius_name, x_name = _antipad_variable_names(layer)
        radius_value, x_value = _layer_antipad_values(config, layer.name)
        hfss[radius_name] = radius_value
        hfss[x_name] = x_value
    for layer in stackup.layers:
        hfss[height_variable(layer)] = layer.thickness
    ring_y_extent = (
        dimensions["d_via"] / 2 + dimensions["transition_via_antipad_radius"]
        + dimensions["local_return_clearance"] + 2 * dimensions["return_column_radius"]
    )
    start_row_extent = (
        dimensions["start_s_line"] / 2 + dimensions["start_w_line"]
        + dimensions["start_g_line"] + dimensions["line_return_edge_offset"]
        + dimensions["return_column_radius"]
    )
    end_row_extent = (
        dimensions["end_s_line"] / 2 + dimensions["end_w_line"]
        + dimensions["end_g_line"] + dimensions["line_return_edge_offset"]
        + dimensions["return_column_radius"]
    )
    board_width = 2 * (max(ring_y_extent, start_row_extent, end_row_extent) + dimensions["side_margin"])
    hfss["BOARD_WIDTH"] = _mm(board_width)
    hfss["BOARD_CENTER_Y"] = "BOARD_WIDTH/2"
    hfss["BOARD_X0"] = "-(START_TRACE_LENGTH+START_FANOUT_LENGTH)"
    hfss["BOARD_X1"] = "END_TRACE_LENGTH+END_FANOUT_LENGTH"
    hfss["BOARD_LENGTH"] = "BOARD_X1-BOARD_X0"
    hfss["BOARD_THICKNESS"] = "+".join(height_variable(layer) for layer in bottom_up)
    hfss["START_PORT_WIDTH"] = "START_S_LINE+4*START_W_LINE+6*START_G_LINE"
    hfss["END_PORT_WIDTH"] = "END_S_LINE+4*END_W_LINE+6*END_G_LINE"
    hfss["VIA_DIFFERENTIAL_IMPEDANCE"] = str(stackup.differential_impedance)
    hfss["VIA_COMMON_IMPEDANCE"] = str(stackup.common_impedance)

    records: list[dict[str, object]] = []
    ground_by_layer: dict[str, object] = {}
    z_origin = "0mm"
    for layer in bottom_up:
        height = height_variable(layer)
        if layer.kind in {"pp", "core"}:
            dielectric = m.create_box(
                ["BOARD_X0", "0mm", z_origin], ["BOARD_LENGTH", "BOARD_WIDTH", height],
                name=_identifier(layer.name), material=mapping[layer.name],
            )
            if not dielectric:
                raise RuntimeError(f"Unable to create dielectric {layer.name}.")
            dielectric.display_wireframe = True
        else:
            ground = m.create_box(
                ["BOARD_X0", "0mm", z_origin], ["BOARD_LENGTH", "BOARD_WIDTH", height],
                name=f"GND_{_identifier(layer.name)}", material="copper",
            )
            if not ground:
                raise RuntimeError(f"Unable to create ground {layer.name}.")
            _set_object_color(ground, colors[layer.name])
            record = {
                "layer": layer, "ground": ground, "z_origin": z_origin,
                "config_index": stackup.layers.index(layer),
            }
            records.append(record)
            ground_by_layer[layer.name] = ground
        z_origin = f"({z_origin})+{height}"

    record_by_name = {record["layer"].name: record for record in records}
    start_antipad_radius, _ = _antipad_variable_names(start_layer)
    end_antipad_radius, _ = _antipad_variable_names(end_layer)
    _create_route_layer_clearance(
        hfss, record_by_name[start_layer.name]["ground"], "start", -1,
        record_by_name[start_layer.name]["z_origin"], height_variable(start_layer),
        start_antipad_radius,
    )
    _create_route_layer_clearance(
        hfss, record_by_name[end_layer.name]["ground"], "end", 1,
        record_by_name[end_layer.name]["z_origin"], height_variable(end_layer),
        end_antipad_radius,
    )
    _subtract_line_reference_clearances(
        hfss, stackup, start_layer, start_references, records, "start", -1
    )
    _subtract_line_reference_clearances(
        hfss, stackup, end_layer, end_references, records, "end", 1
    )

    shallow_index = min(stackup.layers.index(start_layer), stackup.layers.index(end_layer))
    deep_index = max(stackup.layers.index(start_layer), stackup.layers.index(end_layer))
    for record in records:
        if not shallow_index <= int(record["config_index"]) <= deep_index:
            continue
        radius_name, x_name = _antipad_variable_names(record["layer"])
        _create_slot_antipad(
            hfss, record["ground"], record["layer"].name,
            record["z_origin"], height_variable(record["layer"]),
            radius_name, x_name,
        )

    start_objects = _create_line_objects(
        hfss, "start", -1, record_by_name[start_layer.name]["z_origin"],
        height_variable(start_layer), colors[start_layer.name],
    )
    end_objects = _create_line_objects(
        hfss, "end", 1, record_by_name[end_layer.name]["z_origin"],
        height_variable(end_layer), colors[end_layer.name],
    )

    via_centers = {"P": "BOARD_CENTER_Y-D_VIA/2", "N": "BOARD_CENTER_Y+D_VIA/2"}
    for side, center in via_centers.items():
        for first, second in laser_segments:
            shallow, deep = sorted((first, second), key=stackup.layers.index)
            shallow_origin = _origin_expression_bottom_up(bottom_up, shallow.name)
            deep_origin = _origin_expression_bottom_up(bottom_up, deep.name)
            column_height = f"({shallow_origin})+{height_variable(shallow)}-({deep_origin})"
            name = (
                f"SIG_VIA_{side}_LASER_{_identifier(first.name)}_"
                f"{_identifier(second.name)}_COLUMN"
            )
            column = m.create_cylinder(
                "Z", ["0mm", center, deep_origin], "VIA_COLUMN_RADIUS", column_height,
                name=name, material="copper",
            )
            if not column:
                raise RuntimeError(f"Unable to create laser VIA column {name}.")
        if mechanical_segment is not None:
            first, second = mechanical_segment
            shallow, deep = sorted((first, second), key=stackup.layers.index)
            shallow_origin = _origin_expression_bottom_up(bottom_up, shallow.name)
            deep_origin = _origin_expression_bottom_up(bottom_up, deep.name)
            column_height = f"({shallow_origin})+{height_variable(shallow)}-({deep_origin})"
            name = (
                f"SIG_VIA_{side}_MECHANICAL_{_identifier(first.name)}_"
                f"{_identifier(second.name)}_COLUMN"
            )
            column = m.create_cylinder(
                "Z", ["0mm", center, deep_origin],
                "MECHANICAL_VIA_COLUMN_RADIUS", column_height,
                name=name, material="copper",
            )
            if not column:
                raise RuntimeError(f"Unable to create mechanical VIA column {name}.")

        for layer in via_path:
            technology = pad_technology.get(layer.name)
            if technology is None:
                continue
            if layer is start_layer:
                pad_name = f"START_VIA_{side}_PAD"
            elif layer is end_layer:
                pad_name = f"END_VIA_{side}_PAD"
            else:
                pad_name = (
                    f"SIG_VIA_{side}_{_identifier(layer.name)}_"
                    f"{technology.upper()}_PAD"
                )
            radius = (
                "MECHANICAL_VIA_PAD_RADIUS"
                if technology == "mechanical" else "VIA_PAD_RADIUS"
            )
            pad = m.create_cylinder(
                "Z", ["0mm", center, record_by_name[layer.name]["z_origin"]],
                radius, height_variable(layer), name=pad_name, material="copper",
            )
            if not pad:
                raise RuntimeError(f"Unable to create {technology} VIA pad {pad_name}.")
        # Preserve the vertical column as its own physical object.  Only the
        # coplanar line, fanout, and landing pad on each route layer are united.
        start_path = [
            f"START_TRACE_{side}", f"START_FANOUT_{side}", f"START_VIA_{side}_PAD",
        ]
        end_path = [
            f"END_TRACE_{side}", f"END_FANOUT_{side}", f"END_VIA_{side}_PAD",
        ]
        _unite_coplanar_signal(m, start_path, f"start-side {side} line/fanout/pad")
        _unite_coplanar_signal(m, end_path, f"end-side {side} line/fanout/pad")

    start_ref_z0, start_ref_z1 = _reference_span(
        stackup, start_layer, *start_references, bottom_up
    )
    end_ref_z0, end_ref_z1 = _reference_span(
        stackup, end_layer, *end_references, bottom_up
    )
    hfss["START_LOWER_REF_Z"] = start_ref_z0
    hfss["START_UPPER_REF_Z"] = start_ref_z1
    hfss["END_LOWER_REF_Z"] = end_ref_z0
    hfss["END_UPPER_REF_Z"] = end_ref_z1
    return_point_allowed = lambda point: _single_stage_return_point_allowed(
        point, dimensions, start_layer.name, end_layer.name
    )
    _create_line_return_rows(
        hfss, "start", -1, start_ref_z0, start_ref_z1, dimensions,
        return_point_allowed,
    )
    _create_line_return_rows(
        hfss, "end", 1, end_ref_z0, end_ref_z1, dimensions,
        return_point_allowed,
    )
    transition_z0, transition_z1 = _transition_reference_span(
        stackup, start_layer, end_layer,
        start_references, end_references, bottom_up
    )
    _create_local_return_fence(
        hfss, transition_z0, transition_z1, dimensions, return_point_allowed
    )

    start_port_z0, start_port_z1 = _port_span(
        stackup, start_layer, *start_references, bottom_up
    )
    end_port_z0, end_port_z1 = _port_span(
        stackup, end_layer, *end_references, bottom_up
    )
    def port_references(
        route_layer: Layer,
        references: tuple[Layer | None, Layer | None],
    ) -> list[str]:
        upper, lower = references
        return _port_reference_conductors(
            stackup, route_layer, upper, lower, ground_by_layer
        )
    _create_wave_port(
        hfss, "start", "BOARD_X0", start_port_z0, start_port_z1,
        "START_PORT_WIDTH", port_references(start_layer, start_references),
        1, stackup.differential_impedance, stackup.common_impedance,
    )
    _create_wave_port(
        hfss, "end", "BOARD_X1", end_port_z0, end_port_z1,
        "END_PORT_WIDTH", port_references(end_layer, end_references),
        2, stackup.differential_impedance, stackup.common_impedance,
    )


def build_differential_via_project(
    stackup_config: StackupConfig,
    via_config: DifferentialViaConfig,
    project_path: str | Path,
    keep_desktop_open: bool = True,
    log_callback=None,
    new_desktop: bool = False,
) -> Path:
    """Build and save one differential via-transition project.

    By default PyAEDT reuses an available AEDT session so a machine with one
    Electronics Desktop GUI license does not attempt a second checkout.
    """
    _validate_config(stackup_config, via_config)
    project_path = Path(project_path)
    if project_path.exists():
        raise FileExistsError(f"Output project already exists: {project_path}")
    desktop = None
    try:
        version = stackup_config.aedt_version.strip() or None
        desktop = Desktop(
            version=version,
            non_graphical=False,
            new_desktop=new_desktop,
            close_on_exit=False,
        )
        if keep_desktop_open:
            _OPEN_DESKTOPS.append(desktop)
        try:
            hfss = Hfss(
                project=str(project_path), design=stackup_config.design_name,
                solution_type="Terminal", version=version,
                new_desktop=False, close_on_exit=False,
                aedt_process_id=desktop.aedt_process_id,
            )
        except Exception as error:
            mode = "a new AEDT session" if new_desktop else "the available AEDT session"
            raise RuntimeError(
                f"Unable to create the HFSS design using {mode}. "
                "If the Electronics Desktop GUI license is already occupied, "
                "reuse that AEDT session (new_desktop=False) or close the extra session."
            ) from error
        _build_geometry(hfss, stackup_config, via_config)
        create_hfss_analysis(
            hfss,
            create_open_region=via_config.create_open_region,
            open_region_frequency=via_config.open_region_frequency,
            create_setup=via_config.create_setup,
            create_sweep=via_config.create_sweep,
            sweep_start=via_config.sweep_start,
            sweep_stop=via_config.sweep_stop,
            sweep_points=via_config.sweep_points,
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
            if new_desktop:
                desktop.release_desktop(close_projects=True, close_on_exit=True)
            else:
                # Detach only. Never close projects belonging to a reused
                # interactive AEDT session.
                desktop.release_desktop(close_projects=False, close_on_exit=False)


def build_project() -> Path:
    """Build the default eight-layer L2-to-L4 single-stage transition."""
    stackup = eight_layer_example()
    stackup.design_name = DESIGN_NAME
    stackup.aedt_version = AEDT_VERSION
    project_path = PROJECT_PATH
    suffix = 1
    while project_path.exists():
        project_path = PROJECT_PATH.with_name(
            f"{PROJECT_PATH.stem}_{suffix}{PROJECT_PATH.suffix}"
        )
        suffix += 1
    if project_path != PROJECT_PATH:
        print(f"Default output already exists; using: {project_path}")
    return build_differential_via_project(
        stackup, DifferentialViaConfig(), project_path, KEEP_DESKTOP_OPEN
    )


if __name__ == "__main__":
    build_project()
