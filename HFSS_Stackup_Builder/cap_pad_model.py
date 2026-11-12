"""Build a differential AC-coupling capacitor footprint in HFSS.

The model contains PCB metal and dielectric plus either two physical A3D
capacitors or optional ideal Lumped RLC boundaries. Two independent outer-
layer pad pairs are created for the P/N capacitors.

The left and right pad columns fan out through independent laser stacks with
optional cross-layer mechanical spans to configurable route layers. No solve
is started and existing projects are never overwritten.
"""

# Developer: Yetaikunle
# Copyright 2026 Yetaikunle. All rights reserved.

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from math import ceil, hypot
from pathlib import Path
import re

from pyaedt import Desktop, Hfss

try:
    from hfss_stackup_builder import (
        Layer,
        StackupConfig,
        _create_materials,
        _identifier,
        _nearest_copper,
        _resolve_reference_layers,
        _set_object_color,
        copper_layer_colors,
        create_hfss_analysis,
        eight_layer_example,
        height_variable,
        layer_material_groups,
        set_copper_transparency,
    )
    from differential_via_model import DifferentialLineEndConfig, _literal_mm, _mm
except ImportError:  # pragma: no cover
    from .hfss_stackup_builder import (
        Layer,
        StackupConfig,
        _create_materials,
        _identifier,
        _nearest_copper,
        _resolve_reference_layers,
        _set_object_color,
        copper_layer_colors,
        create_hfss_analysis,
        eight_layer_example,
        height_variable,
        layer_material_groups,
        set_copper_transparency,
    )
    from .differential_via_model import DifferentialLineEndConfig, _literal_mm, _mm


@dataclass
class CapViaConfig:
    """One side's laser stack, optionally interrupted by one mechanical span."""

    column_radius: str = "0.057mm"
    pad_radius: str = "0.127mm"
    antipad_radius: str = "0.254mm"
    antipad_x: str = "0.254mm"
    # Retained for older JSON files. CAP solder-mask openings no longer follow
    # VIA anti-pads; breakout traces and their vias are always mask covered.
    follow_solder_mask_antipad: bool = False
    layer_antipads: dict[str, dict[str, str]] = field(default_factory=dict)
    mechanical_enabled: bool = False
    mechanical_start_layer: str = ""
    mechanical_end_layer: str = ""
    mechanical_column_radius: str = "0.075mm"
    mechanical_pad_radius: str = "0.15mm"

    def __post_init__(self) -> None:
        normalized = {}
        for layer, settings in self.layer_antipads.items():
            if isinstance(settings, dict):
                normalized[str(layer)] = {
                    "radius": str(settings.get("radius", self.antipad_radius)),
                    "x": str(settings.get("x", self.antipad_x)),
                }
            else:
                normalized[str(layer)] = {"radius": str(settings), "x": self.antipad_x}
        self.layer_antipads = normalized

    @classmethod
    def from_dict(cls, data: dict) -> "CapViaConfig":
        values = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        values["follow_solder_mask_antipad"] = False
        values["mechanical_enabled"] = str(values.get("mechanical_enabled", False)).lower() in {"true", "1", "yes", "on"}
        if "layer_antipads" in values:
            normalized = {}
            for key, value in values["layer_antipads"].items():
                if isinstance(value, dict):
                    normalized[str(key)] = {
                        "radius": str(value.get("radius", values.get("antipad_radius", "0.254mm"))),
                        "x": str(value.get("x", values.get("antipad_x", "0.254mm"))),
                    }
                else:  # Backward compatibility with the original radius-only CAP JSON.
                    normalized[str(key)] = {
                        "radius": str(value),
                        "x": str(values.get("antipad_x", "0.254mm")),
                    }
            values["layer_antipads"] = normalized
        return cls(**values)


def _default_cap_voids() -> dict[str, dict[str, object]]:
    # X/Y are safe derived placeholders: measured pad-array envelope plus the
    # legacy 100 um ground clearance on each side. They are not BRD measurements.
    return {
        "L1": {"enabled": True, "x": "730um", "y": "776um", "radius": "4mil"},
        "L2": {"enabled": True, "x": "730um", "y": "776um", "radius": "4mil"},
    }


@dataclass
class CapPadConfig:
    """Geometry and analysis settings for one differential capacitor pair."""

    component_side: str = "top"
    route_layers: list[str] = field(default_factory=lambda: ["L3", "L5"])
    input_line: DifferentialLineEndConfig = field(default_factory=lambda: DifferentialLineEndConfig(
        upper_reference_layer_name="L2", lower_reference_layer_name="L4"))
    output_line: DifferentialLineEndConfig = field(default_factory=lambda: DifferentialLineEndConfig(
        upper_reference_layer_name="L4", lower_reference_layer_name="L6"))
    input_via: CapViaConfig = field(default_factory=CapViaConfig)
    output_via: CapViaConfig = field(default_factory=CapViaConfig)
    pad_length: str = "203um"
    pad_width: str = "203um"
    pad_gap: str = "124um"
    pad_center_pitch: str = "327um"
    left_pad_length: str = "203um"
    left_pad_width: str = "203um"
    left_pad_corner_radius: str = "50um"
    right_pad_length: str = "203um"
    right_pad_width: str = "203um"
    right_pad_corner_radius: str = "50um"
    pad_corner_radius: str = "50um"
    pad_clearance: str = "0.10mm"
    pair_pitch: str = "373um"
    input_d_via: str = "373um"
    output_d_via: str = "373um"
    via_inset: str = "0.16mm"
    left_via_x_offset: str = "0mm"
    right_via_x_offset: str = "0mm"
    left_breakout_length: str = "0mm"
    left_breakout_width: str = "0.10mm"
    right_breakout_length: str = "0mm"
    right_breakout_width: str = "0.10mm"
    layer_pad_voids: dict[str, dict[str, object]] = field(default_factory=_default_cap_voids)
    via_column_radius: str = "0.057mm"
    via_pad_radius: str = "0.127mm"
    via_antipad_radius: str = "0.254mm"
    return_vias_enabled: bool = True
    return_column_radius: str = "0.057mm"
    return_via_pitch: str = "0.50mm"
    return_via_clearance: str = "0.25mm"
    side_margin: str = "0.75mm"
    solder_enabled: bool = True
    solder_material: str = "tin"
    solder_height: str = "3mil"
    solder_mask_enabled: bool = True
    solder_mask_dk: str = "3.3"
    solder_mask_df: str = "0.02"
    solder_mask_copper_thickness: str = "15um"
    solder_mask_gap_thickness: str = "25um"
    solder_mask_transition_width: str = "10um"
    solder_mask_opening_expansion: str = "4mil"
    solder_mask_opening_mode: str = "pair_window"
    real_component_enabled: bool = True
    real_component_file: str = ""
    lumped_rlc_enabled: bool = False
    lumped_resistance: str = "0ohm"
    lumped_inductance: str = "0nH"
    lumped_capacitance: str = "0.1uF"
    rlc_source_s2p: str = ""
    rlc_fit_start: str = "10MHz"
    rlc_fit_stop: str = "3GHz"
    comparison_designs_enabled: bool = False
    create_open_region: bool = True
    open_region_frequency: str = "60GHz"
    create_setup: bool = True
    create_sweep: bool = True
    sweep_start: str = "0.01GHz"
    sweep_stop: str = "60GHz"
    sweep_points: int = 401

    @classmethod
    def from_dict(cls, data: dict) -> "CapPadConfig":
        values = {
            name: str(data[name])
            for name in (
                "pad_length", "pad_width", "pad_gap", "pad_corner_radius",
                "pad_center_pitch", "left_pad_length", "left_pad_width", "left_pad_corner_radius",
                "right_pad_length", "right_pad_width", "right_pad_corner_radius",
                "pad_clearance", "pair_pitch", "input_d_via", "output_d_via",
                "via_inset", "via_column_radius",
                "left_via_x_offset", "right_via_x_offset",
                "left_breakout_length", "left_breakout_width",
                "right_breakout_length", "right_breakout_width",
                "via_pad_radius", "via_antipad_radius", "return_column_radius",
                "return_via_pitch", "return_via_clearance", "side_margin",
                "solder_material", "solder_height", "solder_mask_dk", "solder_mask_df",
                "solder_mask_copper_thickness", "solder_mask_gap_thickness",
                "solder_mask_transition_width",
                "solder_mask_opening_expansion", "solder_mask_opening_mode",
                "real_component_file", "lumped_resistance", "lumped_inductance",
                "lumped_capacitance", "rlc_source_s2p", "rlc_fit_start", "rlc_fit_stop",
                "open_region_frequency", "sweep_start", "sweep_stop",
            )
            if name in data
        }
        # Legacy CAP JSON used a same-direction Y translation for each P/N
        # pair.  Its normal value was zero.  If explicit symmetric pitches are
        # absent, match them to the component P/N pitch to preserve that
        # default geometry.
        pair_pitch = str(data.get("pair_pitch", "373um"))
        values.setdefault("input_d_via", pair_pitch)
        values.setdefault("output_d_via", pair_pitch)
        if "component_side" in data:
            values["component_side"] = str(data["component_side"]).strip().lower()
        for name in (
            "return_vias_enabled", "solder_enabled", "solder_mask_enabled",
            "real_component_enabled", "lumped_rlc_enabled", "comparison_designs_enabled",
            "create_open_region", "create_setup", "create_sweep"
        ):
            if name in data:
                value = data[name]
                values[name] = value if isinstance(value, bool) else str(value).lower() in {
                    "1", "true", "yes", "on"
                }
        # Existing JSON files predate surface-process geometry.  Preserve their
        # original output unless at least one new surface-process key is present.
        surface_keys = {
            "solder_enabled", "solder_material", "solder_height",
            "solder_mask_enabled", "solder_mask_dk", "solder_mask_df",
            "solder_mask_copper_thickness", "solder_mask_gap_thickness",
            "solder_mask_transition_width",
            "solder_mask_opening_expansion", "solder_mask_opening_mode",
        }
        if not surface_keys.intersection(data):
            values["solder_enabled"] = False
            values["solder_mask_enabled"] = False
        # CAP JSON written before ideal RLC support represented an open gap.
        if "lumped_rlc_enabled" not in data:
            values["lumped_rlc_enabled"] = False
        # Existing JSON predates packaged physical-component insertion.  Do
        # not silently add a component when reopening one of those files.
        if "real_component_enabled" not in data:
            values["real_component_enabled"] = False
        if "sweep_points" in data:
            values["sweep_points"] = int(data["sweep_points"])
        if "route_layers" in data:
            values["route_layers"] = [str(item) for item in data["route_layers"]]
        if "input_line" in data:
            values["input_line"] = DifferentialLineEndConfig.from_dict(data["input_line"])
        if "output_line" in data:
            values["output_line"] = DifferentialLineEndConfig.from_dict(data["output_line"])
        for key in ("input_via", "output_via"):
            if key in data:
                values[key] = CapViaConfig.from_dict(data[key])
        if "layer_pad_voids" in data and isinstance(data["layer_pad_voids"], dict):
            values["layer_pad_voids"] = {
                str(layer): {
                    "enabled": (settings.get("enabled", True) if isinstance(settings.get("enabled", True), bool)
                                else str(settings.get("enabled", True)).lower() in {"1", "true", "yes", "on"}),
                    "x": str(settings.get("x", "730um")),
                    "y": str(settings.get("y", "776um")),
                    "radius": str(settings.get("radius", "4mil")),
                }
                for layer, settings in data["layer_pad_voids"].items()
                if isinstance(settings, dict)
            }
        return cls(**values)

    def to_dict(self) -> dict:
        return asdict(self)


AEDT_VERSION = ""
DESIGN_NAME = "DifferentialCapPads"
PROJECT_PATH = Path(__file__).with_name("cap_pad_model.aedt")
KEEP_DESKTOP_OPEN = True
_OPEN_DESKTOPS: list[Desktop] = []
_BUNDLED_CAP_COMPONENT = Path(__file__).with_name("components") / "SC04S0J104M_0p1uF.a3dcomp"


def _real_component_path(config: CapPadConfig) -> Path:
    """Resolve a custom component path or the component shipped with the app."""
    raw = config.real_component_file.strip()
    if not raw:
        return _BUNDLED_CAP_COMPONENT.resolve()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parent / path
    return path.resolve()


def _h(layer: Layer) -> str:
    """Return a CAP-namespaced layer-height variable."""
    return f"CAP_{height_variable(layer)}"


def _origin(bottom_up: list[Layer], target_name: str) -> str:
    below: list[str] = []
    for layer in bottom_up:
        if layer.name == target_name:
            return "+".join(below) if below else "0mm"
        below.append(_h(layer))
    raise ValueError(f"Unknown layer: {target_name}")


def _copper_path(stackup: StackupConfig, start: Layer, end: Layer) -> list[Layer]:
    copper = [layer for layer in stackup.layers if layer.kind == "copper"]
    first, last = copper.index(start), copper.index(end)
    if first == last:
        return [copper[first]]
    step = 1 if last > first else -1
    return copper[first:last + step:step]


