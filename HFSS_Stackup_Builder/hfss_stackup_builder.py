"""Reusable PyAEDT builder for a single differential pair in a PCB stackup."""

# Developer: 39004628 / Luxshare
# Copyright © 2026 39004628 / Luxshare. All rights reserved.

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import floor
from pathlib import Path
import re
from typing import Callable, Optional

from pyaedt import Desktop, Hfss


LogCallback = Optional[Callable[[str], None]]

# AEDT display colours are assigned by copper-layer order (L1, L2, ...).
# Keeping this palette here makes the standalone builder and GUI-generated
# projects visually consistent.
COPPER_COLOR_PALETTE = (
    (220, 120, 40), (40, 145, 220), (70, 175, 95), (180, 90, 205),
    (220, 75, 100), (40, 185, 175), (200, 160, 45), (110, 110, 220),
)
RETURN_VIA_COLOR = (145, 145, 145)


def _set_object_color(obj: object, rgb: tuple[int, int, int]) -> None:
    """Set an AEDT object's display colour across PyAEDT versions."""
    try:
        obj.color = rgb
    except (AttributeError, TypeError, ValueError):
        try:
            obj.color = "(%d %d %d)" % rgb
        except (AttributeError, TypeError, ValueError):
            pass


COPPER_TRANSPARENCY = 0.0


def set_copper_transparency(hfss: Hfss, value: float = COPPER_TRANSPARENCY) -> int:
    """Force every copper object to the requested display transparency.

    Copper must stay fully opaque in the 3D view so the layer alignment and
    clearances remain readable. Returns the number of objects updated.
    """
    updated = 0
    objects = getattr(getattr(hfss, "modeler", None), "objects", None) or {}
    for obj in objects.values():
        material = (getattr(obj, "material_name", "") or "").strip().lower()
        if material != "copper":
            continue
        try:
            obj.transparency = value
        except (AttributeError, TypeError, ValueError):
            continue
        updated += 1
    return updated


def copper_layer_colors(config: StackupConfig) -> dict[str, tuple[int, int, int]]:
    """Return deterministic, distinct colours for all copper layers."""
    copper = [layer for layer in config.layers if layer.kind == "copper"]
    return {
        layer.name: COPPER_COLOR_PALETTE[index % len(COPPER_COLOR_PALETTE)]
        for index, layer in enumerate(copper)
    }


_OPEN_DESKTOPS: list[Desktop] = []


