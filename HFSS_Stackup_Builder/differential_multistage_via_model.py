"""Build a two-location differential VIA transition for HFSS.

The route is a laser stack, a transfer-layer parallelogram bridge, a
mechanical VIA, and an optional final laser stack.  Every vertical signal
column remains an independent solid; only coplanar signal metal is united.
"""

# Developer: Yetaikunle
# Copyright © 2026 Yetaikunle. All rights reserved.

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import ceil, floor, hypot, pi, sin, cos
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
        _origin_expression_bottom_up,
        _port_reference_conductors,
        _set_object_color,
        copper_layer_colors,
        create_hfss_analysis,
        eight_layer_example,
        height_variable,
        layer_material_groups,
        set_copper_transparency,
    )
    from differential_via_model import (
        DifferentialLineEndConfig,
        _antipad_variable_names,
        _create_line_return_rows,
        _create_wave_port,
        _distance_to_polygon,
        _layer_antipad_values,
        _line_reference_layers,
        _literal_mm,
        _mm,
        _port_span,
        _reference_span,
        _return_disk_intersects_route,
        _return_disk_intersects_slot,
        _transition_reference_span,
        _unite_coplanar_signal,
        _validate_stackup,
    )
except ImportError:  # pragma: no cover
    from .hfss_stackup_builder import (
        Layer,
        StackupConfig,
        _create_materials,
        _identifier,
        _origin_expression_bottom_up,
        _port_reference_conductors,
        _set_object_color,
        copper_layer_colors,
        create_hfss_analysis,
        eight_layer_example,
        height_variable,
        layer_material_groups,
        set_copper_transparency,
    )
    from .differential_via_model import (
        DifferentialLineEndConfig,
        _antipad_variable_names,
        _create_line_return_rows,
        _create_wave_port,
        _distance_to_polygon,
        _layer_antipad_values,
        _line_reference_layers,
        _literal_mm,
        _mm,
        _port_span,
        _reference_span,
        _return_disk_intersects_route,
        _return_disk_intersects_slot,
        _transition_reference_span,
        _unite_coplanar_signal,
        _validate_stackup,
    )