def _line_reference_clearance_layers(
    stackup: StackupConfig,
    route: Layer,
    line: DifferentialLineEndConfig,
) -> list[Layer]:
    """Return copper layers skipped between one route and its references."""
    upper, lower = _resolve_reference_layers(
        stackup,
        route,
        line.upper_reference_layer_name,
        line.lower_reference_layer_name,
        require_ground_role=False,
    )
    route_index = stackup.layers.index(route)
    upper_index = stackup.layers.index(upper) if upper else route_index
    lower_index = stackup.layers.index(lower) if lower else route_index
    return [
        layer
        for index, layer in enumerate(stackup.layers)
        if layer.kind == "copper"
        and (
            upper_index < index < route_index
            or route_index < index < lower_index
        )
    ]


def _validate(
    stackup: StackupConfig, config: CapPadConfig
) -> tuple[Layer, Layer, Layer, dict[str, float]]:
    if len(config.route_layers) != 2:
        raise ValueError("route_layers must contain input and output copper layers.")
    if config.route_layers[0] == config.route_layers[1]:
        raise ValueError("Input and output route layers must be different.")
    if len({layer.name for layer in stackup.layers}) != len(stackup.layers):
        raise ValueError("Stackup layer names must be unique.")
    copper = [layer for layer in stackup.layers if layer.kind == "copper"]
    if len(copper) < 3:
        raise ValueError("CAP model requires at least three copper layers.")
    if config.component_side not in {"top", "bottom"}:
        raise ValueError("component_side must be 'top' or 'bottom'.")
    component_layer = copper[0] if config.component_side == "top" else copper[-1]
    if (config.component_side == "bottom"
            and config.layer_pad_voids == _default_cap_voids()):
        config.layer_pad_voids = {
            copper[-1].name: {"enabled": True, "x": "730um", "y": "776um", "radius": "4mil"},
            copper[-2].name: {"enabled": True, "x": "730um", "y": "776um", "radius": "4mil"},
        }
    selected: list[Layer] = []
    for name in config.route_layers:
        matches = [layer for layer in copper if layer.name == name]
        if not matches:
            raise ValueError(f"Route layer {name!r} must be a copper layer.")
        if matches[0] is component_layer and config.component_side != "top":
            raise ValueError(
                "Bottom-mounted CAP route layers must differ from the capacitor "
                "mounting layer."
            )
        selected.append(matches[0])
    for prefix, layer, line in (
        ("input", selected[0], config.input_line),
        ("output", selected[1], config.output_line),
    ):
        _resolve_reference_layers(
            stackup, layer, line.upper_reference_layer_name,
            line.lower_reference_layer_name, require_ground_role=False,
            field_prefix=f"CAP {prefix}",
        )

    dimensions: dict[str, float] = {}
    for prefix, line in (("input", config.input_line), ("output", config.output_line)):
        for field_name in ("trace_length", "fanout_length", "w_line", "s_line", "g_line"):
            key = f"{prefix}_{field_name}"
            dimensions[key] = _literal_mm(str(getattr(line, field_name)), key)
    for name in (
        "pad_length", "pad_width", "pad_gap", "pad_corner_radius", "pad_clearance",
        "pair_pitch", "via_inset", "via_column_radius", "via_pad_radius",
        "via_antipad_radius", "return_column_radius", "return_via_pitch",
        "return_via_clearance", "side_margin", "solder_height",
        "left_breakout_length", "left_breakout_width",
        "right_breakout_length", "right_breakout_width",
        "solder_mask_copper_thickness", "solder_mask_gap_thickness",
        "solder_mask_transition_width", "solder_mask_opening_expansion",
    ):
        dimensions[name] = _literal_mm(str(getattr(config, name)), name)
    for side, via, route, line in (
        ("input", config.input_via, selected[0], config.input_line),
        ("output", config.output_via, selected[1], config.output_line),
    ):
        for key in ("column_radius", "pad_radius", "antipad_radius", "antipad_x", "mechanical_column_radius", "mechanical_pad_radius"):
            dimensions[f"{side}_{key}"] = _literal_mm(str(getattr(via, key)), f"{side}_{key}")
        if dimensions[f"{side}_pad_radius"] <= dimensions[f"{side}_column_radius"]:
            raise ValueError(f"{side} pad_radius must exceed column_radius.")
        if dimensions[f"{side}_antipad_radius"] <= dimensions[f"{side}_pad_radius"]:
            raise ValueError(f"{side} antipad_radius must exceed pad_radius.")
        via_path = _copper_path(stackup, component_layer, route)
        clearance_layers = _line_reference_clearance_layers(stackup, route, line)
        configurable_layers = [
            layer for layer in copper
            if layer in via_path or layer in clearance_layers
        ]
        configurable_names = {item.name for item in configurable_layers}
        if any(layer_name not in configurable_names for layer_name in via.layer_antipads):
            raise ValueError(
                f"{side} layer_antipads must refer to copper layers in its VIA path "
                "or skipped-reference clearance span."
            )
        for layer in configurable_layers:
            override = via.layer_antipads.get(layer.name, {})
            radius = _literal_mm(override.get("radius", via.antipad_radius), f"{side} {layer.name} antipad radius")
            x_value = _literal_mm(override.get("x", via.antipad_x), f"{side} {layer.name} antipad +/-X")
            dimensions[f"{side}_antipad_{layer.name}"] = radius
            dimensions[f"{side}_antipad_x_{layer.name}"] = x_value
            required = 0.0
            if layer in via_path:
                required = dimensions[f"{side}_pad_radius"]
                if via.mechanical_enabled and layer.name in (via.mechanical_start_layer, via.mechanical_end_layer):
                    required = max(required, dimensions[f"{side}_mechanical_pad_radius"])
            if radius <= required:
                raise ValueError(f"{side} {layer.name} antipad radius must exceed the via pad radius.")
            if x_value < 0:
                raise ValueError(f"{side} {layer.name} antipad +/-X must be non-negative.")
        if via.mechanical_enabled:
            path = _copper_path(stackup, component_layer, selected[0] if side == "input" else selected[1])
            if len(path) < 2:
                raise ValueError(
                    f"{side} mechanical via requires the route layer to differ "
                    "from the capacitor mounting layer."
                )
            if (via.mechanical_start_layer not in [item.name for item in path]
                    or via.mechanical_end_layer not in [item.name for item in path]
                    or path.index(next(item for item in path if item.name == via.mechanical_start_layer))
                    >= path.index(next(item for item in path if item.name == via.mechanical_end_layer))):
                raise ValueError(f"{side} mechanical span must lie between L1 and its route layer in order.")
            if dimensions[f"{side}_mechanical_pad_radius"] <= dimensions[f"{side}_mechanical_column_radius"]:
                raise ValueError(f"{side} mechanical_pad_radius must exceed mechanical_column_radius.")
    dimensions["input_route_antipad_radius"] = dimensions[f"input_antipad_{selected[0].name}"]
    dimensions["output_route_antipad_radius"] = dimensions[f"output_antipad_{selected[1].name}"]
    if not config.solder_material.strip():
        raise ValueError("solder_material must not be blank.")
    if config.solder_mask_opening_mode != "pair_window":
        raise ValueError("solder_mask_opening_mode must be 'pair_window'.")
    try:
        solder_mask_dk = float(config.solder_mask_dk)
        solder_mask_df = float(config.solder_mask_df)
    except (TypeError, ValueError) as error:
        raise ValueError("solder_mask_dk and solder_mask_df must be numeric.") from error
    if solder_mask_dk <= 0:
        raise ValueError("solder_mask_dk must be positive.")
    if solder_mask_df < 0:
        raise ValueError("solder_mask_df must be non-negative.")
    dimensions["solder_mask_dk"] = solder_mask_dk
    dimensions["solder_mask_df"] = solder_mask_df
    # Keep these values available even in the physical design.  Paired builds
    # promote the same expressions from both designs to shared project
    # variables, so the A3D design must not overwrite a fitted RLC with defaults.
    dimensions["lumped_resistance_ohm"] = _literal_resistance_ohm(
        config.lumped_resistance, "lumped_resistance"
    )
    dimensions["lumped_inductance_h"] = _literal_inductance_h(
        config.lumped_inductance, "lumped_inductance"
    )
    dimensions["lumped_capacitance_f"] = _literal_capacitance_f(
        config.lumped_capacitance, "lumped_capacitance"
    )
    if config.real_component_enabled and config.lumped_rlc_enabled:
        raise ValueError(
            "Physical A3D capacitor and ideal Lumped RLC cannot be enabled together."
        )
    if config.real_component_enabled or config.comparison_designs_enabled:
        component_file = _real_component_path(config)
        if component_file.suffix.lower() != ".a3dcomp":
            raise ValueError("real_component_file must be an .a3dcomp file.")
        if not component_file.is_file():
            raise FileNotFoundError(f"A3D capacitor component not found: {component_file}")
    component_copper_thickness = _literal_mm(
        component_layer.thickness, f"{component_layer.name} copper thickness"
    )
    dimensions["solder_mask_transition_height"] = (
        component_copper_thickness
        + dimensions["solder_mask_copper_thickness"]
        - dimensions["solder_mask_gap_thickness"]
    )
    if dimensions["solder_mask_transition_height"] <= 0:
        raise ValueError(
            "Mounting copper thickness plus copper-cover mask thickness must exceed "
            "the gap-fill mask thickness."
        )
    copper_names = {layer.name for layer in copper}
    if (component_layer.name not in config.layer_pad_voids
            or not config.layer_pad_voids[component_layer.name].get("enabled", False)):
        raise ValueError(
            f"CAP pad void must be enabled on mounting copper {component_layer.name} "
            "to keep the four pads isolated."
        )
    for layer_name, settings in config.layer_pad_voids.items():
        if layer_name not in copper_names:
            raise ValueError(f"CAP pad void layer {layer_name!r} must be a copper layer.")
        if not settings.get("enabled", False):
            continue
        for key in ("x", "y", "radius"):
            dimensions[f"pad_void_{layer_name}_{key}"] = _literal_mm(
                str(settings.get(key, "")), f"CAP {layer_name} pad void {key}"
            )
        if 2 * dimensions[f"pad_void_{layer_name}_radius"] >= min(
            dimensions[f"pad_void_{layer_name}_x"], dimensions[f"pad_void_{layer_name}_y"]
        ):
            raise ValueError(f"CAP {layer_name} pad void radius must be less than half X and Y.")
    component_void_radius = dimensions[f"pad_void_{component_layer.name}_radius"]
    component_void_x = dimensions[f"pad_void_{component_layer.name}_x"]
    component_void_y = dimensions[f"pad_void_{component_layer.name}_y"]
    edge_width = dimensions["solder_mask_transition_width"]
    if edge_width >= component_void_radius or 2 * edge_width >= min(component_void_x, component_void_y):
        raise ValueError(
            "solder_mask_transition_width must fit inside the mounting-layer group-void radius."
        )
    for side, legacy in (("left", config.pad_length), ("right", config.pad_length)):
        for field_name, fallback in (("length", legacy), ("width", config.pad_width), ("corner_radius", config.pad_corner_radius)):
            raw = getattr(config, f"{side}_pad_{field_name}") or fallback
            dimensions[f"{side}_pad_{field_name}"] = _literal_mm(str(raw), f"{side}_pad_{field_name}")
        if 2 * dimensions[f"{side}_pad_corner_radius"] >= min(dimensions[f"{side}_pad_length"], dimensions[f"{side}_pad_width"]):
            raise ValueError(f"{side}_pad_corner_radius (pad_corner_radius) must be less than half its length and width.")
    pitch = config.pad_center_pitch or _mm(dimensions["pad_length"] + dimensions["pad_gap"])
    dimensions["pad_center_pitch"] = _literal_mm(pitch, "pad_center_pitch")
    if dimensions["pad_center_pitch"] <= (dimensions["left_pad_length"] + dimensions["right_pad_length"]) / 2:
        raise ValueError("Pad center pitch must exceed the two pad half-lengths (positive copper gap).")
    if dimensions["pair_pitch"] <= max(
        dimensions["left_pad_width"], dimensions["right_pad_width"]
    ):
        raise ValueError("pair_pitch must exceed the pad widths.")
    dimensions["input_d_via"] = _literal_mm(config.input_d_via, "input_d_via")
    dimensions["output_d_via"] = _literal_mm(config.output_d_via, "output_d_via")
    for side, via in (("left", config.input_via), ("right", config.output_via)):
        prefix = "input" if side == "left" else "output"
        direction = -1 if side == "left" else 1
        offset = getattr(config, f"{side}_via_x_offset") or _mm(
            (1 if side == "left" else -1) * (dimensions["via_inset"] - dimensions[f"{side}_pad_length"] / 2)
        )
        dimensions[f"{side}_via_x_offset"] = _literal_mm(offset, f"{side}_via_x_offset")
        column_radius = dimensions[f"{prefix}_column_radius"]
        landing_radius = dimensions[f"{prefix}_pad_radius"]
        side_via = config.input_via if side == "left" else config.output_via
        if side_via.mechanical_enabled and side_via.mechanical_start_layer == component_layer.name:
            column_radius = dimensions[f"{prefix}_mechanical_column_radius"]
            landing_radius = dimensions[f"{prefix}_mechanical_pad_radius"]
        dimensions[f"{side}_outer_landing_radius"] = landing_radius
        breakout_length = dimensions[f"{side}_breakout_length"]
        pad_center_x = direction * dimensions["pad_center_pitch"] / 2
        if breakout_length > 0:
            if dimensions[f"{side}_breakout_width"] > dimensions[f"{side}_pad_width"]:
                raise ValueError(f"{side}_breakout_width must not exceed the component pad width.")
            dimensions[f"{side}_via_x"] = direction * (
                dimensions["pad_center_pitch"] / 2
                + dimensions[f"{side}_pad_length"] / 2
                + breakout_length
            )
        else:
            dimensions[f"{side}_via_x"] = pad_center_x + dimensions[f"{side}_via_x_offset"]
            # Without a breakout trace, the rounded capacitor pad remains the
            # mounting-layer landing pad and must contain the copper column.
            if abs(dimensions[f"{side}_via_x_offset"]) + column_radius > dimensions[f"{side}_pad_length"] / 2:
                raise ValueError(
                    f"{side} via_inset / via x offset must keep its copper column "
                    "inside the component pad length when breakout length is zero."
                )
        d_key = "input_d_via" if side == "left" else "output_d_via"
        symmetric_y_offset = (
            dimensions[d_key] - dimensions["pair_pitch"]
        ) / 2
        if breakout_length <= 0 and abs(symmetric_y_offset) + column_radius > dimensions[f"{side}_pad_width"] / 2:
            raise ValueError(
                f"{d_key} must keep both symmetric copper columns inside "
                f"the {side} component pads when breakout length is zero."
            )
        if breakout_length > 0 and dimensions[d_key] <= 2 * landing_radius:
            raise ValueError(f"{d_key} must keep the two {side} breakout landing pads separate.")

    expansion = dimensions["solder_mask_opening_expansion"]
    opening_x0 = -dimensions["pad_center_pitch"] / 2 - dimensions["left_pad_length"] / 2 - expansion
    opening_x1 = dimensions["pad_center_pitch"] / 2 + dimensions["right_pad_length"] / 2 + expansion
    window_width = max(dimensions["left_pad_width"], dimensions["right_pad_width"]) + 2 * expansion
    dimensions["solder_mask_window_x0"] = opening_x0
    dimensions["solder_mask_window_length"] = opening_x1 - opening_x0
    dimensions["solder_mask_window_width"] = window_width
    dimensions["solder_mask_window_radius"] = max(
        dimensions["left_pad_corner_radius"], dimensions["right_pad_corner_radius"]
    ) + expansion
    if 2 * dimensions["solder_mask_window_radius"] >= min(
        dimensions["solder_mask_window_length"], dimensions["solder_mask_window_width"]
    ):
        raise ValueError("The solder-mask expansion leaves an invalid pair-window corner radius.")
    # The ideal boundary spans pad-centre to pad-centre.  Its two terminal
    # edges therefore sit inside the left/right metal (or Tin) instead of
    # merely touching the rounded pads at their inner copper edges.
    dimensions["rlc_sheet_length"] = dimensions["pad_center_pitch"]
    dimensions["rlc_sheet_width"] = min(
        dimensions["left_pad_width"], dimensions["right_pad_width"]
    )
    nonnegative = {
        "pad_clearance", "return_via_clearance", "solder_mask_df",
        "solder_mask_opening_expansion", "lumped_resistance_ohm",
        "lumped_inductance_h", "left_breakout_length", "right_breakout_length",
    }
    for name, value in dimensions.items():
        if name.endswith(("_via_x_offset", "_window_x0", "_via_x")):
            continue
        if value < 0 or (value == 0 and name not in nonnegative):
            rule = "non-negative" if name in nonnegative else "positive"
            raise ValueError(f"{name} must be {rule}.")
    if dimensions["pad_corner_radius"] * 2 >= min(
        dimensions["pad_length"], dimensions["pad_width"]
    ):
        raise ValueError("pad_corner_radius must be less than half the smaller pad dimension.")
    if dimensions["via_pad_radius"] <= dimensions["via_column_radius"]:
        raise ValueError("via_pad_radius must exceed via_column_radius.")
    if dimensions["via_antipad_radius"] <= dimensions["via_pad_radius"]:
        raise ValueError("via_antipad_radius must exceed via_pad_radius.")
    return component_layer, selected[0], selected[1], dimensions