def _config_bool(value: object) -> bool:
    """Read booleans from JSON without treating the string 'false' as true."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Layer:
    """One stackup row. Layers are stored top-to-bottom."""

    name: str
    kind: str  # copper, pp, core
    thickness: str
    dk: Optional[float] = None
    df: Optional[float] = None
    material_name: str = ""
    copper_type: str = ""
    role: str = "ground"  # ground or signal; only applicable to copper

    @classmethod
    def from_dict(cls, data: dict) -> "Layer":
        return cls(
            name=str(data["name"]),
            kind=str(data["kind"]).lower(),
            thickness=str(data["thickness"]),
            dk=None if data.get("dk") in (None, "") else float(data["dk"]),
            df=None if data.get("df") in (None, "") else float(data["df"]),
            material_name=str(data.get("material_name", "")),
            copper_type=str(data.get("copper_type", "")),
            role=str(data.get("role", "ground")).lower(),
        )


@dataclass
class StackupConfig:
    """Complete GUI-editable configuration for one HFSS differential model."""

    layers: list[Layer] = field(default_factory=list)
    board_length: str = "100mil"
    board_margin_x: str = "10mil"
    w_line: str = "4.04mil"
    s_line: str = "5.96mil"
    g_line: str = "4.26mil"
    upper_reference_layer_name: str = ""
    lower_reference_layer_name: str = ""
    differential_impedance: float = 93.0
    common_impedance: float = 23.25
    # A local PCB model needs a physical return path between reference planes.
    # These vias are placed on both sides of the signal-layer ground clearance.
    return_vias_enabled: bool = True
    return_via_diameter: str = "2mil"
    return_via_ground_edge_offset: str = "5mil"
    return_via_pitch: str = "5mil"
    # Empty means "use the active AEDT session or the latest installed release".
    aedt_version: str = ""
    design_name: str = "StackupDifferential"
    create_open_region: bool = True
    open_region_frequency: str = "60GHz"
    create_setup: bool = True
    create_sweep: bool = True
    sweep_start: str = "0.01GHz"
    sweep_stop: str = "60GHz"
    sweep_points: int = 401
    port_deembed_distance: str = "-5mm"
    create_tdr_report: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "StackupConfig":
        differential_impedance = float(data.get("differential_impedance", 93.0))
        return cls(
            layers=[Layer.from_dict(item) for item in data.get("layers", [])],
            board_length=str(data.get("board_length", "100mil")),
            board_margin_x=str(data.get("board_margin_x", "10mil")),
            w_line=str(data.get("w_line", "4.04mil")),
            s_line=str(data.get("s_line", "5.96mil")),
            g_line=str(data.get("g_line", "4.26mil")),
            upper_reference_layer_name=str(data.get("upper_reference_layer_name", "")),
            lower_reference_layer_name=str(data.get("lower_reference_layer_name", "")),
            differential_impedance=differential_impedance,
            # Old JSON files did not store this field and used Diff/4.
            common_impedance=float(data.get(
                "common_impedance", differential_impedance / 4.0
            )),
            return_vias_enabled=bool(data.get("return_vias_enabled", True)),
            return_via_diameter=str(data.get("return_via_diameter", "2mil")),
            return_via_ground_edge_offset=str(data.get("return_via_ground_edge_offset", "5mil")),
            return_via_pitch=str(data.get("return_via_pitch", "5mil")),
            aedt_version=str(data.get("aedt_version", "")),
            design_name=str(data.get("design_name", "StackupDifferential")),
            create_open_region=_config_bool(data.get("create_open_region", True)),
            open_region_frequency=str(data.get("open_region_frequency", "60GHz")),
            create_setup=_config_bool(data.get("create_setup", True)),
            create_sweep=_config_bool(data.get("create_sweep", True)),
            sweep_start=str(data.get("sweep_start", "0.01GHz")),
            sweep_stop=str(data.get("sweep_stop", "60GHz")),
            sweep_points=int(data.get("sweep_points", 401)),
            port_deembed_distance=str(data.get("port_deembed_distance", "-5mm")),
            create_tdr_report=_config_bool(data.get("create_tdr_report", True)),
        )


def eight_layer_example() -> StackupConfig:
    """Return the verified eight-layer example shown in the stackup image."""
    return StackupConfig(
        design_name="EightLayerL2Differential",
        upper_reference_layer_name="L1",
        lower_reference_layer_name="L3",
        layers=[
            Layer("L1", "copper", "1.7mil", copper_type="HVLP2"),
            Layer("PP_L1", "pp", "3.3mil", 2.84, 0.0018),
            Layer("L2", "copper", "1.23mil", copper_type="HVLP2", role="signal"),
            Layer("PP_L2", "pp", "3.34mil", 2.84, 0.0018),
            Layer("L3", "copper", "1.4mil", copper_type="HVLP2"),
            Layer("PP_L3", "pp", "3.37mil", 2.84, 0.0018),
            Layer("L4", "copper", "1.2mil", copper_type="HVLP"),
            Layer("PP_L4_CORE", "core", "8mil", 2.99, 0.0019),
            Layer("L5", "copper", "1.2mil", copper_type="HVLP"),
            Layer("PP_L5", "pp", "3.37mil", 2.84, 0.0018),
            Layer("L6", "copper", "1.4mil", copper_type="HVLP2"),
            Layer("PP_L6", "pp", "3.34mil", 2.84, 0.0018),
            Layer("L7", "copper", "1.23mil", copper_type="HVLP2"),
            Layer("PP_L7", "pp", "3.3mil", 2.84, 0.0018),
            Layer("L8", "copper", "1.7mil", copper_type="HVLP2"),
        ],
    )


def _emit(callback: LogCallback, message: str) -> None:
    if callback:
        callback(message)


def _identifier(value: str) -> str:
    result = "".join(char if char.isalnum() or char == "_" else "_" for char in value)
    if not result or result[0].isdigit():
        result = f"L_{result}"
    return result


def height_variable(layer: Layer) -> str:
    """Create a stable AEDT variable name for a layer thickness."""
    name = _identifier(layer.name.upper())
    if name.endswith("_CORE"):
        return name[:-5] + "_H_CORE"
    return f"{name}_H"


def layer_material_groups(config: StackupConfig) -> dict[str, str]:
    """Return the effective material name for each PP/Core layer.

    Blank material names are grouped by exactly matching DK/DF. An explicit material
    name is an override and may be used to split otherwise identical material rows.
    """
    groups: dict[str, str] = {}
    generated_names: dict[tuple[float, float], str] = {}

    for layer in config.layers:
        if layer.kind not in {"pp", "core"}:
            continue
        if layer.dk is None or layer.df is None:
            raise ValueError(f"{layer.name}: PP/Core layers require DK and DF.")
        if layer.material_name.strip():
            groups[layer.name] = layer.material_name.strip()
            continue
        key = (float(layer.dk), float(layer.df))
        if key not in generated_names:
            dk = str(layer.dk).replace(".", "p")
            df = str(layer.df).replace(".", "p")
            generated_names[key] = f"Diel_DK{dk}_DF{df}"
        groups[layer.name] = generated_names[key]
    return groups


def _validate(config: StackupConfig, *, validate_references: bool = True) -> Layer:
    if len(config.layers) < 3:
        raise ValueError("At least three stackup layers are required.")
    if any(layer.kind not in {"copper", "pp", "core"} for layer in config.layers):
        raise ValueError("Layer type must be copper, pp, or core.")
    if len({layer.name for layer in config.layers}) != len(config.layers):
        raise ValueError("Layer names must be unique.")
    signals = [layer for layer in config.layers if layer.kind == "copper" and layer.role == "signal"]
    if len(signals) != 1:
        raise ValueError("Exactly one copper layer must have role 'signal'.")
    signal = signals[0]
    signal_index = config.layers.index(signal)
    if config.differential_impedance <= 0:
        raise ValueError("Differential-mode impedance must be positive.")
    if config.common_impedance <= 0:
        raise ValueError("Common-mode impedance must be positive.")
    if not re.fullmatch(r"\s*[+-]?(?:\d+(?:\.\d*)?|\.\d+)\s*(?:mm|mil|um|in)\s*", config.port_deembed_distance, re.IGNORECASE):
        raise ValueError("Wave-port deembed distance must be a signed literal length (for example -5mm).")

    for layer in config.layers:
        if not layer.thickness.strip():
            raise ValueError(f"{layer.name}: thickness is required.")
        if layer.kind in {"pp", "core"} and (layer.dk is None or layer.df is None):
            raise ValueError(f"{layer.name}: PP/Core layers require DK and DF.")

    if validate_references:
        _resolve_reference_layers(
            config,
            signal,
            config.upper_reference_layer_name,
            config.lower_reference_layer_name,
        )
    return signal


def _sum_expression(items: list[str]) -> str:
    return "+".join(items) if items else "0mil"


def _origin_expression_bottom_up(bottom_up: list[Layer], target_name: str) -> str:
    below: list[str] = []
    for layer in bottom_up:
        if layer.name == target_name:
            return _sum_expression(below)
        below.append(height_variable(layer))
    raise ValueError(f"Unknown layer: {target_name}")


def _nearest_copper(config: StackupConfig, start_index: int, direction: int) -> Layer:
    """Find the first copper layer above (-1) or below (+1) a signal layer."""
    index = start_index + direction
    while 0 <= index < len(config.layers):
        layer = config.layers[index]
        if layer.kind == "copper":
            return layer
        index += direction
    raise ValueError("Signal layer does not have a reference copper layer in this direction.")


def _resolve_reference_layers(
    config: StackupConfig,
    signal: Layer,
    upper_name: str,
    lower_name: str,
    *,
    require_ground_role: bool = True,
    field_prefix: str = "",
) -> tuple[Layer | None, Layer | None]:
    """Resolve explicit reference copper on each physically available side."""
    copper = [layer for layer in config.layers if layer.kind == "copper"]
    signal_copper_index = copper.index(signal)
    signal_index = config.layers.index(signal)
    label = f"{field_prefix} " if field_prefix else ""

    def resolve(name: str, side: str, required: bool) -> Layer | None:
        field = f"{label}{side} reference layer".strip()
        if not required:
            if name.strip():
                raise ValueError(f"{field} is not applicable to external layer {signal.name}.")
            return None
        if not name.strip():
            raise ValueError(f"{field} must be explicitly selected.")
        layer = next((item for item in config.layers if item.name == name), None)
        if layer is None or layer.kind != "copper":
            raise ValueError(f"{field} {name!r} must be a copper layer.")
        if require_ground_role and layer.role != "ground":
            raise ValueError(f"{field} {name!r} must be a ground copper layer.")
        layer_index = config.layers.index(layer)
        if side == "upper" and not layer_index < signal_index:
            raise ValueError(f"{field} must be above route layer {signal.name}.")
        if side == "lower" and not signal_index < layer_index:
            raise ValueError(f"{field} must be below route layer {signal.name}.")
        return layer

    upper = resolve(upper_name, "upper", signal_copper_index > 0)
    lower = resolve(lower_name, "lower", signal_copper_index < len(copper) - 1)
    return upper, lower


def _port_reference_conductors(
    config: StackupConfig,
    route_layer: Layer,
    upper_reference: Layer | None,
    lower_reference: Layer | None,
    ground_by_layer: dict[str, object],
) -> list[str]:
    """Return every ground conductor intersected by a cross-layer port.

    The selected reference layers define the port's Z extent, but every copper
    ground inside that extent must be passed to AEDT as a reference conductor.
    Otherwise skipped copper layers are auto-identified as extra signal
    terminals (for example T1/T2/T5/T6 around the real P/N terminals).
    """
    route_index = config.layers.index(route_layer)
    upper_index = (
        config.layers.index(upper_reference) if upper_reference else route_index
    )
    lower_index = (
        config.layers.index(lower_reference) if lower_reference else route_index
    )
    names: list[str] = []
    # Port sheets are expressed bottom-to-top, so keep the reference list in
    # the same physical order.  P/N traces are separate objects and therefore
    # are intentionally absent from ``ground_by_layer``.
    for layer in reversed(config.layers[upper_index:lower_index + 1]):
        ground = ground_by_layer.get(layer.name)
        if layer.kind == "copper" and ground is not None:
            names.append(ground.name)
    if not names:
        raise RuntimeError(f"No ground conductors found for route layer {route_layer.name}.")
    return names


def _create_materials(hfss: Hfss, config: StackupConfig, mapping: dict[str, str]) -> None:
    created: set[str] = set()
    for layer in config.layers:
        if layer.kind not in {"pp", "core"}:
            continue
        material_name = mapping[layer.name]
        if material_name in created:
            continue
        material = hfss.materials.add_material(material_name)
        if not material:
            material = hfss.materials[material_name]
        material.permittivity = layer.dk
        material.dielectric_loss_tangent = layer.df
        material.update()
        created.add(material_name)


def create_hfss_analysis(
    hfss: Hfss,
    *,
    create_open_region: bool = True,
    open_region_frequency: str = "60GHz",
    create_setup: bool = True,
    create_sweep: bool = True,
    sweep_start: str = "0.01GHz",
    sweep_stop: str = "60GHz",
    sweep_points: int = 401,
) -> None:
    """Create the common Radiation region, Setup1, and Sweep without solving."""
    if create_sweep and not create_setup:
        raise ValueError("create_sweep requires create_setup.")
    if create_sweep and sweep_points < 2:
        raise ValueError("sweep_points must be at least 2.")
    if create_open_region and not hfss.create_open_region(
        frequency=open_region_frequency,
        boundary="Radiation",
        apply_infinite_ground=False,
    ):
        raise RuntimeError("Unable to create open Radiation region.")
    if not create_setup:
        return
    setup = hfss.create_setup(name="Setup1", setup_type="HFSSDriven")
    if not setup:
        raise RuntimeError("Unable to create Setup1.")
    setup.props["SolveType"] = "Broadband"
    setup.props["MultipleAdaptiveFreqsSetup"] = {
        "Low": sweep_start,
        "High": sweep_stop,
    }
    setup.props["MaxDeltaS"] = 0.02
    setup.props["MaximumPasses"] = 12
    setup.props["MinimumPasses"] = 1
    setup.props["MinimumConvergedPasses"] = 1
    if not setup.update():
        raise RuntimeError("Unable to update Setup1.")
    if not create_sweep:
        return
    sweep = setup.add_sweep(name="Sweep", sweep_type="Interpolating")
    if not sweep:
        raise RuntimeError("Unable to create Sweep.")
    sweep.props["RangeType"] = "LinearCount"
    sweep.props["RangeStart"] = sweep_start
    sweep.props["RangeEnd"] = sweep_stop
    sweep.props["RangeCount"] = sweep_points
    sweep.props["SaveFields"] = False
    sweep.props["SaveRadFields"] = False
    sweep.props["InterpTolerance"] = 0.5
    sweep.props["InterpMaxSolns"] = 250
    sweep.props["EnforcePassivity"] = True
    if not sweep.update():
        raise RuntimeError("Unable to update Sweep.")


def _create_signal_copper(hfss: Hfss, layer: Layer, z_origin: str) -> dict[str, object]:
    modeler = hfss.modeler
    height = height_variable(layer)
    signal_id = _identifier(layer.name)
    ground = modeler.create_box(
        ["0mil", "0mil", z_origin],
        ["BOARD_WIDTH", "BOARD_LENGTH", height],
        name=f"GND_{signal_id}",
        material="copper",
    )
    clearance = modeler.create_box(
        ["BOARD_WIDTH/2-(S_LINE/2+W_LINE+G_LINE)", "0mil", z_origin],
        ["S_LINE+2*W_LINE+2*G_LINE", "BOARD_LENGTH", height],
        name=f"{signal_id}_Clearance",
        material="vacuum",
    )
    if not modeler.subtract(ground, clearance, keep_originals=False):
        raise RuntimeError(f"Unable to create clearance on {layer.name}.")
    return {
        "ground": ground,
        "positive": modeler.create_box(
            ["BOARD_WIDTH/2+S_LINE/2", "0mil", z_origin],
            ["W_LINE", "BOARD_LENGTH", height],
            name=f"SIG_P_{signal_id}",
            material="copper",
        ),
        "negative": modeler.create_box(
            ["BOARD_WIDTH/2-S_LINE/2-W_LINE", "0mil", z_origin],
            ["W_LINE", "BOARD_LENGTH", height],
            name=f"SIG_N_{signal_id}",
            material="copper",
        ),
    }


def _adjacent_dielectric(config: StackupConfig, signal_index: int) -> Layer:
    direction = 1 if signal_index == 0 else -1
    index = signal_index + direction
    while 0 <= index < len(config.layers):
        layer = config.layers[index]
        if layer.kind in {"pp", "core"}:
            return layer
        index += direction
    raise ValueError("External signal layer requires an adjacent PP/Core layer.")


def _reference_span_expressions(
    signal: Layer,
    upper_reference: Layer | None,
    lower_reference: Layer | None,
    bottom_up: list[Layer],
) -> tuple[str, str]:
    """Return the outer faces enclosing the signal and selected references."""
    signal_origin = _origin_expression_bottom_up(bottom_up, signal.name)
    z0 = (
        _origin_expression_bottom_up(bottom_up, lower_reference.name)
        if lower_reference else signal_origin
    )
    upper = upper_reference or signal
    upper_origin = _origin_expression_bottom_up(bottom_up, upper.name)
    z1 = f"({upper_origin})+{height_variable(upper)}"
    return z0, z1


def _port_expressions(
    config: StackupConfig,
    signal: Layer,
    upper_reference: Layer | None,
    lower_reference: Layer | None,
    bottom_up: list[Layer],
) -> tuple[str, str]:
    """Return the lower and upper z coordinates of the wave-port sheet."""
    signal_index = config.layers.index(signal)
    signal_origin = _origin_expression_bottom_up(bottom_up, signal.name)
    signal_top = f"({signal_origin})+{height_variable(signal)}"

    if signal_index == 0:  # Top external CPWG: extend above the outer copper.
        if lower_reference is None:
            raise ValueError("Top external signal requires a lower reference layer.")
        z0 = _origin_expression_bottom_up(bottom_up, lower_reference.name)
        dielectric = _adjacent_dielectric(config, signal_index)
        z1 = f"({signal_top})+8*{height_variable(dielectric)}"
    elif signal_index == len(config.layers) - 1:  # Bottom external CPWG.
        if upper_reference is None:
            raise ValueError("Bottom external signal requires an upper reference layer.")
        upper_origin = _origin_expression_bottom_up(bottom_up, upper_reference.name)
        z1 = f"({upper_origin})+{height_variable(upper_reference)}"
        dielectric = _adjacent_dielectric(config, signal_index)
        z0 = f"({signal_origin})-8*{height_variable(dielectric)}"
    else:  # Internal stripline: include the complete thickness of both reference grounds.
        if upper_reference is None or lower_reference is None:
            raise ValueError("Internal signal requires upper and lower reference layers.")
        lower_origin = _origin_expression_bottom_up(bottom_up, lower_reference.name)
        upper_origin = _origin_expression_bottom_up(bottom_up, upper_reference.name)
        # A terminal port needs to intersect each reference conductor.  Therefore
        # the sheet starts at the lower reference's outer (bottom) face and ends
        # at the upper reference's outer (top) face, including both Cu thicknesses.
        z0 = lower_origin
        z1 = f"({upper_origin})+{height_variable(upper_reference)}"
    return z0, z1


def _references_for_port(ground_objects: list[object], port_sheet: object) -> list[str]:
    port_box = port_sheet.bounding_box
    tolerance = 1e-9
    references = []
    for ground in ground_objects:
        box = ground.bounding_box
        x_overlap = box[0] <= port_box[3] + tolerance and box[3] >= port_box[0] - tolerance
        z_overlap = box[2] <= port_box[5] + tolerance and box[5] >= port_box[2] - tolerance
        if x_overlap and z_overlap:
            references.append(ground.name)
    if not references:
        raise RuntimeError("No ground conductors intersect the selected port range.")
    return references


def _length_to_mil(value: str, field_name: str) -> float:
    """Convert a simple GUI length value to mil for via-count calculation.

    AEDT variables are intentionally retained in the created geometry.  The count
    of individual via cylinders, however, has to be known before geometry is made.
    Therefore return-via settings accept a plain number followed by mil, mm, um,
    or inch (for example ``100mil`` or ``2.54mm``).
    """
    match = re.fullmatch(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(mil|mm|um|µm|in)\s*", value, re.IGNORECASE)
    if not match:
        raise ValueError(f"{field_name} must be a simple length with unit (mil, mm, um, or in).")
    magnitude = float(match.group(1))
    unit = match.group(2).lower()
    factors = {"mil": 1.0, "mm": 1000.0 / 25.4, "um": 1.0 / 25.4, "µm": 1.0 / 25.4, "in": 1000.0}
    return magnitude * factors[unit]


def _create_return_vias(
    hfss: Hfss,
    config: StackupConfig,
    z0: str,
    z1: str,
) -> list[object]:
    """Create two rows of through return vias beside the differential pair.

    The signal-layer ground clearance edge is at ``S/2 + W + G`` from the board
    centre.  Each via row is placed a further configurable distance into the
    surrounding ground, so the vias never enter the pair or its CPWG gap.
    """
    if not config.return_vias_enabled:
        return []

    board_length = _length_to_mil(config.board_length, "Board length")
    edge_offset = _length_to_mil(config.return_via_ground_edge_offset, "Return-via ground-edge offset")
    pitch = _length_to_mil(config.return_via_pitch, "Return-via pitch")
    diameter = _length_to_mil(config.return_via_diameter, "Return-via diameter")
    if diameter <= 0 or edge_offset < 0 or pitch <= 0:
        raise ValueError("Return-via diameter and pitch must be positive; edge offset cannot be negative.")
    if board_length < 2 * edge_offset:
        raise ValueError("Board length is too short for the selected return-via edge offset.")

    count = floor((board_length - 2 * edge_offset) / pitch) + 1
    modeler = hfss.modeler
    vias: list[object] = []
    for side, x_center in (
        ("P", "BOARD_WIDTH/2+S_LINE/2+W_LINE+G_LINE+RETURN_VIA_EDGE_OFFSET"),
        ("N", "BOARD_WIDTH/2-S_LINE/2-W_LINE-G_LINE-RETURN_VIA_EDGE_OFFSET"),
    ):
        for index in range(count):
            y_center = f"RETURN_VIA_EDGE_OFFSET+{index}*RETURN_VIA_PITCH"
            via = modeler.create_cylinder(
                "Z",
                [x_center, y_center, z0],
                "RETURN_VIA_DIAMETER/2",
                f"({z1})-({z0})",
                name=f"GND_VIA_{side}_{index + 1:03d}",
                material="copper",
            )
            _set_object_color(via, RETURN_VIA_COLOR)
            vias.append(via)
    return vias


def _subtract_skipped_reference_clearances(
    hfss: Hfss,
    config: StackupConfig,
    signal: Layer,
    upper_reference: Layer | None,
    lower_reference: Layer | None,
    records: list[dict[str, object]],
) -> None:
    """Open the differential trace channel on copper skipped by either reference."""
    signal_index = config.layers.index(signal)
    upper_index = config.layers.index(upper_reference) if upper_reference else signal_index
    lower_index = config.layers.index(lower_reference) if lower_reference else signal_index
    for record in records:
        record_index = int(record["config_index"])
        if not (
            upper_index < record_index < signal_index
            or signal_index < record_index < lower_index
        ):
            continue
        layer = record["layer"]
        tool = hfss.modeler.create_box(
            [
                "BOARD_WIDTH/2-(S_LINE/2+W_LINE+G_LINE)",
                "0mil",
                record["z_origin"],
            ],
            [
                "S_LINE+2*W_LINE+2*G_LINE",
                "BOARD_LENGTH",
                height_variable(layer),
            ],
            name=f"SKIPPED_REF_{_identifier(layer.name)}_TRACE_CLEARANCE",
            material="vacuum",
        )
        if not tool or not hfss.modeler.subtract(
            record["ground"], tool, keep_originals=False
        ):
            raise RuntimeError(
                f"Unable to create skipped-reference clearance on {layer.name}."
            )


def create_stackup_tdr_report(hfss: Hfss) -> str:
    """Create one differential TDR report after Sweep has solved; never start a solve."""
    import csv
    import math
    from tempfile import TemporaryDirectory

    setup = hfss.get_setup("Setup1")
    sweep = next((item for item in setup.sweeps if item.name == "Sweep"), None)
    if sweep is None:
        raise ValueError("Setup1 : Sweep is missing; generate with both Setup and Sweep enabled.")
    try:
        solved = bool(sweep.is_solved)
    except (IndexError, KeyError, RuntimeError, TypeError, ValueError):
        solved = False
    if not solved:
        raise ValueError("Setup1 : Sweep is not solved. Solve it in AEDT before creating TDRZt(Diff1).")
    name = "Auto TDR Diff1"
    def has_valid_data() -> bool:
        # A successful AEDT CreateReport call can still produce an all-NaN plot.
        with TemporaryDirectory(prefix="stackup_diff1_tdr_") as directory:
            csv_path = hfss.post.export_report_to_csv(directory, name)
            if not csv_path or not Path(csv_path).is_file():
                return False
            with open(csv_path, newline="", encoding="utf-8-sig") as stream:
                reader = csv.DictReader(stream)
                time_column = next((key for key in reader.fieldnames or () if key.startswith("Time [")), None)
                impedance_column = next((key for key in reader.fieldnames or () if key.startswith("TDRZt(Diff1) [")), None)
                if not time_column or not impedance_column:
                    return False
                rows = list(reader)
                if len(rows) != 501:
                    return False
                try:
                    times = [float(row[time_column]) for row in rows]
                    impedances = [float(row[impedance_column]) for row in rows]
                except (KeyError, TypeError, ValueError):
                    return False
                time_scale = 1 if time_column == "Time [ps]" else 1e12 if time_column == "Time [s]" else None
                return bool(time_scale and abs(times[0] * time_scale) < 0.01
                            and abs(times[-1] * time_scale - 400) < 0.01
                            and all(math.isfinite(value) for value in impedances))

    existing = name in list(hfss.oreportsetup.GetAllReportNames())
    if existing and has_valid_data():
        return name
    if existing:
        hfss.oreportsetup.DeleteReports([name])

    # AEDT 2025 R2 needs Diff before Domain to preserve both mixed-mode and
    # time settings. PyAEDT 1.4's differential_pairs context drops the time
    # controls, while its Time context drops the differential-pair selection.
    context = [
        "Diff:=", "Differential Pairs", "Domain:=", "Time",
        "HoldTime:=", 1, "RiseTime:=", 1e-11,
        "StepTime:=", 8e-13, "Step:=", True,
        "WindowWidth:=", 1, "WindowType:=", 4,
        "KaiserParameter:=", 1, "MaximumTime:=", 4e-10,
    ]
    hfss.oreportsetup.CreateReport(
        name, "Terminal Solution Data", "Rectangular Plot", "Setup1 : Sweep",
        context, ["Time:=", ["All"]],
        ["X Component:=", "Time", "Y Component:=", ["TDRZt(Diff1)"]],
    )
    if name not in list(hfss.oreportsetup.GetAllReportNames()) or not has_valid_data():
        if name in list(hfss.oreportsetup.GetAllReportNames()):
            hfss.oreportsetup.DeleteReports([name])
        raise RuntimeError("AEDT did not produce finite 0–400 ps TDRZt(Diff1) data.")
    hfss.save_project()
    return name


def build_aedt_project(
    config: StackupConfig,
    project_path: str | Path,
    keep_desktop_open: bool = True,
    log_callback: LogCallback = None,
) -> Path:
    """Create an AEDT project from a GUI/JSON stackup configuration."""
    signal = _validate(config)
    if config.create_tdr_report and not (config.create_setup and config.create_sweep):
        raise ValueError("TDR report requires both Setup1 and Sweep.")
    upper_reference, lower_reference = _resolve_reference_layers(
        config,
        signal,
        config.upper_reference_layer_name,
        config.lower_reference_layer_name,
    )
    material_mapping = layer_material_groups(config)
    project_path = Path(project_path)
    if project_path.exists():
        raise FileExistsError(f"Project already exists: {project_path}")

    _emit(log_callback, "Starting AEDT...")
    desktop = None
    try:
        aedt_version = config.aedt_version.strip() or None
        version_label = aedt_version or "automatic (active/latest installed AEDT)"
        _emit(log_callback, f"AEDT version: {version_label}")
        desktop = Desktop(
            version=aedt_version,
            non_graphical=False,
            new_desktop=False,
            close_on_exit=False,
        )
        if keep_desktop_open:
            _OPEN_DESKTOPS.append(desktop)
        hfss = Hfss(
            project=str(project_path),
            design=config.design_name,
            solution_type="Terminal",
            version=aedt_version,
            new_desktop=False,
            close_on_exit=False,
            aedt_process_id=desktop.aedt_process_id,
        )
        _emit(log_callback, f"Creating design: {config.design_name}")

        bottom_up = list(reversed(config.layers))
        hfss["W_LINE"] = config.w_line
        hfss["S_LINE"] = config.s_line
        hfss["G_LINE"] = config.g_line
        hfss["DIFFERENTIAL_IMPEDANCE"] = str(config.differential_impedance)
        hfss["COMMON_IMPEDANCE"] = str(config.common_impedance)
        hfss["BOARD_LENGTH"] = config.board_length
        hfss["BOARD_MARGIN_X"] = config.board_margin_x
        hfss["PORT_X"] = "6*G_LINE+4*W_LINE+S_LINE"
        hfss["BOARD_WIDTH"] = "PORT_X+2*BOARD_MARGIN_X"
        hfss["RETURN_VIA_DIAMETER"] = config.return_via_diameter
        hfss["RETURN_VIA_EDGE_OFFSET"] = config.return_via_ground_edge_offset
        hfss["RETURN_VIA_PITCH"] = config.return_via_pitch
        copper = [layer for layer in config.layers if layer.kind == "copper"]
        hfss["UPPER_REFERENCE_LAYER"] = (
            str(copper.index(upper_reference) + 1) if upper_reference else "0"
        )
        hfss["LOWER_REFERENCE_LAYER"] = (
            str(copper.index(lower_reference) + 1) if lower_reference else "0"
        )
        for layer in config.layers:
            hfss[height_variable(layer)] = layer.thickness
        hfss["BOARD_THICKNESS"] = _sum_expression([height_variable(layer) for layer in bottom_up])

        _create_materials(hfss, config, material_mapping)
        modeler = hfss.modeler
        modeler.model_units = "mil"
        colors = copper_layer_colors(config)
        ground_by_layer: dict[str, object] = {}
        records: list[dict[str, object]] = []
        z_origin = "0mil"
        for layer in bottom_up:
            if layer.kind in {"pp", "core"}:
                dielectric = modeler.create_box(
                    ["0mil", "0mil", z_origin],
                    ["BOARD_WIDTH", "BOARD_LENGTH", height_variable(layer)],
                    name=_identifier(layer.name),
                    material=material_mapping[layer.name],
                )
                dielectric.display_wireframe = True
            elif layer.role == "signal":
                signal_objects = _create_signal_copper(hfss, layer, z_origin)
                layer_color = colors[layer.name]
                for copper_object in signal_objects.values():
                    if copper_object:
                        _set_object_color(copper_object, layer_color)
                ground_by_layer[layer.name] = signal_objects["ground"]
                records.append({
                    "layer": layer,
                    "ground": signal_objects["ground"],
                    "z_origin": z_origin,
                    "config_index": config.layers.index(layer),
                })
            else:
                ground = modeler.create_box(
                    ["0mil", "0mil", z_origin],
                    ["BOARD_WIDTH", "BOARD_LENGTH", height_variable(layer)],
                    name=f"GND_{_identifier(layer.name)}",
                    material="copper",
                )
                _set_object_color(ground, colors[layer.name])
                ground_by_layer[layer.name] = ground
                records.append({
                    "layer": layer,
                    "ground": ground,
                    "z_origin": z_origin,
                    "config_index": config.layers.index(layer),
                })
            z_origin = f"({z_origin})+{height_variable(layer)}"

        _subtract_skipped_reference_clearances(
            hfss, config, signal, upper_reference, lower_reference, records
        )
        return_z0, return_z1 = _reference_span_expressions(
            signal, upper_reference, lower_reference, bottom_up
        )
        hfss["UPPER_REF_Z"] = return_z1
        hfss["LOWER_REF_Z"] = return_z0
        return_vias = _create_return_vias(hfss, config, return_z0, return_z1)
        if return_vias:
            _emit(log_callback, f"Creating {len(return_vias)} through return vias (two rows).")
            # Keep vias as independent solids.  Uniting every reference plane
            # would collapse their per-layer display colours into one object.

        z0, z1 = _port_expressions(
            config, signal, upper_reference, lower_reference, bottom_up
        )
        hfss["PORT_Z0"] = z0
        hfss["PORT_Z1"] = z1
        hfss["PORT_Z"] = "PORT_Z1-PORT_Z0"
        port_x_start = "BOARD_WIDTH/2-PORT_X/2"
        port_w1 = modeler.create_rectangle(
            "XZ", [port_x_start, "0mil", "PORT_Z0"], ["PORT_Z", "PORT_X"], name="PortSheet_W1"
        )
        port_w2 = modeler.create_rectangle(
            "XZ", [port_x_start, "BOARD_LENGTH", "PORT_Z0"], ["PORT_Z", "PORT_X"], name="PortSheet_W2"
        )
        references = _port_reference_conductors(
            config, signal, upper_reference, lower_reference, ground_by_layer
        )
        _emit(log_callback, f"Assigning ports with references: {', '.join(references)}")
        for name, sheet in (("w1", port_w1), ("w2", port_w2)):
            port = hfss.wave_port(
                sheet,
                reference=references,
                create_port_sheet=False,
                modes=1,
                impedance=50,
                name=name,
                deembed=config.port_deembed_distance,
                terminals_rename=True,
            )
            if not port:
                raise RuntimeError(f"Unable to assign wave port {name}.")
            expected = hfss.value_with_units(config.port_deembed_distance)
            if port.props.get("DoDeembed") is not True or port.props.get("DeembedDist") != expected:
                raise RuntimeError(f"Wave port {name} did not retain deembed distance {expected}.")

        for index in (1, 2):
            if not hfss.set_differential_pair(
                assignment=f"w{index}_T1",
                reference=f"w{index}_T2",
                common_mode=f"Comm{index}",
                differential_mode=f"Diff{index}",
                common_reference=config.common_impedance,
                differential_reference=config.differential_impedance,
                active=True,
                matched=False,
            ):
                raise RuntimeError(f"Unable to create differential pair w{index}.")

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

        if config.create_tdr_report:
            _emit(log_callback, "TDRZt(Diff1) is configured for post-solve creation. "
                  "AEDT 2025 R2 does not preserve Time Domain settings in unsolved reports; "
                  "use the GUI's post-solve TDR button after manually solving Sweep.")

        set_copper_transparency(hfss)
        if not hfss.save_project(project_path, overwrite=False):
            raise RuntimeError(f"Unable to save project: {project_path}")
        hfss.modeler.fit_all()
        _emit(log_callback, f"Project created: {project_path}")
        return project_path
    finally:
        if desktop and not keep_desktop_open:
            desktop.release_desktop(close_projects=False, close_on_exit=False)