@dataclass
class MultiStageDifferentialViaConfig:
    """Configuration for laser -> bridge -> mechanical -> optional laser."""

    route_layers: list[str] = field(default_factory=lambda: ["L2", "L4", "L7", "L7"])
    start_line: DifferentialLineEndConfig = field(default_factory=lambda: DifferentialLineEndConfig(
        upper_reference_layer_name="L1", lower_reference_layer_name="L3"
    ))
    end_line: DifferentialLineEndConfig = field(default_factory=lambda: DifferentialLineEndConfig(
        upper_reference_layer_name="L6", lower_reference_layer_name="L8"
    ))
    stage1_d_via: str = "0.5mm"
    stage2_d_via: str = "0.8mm"
    bridge_clear_length: str = "0.5mm"
    bridge_width: str = "0.1mm"
    via_column_radius: str = "0.057mm"
    via_pad_radius: str = "0.127mm"
    mechanical_column_radius: str = "3mil"
    mechanical_pad_radius: str = "6mil"
    via_antipad_radius: str = "10mil"
    via_antipad_x: str = "10mil"
    layer_antipads: dict[str, dict[str, str]] = field(default_factory=dict)
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
    def from_dict(cls, data: dict) -> "MultiStageDifferentialViaConfig":
        values: dict[str, object] = {
            name: str(data[name])
            for name in (
                "stage1_d_via", "stage2_d_via", "bridge_clear_length", "bridge_width",
                "via_column_radius", "via_pad_radius", "mechanical_column_radius",
                "mechanical_pad_radius", "via_antipad_radius", "via_antipad_x",
                "return_column_radius", "line_return_pitch", "line_return_edge_offset",
                "local_return_pitch", "local_return_clearance", "side_margin",
                "open_region_frequency", "sweep_start", "sweep_stop",
            )
            if name in data
        }
        if "route_layers" in data:
            values["route_layers"] = [str(item) for item in data["route_layers"]]
        if "start_line" in data:
            values["start_line"] = DifferentialLineEndConfig.from_dict(data["start_line"])
        if "end_line" in data:
            values["end_line"] = DifferentialLineEndConfig.from_dict(data["end_line"])
        if "sweep_points" in data:
            values["sweep_points"] = int(data["sweep_points"])
        for name in ("create_open_region", "create_setup", "create_sweep"):
            if name in data:
                value = data[name]
                values[name] = value if isinstance(value, bool) else str(value).lower() in {
                    "1", "true", "yes", "on",
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
DESIGN_NAME = "MultiStageDifferentialViaTransition"
PROJECT_PATH = Path(__file__).with_name("differential_multistage_via_model.aedt")
KEEP_DESKTOP_OPEN = True
_OPEN_DESKTOPS: list[Desktop] = []


def _require_frequency(value: str, name: str) -> None:
    match = re.fullmatch(
        r"\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(Hz|kHz|MHz|GHz|THz)\s*",
        value,
        re.IGNORECASE,
    )
    if not match or float(match.group(1)) <= 0:
        raise ValueError(f"{name} must be a positive literal frequency.")


def _resolve_layers(
    stackup: StackupConfig, config: MultiStageDifferentialViaConfig
) -> tuple[Layer, Layer, Layer, Layer, list[Layer]]:
    _validate_stackup(stackup)
    if len(config.route_layers) != 4:
        raise ValueError("Two-stage VIA requires exactly four route_layers.")
    copper = [layer for layer in stackup.layers if layer.kind == "copper"]
    resolved: list[Layer] = []
    for name in config.route_layers:
        layer = next((item for item in copper if item.name == name), None)
        if layer is None:
            raise ValueError(f"Route layer {name!r} must be a copper layer.")
        resolved.append(layer)
    indices = [copper.index(layer) for layer in resolved]
    if not (indices[0] < indices[1] < indices[2] <= indices[3]):
        raise ValueError(
            "Layer order must be input < transfer < mechanical end <= final output."
        )
    return resolved[0], resolved[1], resolved[2], resolved[3], copper


def _validate_config(
    stackup: StackupConfig, config: MultiStageDifferentialViaConfig
) -> tuple[Layer, Layer, Layer, Layer, dict[str, float]]:
    start, transfer, mechanical_end, output, copper = _resolve_layers(stackup, config)
    start_references = _line_reference_layers(
        stackup, start, config.start_line, "start"
    )
    end_references = _line_reference_layers(
        stackup, output, config.end_line, "end"
    )
    dimensions: dict[str, float] = {}
    for prefix, line in (("start", config.start_line), ("end", config.end_line)):
        for field_name in ("trace_length", "fanout_length", "w_line", "s_line", "g_line"):
            key = f"{prefix}_{field_name}"
            dimensions[key] = _literal_mm(str(getattr(line, field_name)), key)
    for field_name in (
        "stage1_d_via", "stage2_d_via", "bridge_clear_length", "bridge_width",
        "via_column_radius", "via_pad_radius", "mechanical_column_radius",
        "mechanical_pad_radius", "via_antipad_radius", "via_antipad_x",
        "return_column_radius", "line_return_pitch", "line_return_edge_offset",
        "local_return_pitch", "local_return_clearance", "side_margin",
    ):
        dimensions[field_name] = _literal_mm(str(getattr(config, field_name)), field_name)
    nonnegative = {"line_return_edge_offset", "local_return_clearance"}
    for name, value in dimensions.items():
        if value < 0 or (value == 0 and name not in nonnegative):
            rule = "non-negative" if name in nonnegative else "positive"
            raise ValueError(f"{name} must be {rule}.")
    if dimensions["stage2_d_via"] <= dimensions["stage1_d_via"]:
        raise ValueError("stage2_d_via must be greater than stage1_d_via.")
    if dimensions["via_pad_radius"] <= dimensions["via_column_radius"]:
        raise ValueError("via_pad_radius must be greater than via_column_radius.")
    if dimensions["mechanical_pad_radius"] <= dimensions["mechanical_column_radius"]:
        raise ValueError(
            "mechanical_pad_radius must be greater than mechanical_column_radius."
        )
    if config.create_sweep and not config.create_setup:
        raise ValueError("create_sweep requires create_setup.")
    if config.create_open_region:
        _require_frequency(config.open_region_frequency, "open_region_frequency")
    if config.create_setup:
        _require_frequency(config.sweep_start, "sweep_start")
        _require_frequency(config.sweep_stop, "sweep_stop")
    if config.create_sweep and config.sweep_points < 2:
        raise ValueError("sweep_points must be at least 2.")

    start_index = copper.index(start)
    transfer_index = copper.index(transfer)
    mechanical_index = copper.index(mechanical_end)
    output_index = copper.index(output)
    route = copper[start_index:output_index + 1]
    radius_values: list[float] = []
    x_values: list[float] = []
    for layer in route:
        radius_text, x_text = _layer_antipad_values(config, layer.name)
        radius = _literal_mm(radius_text, f"via_antipad_radius_{layer.name}")
        x_value = _literal_mm(x_text, f"via_antipad_x_{layer.name}")
        if radius <= 0 or x_value <= 0:
            raise ValueError(f"{layer.name} anti-pad radius and X must be positive.")
        active_radius = dimensions["via_column_radius"]
        layer_index = copper.index(layer)
        if start_index <= layer_index <= transfer_index:
            active_radius = max(active_radius, dimensions["via_pad_radius"])
        if layer_index in {transfer_index, mechanical_index}:
            active_radius = max(active_radius, dimensions["mechanical_pad_radius"])
        elif transfer_index < layer_index < mechanical_index:
            active_radius = max(active_radius, dimensions["mechanical_column_radius"])
        if mechanical_index < layer_index <= output_index:
            active_radius = max(active_radius, dimensions["via_pad_radius"])
        if radius <= active_radius:
            raise ValueError(
                f"via_antipad_radius_{layer.name} must exceed active pad/column radius."
            )
        dimensions[f"via_antipad_radius_{layer.name}"] = radius
        dimensions[f"via_antipad_x_{layer.name}"] = x_value
        radius_values.append(radius)
        x_values.append(x_value)
    dimensions["transition_via_antipad_radius"] = max(radius_values)
    dimensions["transition_via_antipad_x"] = max(x_values)
    dimensions["stage2_x"] = (
        dimensions["via_pad_radius"] + dimensions["bridge_clear_length"]
        + dimensions["mechanical_pad_radius"]
    )
    # Validate port/reference availability for both ends.
    bottom_up = list(reversed(stackup.layers))
    _port_span(stackup, start, *start_references, bottom_up)
    _port_span(stackup, output, *end_references, bottom_up)
    return start, transfer, mechanical_end, output, dimensions


def _create_fanout(
    hfss: Hfss,
    name: str,
    x_line: str,
    x_via: str,
    line_center: str,
    via_center: str,
    width_variable: str,
    pad_radius_variable: str,
    z_origin: str,
    height: str,
) -> object:
    points = [
        [x_line, f"({line_center})-{width_variable}/2", z_origin],
        [x_line, f"({line_center})+{width_variable}/2", z_origin],
        [x_via, f"({via_center})+{pad_radius_variable}", z_origin],
        [x_via, f"({via_center})-{pad_radius_variable}", z_origin],
    ]
    sheet = hfss.modeler.create_polyline(
        points, cover_surface=True, close_surface=True, name=name, material="copper"
    )
    if not sheet:
        raise RuntimeError(f"Unable to create {name}.")
    solid = hfss.modeler.sweep_along_vector(sheet, ["0mm", "0mm", height])
    if not solid:
        raise RuntimeError(f"Unable to sweep {name}.")
    return solid


def _create_line_objects(
    hfss: Hfss,
    prefix: str,
    direction: int,
    via_x: str,
    d_variable: str,
    pad_radius_variable: str,
    z_origin: str,
    height: str,
    color: tuple[int, int, int],
) -> None:
    p = prefix.upper()
    line_centers = {
        "P": f"BOARD_CENTER_Y-({p}_W_LINE+{p}_S_LINE)/2",
        "N": f"BOARD_CENTER_Y+({p}_W_LINE+{p}_S_LINE)/2",
    }
    via_centers = {
        "P": f"BOARD_CENTER_Y-{d_variable}/2",
        "N": f"BOARD_CENTER_Y+{d_variable}/2",
    }
    for side in ("P", "N"):
        if direction < 0:
            trace_x = "BOARD_X0"
            x_line = f"-{p}_FANOUT_LENGTH"
        else:
            trace_x = f"({via_x})+{p}_FANOUT_LENGTH"
            x_line = trace_x
        trace = hfss.modeler.create_box(
            [trace_x, f"({line_centers[side]})-{p}_W_LINE/2", z_origin],
            [f"{p}_TRACE_LENGTH", f"{p}_W_LINE", height],
            name=f"{p}_TRACE_{side}", material="copper",
        )
        fanout = _create_fanout(
            hfss, f"{p}_FANOUT_{side}", x_line, via_x,
            line_centers[side], via_centers[side], f"{p}_W_LINE",
            pad_radius_variable, z_origin, height,
        )
        if not trace:
            raise RuntimeError(f"Unable to create {p}_TRACE_{side}.")
        _set_object_color(trace, color)
        _set_object_color(fanout, color)


def _create_route_clearance(
    hfss: Hfss,
    ground: object,
    prefix: str,
    direction: int,
    via_x: str,
    d_variable: str,
    radius_variable: str,
    z_origin: str,
    height: str,
    name_suffix: str = "",
) -> None:
    p = prefix.upper()
    object_prefix = f"{p}{name_suffix}"
    if direction < 0:
        x_line = f"-{p}_FANOUT_LENGTH"
        x_trace = "BOARD_X0"
    else:
        x_line = f"({via_x})+{p}_FANOUT_LENGTH"
        x_trace = x_line
    straight = hfss.modeler.create_box(
        [x_trace, f"BOARD_CENTER_Y-({p}_S_LINE+2*{p}_W_LINE+2*{p}_G_LINE)/2", z_origin],
        [f"{p}_TRACE_LENGTH", f"{p}_S_LINE+2*{p}_W_LINE+2*{p}_G_LINE", height],
        name=f"{object_prefix}_TRACE_CLEARANCE", material="vacuum",
    )
    if not straight or not hfss.modeler.subtract(ground, straight, keep_originals=False):
        raise RuntimeError(f"Unable to create {p} trace clearance.")
    line_half = f"({p}_S_LINE+2*{p}_W_LINE+2*{p}_G_LINE)/2"
    via_half = f"({d_variable}/2+{radius_variable})"
    for suffix, sign in (("", "+"), ("_MIRROR", "-")):
        points = [
            [x_line, "BOARD_CENTER_Y", z_origin],
            [x_line, f"BOARD_CENTER_Y{sign}{line_half}", z_origin],
            [via_x, f"BOARD_CENTER_Y{sign}{via_half}", z_origin],
            [via_x, "BOARD_CENTER_Y", z_origin],
        ]
        sheet = hfss.modeler.create_polyline(
            points, cover_surface=True, close_surface=True,
            name=f"{object_prefix}_FANOUT_CLEARANCE{suffix}", material="vacuum",
        )
        tool = hfss.modeler.sweep_along_vector(sheet, ["0mm", "0mm", height]) if sheet else None
        if not tool or not hfss.modeler.subtract(ground, tool, keep_originals=False):
            raise RuntimeError(f"Unable to subtract {p} fanout clearance{suffix}.")


def _subtract_line_reference_clearances(
    hfss: Hfss,
    stackup: StackupConfig,
    line_layer: Layer,
    references: tuple[Layer | None, Layer | None],
    records: list[dict[str, object]],
    prefix: str,
    direction: int,
    via_x: str,
    d_variable: str,
) -> None:
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
        _create_route_clearance(
            hfss,
            record["ground"],
            prefix,
            direction,
            via_x,
            d_variable,
            radius_name,
            record["z_origin"],
            height_variable(layer),
            name_suffix=f"_SKIPPED_REF_{_identifier(layer.name)}",
        )


def _create_slot_tool(
    hfss: Hfss,
    prefix: str,
    via_x: str,
    d_variable: str,
    z_origin: str,
    height: str,
    radius_variable: str,
    x_variable: str,
) -> object:
    m = hfss.modeler
    circle_p = m.create_cylinder(
        "Z", [via_x, f"BOARD_CENTER_Y-{d_variable}/2", z_origin],
        radius_variable, height, name=prefix, material="vacuum",
    )
    circle_n = m.create_cylinder(
        "Z", [via_x, f"BOARD_CENTER_Y+{d_variable}/2", z_origin],
        radius_variable, height, name=f"{prefix}_N_CIRCLE", material="vacuum",
    )
    negative = m.create_box(
        [f"({via_x})-{x_variable}", f"BOARD_CENTER_Y-{d_variable}/2", z_origin],
        [x_variable, d_variable, height],
        name=f"{prefix}_NECK_NEG_X", material="vacuum",
    )
    positive = m.create_box(
        [via_x, f"BOARD_CENTER_Y-{d_variable}/2", z_origin],
        [x_variable, d_variable, height],
        name=f"{prefix}_NECK_POS_X", material="vacuum",
    )
    if not all((circle_p, circle_n, negative, positive)):
        raise RuntimeError(f"Unable to create slot anti-pad {prefix}.")
    if not m.unite([circle_p.name, circle_n.name, negative.name, positive.name]):
        raise RuntimeError(f"Unable to unite slot anti-pad {prefix}.")
    return circle_p


def _create_bridge_solid(
    hfss: Hfss,
    name: str,
    side: str,
    width: str,
    z_origin: str,
    height: str,
    material: str,
) -> object:
    sign = "-" if side == "P" else "+"
    start_center = f"BOARD_CENTER_Y{sign}STAGE1_D_VIA/2"
    end_center = f"BOARD_CENTER_Y{sign}STAGE2_D_VIA/2"
    points = [
        ["0mm", f"({start_center})-({width})/2", z_origin],
        ["0mm", f"({start_center})+({width})/2", z_origin],
        ["STAGE2_X", f"({end_center})+({width})/2", z_origin],
        ["STAGE2_X", f"({end_center})-({width})/2", z_origin],
    ]
    sheet = hfss.modeler.create_polyline(
        points, cover_surface=True, close_surface=True, name=name, material=material,
    )
    solid = hfss.modeler.sweep_along_vector(sheet, ["0mm", "0mm", height]) if sheet else None
    if not solid:
        raise RuntimeError(f"Unable to create bridge {name}.")
    return solid


def _ellipse_return_points(a: float, b: float, pitch: float) -> list[tuple[float, float]]:
    """Return no-more-than-pitch equal-arc samples around an ellipse."""
    dense_count = 2048
    dense = [
        (a * cos(2 * pi * index / dense_count), b * sin(2 * pi * index / dense_count))
        for index in range(dense_count)
    ]
    lengths = [
        hypot(
            dense[(index + 1) % dense_count][0] - dense[index][0],
            dense[(index + 1) % dense_count][1] - dense[index][1],
        )
        for index in range(dense_count)
    ]
    perimeter = sum(lengths)
    count = max(8, ceil(perimeter / pitch))
    spacing = perimeter / count
    points: list[tuple[float, float]] = []
    segment = 0
    traversed = 0.0
    for point_index in range(count):
        target = point_index * spacing
        while traversed + lengths[segment] < target:
            traversed += lengths[segment]
            segment += 1
        fraction = 0.0 if lengths[segment] == 0 else (target - traversed) / lengths[segment]
        first, second = dense[segment], dense[(segment + 1) % dense_count]
        points.append((
            first[0] + fraction * (second[0] - first[0]),
            first[1] + fraction * (second[1] - first[1]),
        ))
    return points


def _multistage_return_point_allowed(
    point: tuple[float, float], dimensions: dict[str, float],
    start_layer_name: str, transfer_layer_name: str, output_layer_name: str,
) -> bool:
    """Reject a complete return-column disk that touches any two-stage void."""
    return_radius = dimensions["return_column_radius"]
    stage2_x = dimensions["stage2_x"]
    radius = dimensions["transition_via_antipad_radius"]
    x_extent = dimensions["transition_via_antipad_x"]
    if (
        _return_disk_intersects_slot(
            point, 0.0, dimensions["stage1_d_via"],
            radius, x_extent, return_radius,
        )
        or _return_disk_intersects_slot(
            point, stage2_x, dimensions["stage2_d_via"],
            radius, x_extent, return_radius,
        )
        or _return_disk_intersects_route(
            point, dimensions, "start", -1, 0.0, dimensions["stage1_d_via"],
            dimensions[f"via_antipad_radius_{start_layer_name}"],
        )
        or _return_disk_intersects_route(
            point, dimensions, "end", 1, stage2_x, dimensions["stage2_d_via"],
            dimensions[f"via_antipad_radius_{output_layer_name}"],
        )
    ):
        return False

    # The transfer-layer clearance also includes two slanted bridge strips.
    bridge_half_width = dimensions[f"via_antipad_radius_{transfer_layer_name}"]
    for sign in (-1, 1):
        start_y = sign * dimensions["stage1_d_via"] / 2
        end_y = sign * dimensions["stage2_d_via"] / 2
        bridge = [
            (0.0, start_y - bridge_half_width),
            (0.0, start_y + bridge_half_width),
            (stage2_x, end_y + bridge_half_width),
            (stage2_x, end_y - bridge_half_width),
        ]
        if _distance_to_polygon(point, bridge) < return_radius:
            return False
    return True


def _create_ellipse_return_fence(
    hfss: Hfss, z0: str, z1: str, dimensions: dict[str, float],
    point_allowed: Callable[[tuple[float, float]], bool] | None = None,
) -> list[object]:
    expansion = dimensions["local_return_clearance"] + dimensions["return_column_radius"]
    extent = max(
        dimensions["transition_via_antipad_radius"],
        dimensions["transition_via_antipad_x"],
    )
    a = dimensions["stage2_x"] / 2 + extent + expansion
    b = (
        dimensions["stage2_d_via"] / 2
        + dimensions["transition_via_antipad_radius"] + expansion
    )
    center_x = dimensions["stage2_x"] / 2
    points = _ellipse_return_points(a, b, dimensions["local_return_pitch"])
    vias: list[object] = []
    for local_x, local_y in points:
        point = center_x + local_x, local_y
        if point_allowed is not None and not point_allowed(point):
            continue
        index = len(vias) + 1
        via = hfss.modeler.create_cylinder(
            "Z", [_mm(point[0]), f"BOARD_CENTER_Y+({_mm(point[1])})", z0],
            "RETURN_COLUMN_RADIUS", f"({z1})-({z0})",
            name=f"MULTI_RETURN_VIA_{index:03d}_COLUMN", material="copper",
        )
        if not via:
            raise RuntimeError(f"Unable to create ellipse return via {index}.")
        _set_object_color(via, (145, 145, 145))
        vias.append(via)
    return vias


def _column_span(
    stackup: StackupConfig, bottom_up: list[Layer], first: Layer, second: Layer
) -> tuple[str, str]:
    shallow, deep = sorted((first, second), key=stackup.layers.index)
    shallow_origin = _origin_expression_bottom_up(bottom_up, shallow.name)
    deep_origin = _origin_expression_bottom_up(bottom_up, deep.name)
    return deep_origin, f"({shallow_origin})+{height_variable(shallow)}-({deep_origin})"


def _build_geometry(
    hfss: Hfss, stackup: StackupConfig, config: MultiStageDifferentialViaConfig
) -> None:
    start, transfer, mechanical_end, output, dimensions = _validate_config(stackup, config)
    start_references = _line_reference_layers(
        stackup, start, config.start_line, "start"
    )
    end_references = _line_reference_layers(
        stackup, output, config.end_line, "end"
    )
    copper = [layer for layer in stackup.layers if layer.kind == "copper"]
    indices = [copper.index(layer) for layer in (start, transfer, mechanical_end, output)]
    stage1_path = copper[indices[0]:indices[1] + 1]
    mechanical_path = copper[indices[1]:indices[2] + 1]
    final_path = copper[indices[2]:indices[3] + 1]
    bottom_up = list(reversed(stackup.layers))
    mapping = layer_material_groups(stackup)
    _create_materials(hfss, stackup, mapping)
    colors = copper_layer_colors(stackup)
    m = hfss.modeler
    m.model_units = "mm"

    variables = {
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
        "STAGE1_D_VIA": config.stage1_d_via,
        "STAGE2_D_VIA": config.stage2_d_via,
        "BRIDGE_CLEAR_LENGTH": config.bridge_clear_length,
        "BRIDGE_WIDTH": config.bridge_width,
        "VIA_COLUMN_RADIUS": config.via_column_radius,
        "VIA_PAD_RADIUS": config.via_pad_radius,
        "MECHANICAL_VIA_COLUMN_RADIUS": config.mechanical_column_radius,
        "MECHANICAL_VIA_PAD_RADIUS": config.mechanical_pad_radius,
        "VIA_ANTIPAD_RADIUS": config.via_antipad_radius,
        "VIA_ANTIPAD_X": config.via_antipad_x,
        "RETURN_COLUMN_RADIUS": config.return_column_radius,
        "LINE_RETURN_PITCH": config.line_return_pitch,
        "LINE_RETURN_EDGE_OFFSET": config.line_return_edge_offset,
        "LOCAL_RETURN_PITCH": config.local_return_pitch,
        "LOCAL_RETURN_CLEARANCE": config.local_return_clearance,
        "SIDE_MARGIN": config.side_margin,
    }
    for name, value in variables.items():
        hfss[name] = value
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
    for layer in copper:
        radius_name, x_name = _antipad_variable_names(layer)
        radius_value, x_value = _layer_antipad_values(config, layer.name)
        hfss[radius_name] = radius_value
        hfss[x_name] = x_value
    for layer in stackup.layers:
        hfss[height_variable(layer)] = layer.thickness
    hfss["STAGE2_X"] = "VIA_PAD_RADIUS+BRIDGE_CLEAR_LENGTH+MECHANICAL_VIA_PAD_RADIUS"
    ring_y_extent = (
        dimensions["stage2_d_via"] / 2 + dimensions["transition_via_antipad_radius"]
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
    hfss["BOARD_X1"] = "STAGE2_X+END_FANOUT_LENGTH+END_TRACE_LENGTH"
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
            body = m.create_box(
                ["BOARD_X0", "0mm", z_origin], ["BOARD_LENGTH", "BOARD_WIDTH", height],
                name=_identifier(layer.name), material=mapping[layer.name],
            )
            if not body:
                raise RuntimeError(f"Unable to create dielectric {layer.name}.")
            body.display_wireframe = True
        else:
            ground = m.create_box(
                ["BOARD_X0", "0mm", z_origin], ["BOARD_LENGTH", "BOARD_WIDTH", height],
                name=f"GND_{_identifier(layer.name)}", material="copper",
            )
            if not ground:
                raise RuntimeError(f"Unable to create ground {layer.name}.")
            _set_object_color(ground, colors[layer.name])
            records.append({
                "layer": layer, "ground": ground, "z_origin": z_origin,
                "config_index": stackup.layers.index(layer),
            })
            ground_by_layer[layer.name] = ground
        z_origin = f"({z_origin})+{height}"
    record_by_name = {record["layer"].name: record for record in records}

    start_radius, _ = _antipad_variable_names(start)
    output_radius, _ = _antipad_variable_names(output)
    _create_route_clearance(
        hfss, record_by_name[start.name]["ground"], "start", -1, "0mm",
        "STAGE1_D_VIA", start_radius, record_by_name[start.name]["z_origin"],
        height_variable(start),
    )
    _create_route_clearance(
        hfss, record_by_name[output.name]["ground"], "end", 1, "STAGE2_X",
        "STAGE2_D_VIA", output_radius, record_by_name[output.name]["z_origin"],
        height_variable(output),
    )
    _subtract_line_reference_clearances(
        hfss, stackup, start, start_references, records,
        "start", -1, "0mm", "STAGE1_D_VIA",
    )
    _subtract_line_reference_clearances(
        hfss, stackup, output, end_references, records,
        "end", 1, "STAGE2_X", "STAGE2_D_VIA",
    )

    for layer in stage1_path[:-1]:
        record = record_by_name[layer.name]
        radius_name, x_name = _antipad_variable_names(layer)
        tool = _create_slot_tool(
            hfss, f"STAGE1_{_identifier(layer.name)}_SIG_SLOT_ANTIPAD",
            "0mm", "STAGE1_D_VIA", record["z_origin"], height_variable(layer),
            radius_name, x_name,
        )
        if not m.subtract(record["ground"], tool, keep_originals=False):
            raise RuntimeError(f"Unable to subtract stage-1 anti-pad on {layer.name}.")
    for layer in copper[indices[1] + 1:indices[3] + 1]:
        record = record_by_name[layer.name]
        radius_name, x_name = _antipad_variable_names(layer)
        tool = _create_slot_tool(
            hfss, f"STAGE2_{_identifier(layer.name)}_SIG_SLOT_ANTIPAD",
            "STAGE2_X", "STAGE2_D_VIA", record["z_origin"], height_variable(layer),
            radius_name, x_name,
        )
        if not m.subtract(record["ground"], tool, keep_originals=False):
            raise RuntimeError(f"Unable to subtract stage-2 anti-pad on {layer.name}.")

    transfer_record = record_by_name[transfer.name]
    transfer_radius, transfer_x = _antipad_variable_names(transfer)
    stage1_tool = _create_slot_tool(
        hfss, f"STAGE1_{_identifier(transfer.name)}_SIG_SLOT_ANTIPAD",
        "0mm", "STAGE1_D_VIA", transfer_record["z_origin"], height_variable(transfer),
        transfer_radius, transfer_x,
    )
    stage2_tool = _create_slot_tool(
        hfss, f"STAGE2_{_identifier(transfer.name)}_SIG_SLOT_ANTIPAD",
        "STAGE2_X", "STAGE2_D_VIA", transfer_record["z_origin"], height_variable(transfer),
        transfer_radius, transfer_x,
    )
    bridge_clearance_p = _create_bridge_solid(
        hfss, "TRANSFER_BRIDGE_P_CLEARANCE", "P", f"2*{transfer_radius}",
        transfer_record["z_origin"], height_variable(transfer), "vacuum",
    )
    bridge_clearance_n = _create_bridge_solid(
        hfss, "TRANSFER_BRIDGE_N_CLEARANCE", "N", f"2*{transfer_radius}",
        transfer_record["z_origin"], height_variable(transfer), "vacuum",
    )
    if not m.unite([
        stage1_tool.name, stage2_tool.name,
        bridge_clearance_p.name, bridge_clearance_n.name,
    ]):
        raise RuntimeError("Unable to unite transfer-layer signal clearance.")
    if not m.subtract(transfer_record["ground"], stage1_tool, keep_originals=False):
        raise RuntimeError("Unable to subtract transfer-layer signal clearance.")

    output_pad_radius = (
        "MECHANICAL_VIA_PAD_RADIUS" if output is mechanical_end else "VIA_PAD_RADIUS"
    )
    _create_line_objects(
        hfss, "start", -1, "0mm", "STAGE1_D_VIA", "VIA_PAD_RADIUS",
        record_by_name[start.name]["z_origin"], height_variable(start), colors[start.name],
    )
    _create_line_objects(
        hfss, "end", 1, "STAGE2_X", "STAGE2_D_VIA", output_pad_radius,
        record_by_name[output.name]["z_origin"], height_variable(output), colors[output.name],
    )

    bridge_objects: dict[str, object] = {}
    for side in ("P", "N"):
        bridge_objects[side] = _create_bridge_solid(
            hfss, f"TRANSFER_BRIDGE_{side}", side, "BRIDGE_WIDTH",
            transfer_record["z_origin"], height_variable(transfer), "copper",
        )
        _set_object_color(bridge_objects[side], colors[transfer.name])

    via_centers = {
        "P": ("BOARD_CENTER_Y-STAGE1_D_VIA/2", "BOARD_CENTER_Y-STAGE2_D_VIA/2"),
        "N": ("BOARD_CENTER_Y+STAGE1_D_VIA/2", "BOARD_CENTER_Y+STAGE2_D_VIA/2"),
    }
    for side, (stage1_center, stage2_center) in via_centers.items():
        for first, second in zip(stage1_path, stage1_path[1:]):
            column_z, column_height = _column_span(stackup, bottom_up, first, second)
            name = f"STAGE1_VIA_{side}_LASER_{_identifier(first.name)}_{_identifier(second.name)}_COLUMN"
            column = m.create_cylinder(
                "Z", ["0mm", stage1_center, column_z], "VIA_COLUMN_RADIUS", column_height,
                name=name, material="copper",
            )
            if not column:
                raise RuntimeError(f"Unable to create {name}.")
        mech_z, mech_height = _column_span(stackup, bottom_up, transfer, mechanical_end)
        mech_name = (
            f"STAGE2_VIA_{side}_MECHANICAL_{_identifier(transfer.name)}_"
            f"{_identifier(mechanical_end.name)}_COLUMN"
        )
        mechanical_column = m.create_cylinder(
            "Z", ["STAGE2_X", stage2_center, mech_z],
            "MECHANICAL_VIA_COLUMN_RADIUS", mech_height,
            name=mech_name, material="copper",
        )
        if not mechanical_column:
            raise RuntimeError(f"Unable to create {mech_name}.")
        for first, second in zip(final_path, final_path[1:]):
            column_z, column_height = _column_span(stackup, bottom_up, first, second)
            name = f"STAGE2_VIA_{side}_LASER_{_identifier(first.name)}_{_identifier(second.name)}_COLUMN"
            column = m.create_cylinder(
                "Z", ["STAGE2_X", stage2_center, column_z],
                "VIA_COLUMN_RADIUS", column_height, name=name, material="copper",
            )
            if not column:
                raise RuntimeError(f"Unable to create {name}.")

        for layer in stage1_path:
            if layer is start:
                name = f"START_VIA_{side}_PAD"
            elif layer is transfer:
                name = f"STAGE1_TRANSFER_VIA_{side}_PAD"
            else:
                name = f"STAGE1_VIA_{side}_{_identifier(layer.name)}_LASER_PAD"
            pad = m.create_cylinder(
                "Z", ["0mm", stage1_center, record_by_name[layer.name]["z_origin"]],
                "VIA_PAD_RADIUS", height_variable(layer), name=name, material="copper",
            )
            if not pad:
                raise RuntimeError(f"Unable to create {name}.")
        stage2_transfer_name = f"STAGE2_TRANSFER_VIA_{side}_MECHANICAL_PAD"
        stage2_transfer_pad = m.create_cylinder(
            "Z", ["STAGE2_X", stage2_center, transfer_record["z_origin"]],
            "MECHANICAL_VIA_PAD_RADIUS", height_variable(transfer),
            name=stage2_transfer_name, material="copper",
        )
        mechanical_end_name = f"STAGE2_VIA_{side}_MECHANICAL_END_PAD"
        mechanical_end_pad = m.create_cylinder(
            "Z", ["STAGE2_X", stage2_center, record_by_name[mechanical_end.name]["z_origin"]],
            "MECHANICAL_VIA_PAD_RADIUS", height_variable(mechanical_end),
            name=mechanical_end_name, material="copper",
        )
        if not stage2_transfer_pad or not mechanical_end_pad:
            raise RuntimeError(f"Unable to create stage-2 mechanical pads for {side}.")
        output_pad_name = mechanical_end_name
        for layer in final_path[1:]:
            output_pad_name = (
                f"END_VIA_{side}_PAD" if layer is output
                else f"STAGE2_VIA_{side}_{_identifier(layer.name)}_LASER_PAD"
            )
            pad = m.create_cylinder(
                "Z", ["STAGE2_X", stage2_center, record_by_name[layer.name]["z_origin"]],
                "VIA_PAD_RADIUS", height_variable(layer), name=output_pad_name,
                material="copper",
            )
            if not pad:
                raise RuntimeError(f"Unable to create {output_pad_name}.")

        _unite_coplanar_signal(
            m, [f"START_TRACE_{side}", f"START_FANOUT_{side}", f"START_VIA_{side}_PAD"],
            f"multi-stage input {side}",
        )
        _unite_coplanar_signal(
            m,
            [
                f"STAGE1_TRANSFER_VIA_{side}_PAD", f"TRANSFER_BRIDGE_{side}",
                stage2_transfer_name,
            ],
            f"multi-stage transfer {side}",
        )
        _unite_coplanar_signal(
            m, [f"END_TRACE_{side}", f"END_FANOUT_{side}", output_pad_name],
            f"multi-stage output {side}",
        )

    start_ref_z0, start_ref_z1 = _reference_span(
        stackup, start, *start_references, bottom_up
    )
    end_ref_z0, end_ref_z1 = _reference_span(
        stackup, output, *end_references, bottom_up
    )
    hfss["START_LOWER_REF_Z"] = start_ref_z0
    hfss["START_UPPER_REF_Z"] = start_ref_z1
    hfss["END_LOWER_REF_Z"] = end_ref_z0
    hfss["END_UPPER_REF_Z"] = end_ref_z1
    return_point_allowed = lambda point: _multistage_return_point_allowed(
        point, dimensions, start.name, transfer.name, output.name
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
        stackup, start, output, start_references, end_references, bottom_up
    )
    _create_ellipse_return_fence(
        hfss, transition_z0, transition_z1, dimensions, return_point_allowed
    )

    start_port_z0, start_port_z1 = _port_span(
        stackup, start, *start_references, bottom_up
    )
    end_port_z0, end_port_z1 = _port_span(
        stackup, output, *end_references, bottom_up
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
        "START_PORT_WIDTH", port_references(start, start_references),
        1, stackup.differential_impedance, stackup.common_impedance,
    )
    _create_wave_port(
        hfss, "end", "BOARD_X1", end_port_z0, end_port_z1,
        "END_PORT_WIDTH", port_references(output, end_references),
        2, stackup.differential_impedance, stackup.common_impedance,
    )


def build_multistage_differential_via_project(
    stackup_config: StackupConfig,
    via_config: MultiStageDifferentialViaConfig,
    project_path: str | Path,
    keep_desktop_open: bool = True,
    log_callback=None,
) -> Path:
    """Build and save a two-location differential VIA project without solving."""
    _validate_config(stackup_config, via_config)
    project_path = Path(project_path)
    if project_path.exists():
        raise FileExistsError(f"Output project already exists: {project_path}")
    desktop = None
    try:
        version = stackup_config.aedt_version.strip() or None
        desktop = Desktop(
            version=version, non_graphical=False, new_desktop=False, close_on_exit=False,
        )
        if keep_desktop_open:
            _OPEN_DESKTOPS.append(desktop)
        hfss = Hfss(
            project=str(project_path), design=stackup_config.design_name,
            solution_type="Terminal", version=version,
            new_desktop=False, close_on_exit=False,
            aedt_process_id=desktop.aedt_process_id,
        )
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
            desktop.release_desktop(close_projects=False, close_on_exit=False)


def build_project() -> Path:
    stackup = eight_layer_example()
    stackup.design_name = DESIGN_NAME
    stackup.aedt_version = AEDT_VERSION
    project_path = PROJECT_PATH
    suffix = 1
    while project_path.exists():
        project_path = PROJECT_PATH.with_name(f"{PROJECT_PATH.stem}_{suffix}{PROJECT_PATH.suffix}")
        suffix += 1
    return build_multistage_differential_via_project(
        stackup, MultiStageDifferentialViaConfig(), project_path, KEEP_DESKTOP_OPEN
    )


if __name__ == "__main__":
    build_project()