def _literal_capacitance_f(value: str, field_name: str) -> float:
    """Parse a positive literal capacitance and return farads."""
    match = re.fullmatch(
        r"\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(f|mf|uf|nf|pf)\s*",
        str(value), re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"{field_name} must use F, mF, uF, nF, or pF.")
    factors = {"f": 1.0, "mf": 1e-3, "uf": 1e-6, "nf": 1e-9, "pf": 1e-12}
    result = float(match.group(1)) * factors[match.group(2).lower()]
    if result <= 0:
        raise ValueError(f"{field_name} must be positive.")
    return result


def _literal_resistance_ohm(value: str, field_name: str) -> float:
    """Parse a non-negative literal resistance and return ohms."""
    match = re.fullmatch(
        r"\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(ohm|mohm|kohm)\s*",
        str(value), re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"{field_name} must use ohm, mohm, or kohm.")
    factors = {"ohm": 1.0, "mohm": 1e-3, "kohm": 1e3}
    result = float(match.group(1)) * factors[match.group(2).lower()]
    if result < 0:
        raise ValueError(f"{field_name} must be non-negative.")
    return result


def _literal_inductance_h(value: str, field_name: str) -> float:
    """Parse a non-negative literal inductance and return henries."""
    match = re.fullmatch(
        r"\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*(h|mh|uh|nh|ph)\s*",
        str(value), re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"{field_name} must use H, mH, uH, nH, or pH.")
    factors = {"h": 1.0, "mh": 1e-3, "uh": 1e-6, "nh": 1e-9, "ph": 1e-12}
    result = float(match.group(1)) * factors[match.group(2).lower()]
    if result < 0:
        raise ValueError(f"{field_name} must be non-negative.")
    return result


def _create_rounded_prism(
    hfss: Hfss,
    name: str,
    x0: str,
    y0: str,
    z0: str,
    length: str,
    width: str,
    radius: str,
    height: str,
    material: str,
    color: tuple[int, int, int] | None = None,
) -> object:
    """Create one rounded-rectangle sheet and sweep it into a solid.

    The outline is a single closed polyline made from four lines and four
    three-point circular arcs.  Do not rebuild this shape from boxes and
    cylinders: their coincident/tangent faces leave sliver faces after AEDT
    boolean operations, which is especially visible on narrow mask rings.
    """
    m = hfss.modeler
    q = "0.7071067811865476"
    x_left = f"({x0})"
    x_left_tangent = f"({x0})+({radius})"
    x_right_tangent = f"({x0})+({length})-({radius})"
    x_right = f"({x0})+({length})"
    y_bottom = f"({y0})"
    y_bottom_tangent = f"({y0})+({radius})"
    y_top_tangent = f"({y0})+({width})-({radius})"
    y_top = f"({y0})+({width})"
    qr = f"{q}*({radius})"
    points = [
        [x_left_tangent, y_bottom, z0],
        [x_right_tangent, y_bottom, z0],
        [f"({x_right_tangent})+({qr})", f"({y_bottom_tangent})-({qr})", z0],
        [x_right, y_bottom_tangent, z0],
        [x_right, y_top_tangent, z0],
        [f"({x_right_tangent})+({qr})", f"({y_top_tangent})+({qr})", z0],
        [x_right_tangent, y_top, z0],
        [x_left_tangent, y_top, z0],
        [f"({x_left_tangent})-({qr})", f"({y_top_tangent})+({qr})", z0],
        [x_left, y_top_tangent, z0],
        [x_left, y_bottom_tangent, z0],
        [f"({x_left_tangent})-({qr})", f"({y_bottom_tangent})-({qr})", z0],
        [x_left_tangent, y_bottom, z0],
    ]
    segments = ["Line", "Arc", "Line", "Arc", "Line", "Arc", "Line", "Arc"]
    main = m.create_polyline(
        points, segment_type=segments, cover_surface=True, close_surface=True,
        name=name, material=material,
    )
    if not main:
        raise RuntimeError(f"Unable to create continuous rounded outline for {name}.")
    swept = m.sweep_along_vector(main, ["0mm", "0mm", height])
    if not swept:
        raise RuntimeError(f"Unable to sweep rounded outline for {name}.")
    if color is not None:
        _set_object_color(main, color)
    return main


def _create_rounded_pad(
    hfss: Hfss,
    name: str,
    x0: str,
    y0: str,
    z0: str,
    pad_height: str,
    color: tuple[int, int, int],
    column: str = "LEFT",
) -> object:
    length, width, radius = (
        f"CAP_{column}_PAD_{part}" for part in ("LENGTH", "WIDTH", "CORNER_RADIUS")
    )
    return _create_rounded_prism(
        hfss, name, x0, y0, z0, length, width, radius, pad_height,
        "copper", color,
    )


def _create_solder_mask_material(hfss: Hfss, config: CapPadConfig) -> str:
    """Create the CAP-local finite-thickness solder-mask dielectric."""
    name = "CAP_SolderMask_DK3p3_DF0p02"
    material = hfss.materials.add_material(name)
    if not material:
        material = hfss.materials[name]
    material.permittivity = float(config.solder_mask_dk)
    material.dielectric_loss_tangent = float(config.solder_mask_df)
    if not material.update():
        raise RuntimeError("Unable to update CAP solder-mask material.")
    return name


def _require_solder_material(hfss: Hfss, material_name: str) -> None:
    """Require AEDT's finite-conductivity solder material without a PEC fallback."""
    exists_material = getattr(hfss.materials, "exists_material", None)
    if exists_material is not None and not exists_material(material_name):
        raise ValueError(f"AEDT material {material_name!r} is not available for CAP solder.")


def _create_cap_solder(
    hfss: Hfss, config: CapPadConfig, component_z: str
) -> None:
    if not config.solder_enabled:
        return
    _require_solder_material(hfss, config.solder_material)
    solder_z = (
        component_z if config.component_side == "top"
        else "-CAP_SOLDER_HEIGHT"
    )
    for side, y in (("P", "CAP_P_Y"), ("N", "CAP_N_Y")):
        for column in ("LEFT", "RIGHT"):
            _create_rounded_prism(
                hfss, f"CAP_{side}_{column}_TIN", f"CAP_{column}_PAD_X0",
                f"({y})-CAP_{column}_PAD_WIDTH/2", solder_z,
                f"CAP_{column}_PAD_LENGTH", f"CAP_{column}_PAD_WIDTH",
                f"CAP_{column}_PAD_CORNER_RADIUS", "CAP_SOLDER_HEIGHT",
                config.solder_material, (175, 175, 190),
            )


def _create_cap_lumped_rlc(
    hfss: Hfss,
    config: CapPadConfig,
    component_z: str,
    resistance_ohm: float | None,
    inductance_h: float | None,
    capacitance_f: float | None,
) -> None:
    """Bridge each P/N pad pair with a centre-to-centre series RLC sheet."""
    if not config.lumped_rlc_enabled:
        return
    if resistance_ohm is None or inductance_h is None or capacitance_f is None:
        raise RuntimeError("Validated lumped RLC values are unavailable.")
    if config.solder_enabled:
        sheet_z = (
            f"({component_z})+CAP_SOLDER_HEIGHT"
            if config.component_side == "top"
            else f"({component_z})-CAP_SOLDER_HEIGHT"
        )
    else:
        # Without a solder solid there is no Tin outer surface; keep the ideal
        # connection on the exposed copper-pad surface.
        sheet_z = component_z
    for side, y in (("P", "CAP_P_Y"), ("N", "CAP_N_Y")):
        sheet = hfss.modeler.create_rectangle(
            "XY",
            [
                "CAP_LEFT_PAD_CENTER_X",
                f"({y})-CAP_RLC_SHEET_WIDTH/2",
                sheet_z,
            ],
            ["CAP_RLC_SHEET_LENGTH", "CAP_RLC_SHEET_WIDTH"],
            name=f"CAP_{side}_RLC_SHEET", material="vacuum",
        )
        if not sheet:
            raise RuntimeError(f"Unable to create CAP {side} Lumped RLC sheet.")
        _set_object_color(sheet, (40, 210, 220))
        # AssignLumpedRLC in AEDT 2025 R2 treats variable expressions in a
        # CurrentLine as zero-length even though the sheet itself evaluates
        # correctly.  Read the evaluated sheet bounds and use an explicit
        # centre line; R/L/C remain project/design-variable expressions.
        bounds = sheet.bounding_box
        units = hfss.modeler.model_units
        current_y = (bounds[1] + bounds[4]) / 2
        current_line = {
            "Start": [
                f"{bounds[0]:.12g}{units}", f"{current_y:.12g}{units}",
                f"{bounds[2]:.12g}{units}",
            ],
            "End": [
                f"{bounds[3]:.12g}{units}", f"{current_y:.12g}{units}",
                f"{bounds[2]:.12g}{units}",
            ],
        }
        # PyAEDT 1.4's ``assign_lumped_rlc_to_sheet`` appends ``F`` to a
        # numeric value.  AEDT 2025 R2 serializes that as a lowercase ``f``
        # (for example ``1e-08f``) and reports an unexpected/missing unit type.
        # Build the same boundary directly with the unambiguous ``farad`` unit.
        boundary = hfss._create_boundary(
            f"CAP_{side}_LUMPED_RLC",
            {
                "Objects": [sheet.name],
                "CurrentLine": current_line,
                "RLC Type": "Serial",
                "UseResist": resistance_ohm > 0,
                "Resistance": "CAP_RLC_RESISTANCE",
                "UseInduct": inductance_h > 0,
                "Inductance": "CAP_RLC_INDUCTANCE",
                "UseCap": True,
                "Capacitance": "CAP_RLC_CAPACITANCE",
            },
            "Lumped RLC",
        )
        if not boundary:
            raise RuntimeError(f"Unable to assign CAP {side} Lumped RLC boundary.")


def _insert_real_capacitors(hfss: Hfss, config: CapPadConfig) -> None:
    """Insert the same physical 0.1 uF component on the P and N pad pairs."""
    if not config.real_component_enabled:
        return
    component_file = _real_component_path(config)
    coordinate_suffix = "ASSEMBLY_CS" if config.solder_enabled else "COMPONENT_CS"
    for side in ("P", "N"):
        component = hfss.modeler.insert_3d_component(
            input_file=str(component_file),
            coordinate_system=f"CAP_{side}_{coordinate_suffix}",
            name=f"CAP_{side}_SC04S0J104M_0P1UF",
        )
        if not component:
            raise RuntimeError(f"Unable to insert the physical CAP {side} A3D component.")


def _create_cap_solder_mask(
    hfss: Hfss,
    config: CapPadConfig,
    component_layer: Layer,
    component_record: dict[str, object],
    dimensions: dict[str, float],
) -> None:
    """Create one continuous conformal mask across copper and recessed gaps."""
    if not config.solder_mask_enabled:
        return
    material = _create_solder_mask_material(hfss, config)
    m = hfss.modeler
    layer_suffix = _identifier(component_layer.name).upper()
    void_x = f"CAP_PAD_VOID_{layer_suffix}_X"
    void_y = f"CAP_PAD_VOID_{layer_suffix}_Y"
    void_radius = f"CAP_PAD_VOID_{layer_suffix}_RADIUS"
    if config.component_side == "top":
        gap_z = str(component_record["z_origin"])
        cover_z = "CAP_BOARD_THICKNESS"
        transition_z = (
            f"({component_record['z_origin']})+CAP_SOLDERMASK_GAP_THICKNESS"
            "-CAP_SOLDERMASK_BOOLEAN_OVERLAP"
        )
        window_z = gap_z
    else:
        gap_z = (
            f"({component_record['z_origin']})+{_h(component_layer)}"
            "-CAP_SOLDERMASK_GAP_THICKNESS"
        )
        cover_z = "-CAP_SOLDERMASK_COPPER_THICKNESS"
        transition_z = cover_z
        window_z = cover_z

    gap_mask = _create_rounded_prism(
        hfss, "CAP_SOLDERMASK_GAP_FILL", f"-{void_x}/2",
        f"CAP_BOARD_CENTER_Y-{void_y}/2", gap_z,
        void_x, void_y, void_radius, "CAP_SOLDERMASK_GAP_THICKNESS",
        material, (30, 125, 45),
    )
    cover_mask = m.create_box(
        ["CAP_BOARD_X0", "0mm", cover_z],
        ["CAP_BOARD_LENGTH", "CAP_BOARD_WIDTH", "CAP_SOLDERMASK_COPPER_THICKNESS"],
        name="CAP_SOLDERMASK_COPPER_COVER", material=material,
    )
    if not cover_mask:
        raise RuntimeError("Unable to create CAP copper-cover solder mask.")
    _set_object_color(cover_mask, (30, 125, 45))

    # The cover occupies only the surface-copper region outside the existing
    # mounting-layer group void.  The recessed mask fills that void separately.
    cover_void = _create_rounded_prism(
        hfss, "CAP_SOLDERMASK_COVER_GROUP_VOID", f"-{void_x}/2",
        f"CAP_BOARD_CENTER_Y-{void_y}/2", cover_z,
        void_x, void_y, void_radius, "CAP_SOLDERMASK_COPPER_THICKNESS",
        "vacuum",
    )
    if not m.subtract(cover_mask, cover_void, keep_originals=False):
        raise RuntimeError("Unable to remove the CAP group void from the solder-mask cover.")

    # Bridge the vertical copper step with a narrow ring inside the group void.
    # Its bottom/top faces coincide with the recessed fill and copper cover, so
    # the three pieces can be united into one watertight dielectric body.
    transition_mask = _create_rounded_prism(
        hfss, "CAP_SOLDERMASK_EDGE_TRANSITION",
        f"(-{void_x}/2)-CAP_SOLDERMASK_BOOLEAN_OVERLAP",
        f"CAP_BOARD_CENTER_Y-{void_y}/2-CAP_SOLDERMASK_BOOLEAN_OVERLAP",
        transition_z,
        f"{void_x}+2*CAP_SOLDERMASK_BOOLEAN_OVERLAP",
        f"{void_y}+2*CAP_SOLDERMASK_BOOLEAN_OVERLAP",
        f"{void_radius}+CAP_SOLDERMASK_BOOLEAN_OVERLAP",
        "CAP_SOLDERMASK_TRANSITION_SWEEP_HEIGHT",
        material, (30, 125, 45),
    )
    transition_inner = _create_rounded_prism(
        hfss, "CAP_SOLDERMASK_EDGE_TRANSITION_INNER",
        f"(-{void_x}/2)+CAP_SOLDERMASK_TRANSITION_WIDTH",
        f"CAP_BOARD_CENTER_Y-{void_y}/2+CAP_SOLDERMASK_TRANSITION_WIDTH",
        transition_z,
        f"{void_x}-2*CAP_SOLDERMASK_TRANSITION_WIDTH",
        f"{void_y}-2*CAP_SOLDERMASK_TRANSITION_WIDTH",
        f"{void_radius}-CAP_SOLDERMASK_TRANSITION_WIDTH",
        "CAP_SOLDERMASK_TRANSITION_HEIGHT", "vacuum",
    )
    # Breakout traces and their external vias are intentionally tented. Remove
    # the recessed group-void mask where breakout copper exists, then add mask
    # at the normal copper-cover height. The final CAP pair window below cuts
    # only the capacitor-pad area (including its configured 4 mil expansion).
    for prefix, column, x_pad_edge, x_via, via, breakout_length in (
        (
            "INPUT", "LEFT", "CAP_LEFT_PAD_X0", "CAP_LEFT_VIA_X",
            config.input_via, dimensions["left_breakout_length"],
        ),
        (
            "OUTPUT", "RIGHT", "CAP_RIGHT_PAD_X0+CAP_RIGHT_PAD_LENGTH",
            "CAP_RIGHT_VIA_X", config.output_via,
            dimensions["right_breakout_length"],
        ),
    ):
        if breakout_length <= 0:
            continue
        landing_radius = f"CAP_{prefix}_VIA_PAD_RADIUS"
        if via.mechanical_enabled and via.mechanical_start_layer == component_layer.name:
            landing_radius = f"CAP_{prefix}_MECHANICAL_PAD_RADIUS"
        for side, pad_center, via_center in (
            ("P", "CAP_P_Y", f"CAP_{prefix}_P_VIA_Y"),
            ("N", "CAP_N_Y", f"CAP_{prefix}_N_VIA_Y"),
        ):
            gap_cut = _create_fanout(
                hfss, f"CAP_{prefix}_{side}_BREAKOUT_MASK_GAP_CUT",
                x_pad_edge, x_via, pad_center, via_center,
                f"CAP_{column}_BREAKOUT_WIDTH", landing_radius,
                gap_z, "CAP_SOLDERMASK_GAP_THICKNESS", None,
                material="vacuum",
            )
            gap_landing_cut = m.create_cylinder(
                "Z", [x_via, via_center, gap_z], landing_radius,
                "CAP_SOLDERMASK_GAP_THICKNESS",
                name=f"CAP_{prefix}_{side}_VIA_MASK_GAP_CUT",
                material="vacuum",
            )
            if not gap_landing_cut:
                raise RuntimeError(f"Unable to create {prefix} {side} mask gap cut.")
            if not m.unite([gap_cut.name, gap_landing_cut.name]):
                raise RuntimeError(f"Unable to unite {prefix} {side} mask gap cut.")
            if not m.subtract(gap_mask, gap_cut, keep_originals=False):
                raise RuntimeError(f"Unable to clear recessed mask from {prefix} {side} breakout copper.")

            trace_cover = _create_fanout(
                hfss, f"CAP_{prefix}_{side}_BREAKOUT_MASK_COVER",
                x_pad_edge, x_via, pad_center, via_center,
                f"CAP_{column}_BREAKOUT_WIDTH", landing_radius,
                cover_z, "CAP_SOLDERMASK_COPPER_THICKNESS", (30, 125, 45),
                material=material,
            )
            via_cover = m.create_cylinder(
                "Z", [x_via, via_center, cover_z], landing_radius,
                "CAP_SOLDERMASK_COPPER_THICKNESS",
                name=f"CAP_{prefix}_{side}_VIA_MASK_COVER",
                material=material,
            )
            if not via_cover:
                raise RuntimeError(f"Unable to create {prefix} {side} via mask cover.")
            _set_object_color(via_cover, (30, 125, 45))
            if not m.unite([cover_mask.name, trace_cover.name, via_cover.name]):
                raise RuntimeError(f"Unable to cover {prefix} {side} breakout and via with mask.")

    if not m.subtract(transition_mask, transition_inner, keep_originals=False):
        raise RuntimeError("Unable to create the CAP solder-mask edge transition ring.")
    mask_parts = [cover_mask.name, gap_mask.name, transition_mask.name]
    if not m.unite(mask_parts):
        raise RuntimeError("Unable to unite the continuous CAP solder mask.")

    # Each differential lane uses one common opening spanning both capacitor
    # terminals.  This deliberately removes the unmanufacturable central dam.
    for side, y in (("P", "CAP_P_Y"), ("N", "CAP_N_Y")):
        window = _create_rounded_prism(
            hfss, f"CAP_{side}_SOLDERMASK_PAIR_WINDOW",
            "CAP_SOLDERMASK_WINDOW_X0",
            f"({y})-CAP_SOLDERMASK_WINDOW_WIDTH/2", window_z,
            "CAP_SOLDERMASK_WINDOW_LENGTH", "CAP_SOLDERMASK_WINDOW_WIDTH",
            "CAP_SOLDERMASK_WINDOW_RADIUS",
            f"({_h(component_layer)})+CAP_SOLDERMASK_COPPER_THICKNESS",
            "vacuum",
        )
        if not m.subtract(cover_mask, window, keep_originals=False):
            raise RuntimeError(f"Unable to subtract the CAP {side} solder-mask pair window.")


def _subtract_rounded_cap_void(
    hfss: Hfss, ground: object, layer: Layer, z0: str, height: str
) -> None:
    """Cut one group-centred rounded rectangle from a selected copper layer."""
    suffix = _identifier(layer.name).upper()
    x_size = f"CAP_PAD_VOID_{suffix}_X"
    y_size = f"CAP_PAD_VOID_{suffix}_Y"
    radius = f"CAP_PAD_VOID_{suffix}_RADIUS"
    x0 = f"-{x_size}/2"
    y0 = f"CAP_BOARD_CENTER_Y-{y_size}/2"
    name = f"CAP_{suffix}_PAD_GROUP_VOID"
    void = _create_rounded_prism(
        hfss, name, x0, y0, z0, x_size, y_size, radius, height, "vacuum",
    )
    if not hfss.modeler.subtract(ground, void, keep_originals=False):
        raise RuntimeError(f"Unable to subtract CAP pad-group void on {layer.name}.")


def _subtract_cap_slot_antipad(
    hfss: Hfss, ground: object, prefix: str, layer: Layer,
    x_center: str, z0: str, height: str,
) -> None:
    """Cut one connected P/N slot using this side's per-layer R and +/-X."""
    suffix = _identifier(layer.name).upper()
    name = f"CAP_{prefix}_{suffix}_SIG_SLOT_ANTIPAD"
    slot = _create_cap_slot_prism(
        hfss, name, prefix, suffix, x_center, z0, height, "vacuum",
    )
    if not hfss.modeler.subtract(ground, slot, keep_originals=False):
        raise RuntimeError(f"Unable to subtract {prefix} slot anti-pad on {layer.name}.")


def _create_cap_slot_prism(
    hfss: Hfss,
    name: str,
    prefix: str,
    layer_suffix: str,
    x_center: str,
    z0: str,
    height: str,
    material: str,
    radial_adjust: str = "0mm",
) -> object:
    """Create the exact two-circle-plus-neck VIA slot used by copper and mask."""
    radius = f"CAP_{prefix}_VIA_ANTIPAD_RADIUS_{layer_suffix}+({radial_adjust})"
    x_extent = f"CAP_{prefix}_VIA_ANTIPAD_X_{layer_suffix}+({radial_adjust})"
    m = hfss.modeler
    circle_p = m.create_cylinder(
        "Z", [x_center, f"CAP_{prefix}_P_VIA_Y", z0], radius, height,
        name=name, material=material,
    )
    circle_n = m.create_cylinder(
        "Z", [x_center, f"CAP_{prefix}_N_VIA_Y", z0], radius, height,
        name=f"{name}_N_CIRCLE", material=material,
    )
    neck = m.create_box(
        [f"({x_center})-({x_extent})", f"CAP_{prefix}_P_VIA_Y", z0],
        [f"2*({x_extent})", f"CAP_{prefix}_N_VIA_Y-CAP_{prefix}_P_VIA_Y", height],
        name=f"{name}_NECK", material=material,
    )
    if not circle_p or not circle_n or not neck:
        raise RuntimeError(f"Unable to create {name}.")
    if not m.unite([circle_p.name, circle_n.name, neck.name]):
        raise RuntimeError(f"Unable to unite {name}.")
    return circle_p


def _create_fanout(
    hfss: Hfss,
    name: str,
    x_line: str,
    x_via: str,
    line_center: str,
    via_center: str,
    width_variable: str,
    via_radius_variable: str,
    z0: str,
    height: str,
    color: tuple[int, int, int] | None,
    material: str = "copper",
) -> object:
    points = [
        [x_line, f"({line_center})-({width_variable})/2", z0],
        [x_line, f"({line_center})+({width_variable})/2", z0],
        [x_via, f"({via_center})+({via_radius_variable})", z0],
        [x_via, f"({via_center})-({via_radius_variable})", z0],
    ]
    sheet = hfss.modeler.create_polyline(
        points, cover_surface=True, close_surface=True, name=name, material=material
    )
    if not sheet:
        raise RuntimeError(f"Unable to create {name}.")
    solid = hfss.modeler.sweep_along_vector(sheet, ["0mm", "0mm", height])
    if not solid:
        raise RuntimeError(f"Unable to sweep {name}.")
    if color is not None:
        _set_object_color(solid, color)
    return solid


def _subtract_pad_breakout_clearance(
    hfss: Hfss,
    ground: object,
    prefix: str,
    column: str,
    x_pad_edge: str,
    x_via: str,
    z0: str,
    height: str,
    layer_suffix: str,
) -> None:
    """Clear mounting-layer copper around one side's two pad breakouts."""
    p = prefix.upper()
    c = column.upper()
    pad_centers = {"P": "CAP_P_Y", "N": "CAP_N_Y"}
    via_centers = {"P": f"CAP_{p}_P_VIA_Y", "N": f"CAP_{p}_N_VIA_Y"}
    for side in ("P", "N"):
        tool = _create_fanout(
            hfss,
            f"CAP_{p}_PAD_BREAKOUT_{side}_CLEARANCE",
            x_pad_edge,
            x_via,
            pad_centers[side],
            via_centers[side],
            f"CAP_{c}_BREAKOUT_WIDTH+2*CAP_PAD_CLEARANCE",
            f"CAP_{p}_VIA_ANTIPAD_RADIUS_{layer_suffix}",
            z0,
            height,
            None,
            material="vacuum",
        )
        if not hfss.modeler.subtract(ground, tool, keep_originals=False):
            raise RuntimeError(f"Unable to create {p} pad-breakout clearance {side}.")


def _create_pad_breakout(
    hfss: Hfss,
    pad: object,
    prefix: str,
    column: str,
    side: str,
    x_pad_edge: str,
    x_via: str,
    pad_center: str,
    via_center: str,
    z0: str,
    height: str,
    landing_radius: str,
    color: tuple[int, int, int],
) -> None:
    """Join one capacitor pad to an external signal via with a short trace."""
    p = prefix.upper()
    c = column.upper()
    breakout = _create_fanout(
        hfss,
        f"CAP_{p}_PAD_BREAKOUT_{side}",
        x_pad_edge,
        x_via,
        pad_center,
        via_center,
        f"CAP_{c}_BREAKOUT_WIDTH",
        landing_radius,
        z0,
        height,
        color,
    )
    landing = hfss.modeler.create_cylinder(
        "Z", [x_via, via_center, z0], landing_radius, height,
        name=f"CAP_{p}_VIA_{side}_OUTER_LANDING_PAD", material="copper",
    )
    if not landing:
        raise RuntimeError(f"Unable to create {p} outer landing pad {side}.")
    _set_object_color(landing, color)
    if not hfss.modeler.unite([pad.name, breakout.name, landing.name]):
        raise RuntimeError(f"Unable to unite {p} pad breakout {side}.")


def _subtract_route_clearance(
    hfss: Hfss,
    ground: object,
    prefix: str,
    direction: int,
    x_via: str,
    z0: str,
    height: str,
    antipad_radius: str | None = None,
    name_suffix: str = "",
) -> None:
    p = prefix.upper()
    object_prefix = f"CAP_{p}{name_suffix}"
    antipad_radius = antipad_radius or f"CAP_{p}_VIA_ANTIPAD_RADIUS"
    if direction < 0:
        trace_x = "CAP_BOARD_X0"
        x_line = f"({x_via})-CAP_{p}_FANOUT_LENGTH"
    else:
        trace_x = f"({x_via})+CAP_{p}_FANOUT_LENGTH"
        x_line = trace_x
    straight = hfss.modeler.create_box(
        [trace_x, f"CAP_BOARD_CENTER_Y-(CAP_{p}_S_LINE+2*CAP_{p}_W_LINE+2*CAP_{p}_G_LINE)/2", z0],
        [f"CAP_{p}_TRACE_LENGTH", f"CAP_{p}_S_LINE+2*CAP_{p}_W_LINE+2*CAP_{p}_G_LINE", height],
        name=f"{object_prefix}_TRACE_CLEARANCE", material="vacuum",
    )
    if not straight or not hfss.modeler.subtract(ground, straight, keep_originals=False):
        raise RuntimeError(f"Unable to create {p} trace clearance.")
    points = [
        [x_line, f"CAP_BOARD_CENTER_Y-(CAP_{p}_S_LINE+2*CAP_{p}_W_LINE+2*CAP_{p}_G_LINE)/2", z0],
        [x_line, f"CAP_BOARD_CENTER_Y+(CAP_{p}_S_LINE+2*CAP_{p}_W_LINE+2*CAP_{p}_G_LINE)/2", z0],
        [x_via, f"CAP_{p}_N_VIA_Y+{antipad_radius}", z0],
        [x_via, f"CAP_{p}_P_VIA_Y-{antipad_radius}", z0],
    ]
    sheet = hfss.modeler.create_polyline(
        points, cover_surface=True, close_surface=True,
        name=f"{object_prefix}_FANOUT_CLEARANCE", material="vacuum",
    )
    tool = sheet and hfss.modeler.sweep_along_vector(sheet, ["0mm", "0mm", height])
    if not tool or not hfss.modeler.subtract(ground, tool, keep_originals=False):
        raise RuntimeError(f"Unable to create {p} fanout clearance.")


def _subtract_line_reference_clearances(
    hfss: Hfss,
    stackup: StackupConfig,
    records: dict[str, dict[str, object]],
    route: Layer,
    line: DifferentialLineEndConfig,
    prefix: str,
    direction: int,
    x_via: str,
) -> None:
    """Open trace/fanout corridors on copper skipped by a CAP reference."""
    p = prefix.upper()
    for layer in _line_reference_clearance_layers(stackup, route, line):
        record = records[layer.name]
        suffix = _identifier(layer.name).upper()
        _subtract_route_clearance(
            hfss,
            record["ground"],
            prefix,
            direction,
            x_via,
            record["z_origin"],
            _h(layer),
            f"CAP_{p}_VIA_ANTIPAD_RADIUS_{suffix}",
            name_suffix=f"_SKIPPED_REF_{suffix}",
        )


def _line_geometry(
    hfss: Hfss,
    prefix: str,
    direction: int,
    x_via: str,
    z0: str,
    height: str,
    color: tuple[int, int, int],
    landing_radius: str | None = None,
) -> None:
    m = hfss.modeler
    p = prefix.upper()
    landing_radius = landing_radius or f"CAP_{p}_VIA_PAD_RADIUS"
    line_centers = {
        "P": f"CAP_BOARD_CENTER_Y-(CAP_{p}_W_LINE+CAP_{p}_S_LINE)/2",
        "N": f"CAP_BOARD_CENTER_Y+(CAP_{p}_W_LINE+CAP_{p}_S_LINE)/2",
    }
    via_centers = {"P": f"CAP_{p}_P_VIA_Y", "N": f"CAP_{p}_N_VIA_Y"}
    for side in ("P", "N"):
        if direction < 0:
            trace_x = "CAP_BOARD_X0"
            x_line = f"({x_via})-CAP_{p}_FANOUT_LENGTH"
        else:
            trace_x = f"({x_via})+CAP_{p}_FANOUT_LENGTH"
            x_line = trace_x
        trace = m.create_box(
            [trace_x, f"({line_centers[side]})-CAP_{p}_W_LINE/2", z0],
            [f"CAP_{p}_TRACE_LENGTH", f"CAP_{p}_W_LINE", height],
            name=f"CAP_{p}_TRACE_{side}", material="copper",
        )
        if not trace:
            raise RuntimeError(f"Unable to create {p} trace {side}.")
        _set_object_color(trace, color)
        fanout = _create_fanout(
            hfss, f"CAP_{p}_FANOUT_{side}", x_line, x_via,
            line_centers[side], via_centers[side], f"CAP_{p}_W_LINE",
            landing_radius, z0, height, color,
        )
        landing = m.create_cylinder(
            "Z", [x_via, via_centers[side], z0], landing_radius, height,
            name=f"CAP_{p}_VIA_{side}_LANDING_PAD", material="copper",
        )
        if not landing:
            raise RuntimeError(f"Unable to create {p} landing pad {side}.")
        if not m.unite([trace.name, fanout.name, landing.name]):
            raise RuntimeError(f"Unable to unite {p} route {side}.")


def _via_stack(
    hfss: Hfss,
    stackup: StackupConfig,
    bottom_up: list[Layer],
    records: dict[str, dict[str, object]],
    top: Layer,
    route: Layer,
    prefix: str,
    x: str,
    via_config: CapViaConfig,
) -> None:
    m = hfss.modeler
    path = _copper_path(stackup, top, route)
    if len(path) < 2:
        return
    mechanical_start = path.index(next(item for item in path if item.name == via_config.mechanical_start_layer)) if via_config.mechanical_enabled else -1
    mechanical_end = path.index(next(item for item in path if item.name == via_config.mechanical_end_layer)) if via_config.mechanical_enabled else -1
    segments = [(path[index], path[index + 1], False) for index in range(mechanical_start)] if via_config.mechanical_enabled else []
    if via_config.mechanical_enabled:
        segments.append((path[mechanical_start], path[mechanical_end], True))
        segments += [(path[index], path[index + 1], False) for index in range(mechanical_end, len(path) - 1)]
    else:
        segments = [(first, second, False) for first, second in zip(path, path[1:])]
    intermediate = {layer.name for layer in path[1:-1]}
    if via_config.mechanical_enabled:
        intermediate -= {item.name for item in path[mechanical_start + 1:mechanical_end]}
    for side, y in (("P", f"CAP_{prefix}_P_VIA_Y"), ("N", f"CAP_{prefix}_N_VIA_Y")):
        for first, second, mechanical in segments:
            shallow, deep = sorted((first, second), key=stackup.layers.index)
            shallow_origin = _origin(bottom_up, shallow.name)
            deep_origin = _origin(bottom_up, deep.name)
            height = f"({shallow_origin})+{_h(shallow)}-({deep_origin})"
            name = f"CAP_{prefix}_VIA_{side}_{_identifier(first.name)}_{_identifier(second.name)}_COLUMN"
            column = m.create_cylinder(
                "Z", [x, y, deep_origin],
                f"CAP_{prefix}_MECHANICAL_COLUMN_RADIUS" if mechanical else f"CAP_{prefix}_VIA_COLUMN_RADIUS",
                height,
                name=name, material="copper",
            )
            if not column:
                raise RuntimeError(f"Unable to create {name}.")
        for layer in path[1:-1]:
            if layer.name not in intermediate:
                continue
            mech_pad = via_config.mechanical_enabled and layer.name in {
                via_config.mechanical_start_layer, via_config.mechanical_end_layer,
            }
            pad = m.create_cylinder(
                "Z", [x, y, records[layer.name]["z_origin"]],
                f"CAP_{prefix}_MECHANICAL_PAD_RADIUS" if mech_pad else f"CAP_{prefix}_VIA_PAD_RADIUS",
                _h(layer),
                name=f"CAP_{prefix}_VIA_{side}_{_identifier(layer.name)}_PAD", material="copper",
            )
            if not pad:
                raise RuntimeError(f"Unable to create intermediate pad on {layer.name}.")


def _sample_edge(start: float, stop: float, pitch: float) -> list[float]:
    count = max(1, ceil(abs(stop - start) / pitch))
    return [start + (stop - start) * index / count for index in range(count + 1)]


def _return_fence_points(dimensions: dict[str, float]) -> list[tuple[float, float]]:
    x_half = dimensions["pad_center_pitch"] / 2 + max(dimensions["left_pad_length"], dimensions["right_pad_length"]) / 2 + dimensions["return_via_clearance"]
    y_half = dimensions["pair_pitch"] / 2 + max(dimensions["left_pad_width"], dimensions["right_pad_width"]) / 2 + dimensions["return_via_clearance"]
    pitch = dimensions["return_via_pitch"]
    points: list[tuple[float, float]] = []
    for x in _sample_edge(-x_half, x_half, pitch):
        points.extend([(x, -y_half), (x, y_half)])
    vertical = _sample_edge(-y_half, y_half, pitch)[1:-1]
    for y in vertical:
        points.extend([(-x_half, y), (x_half, y)])
    return points


def _line_return_points(dimensions: dict[str, float]) -> list[tuple[float, float]]:
    """Return two ground-via rows alongside each outer trace and fanout."""
    pitch = dimensions["return_via_pitch"]
    via_radius = dimensions["return_column_radius"]
    clearance = dimensions["return_via_clearance"]
    left_via_x = dimensions["left_via_x"]
    right_via_x = dimensions["right_via_x"]
    board_x0 = left_via_x - dimensions["input_fanout_length"] - dimensions["input_trace_length"]
    board_x1 = right_via_x + dimensions["output_fanout_length"] + dimensions["output_trace_length"]
    edge_inset = via_radius + clearance
    points: list[tuple[float, float]] = []
    for prefix, x0, x1 in (
        ("input", board_x0 + edge_inset, left_via_x),
        ("output", right_via_x, board_x1 - edge_inset),
    ):
        if x1 <= x0:
            continue
        outer_edge = dimensions[f"{prefix}_s_line"] / 2 + dimensions[f"{prefix}_w_line"]
        y_offset = outer_edge + clearance + via_radius
        for x in _sample_edge(x0, x1, pitch):
            points.extend([(x, -y_offset), (x, y_offset)])
    return points


def _return_point_has_board_edge_margin(
    point: tuple[float, float], dimensions: dict[str, float]
) -> bool:
    """Keep a return-VIA edge plus clearance inside every copper plane."""
    left_via_x = dimensions["left_via_x"]
    right_via_x = dimensions["right_via_x"]
    board_x0 = (
        left_via_x
        - dimensions["input_fanout_length"]
        - dimensions["input_trace_length"]
    )
    board_x1 = (
        right_via_x
        + dimensions["output_fanout_length"]
        + dimensions["output_trace_length"]
    )
    board_y_half = (
        dimensions["pair_pitch"]
        + max(dimensions["left_pad_width"], dimensions["right_pad_width"])
        + 2 * dimensions["side_margin"]
    ) / 2
    inset = dimensions["return_column_radius"] + dimensions["return_via_clearance"]
    x, y = point
    return (
        board_x0 + inset <= x <= board_x1 - inset
        and -board_y_half + inset <= y <= board_y_half - inset
    )


def _distance_to_rectangle(
    point: tuple[float, float], x0: float, x1: float, y0: float, y1: float
) -> float:
    dx = max(x0 - point[0], 0.0, point[0] - x1)
    dy = max(y0 - point[1], 0.0, point[1] - y1)
    return hypot(dx, dy)


def _distance_to_segment(
    point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length2 = dx * dx + dy * dy
    if not length2:
        return hypot(point[0] - start[0], point[1] - start[1])
    t = max(0.0, min(1.0, ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length2))
    return hypot(point[0] - (start[0] + t * dx), point[1] - (start[1] + t * dy))


def _distance_to_polygon(point: tuple[float, float], vertices: list[tuple[float, float]]) -> float:
    inside = False
    previous = vertices[-1]
    for current in vertices:
        if ((current[1] > point[1]) != (previous[1] > point[1])
                and point[0] < (previous[0] - current[0]) * (point[1] - current[1])
                / (previous[1] - current[1]) + current[0]):
            inside = not inside
        previous = current
    if inside:
        return 0.0
    return min(
        _distance_to_segment(point, vertices[index - 1], vertices[index])
        for index in range(len(vertices))
    )


def _return_point_intersects_void(
    point: tuple[float, float], dimensions: dict[str, float], config: CapPadConfig
) -> bool:
    """True when a return-via disk overlaps any pad, slot, or route void."""
    via_radius = dimensions["return_column_radius"]

    # Layer-specific rounded rectangles centred on the complete four-pad group.
    for layer, settings in config.layer_pad_voids.items():
        if not settings.get("enabled", False):
            continue
        half_x = dimensions[f"pad_void_{layer}_x"] / 2
        half_y = dimensions[f"pad_void_{layer}_y"] / 2
        corner = dimensions[f"pad_void_{layer}_radius"]
        qx = abs(point[0]) - (half_x - corner)
        qy = abs(point[1]) - (half_y - corner)
        rounded_rect_sdf = hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - corner
        if rounded_rect_sdf < via_radius:
            return True

    pad_pitch = dimensions["pad_center_pitch"]
    for prefix, x_center, d_via in (
        ("input", dimensions["left_via_x"], dimensions["input_d_via"]),
        ("output", dimensions["right_via_x"], dimensions["output_d_via"]),
    ):
        p_y = -d_via / 2
        n_y = d_via / 2
        # A through return via must remain outside every layer's independent slot.
        radius_prefix = f"{prefix}_antipad_"
        for key, slot_radius in dimensions.items():
            if not key.startswith(radius_prefix) or key.startswith(f"{prefix}_antipad_x_"):
                continue
            layer = key[len(radius_prefix):]
            x_key = f"{prefix}_antipad_x_{layer}"
            if x_key not in dimensions:
                continue
            x_extent = dimensions[x_key]
            if (hypot(point[0] - x_center, point[1] - p_y) < slot_radius + via_radius
                    or hypot(point[0] - x_center, point[1] - n_y) < slot_radius + via_radius
                    or _distance_to_rectangle(
                        point, x_center - x_extent, x_center + x_extent,
                        min(p_y, n_y), max(p_y, n_y),
                    ) < via_radius):
                return True

        # When the signal hole is pulled outside the component pad, also keep
        # return vias away from the short mounting-layer breakout corridor.
        side = "left" if prefix == "input" else "right"
        if dimensions[f"{side}_breakout_length"] > 0:
            direction = -1 if side == "left" else 1
            pad_edge_x = direction * (
                pad_pitch / 2 + dimensions[f"{side}_pad_length"] / 2
            )
            pad_half_width = dimensions[f"{side}_breakout_width"] / 2 + dimensions["pad_clearance"]
            slot_radius = max(
                value for key, value in dimensions.items()
                if key.startswith(f"{prefix}_antipad_")
                and not key.startswith(f"{prefix}_antipad_x")
            )
            for pad_y, via_y in (
                (-dimensions["pair_pitch"] / 2, p_y),
                (dimensions["pair_pitch"] / 2, n_y),
            ):
                breakout_polygon = [
                    (pad_edge_x, pad_y - pad_half_width),
                    (pad_edge_x, pad_y + pad_half_width),
                    (x_center, via_y + slot_radius),
                    (x_center, via_y - slot_radius),
                ]
                if _distance_to_polygon(point, breakout_polygon) < via_radius:
                    return True

        # Straight W/S/G clearance plus the trapezoidal fanout clearance on
        # this side's route layer.
        trace_half = (dimensions[f"{prefix}_s_line"] + 2 * dimensions[f"{prefix}_w_line"]
                      + 2 * dimensions[f"{prefix}_g_line"]) / 2
        fanout = dimensions[f"{prefix}_fanout_length"]
        trace = dimensions[f"{prefix}_trace_length"]
        direction = -1 if prefix == "input" else 1
        line_x = x_center + direction * fanout
        remote_x = line_x + direction * trace
        if _distance_to_rectangle(
            point, min(line_x, remote_x), max(line_x, remote_x), -trace_half, trace_half
        ) < via_radius:
            return True
        slot_radius = dimensions[f"{prefix}_route_antipad_radius"]
        fanout_polygon = [
            (line_x, -trace_half), (line_x, trace_half),
            (x_center, n_y + slot_radius), (x_center, p_y - slot_radius),
        ]
        if _distance_to_polygon(point, fanout_polygon) < via_radius:
            return True
    return False


def _all_return_points(
    dimensions: dict[str, float], config: CapPadConfig | None = None
) -> list[tuple[float, float]]:
    """Combine fences, reject all void overlaps, and suppress near-duplicates."""
    minimum = max(2 * dimensions["return_column_radius"], 1e-9)
    accepted: list[tuple[float, float]] = []
    for point in _return_fence_points(dimensions) + _line_return_points(dimensions):
        if not _return_point_has_board_edge_margin(point, dimensions):
            continue
        if config is not None and _return_point_intersects_void(point, dimensions, config):
            continue
        if all((point[0] - other[0]) ** 2 + (point[1] - other[1]) ** 2 >= minimum ** 2
               for other in accepted):
            accepted.append(point)
    return accepted


def _reference_span(
    stackup: StackupConfig, layer: Layer, bottom_up: list[Layer],
    line: DifferentialLineEndConfig,
) -> tuple[str, str]:
    upper, lower = _resolve_reference_layers(
        stackup, layer, line.upper_reference_layer_name,
        line.lower_reference_layer_name, require_ground_role=False,
    )
    origin = _origin(bottom_up, layer.name)
    return (_origin(bottom_up, lower.name) if lower else origin,
            f"({_origin(bottom_up, upper.name if upper else layer.name)})+{_h(upper or layer)}")


def _port_span(
    stackup: StackupConfig, layer: Layer, bottom_up: list[Layer],
    line: DifferentialLineEndConfig,
) -> tuple[str, str]:
    # CAP defaults use internal route layers.  Keep support for the bottom
    # external copper, whose port must extend beyond its adjacent dielectric.
    copper = [item for item in stackup.layers if item.kind == "copper"]
    index = copper.index(layer)
    if index != len(copper) - 1:
        return _reference_span(stackup, layer, bottom_up, line)
    upper, _ = _resolve_reference_layers(
        stackup, layer, line.upper_reference_layer_name,
        line.lower_reference_layer_name, require_ground_role=False,
    )
    dielectric = next(
        item for item in reversed(stackup.layers[:stackup.layers.index(layer)])
        if item.kind in {"pp", "core"}
    )
    z1 = f"({_origin(bottom_up, upper.name)})+{_h(upper)}"
    return f"({z1})-8*{_h(dielectric)}", z1


def _port_references(ground_objects: list[object], port_sheet: object) -> list[str]:
    port_box = port_sheet.bounding_box
    names: list[str] = []
    for ground in ground_objects:
        box = ground.bounding_box
        if box[0] <= port_box[3] and box[3] >= port_box[0] and box[2] <= port_box[5] and box[5] >= port_box[2]:
            names.append(ground.name)
    if not names:
        raise RuntimeError(f"No ground reference intersects {port_sheet.name}.")
    return names


def _create_port(
    hfss: Hfss,
    prefix: str,
    x: str,
    z0: str,
    z1: str,
    ground_objects: list[object],
    pair_index: int,
    differential_impedance: float,
    common_impedance: float,
) -> None:
    p = prefix.upper()
    hfss[f"CAP_{p}_PORT_Z0"] = z0
    hfss[f"CAP_{p}_PORT_Z1"] = z1
    hfss[f"CAP_{p}_PORT_Z"] = f"CAP_{p}_PORT_Z1-CAP_{p}_PORT_Z0"
    sheet = hfss.modeler.create_rectangle(
        "YZ", [x, f"CAP_BOARD_CENTER_Y-CAP_{p}_PORT_WIDTH/2", f"CAP_{p}_PORT_Z0"],
        [f"CAP_{p}_PORT_WIDTH", f"CAP_{p}_PORT_Z"], name=f"CAP_{p}_WAVE_PORT_SHEET",
    )
    if not sheet:
        raise RuntimeError(f"Unable to create CAP {p} port sheet.")
    name = f"CAP_{p}_WAVE_PORT"
    if not hfss.wave_port(
        sheet, reference=_port_references(ground_objects, sheet),
        create_port_sheet=False, modes=2, impedance=50, name=name, terminals_rename=True,
    ):
        raise RuntimeError(f"Unable to assign {name}.")
    for assignment, reference in ((f"{name}_T1", f"{name}_T2"), (f"{name}_1", f"{name}_2")):
        if hfss.set_differential_pair(
            assignment=assignment, reference=reference,
            common_mode=f"CAP_Comm{pair_index}", differential_mode=f"CAP_Diff{pair_index}",
            common_reference=common_impedance,
            differential_reference=differential_impedance,
            active=True, matched=False,
        ):
            return
    raise RuntimeError(f"Unable to configure differential pair for {name}.")


def _build_geometry(hfss: Hfss, stackup: StackupConfig, config: CapPadConfig) -> None:
    component_layer, input_layer, output_layer, dimensions = _validate(stackup, config)
    bottom_up = list(reversed(stackup.layers))
    mapping = layer_material_groups(stackup)
    _create_materials(hfss, stackup, mapping)
    colors = copper_layer_colors(stackup)
    m = hfss.modeler
    m.model_units = "mm"

    variables = {
        "CAP_PAD_LENGTH": config.pad_length,
        "CAP_PAD_WIDTH": config.pad_width,
        "CAP_PAD_GAP": config.pad_gap,
        "CAP_PAD_CENTER_PITCH": _mm(dimensions["pad_center_pitch"]),
        "CAP_LEFT_PAD_LENGTH": _mm(dimensions["left_pad_length"]),
        "CAP_LEFT_PAD_WIDTH": _mm(dimensions["left_pad_width"]),
        "CAP_LEFT_PAD_CORNER_RADIUS": _mm(dimensions["left_pad_corner_radius"]),
        "CAP_RIGHT_PAD_LENGTH": _mm(dimensions["right_pad_length"]),
        "CAP_RIGHT_PAD_WIDTH": _mm(dimensions["right_pad_width"]),
        "CAP_RIGHT_PAD_CORNER_RADIUS": _mm(dimensions["right_pad_corner_radius"]),
        "CAP_PAD_CORNER_RADIUS": config.pad_corner_radius,
        "CAP_PAD_CLEARANCE": config.pad_clearance,
        "CAP_LEFT_BREAKOUT_LENGTH": config.left_breakout_length,
        "CAP_LEFT_BREAKOUT_WIDTH": config.left_breakout_width,
        "CAP_RIGHT_BREAKOUT_LENGTH": config.right_breakout_length,
        "CAP_RIGHT_BREAKOUT_WIDTH": config.right_breakout_width,
        "CAP_PAIR_PITCH": config.pair_pitch,
        "CAP_INPUT_D_VIA": config.input_d_via,
        "CAP_OUTPUT_D_VIA": config.output_d_via,
        "CAP_VIA_INSET": config.via_inset,
        "CAP_VIA_COLUMN_RADIUS": config.via_column_radius,
        "CAP_VIA_PAD_RADIUS": config.via_pad_radius,
        "CAP_VIA_ANTIPAD_RADIUS": config.via_antipad_radius,
        "CAP_RETURN_COLUMN_RADIUS": config.return_column_radius,
        "CAP_RETURN_VIA_PITCH": config.return_via_pitch,
        "CAP_RETURN_VIA_CLEARANCE": config.return_via_clearance,
        "CAP_SIDE_MARGIN": config.side_margin,
        "CAP_SOLDER_HEIGHT": config.solder_height,
        "CAP_SOLDERMASK_COPPER_THICKNESS": config.solder_mask_copper_thickness,
        "CAP_SOLDERMASK_GAP_THICKNESS": config.solder_mask_gap_thickness,
        "CAP_SOLDERMASK_TRANSITION_WIDTH": config.solder_mask_transition_width,
        "CAP_SOLDERMASK_TRANSITION_HEIGHT": _mm(dimensions["solder_mask_transition_height"]),
        "CAP_SOLDERMASK_BOOLEAN_OVERLAP": "0.1um",
        "CAP_SOLDERMASK_TRANSITION_SWEEP_HEIGHT": (
            "CAP_SOLDERMASK_TRANSITION_HEIGHT+CAP_SOLDERMASK_BOOLEAN_OVERLAP"
        ),
        "CAP_SOLDERMASK_OPENING_EXPANSION": config.solder_mask_opening_expansion,
        "CAP_SOLDERMASK_WINDOW_X0": _mm(dimensions["solder_mask_window_x0"]),
        "CAP_SOLDERMASK_WINDOW_LENGTH": _mm(dimensions["solder_mask_window_length"]),
        "CAP_SOLDERMASK_WINDOW_WIDTH": _mm(dimensions["solder_mask_window_width"]),
        "CAP_SOLDERMASK_WINDOW_RADIUS": _mm(dimensions["solder_mask_window_radius"]),
        "CAP_RLC_SHEET_LENGTH": _mm(dimensions["rlc_sheet_length"]),
        "CAP_RLC_SHEET_WIDTH": _mm(dimensions["rlc_sheet_width"]),
        "CAP_RLC_RESISTANCE": f"{dimensions.get('lumped_resistance_ohm', 0.0):.12g}ohm",
        "CAP_RLC_INDUCTANCE": f"{dimensions.get('lumped_inductance_h', 0.0):.12g}H",
        "CAP_RLC_CAPACITANCE": f"{dimensions.get('lumped_capacitance_f', 0.1e-6):.12g}farad",
        "CAP_INPUT_TRACE_LENGTH": config.input_line.trace_length,
        "CAP_INPUT_FANOUT_LENGTH": config.input_line.fanout_length,
        "CAP_INPUT_W_LINE": config.input_line.w_line,
        "CAP_INPUT_S_LINE": config.input_line.s_line,
        "CAP_INPUT_G_LINE": config.input_line.g_line,
        "CAP_OUTPUT_TRACE_LENGTH": config.output_line.trace_length,
        "CAP_OUTPUT_FANOUT_LENGTH": config.output_line.fanout_length,
        "CAP_OUTPUT_W_LINE": config.output_line.w_line,
        "CAP_OUTPUT_S_LINE": config.output_line.s_line,
        "CAP_OUTPUT_G_LINE": config.output_line.g_line,
    }
    for prefix, via, route, line in (
        ("INPUT", config.input_via, input_layer, config.input_line),
        ("OUTPUT", config.output_via, output_layer, config.output_line),
    ):
        variables.update({
            f"CAP_{prefix}_VIA_COLUMN_RADIUS": via.column_radius,
            f"CAP_{prefix}_VIA_PAD_RADIUS": via.pad_radius,
            f"CAP_{prefix}_VIA_ANTIPAD_RADIUS": via.antipad_radius,
            f"CAP_{prefix}_VIA_ANTIPAD_X": via.antipad_x,
            f"CAP_{prefix}_MECHANICAL_COLUMN_RADIUS": via.mechanical_column_radius,
            f"CAP_{prefix}_MECHANICAL_PAD_RADIUS": via.mechanical_pad_radius,
        })
        via_path = _copper_path(stackup, component_layer, route)
        clearance_layers = _line_reference_clearance_layers(stackup, route, line)
        for layer in (
            item for item in stackup.layers
            if item.kind == "copper"
            and (item in via_path or item in clearance_layers)
        ):
            override = via.layer_antipads.get(layer.name, {})
            suffix = _identifier(layer.name)
            variables[f"CAP_{prefix}_VIA_ANTIPAD_RADIUS_{suffix}"] = override.get("radius", via.antipad_radius)
            variables[f"CAP_{prefix}_VIA_ANTIPAD_X_{suffix}"] = override.get("x", via.antipad_x)
    for layer_name, settings in config.layer_pad_voids.items():
        if not settings.get("enabled", False):
            continue
        suffix = _identifier(layer_name).upper()
        variables[f"CAP_PAD_VOID_{suffix}_X"] = str(settings["x"])
        variables[f"CAP_PAD_VOID_{suffix}_Y"] = str(settings["y"])
        variables[f"CAP_PAD_VOID_{suffix}_RADIUS"] = str(settings["radius"])
    for name, value in variables.items():
        hfss[name] = value
    for layer in stackup.layers:
        hfss[_h(layer)] = layer.thickness
    hfss["CAP_LEFT_PAD_CENTER_X"] = "-CAP_PAD_CENTER_PITCH/2"
    hfss["CAP_RIGHT_PAD_CENTER_X"] = "CAP_PAD_CENTER_PITCH/2"
    hfss["CAP_LEFT_PAD_X0"] = "CAP_LEFT_PAD_CENTER_X-CAP_LEFT_PAD_LENGTH/2"
    hfss["CAP_RIGHT_PAD_X0"] = "CAP_RIGHT_PAD_CENTER_X-CAP_RIGHT_PAD_LENGTH/2"
    hfss["CAP_LEFT_VIA_X"] = (
        "CAP_LEFT_PAD_X0-CAP_LEFT_BREAKOUT_LENGTH"
        if dimensions["left_breakout_length"] > 0
        else f"CAP_LEFT_PAD_CENTER_X+{_mm(dimensions['left_via_x_offset'])}"
    )
    hfss["CAP_RIGHT_VIA_X"] = (
        "CAP_RIGHT_PAD_X0+CAP_RIGHT_PAD_LENGTH+CAP_RIGHT_BREAKOUT_LENGTH"
        if dimensions["right_breakout_length"] > 0
        else f"CAP_RIGHT_PAD_CENTER_X+{_mm(dimensions['right_via_x_offset'])}"
    )
    board_width = dimensions["pair_pitch"] + max(dimensions["left_pad_width"], dimensions["right_pad_width"]) + 2 * dimensions["side_margin"]
    hfss["CAP_BOARD_WIDTH"] = _mm(board_width)
    hfss["CAP_BOARD_CENTER_Y"] = "CAP_BOARD_WIDTH/2"
    hfss["CAP_P_Y"] = "CAP_BOARD_CENTER_Y-CAP_PAIR_PITCH/2"
    hfss["CAP_N_Y"] = "CAP_BOARD_CENTER_Y+CAP_PAIR_PITCH/2"
    hfss["CAP_INPUT_P_VIA_Y"] = "CAP_BOARD_CENTER_Y-CAP_INPUT_D_VIA/2"
    hfss["CAP_INPUT_N_VIA_Y"] = "CAP_BOARD_CENTER_Y+CAP_INPUT_D_VIA/2"
    hfss["CAP_OUTPUT_P_VIA_Y"] = "CAP_BOARD_CENTER_Y-CAP_OUTPUT_D_VIA/2"
    hfss["CAP_OUTPUT_N_VIA_Y"] = "CAP_BOARD_CENTER_Y+CAP_OUTPUT_D_VIA/2"
    hfss["CAP_BOARD_X0"] = "CAP_LEFT_VIA_X-CAP_INPUT_FANOUT_LENGTH-CAP_INPUT_TRACE_LENGTH"
    hfss["CAP_BOARD_X1"] = "CAP_RIGHT_VIA_X+CAP_OUTPUT_FANOUT_LENGTH+CAP_OUTPUT_TRACE_LENGTH"
    hfss["CAP_BOARD_LENGTH"] = "CAP_BOARD_X1-CAP_BOARD_X0"
    hfss["CAP_BOARD_THICKNESS"] = "+".join(_h(layer) for layer in bottom_up)
    hfss["CAP_INPUT_PORT_WIDTH"] = "CAP_INPUT_S_LINE+4*CAP_INPUT_W_LINE+6*CAP_INPUT_G_LINE"
    hfss["CAP_OUTPUT_PORT_WIDTH"] = "CAP_OUTPUT_S_LINE+4*CAP_OUTPUT_W_LINE+6*CAP_OUTPUT_G_LINE"

    records: dict[str, dict[str, object]] = {}
    ground_objects: list[object] = []
    z0 = "0mm"
    for layer in bottom_up:
        if layer.kind in {"pp", "core"}:
            obj = m.create_box(
                ["CAP_BOARD_X0", "0mm", z0], ["CAP_BOARD_LENGTH", "CAP_BOARD_WIDTH", _h(layer)],
                name=f"CAP_{_identifier(layer.name)}", material=mapping[layer.name],
            )
            if not obj:
                raise RuntimeError(f"Unable to create dielectric {layer.name}.")
            obj.display_wireframe = True
        else:
            obj = m.create_box(
                ["CAP_BOARD_X0", "0mm", z0], ["CAP_BOARD_LENGTH", "CAP_BOARD_WIDTH", _h(layer)],
                name=f"CAP_GND_{_identifier(layer.name)}", material="copper",
            )
            if not obj:
                raise RuntimeError(f"Unable to create copper layer {layer.name}.")
            _set_object_color(obj, colors[layer.name])
            records[layer.name] = {"layer": layer, "ground": obj, "z_origin": z0}
            ground_objects.append(obj)
        z0 = f"({z0})+{_h(layer)}"

    component_record = records[component_layer.name]
    component_suffix = _identifier(component_layer.name).upper()
    # Clear the short pad-to-via corridors while the mounting-layer ground is
    # still intact. The later group and slot voids may overlap these corridors.
    for prefix, column, x_pad_edge, x_via, length in (
        ("INPUT", "LEFT", "CAP_LEFT_PAD_X0", "CAP_LEFT_VIA_X", dimensions["left_breakout_length"]),
        (
            "OUTPUT", "RIGHT", "CAP_RIGHT_PAD_X0+CAP_RIGHT_PAD_LENGTH",
            "CAP_RIGHT_VIA_X", dimensions["right_breakout_length"],
        ),
    ):
        if length > 0:
            _subtract_pad_breakout_clearance(
                hfss, component_record["ground"], prefix, column,
                x_pad_edge, x_via, component_record["z_origin"],
                _h(component_layer), component_suffix,
            )

    # The capacitor footprint void is one group-centred rounded rectangle per
    # enabled copper layer. It is independent of the two signal-via slots.
    for layer_name, settings in config.layer_pad_voids.items():
        if settings.get("enabled", False):
            record = records[layer_name]
            _subtract_rounded_cap_void(
                hfss, record["ground"], record["layer"],
                record["z_origin"], _h(record["layer"]),
            )

    paths = {
        "INPUT": (input_layer, "CAP_LEFT_VIA_X", config.input_via),
        "OUTPUT": (output_layer, "CAP_RIGHT_VIA_X", config.output_via),
    }
    # Each left/right via stack has its own connected P/N slot on every copper
    # layer in its path. Radius and +/-X can be overridden independently.
    for prefix, (route, x, via) in paths.items():
        for layer in _copper_path(stackup, component_layer, route):
            record = records[layer.name]
            _subtract_cap_slot_antipad(
                hfss, record["ground"], prefix, layer, x,
                record["z_origin"], _h(layer),
            )

    _subtract_route_clearance(
        hfss, records[input_layer.name]["ground"], "input", -1, "CAP_LEFT_VIA_X",
        records[input_layer.name]["z_origin"], _h(input_layer),
        f"CAP_INPUT_VIA_ANTIPAD_RADIUS_{_identifier(input_layer.name)}",
    )
    _subtract_route_clearance(
        hfss, records[output_layer.name]["ground"], "output", 1, "CAP_RIGHT_VIA_X",
        records[output_layer.name]["z_origin"], _h(output_layer),
        f"CAP_OUTPUT_VIA_ANTIPAD_RADIUS_{_identifier(output_layer.name)}",
    )
    _subtract_line_reference_clearances(
        hfss, stackup, records, input_layer, config.input_line,
        "input", -1, "CAP_LEFT_VIA_X",
    )
    _subtract_line_reference_clearances(
        hfss, stackup, records, output_layer, config.output_line,
        "output", 1, "CAP_RIGHT_VIA_X",
    )

    # The four primary objects intentionally remain separate from via columns.
    component_pads: dict[tuple[str, str], object] = {}
    for side, y in (("P", "CAP_P_Y"), ("N", "CAP_N_Y")):
        for column in ("LEFT", "RIGHT"):
            component_pads[(column, side)] = _create_rounded_pad(
                hfss, f"CAP_{side}_{column}_PAD", f"CAP_{column}_PAD_X0",
                f"({y})-CAP_{column}_PAD_WIDTH/2",
                component_record["z_origin"], _h(component_layer),
                colors[component_layer.name], column=column,
            )

    for prefix, column, x_pad_edge, x_via, via_config, length in (
        (
            "INPUT", "LEFT", "CAP_LEFT_PAD_X0+1um", "CAP_LEFT_VIA_X",
            config.input_via, dimensions["left_breakout_length"],
        ),
        (
            "OUTPUT", "RIGHT", "CAP_RIGHT_PAD_X0+CAP_RIGHT_PAD_LENGTH-1um",
            "CAP_RIGHT_VIA_X", config.output_via, dimensions["right_breakout_length"],
        ),
    ):
        if length <= 0:
            continue
        landing_radius = f"CAP_{prefix}_VIA_PAD_RADIUS"
        if via_config.mechanical_enabled and via_config.mechanical_start_layer == component_layer.name:
            landing_radius = f"CAP_{prefix}_MECHANICAL_PAD_RADIUS"
        for side, pad_center, via_center in (
            ("P", "CAP_P_Y", f"CAP_{prefix}_P_VIA_Y"),
            ("N", "CAP_N_Y", f"CAP_{prefix}_N_VIA_Y"),
        ):
            _create_pad_breakout(
                hfss, component_pads[(column, side)], prefix, column, side,
                x_pad_edge, x_via, pad_center, via_center,
                component_record["z_origin"], _h(component_layer),
                landing_radius, colors[component_layer.name],
            )

    component_z = "CAP_BOARD_THICKNESS" if config.component_side == "top" else "0mm"
    _create_cap_solder_mask(hfss, config, component_layer, component_record, dimensions)
    _create_cap_solder(hfss, config, component_z)
    _create_cap_lumped_rlc(
        hfss, config, component_z,
        dimensions.get("lumped_resistance_ohm"),
        dimensions.get("lumped_inductance_h"),
        dimensions.get("lumped_capacitance_f"),
    )

    _line_geometry(
        hfss, "input", -1, "CAP_LEFT_VIA_X", records[input_layer.name]["z_origin"],
        _h(input_layer), colors[input_layer.name],
        "CAP_INPUT_MECHANICAL_PAD_RADIUS" if config.input_via.mechanical_enabled and config.input_via.mechanical_end_layer == input_layer.name else None,
    )
    _line_geometry(
        hfss, "output", 1, "CAP_RIGHT_VIA_X", records[output_layer.name]["z_origin"],
        _h(output_layer), colors[output_layer.name],
        "CAP_OUTPUT_MECHANICAL_PAD_RADIUS" if config.output_via.mechanical_enabled and config.output_via.mechanical_end_layer == output_layer.name else None,
    )
    _via_stack(hfss, stackup, bottom_up, records, component_layer, input_layer, "INPUT", "CAP_LEFT_VIA_X", config.input_via)
    _via_stack(hfss, stackup, bottom_up, records, component_layer, output_layer, "OUTPUT", "CAP_RIGHT_VIA_X", config.output_via)

    if config.return_vias_enabled:
        for index, (x, y) in enumerate(_all_return_points(dimensions, config), 1):
            via = m.create_cylinder(
                "Z", [_mm(x), f"CAP_BOARD_CENTER_Y+({_mm(y)})", "0mm"],
                "CAP_RETURN_COLUMN_RADIUS", "CAP_BOARD_THICKNESS",
                name=f"CAP_RETURN_VIA_{index:03d}_COLUMN", material="copper",
            )
            if not via:
                raise RuntimeError(f"Unable to create CAP return via {index}.")

    # Component origins are at each gap centre on the selected outer surface.
    component_y_axis = [0, 1, 0] if config.component_side == "top" else [0, -1, 0]
    for side, y in (("P", "CAP_P_Y"), ("N", "CAP_N_Y")):
        cs = m.create_coordinate_system(
            origin=["0mm", y, component_z],
            name=f"CAP_{side}_COMPONENT_CS", mode="axis",
            x_pointing=[1, 0, 0], y_pointing=component_y_axis,
        )
        if not cs:
            raise RuntimeError(f"Unable to create CAP {side} component coordinate system.")
        if config.solder_enabled:
            assembly_z = (
                "CAP_BOARD_THICKNESS+CAP_SOLDER_HEIGHT"
                if config.component_side == "top" else "-CAP_SOLDER_HEIGHT"
            )
            assembly_cs = m.create_coordinate_system(
                origin=["0mm", y, assembly_z],
                name=f"CAP_{side}_ASSEMBLY_CS", mode="axis",
                x_pointing=[1, 0, 0], y_pointing=component_y_axis,
            )
            if not assembly_cs:
                raise RuntimeError(f"Unable to create CAP {side} assembly coordinate system.")
    _insert_real_capacitors(hfss, config)
    # AEDT makes the most recently created coordinate system active.  Restore
    # Global before creating ports, otherwise their coordinates are offset by
    # the N-component origin.
    if not m.set_working_coordinate_system("Global"):
        raise RuntimeError("Unable to restore the Global working coordinate system.")

    input_z0, input_z1 = _port_span(stackup, input_layer, bottom_up, config.input_line)
    output_z0, output_z1 = _port_span(stackup, output_layer, bottom_up, config.output_line)
    _create_port(
        hfss, "input", "CAP_BOARD_X0", input_z0, input_z1,
        ground_objects, 1, stackup.differential_impedance, stackup.common_impedance,
    )
    _create_port(
        hfss, "output", "CAP_BOARD_X1", output_z0, output_z1,
        ground_objects, 2, stackup.differential_impedance, stackup.common_impedance,
    )


def _project_cap_expression(expression: str) -> str:
    """Convert references to local CAP variables into project references."""
    return re.sub(
        r"(?<![$A-Za-z0-9_])(CAP_[A-Za-z0-9_]+)",
        lambda match: f"${match.group(1)}",
        str(expression),
    )


def _promote_cap_variables_to_project(
    hfss: Hfss, update_project_values: bool = True
) -> None:
    """Share all generated CAP variables while retaining local aliases."""
    names = [
        name for name in hfss.variable_manager.design_variable_names
        if name.startswith("CAP_")
    ]
    expressions = {
        name: str(hfss.variable_manager[name].expression)
        for name in names
    }
    if update_project_values:
        for name in names:
            hfss[f"${name}"] = _project_cap_expression(expressions[name])
    for name in names:
        hfss[name] = f"${name}"


def _create_cap_analysis(hfss: Hfss, config: CapPadConfig) -> None:
    create_hfss_analysis(
        hfss,
        create_open_region=config.create_open_region,
        open_region_frequency=config.open_region_frequency,
        create_setup=config.create_setup,
        create_sweep=config.create_sweep,
        sweep_start=config.sweep_start,
        sweep_stop=config.sweep_stop,
        sweep_points=config.sweep_points,
    )


def build_cap_pad_project(
    stackup_config: StackupConfig,
    cap_config: CapPadConfig,
    project_path: str | Path,
    keep_desktop_open: bool = True,
    log_callback=None,
    new_desktop: bool = False,
) -> Path:
    """Build and save one CAP project, optionally with paired RLC/A3D designs."""
    _validate(stackup_config, cap_config)
    project_path = Path(project_path)
    if project_path.exists():
        raise FileExistsError(f"Output project already exists: {project_path}")
    desktop = None
    try:
        version = stackup_config.aedt_version.strip() or None
        desktop = Desktop(
            version=version, non_graphical=False, new_desktop=new_desktop, close_on_exit=False,
        )
        if keep_desktop_open:
            _OPEN_DESKTOPS.append(desktop)
        first_design = (
            "CAP_RLC_FAST" if cap_config.comparison_designs_enabled
            else stackup_config.design_name
        )
        hfss = Hfss(
            project=str(project_path), design=first_design,
            solution_type="Terminal", version=version,
            new_desktop=False, close_on_exit=False,
            aedt_process_id=desktop.aedt_process_id,
        )
        if cap_config.comparison_designs_enabled:
            rlc_config = deepcopy(cap_config)
            rlc_config.comparison_designs_enabled = False
            rlc_config.real_component_enabled = False
            rlc_config.lumped_rlc_enabled = True
            physical_config = deepcopy(cap_config)
            physical_config.comparison_designs_enabled = False
            physical_config.real_component_enabled = True
            physical_config.lumped_rlc_enabled = False
            _validate(stackup_config, rlc_config)
            _validate(stackup_config, physical_config)
            _build_geometry(hfss, stackup_config, rlc_config)
            _create_cap_analysis(hfss, rlc_config)
            _promote_cap_variables_to_project(hfss)
            hfss.modeler.fit_all()
            hfss.insert_design("CAP_A3D_VERIFY", solution_type="Terminal")
            if hfss.design_name != "CAP_A3D_VERIFY":
                raise RuntimeError("Unable to create CAP_A3D_VERIFY design.")
            _build_geometry(hfss, stackup_config, physical_config)
            _create_cap_analysis(hfss, physical_config)
            _promote_cap_variables_to_project(hfss, update_project_values=False)
        else:
            _build_geometry(hfss, stackup_config, cap_config)
            _create_cap_analysis(hfss, cap_config)
        set_copper_transparency(hfss)
        if not hfss.save_project(project_path, overwrite=False):
            raise RuntimeError(f"Unable to save project: {project_path}")
        hfss.modeler.fit_all()
        if log_callback:
            log_callback(f"CAP pad project created: {project_path}")
        return project_path
    finally:
        if desktop and not keep_desktop_open:
            if new_desktop:
                desktop.release_desktop(close_projects=True, close_on_exit=True)
            else:
                desktop.release_desktop(close_projects=False, close_on_exit=False)


def build_project() -> Path:
    """Build the default eight-layer L3-to-L5 CAP footprint."""
    stackup = eight_layer_example()
    stackup.design_name = DESIGN_NAME
    stackup.aedt_version = AEDT_VERSION
    output = PROJECT_PATH
    suffix = 1
    while output.exists():
        output = PROJECT_PATH.with_name(f"{PROJECT_PATH.stem}_{suffix}{PROJECT_PATH.suffix}")
        suffix += 1
    return build_cap_pad_project(stackup, CapPadConfig(), output, KEEP_DESKTOP_OPEN)


if __name__ == "__main__":
    build_project()
