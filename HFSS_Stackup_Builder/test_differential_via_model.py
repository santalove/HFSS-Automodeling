"""AEDT-free structural tests for :mod:`differential_via_model`."""

from __future__ import annotations

from math import hypot
from pathlib import Path
import unittest
from unittest.mock import patch

import differential_via_model as via_model
from hfss_stackup_builder import eight_layer_example


class _Object:
    def __init__(self, name: str, bounding_box=None):
        self.name = name
        self.bounding_box = bounding_box or [-3.0, 0.0, 0.0, 3.0, 5.0, 10.0]
        self.display_wireframe = False
        self.color = None


class _Material:
    def __init__(self):
        self.permittivity = None
        self.dielectric_loss_tangent = None

    def update(self):
        return True


class _Materials(dict):
    def add_material(self, name):
        material = _Material()
        self[name] = material
        return material


class _Modeler:
    def __init__(self):
        self.model_units = None
        self.created = []
        self.box_args = {}
        self.cylinder_args = {}
        self.polyline_args = {}
        self.rectangle_args = {}
        self.subtractions = []
        self.unions = []

    def _add(self, name, bounding_box=None):
        self.created.append(name)
        return _Object(name, bounding_box)

    def create_box(self, origin, sizes, name, material):
        self.box_args[name] = (origin, sizes, material)
        return self._add(name)

    def create_cylinder(self, axis, origin, radius, height, name, material):
        self.cylinder_args[name] = (axis, origin, radius, height, material)
        return self._add(name)

    def create_polyline(self, points, cover_surface, close_surface, name, material):
        self.polyline_args[name] = (points, cover_surface, close_surface, material)
        return self._add(name)

    def sweep_along_vector(self, assignment, vector):
        return assignment

    def create_rectangle(self, plane, origin, sizes, name):
        self.rectangle_args[name] = (plane, origin, sizes)
        x = -3.0 if name.startswith("START") else 3.0
        return self._add(name, [x, 0.0, 0.0, x, 5.0, 10.0])

    def subtract(self, blank, tool, keep_originals=False):
        blank_name = blank.name if hasattr(blank, "name") else str(blank)
        tool_name = tool.name if hasattr(tool, "name") else str(tool)
        self.subtractions.append((blank_name, tool_name))
        return True

    def unite(self, assignments):
        self.unions.append(list(assignments))
        return True

    def fit_all(self):
        return True


class _Hfss:
    def __init__(self):
        self.variables = {}
        self.variable_order = []
        self.modeler = _Modeler()
        self.materials = _Materials()
        self.wave_ports = []
        self.pairs = []

    def __setitem__(self, key, value):
        self.variables[key] = value
        self.variable_order.append(key)

    def __getitem__(self, key):
        return self.variables[key]

    def wave_port(self, sheet, **kwargs):
        self.wave_ports.append((sheet.name, kwargs))
        return True

    def set_differential_pair(self, **kwargs):
        self.pairs.append(kwargs)
        return True


class DifferentialViaModelTests(unittest.TestCase):
    def setUp(self):
        self.stackup = eight_layer_example()
        self.config = via_model.DifferentialViaConfig()

    def _build(self, config=None):
        hfss = _Hfss()
        via_model._build_geometry(hfss, self.stackup, config or self.config)
        return hfss

    def test_default_l2_to_l4_structure(self):
        hfss = self._build()
        names = set(hfss.modeler.created)
        self.assertTrue({
            "SIG_VIA_P_LASER_L2_L3_COLUMN", "SIG_VIA_P_LASER_L3_L4_COLUMN",
            "SIG_VIA_N_LASER_L2_L3_COLUMN", "SIG_VIA_N_LASER_L3_L4_COLUMN",
        } <= names)
        self.assertTrue({
            "START_VIA_P_PAD", "START_VIA_N_PAD", "END_VIA_P_PAD", "END_VIA_N_PAD",
            "START_TRACE_P", "START_TRACE_N", "END_TRACE_P", "END_TRACE_N",
            "START_FANOUT_P", "START_FANOUT_N", "END_FANOUT_P", "END_FANOUT_N",
            "SIG_VIA_P_L3_LASER_PAD", "SIG_VIA_N_L3_LASER_PAD",
        } <= names)
        self.assertFalse(any(name.endswith("_DRILL") for name in names))
        signal_unions = [
            union for union in hfss.modeler.unions
            if any("_TRACE_" in name for name in union)
        ]
        self.assertEqual(4, len(signal_unions))
        self.assertEqual(
            ["START_TRACE_P", "START_FANOUT_P", "START_VIA_P_PAD"],
            signal_unions[0],
        )
        self.assertEqual(
            ["END_TRACE_P", "END_FANOUT_P", "END_VIA_P_PAD"],
            signal_unions[1],
        )
        self.assertFalse(any(
            name.endswith("_COLUMN") for union in signal_unions for name in union
        ))

        slot_antipads = {
            "L2_SIG_SLOT_ANTIPAD", "L3_SIG_SLOT_ANTIPAD", "L4_SIG_SLOT_ANTIPAD",
        }
        self.assertTrue(slot_antipads <= names)
        self.assertTrue({
            ("GND_L2", "L2_SIG_SLOT_ANTIPAD"),
            ("GND_L3", "L3_SIG_SLOT_ANTIPAD"),
            ("GND_L4", "L4_SIG_SLOT_ANTIPAD"),
        } <= set(hfss.modeler.subtractions))
        for layer in ("L2", "L3", "L4"):
            prefix = f"{layer}_SIG_SLOT_ANTIPAD"
            self.assertEqual(
                f"VIA_ANTIPAD_RADIUS_{layer}",
                hfss.modeler.cylinder_args[prefix][2],
            )
            self.assertEqual(
                f"VIA_ANTIPAD_RADIUS_{layer}",
                hfss.modeler.cylinder_args[f"{prefix}_N_CIRCLE"][2],
            )
            z_origin = hfss.modeler.box_args[f"GND_{layer}"][0][2]
            self.assertEqual(
                ([f"-VIA_ANTIPAD_X_{layer}", "BOARD_CENTER_Y-D_VIA/2", z_origin],
                 [f"VIA_ANTIPAD_X_{layer}", "D_VIA", f"{layer}_H"], "vacuum"),
                hfss.modeler.box_args[f"{prefix}_NECK_NEG_X"],
            )
            self.assertEqual(
                (["0mm", "BOARD_CENTER_Y-D_VIA/2", z_origin],
                 [f"VIA_ANTIPAD_X_{layer}", "D_VIA", f"{layer}_H"], "vacuum"),
                hfss.modeler.box_args[f"{prefix}_NECK_POS_X"],
            )
            self.assertIn(
                [prefix, f"{prefix}_N_CIRCLE", f"{prefix}_NECK_NEG_X",
                 f"{prefix}_NECK_POS_X"],
                hfss.modeler.unions,
            )
        local_returns = {name for name in names if name.startswith("LOCAL_RETURN_VIA_")}
        # Five former candidates overlap the two fanout-clearance polygons.
        self.assertEqual(8, len(local_returns))
        self.assertIn("START_RETURN_VIA_L_012_COLUMN", names)
        self.assertIn("END_RETURN_VIA_R_012_COLUMN", names)

        self.assertEqual(2, len(hfss.wave_ports))
        self.assertEqual({"START_WAVE_PORT_SHEET", "END_WAVE_PORT_SHEET"}, {
            item[0] for item in hfss.wave_ports
        })
        self.assertEqual({"Diff1", "Diff2"}, {pair["differential_mode"] for pair in hfss.pairs})
        self.assertTrue(hfss.variables["START_PORT_Z1"].endswith("+L1_H"))
        self.assertTrue(hfss.variables["END_PORT_Z1"].endswith("+L3_H"))
        self.assertEqual("START_PORT_Z1-START_PORT_Z0", hfss.variables["START_PORT_Z"])
        self.assertEqual("END_PORT_Z1-END_PORT_Z0", hfss.variables["END_PORT_Z"])
        self.assertEqual("10mil", hfss.variables["VIA_ANTIPAD_X"])
        for layer in ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"):
            self.assertEqual("10mil", hfss.variables[f"VIA_ANTIPAD_RADIUS_{layer}"])
            self.assertEqual("10mil", hfss.variables[f"VIA_ANTIPAD_X_{layer}"])

    def test_l1_to_l4_uses_surface_and_internal_ports(self):
        config = via_model.DifferentialViaConfig(
            route_layers=["L1", "L4"],
            start_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="", lower_reference_layer_name="L2",
            ),
        )
        hfss = self._build(config)
        self.assertTrue(
            hfss.variables["START_PORT_Z1"].endswith("+L1_H)+8*PP_L1_H")
        )
        self.assertTrue(hfss.variables["END_PORT_Z1"].endswith("+L3_H"))
        self.assertIn("L1_SIG_SLOT_ANTIPAD", hfss.modeler.created)
        self.assertIn("L4_SIG_SLOT_ANTIPAD", hfss.modeler.created)

    def test_l8_surface_port_uses_inward_reference_and_eight_pp_height(self):
        config = via_model.DifferentialViaConfig(
            route_layers=["L2", "L8"],
            end_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L7", lower_reference_layer_name="",
            ),
        )
        hfss = self._build(config)
        self.assertEqual(
            f"({hfss.variables['END_PORT_Z1']})-8*PP_L7_H",
            hfss.variables["END_PORT_Z0"],
        )

    def test_port_references_are_filtered_by_actual_x_and_z_intersection(self):
        sheet = _Object("PORT", [0.0, -1.0, 2.0, 0.0, 1.0, 4.0])
        grounds = [
            _Object("GND_MATCH", [-1.0, -2.0, 3.0, 1.0, 2.0, 3.1]),
            _Object("GND_WRONG_X", [2.0, -2.0, 3.0, 3.0, 2.0, 3.1]),
            _Object("GND_WRONG_Z", [-1.0, -2.0, 7.0, 1.0, 2.0, 8.0]),
        ]
        self.assertEqual(["GND_MATCH"], via_model._references_for_port(grounds, sheet))

    def test_stackup_impedance_drives_both_mixed_mode_pairs(self):
        self.stackup.differential_impedance = 100.0
        self.stackup.common_impedance = 31.5
        hfss = self._build()
        self.assertEqual("100.0", hfss.variables["VIA_DIFFERENTIAL_IMPEDANCE"])
        self.assertEqual("31.5", hfss.variables["VIA_COMMON_IMPEDANCE"])
        for pair in hfss.pairs:
            self.assertEqual(100.0, pair["differential_reference"])
            self.assertEqual(31.5, pair["common_reference"])

    def test_reverse_route_keeps_physical_column_span(self):
        forward = self._build(via_model.DifferentialViaConfig(route_layers=["L2", "L4"]))
        reverse = self._build(via_model.DifferentialViaConfig(
            route_layers=["L4", "L2"],
            start_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L3", lower_reference_layer_name="L5",
            ),
            end_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L1", lower_reference_layer_name="L3",
            ),
        ))
        forward_columns = sorted(
            args[1:4] for name, args in forward.modeler.cylinder_args.items()
            if name.startswith("SIG_VIA_P_LASER_") and name.endswith("_COLUMN")
        )
        reverse_columns = sorted(
            args[1:4] for name, args in reverse.modeler.cylinder_args.items()
            if name.startswith("SIG_VIA_P_LASER_") and name.endswith("_COLUMN")
        )
        self.assertEqual(forward_columns, reverse_columns)
        self.assertEqual("START_W_LINE", forward.modeler.box_args["START_TRACE_P"][1][1])
        self.assertEqual("START_W_LINE", reverse.modeler.box_args["START_TRACE_P"][1][1])

    def test_mixed_laser_mechanical_laser_topology(self):
        config = via_model.DifferentialViaConfig(
            route_layers=["L2", "L7"],
            end_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L6", lower_reference_layer_name="L8",
            ),
            mechanical_via_enabled=True,
            mechanical_start_layer="L3",
        )
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        for side in ("P", "N"):
            self.assertTrue({
                f"SIG_VIA_{side}_LASER_L2_L3_COLUMN",
                f"SIG_VIA_{side}_MECHANICAL_L3_L6_COLUMN",
                f"SIG_VIA_{side}_LASER_L6_L7_COLUMN",
                f"START_VIA_{side}_PAD",
                f"SIG_VIA_{side}_L3_MECHANICAL_PAD",
                f"SIG_VIA_{side}_L6_MECHANICAL_PAD",
                f"END_VIA_{side}_PAD",
            } <= names)
            self.assertFalse(any(
                name.startswith(f"SIG_VIA_{side}_L4_")
                or name.startswith(f"SIG_VIA_{side}_L5_")
                for name in names
            ))
            self.assertEqual(
                "MECHANICAL_VIA_COLUMN_RADIUS",
                hfss.modeler.cylinder_args[
                    f"SIG_VIA_{side}_MECHANICAL_L3_L6_COLUMN"
                ][2],
            )
            self.assertEqual(
                "MECHANICAL_VIA_PAD_RADIUS",
                hfss.modeler.cylinder_args[f"SIG_VIA_{side}_L3_MECHANICAL_PAD"][2],
            )
        self.assertEqual("3mil", hfss.variables["MECHANICAL_VIA_COLUMN_RADIUS"])
        self.assertEqual("6mil", hfss.variables["MECHANICAL_VIA_PAD_RADIUS"])
        signal_unions = [
            union for union in hfss.modeler.unions
            if any("_TRACE_" in name for name in union)
        ]
        self.assertFalse(any(
            "COLUMN" in name or "MECHANICAL" in name
            for union in signal_unions for name in union
        ))

    def test_selectable_mechanical_end_supports_multiple_final_lasers(self):
        config = via_model.DifferentialViaConfig(
            route_layers=["L2", "L8"],
            end_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L7", lower_reference_layer_name="",
            ),
            mechanical_via_enabled=True,
            mechanical_start_layer="L3",
            mechanical_end_layer="L5",
        )
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        for side in ("P", "N"):
            self.assertTrue({
                f"SIG_VIA_{side}_MECHANICAL_L3_L5_COLUMN",
                f"SIG_VIA_{side}_LASER_L5_L6_COLUMN",
                f"SIG_VIA_{side}_LASER_L6_L7_COLUMN",
                f"SIG_VIA_{side}_LASER_L7_L8_COLUMN",
            } <= names)

    def test_mechanical_end_can_be_the_end_route_layer(self):
        config = via_model.DifferentialViaConfig(
            route_layers=["L2", "L7"],
            end_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L6", lower_reference_layer_name="L8",
            ),
            mechanical_via_enabled=True,
            mechanical_start_layer="L3",
            mechanical_end_layer="L7",
        )
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        self.assertIn("SIG_VIA_P_MECHANICAL_L3_L7_COLUMN", names)
        self.assertFalse(any(
            name.startswith("SIG_VIA_P_LASER_L3_")
            or name.startswith("SIG_VIA_P_LASER_L4_")
            or name.startswith("SIG_VIA_P_LASER_L5_")
            or name.startswith("SIG_VIA_P_LASER_L6_")
            for name in names
        ))

    def test_all_laser_stack_has_pad_on_every_copper_layer(self):
        config = via_model.DifferentialViaConfig(
            route_layers=["L1", "L6"],
            start_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="", lower_reference_layer_name="L2",
            ),
            end_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L5", lower_reference_layer_name="L7",
            ),
        )
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        for side in ("P", "N"):
            columns = {
                name for name in names
                if name.startswith(f"SIG_VIA_{side}_LASER_") and name.endswith("_COLUMN")
            }
            self.assertEqual(5, len(columns))
            self.assertTrue({
                f"START_VIA_{side}_PAD", f"END_VIA_{side}_PAD",
                f"SIG_VIA_{side}_L2_LASER_PAD", f"SIG_VIA_{side}_L3_LASER_PAD",
                f"SIG_VIA_{side}_L4_LASER_PAD", f"SIG_VIA_{side}_L5_LASER_PAD",
            } <= names)

    def test_reverse_mixed_stack_preserves_electrical_direction(self):
        config = via_model.DifferentialViaConfig(
            route_layers=["L7", "L2"], mechanical_via_enabled=True,
            mechanical_start_layer="L6",
            start_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L6", lower_reference_layer_name="L8",
            ),
            end_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L1", lower_reference_layer_name="L3",
            ),
        )
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        self.assertTrue({
            "SIG_VIA_P_LASER_L7_L6_COLUMN",
            "SIG_VIA_P_MECHANICAL_L6_L3_COLUMN",
            "SIG_VIA_P_LASER_L3_L2_COLUMN",
        } <= names)
        self.assertFalse(any(
            name.startswith("SIG_VIA_P_L4_") or name.startswith("SIG_VIA_P_L5_")
            for name in names
        ))

    def test_per_layer_antipad_overrides_drive_each_copper(self):
        config = via_model.DifferentialViaConfig(
            layer_antipads={
                "L2": {"radius": "11mil", "x": "8mil"},
                "L3": {"radius": "12mil", "x": "9mil"},
                "L4": {"radius": "13mil", "x": "10mil"},
            }
        )
        hfss = self._build(config)
        for layer, radius, x_value in (
            ("L2", "11mil", "8mil"),
            ("L3", "12mil", "9mil"),
            ("L4", "13mil", "10mil"),
        ):
            self.assertEqual(radius, hfss.variables[f"VIA_ANTIPAD_RADIUS_{layer}"])
            self.assertEqual(x_value, hfss.variables[f"VIA_ANTIPAD_X_{layer}"])
            self.assertEqual(
                f"VIA_ANTIPAD_RADIUS_{layer}",
                hfss.modeler.cylinder_args[f"{layer}_SIG_SLOT_ANTIPAD"][2],
            )
            self.assertEqual(
                f"VIA_ANTIPAD_X_{layer}",
                hfss.modeler.box_args[f"{layer}_SIG_SLOT_ANTIPAD_NECK_POS_X"][1][0],
            )

    def test_config_round_trip_preserves_mechanical_and_layer_antipads(self):
        config = via_model.DifferentialViaConfig(
            route_layers=["L2", "L7"], mechanical_via_enabled=True,
            mechanical_start_layer="L3", mechanical_end_layer="L5",
            mechanical_column_radius="3mil",
            mechanical_pad_radius="6mil",
            layer_antipads={"L4": {"radius": "12mil", "x": "9mil"}},
        )
        restored = via_model.DifferentialViaConfig.from_dict(config.to_dict())
        self.assertTrue(restored.mechanical_via_enabled)
        self.assertEqual("L3", restored.mechanical_start_layer)
        self.assertEqual("L5", restored.mechanical_end_layer)
        self.assertEqual("3mil", restored.mechanical_column_radius)
        self.assertEqual("6mil", restored.mechanical_pad_radius)
        self.assertEqual(
            {"radius": "12mil", "x": "9mil"}, restored.layer_antipads["L4"]
        )
        self.assertEqual("L1", restored.start_line.upper_reference_layer_name)
        self.assertEqual("L3", restored.start_line.lower_reference_layer_name)
        self.assertEqual("L3", restored.end_line.upper_reference_layer_name)
        self.assertEqual("L5", restored.end_line.lower_reference_layer_name)

    def test_separated_end_reference_controls_clearance_port_and_return_span(self):
        config = via_model.DifferentialViaConfig(
            end_line=via_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L3",
                lower_reference_layer_name="L8",
            ),
        )
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        for layer in ("L5", "L6", "L7"):
            prefix = f"END_SKIPPED_REF_{layer}"
            self.assertIn(f"{prefix}_TRACE_CLEARANCE", names)
            self.assertIn(f"{prefix}_FANOUT_CLEARANCE", names)
            self.assertIn(f"{prefix}_FANOUT_CLEARANCE_MIRROR", names)
            self.assertIn(
                f"VIA_ANTIPAD_RADIUS_{layer}",
                hfss.modeler.polyline_args[f"{prefix}_FANOUT_CLEARANCE"][0][2][1],
            )
        self.assertFalse(any(name.startswith("END_SKIPPED_REF_L8_") for name in names))
        self.assertEqual("8", hfss.variables["END_LOWER_REFERENCE_LAYER"])
        self.assertEqual(
            ["GND_L8", "GND_L7", "GND_L6", "GND_L5", "GND_L4", "GND_L3"],
            hfss.wave_ports[1][1]["reference"],
        )
        end_return = hfss.modeler.cylinder_args["END_RETURN_VIA_L_001_COLUMN"]
        self.assertEqual(hfss.variables["END_LOWER_REF_Z"], end_return[1][2])
        self.assertEqual(
            f"({hfss.variables['END_UPPER_REF_Z']})-({hfss.variables['END_LOWER_REF_Z']})",
            end_return[3],
        )

    def test_line_references_are_explicit_and_must_bracket_route(self):
        cases = (
            (
                via_model.DifferentialViaConfig.from_dict({
                    "route_layers": ["L2", "L4"],
                    "start_line": {"w_line": "100um"},
                }),
                "start upper reference.*explicitly selected",
            ),
            (
                via_model.DifferentialViaConfig(
                    start_line=via_model.DifferentialLineEndConfig(
                        upper_reference_layer_name="PP_L1",
                        lower_reference_layer_name="L3",
                    ),
                ),
                "must be a copper layer",
            ),
            (
                via_model.DifferentialViaConfig(
                    start_line=via_model.DifferentialLineEndConfig(
                        upper_reference_layer_name="L3",
                        lower_reference_layer_name="L4",
                    ),
                ),
                "must be above route layer L2",
            ),
        )
        for config, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    via_model._validate_config(self.stackup, config)

    def test_independent_end_dimensions_drive_geometry(self):
        config = via_model.DifferentialViaConfig(
            start_line=via_model.DifferentialLineEndConfig(
                trace_length="1.2mm", fanout_length="0.4mm",
                w_line="80um", s_line="90um", g_line="30um",
                upper_reference_layer_name="L1", lower_reference_layer_name="L3",
            ),
            end_line=via_model.DifferentialLineEndConfig(
                trace_length="2mm", fanout_length="0.7mm",
                w_line="130um", s_line="160um", g_line="60um",
                upper_reference_layer_name="L3", lower_reference_layer_name="L5",
            ),
        )
        hfss = self._build(config)
        self.assertEqual("80um", hfss.variables["START_W_LINE"])
        self.assertEqual("130um", hfss.variables["END_W_LINE"])
        self.assertIn("START_W_LINE", str(hfss.modeler.polyline_args["START_FANOUT_P"][0]))
        self.assertIn("END_W_LINE", str(hfss.modeler.polyline_args["END_FANOUT_P"][0]))
        self.assertIn(
            "START_S_LINE/2+START_W_LINE+START_G_LINE",
            hfss.modeler.cylinder_args["START_RETURN_VIA_L_001_COLUMN"][1][1],
        )
        self.assertIn(
            "END_S_LINE/2+END_W_LINE+END_G_LINE",
            hfss.modeler.cylinder_args["END_RETURN_VIA_L_001_COLUMN"][1][1],
        )

    def test_route_layer_fanout_clearance_is_subtracted_on_both_y_sides(self):
        hfss = self._build()
        for prefix, ground in (("START", "GND_L2"), ("END", "GND_L4")):
            layer = ground.removeprefix("GND_")
            positive = f"{prefix}_FANOUT_CLEARANCE"
            negative = f"{prefix}_FANOUT_CLEARANCE_MIRROR"
            self.assertIn(positive, hfss.modeler.polyline_args)
            self.assertIn(negative, hfss.modeler.polyline_args)
            positive_points = hfss.modeler.polyline_args[positive][0]
            negative_points = hfss.modeler.polyline_args[negative][0]
            self.assertEqual("BOARD_CENTER_Y", positive_points[0][1])
            self.assertEqual("BOARD_CENTER_Y", negative_points[0][1])
            self.assertIn("BOARD_CENTER_Y+", positive_points[1][1])
            self.assertIn("BOARD_CENTER_Y-", negative_points[1][1])
            self.assertEqual(
                f"BOARD_CENTER_Y+(D_VIA/2+VIA_ANTIPAD_RADIUS_{layer})",
                positive_points[2][1],
            )
            self.assertEqual(
                f"BOARD_CENTER_Y-(D_VIA/2+VIA_ANTIPAD_RADIUS_{layer})",
                negative_points[2][1],
            )
            self.assertEqual(positive_points[0][0], negative_points[0][0])
            self.assertEqual(positive_points[2][0], negative_points[2][0])
            self.assertIn((ground, positive), hfss.modeler.subtractions)
            self.assertIn((ground, negative), hfss.modeler.subtractions)

    def test_slot_fence_spacing_and_clearance(self):
        d_via = 0.5
        radius = 0.254
        neck_x = 0.254
        return_radius = 0.057
        requested_clearance = 0.0508
        points = via_model._slot_return_points(
            d_via, radius, neck_x, return_radius, requested_clearance, 0.254,
        )
        self.assertEqual(13, len(points))
        neighbor_distances = [
            hypot(
                points[(index + 1) % len(points)][0] - points[index][0],
                points[(index + 1) % len(points)][1] - points[index][1],
            )
            for index in range(len(points))
        ]
        self.assertLessEqual(max(neighbor_distances), 0.254)
        for x, y in points:
            circle_distance = min(
                hypot(x, y - d_via / 2) - radius,
                hypot(x, y + d_via / 2) - radius,
            )
            rectangle_dx = max(abs(x) - neck_x, 0.0)
            rectangle_dy = max(abs(y) - d_via / 2, 0.0)
            rectangle_distance = hypot(rectangle_dx, rectangle_dy)
            edge_distance = min(circle_distance, rectangle_distance)
            clearance = edge_distance - return_radius
            self.assertGreaterEqual(clearance, requested_clearance - 2e-6)

    def test_local_fence_full_columns_avoid_slot_and_route_voids(self):
        start, end, dimensions = via_model._validate_config(self.stackup, self.config)
        candidates = via_model._slot_return_points(
            dimensions["d_via"], dimensions["transition_via_antipad_radius"],
            dimensions["transition_via_antipad_x"], dimensions["return_column_radius"],
            dimensions["local_return_clearance"], dimensions["local_return_pitch"],
        )
        accepted = [
            point for point in candidates
            if via_model._single_stage_return_point_allowed(
                point, dimensions, start.name, end.name
            )
        ]
        self.assertEqual(8, len(accepted))
        self.assertLess(len(accepted), len(candidates))
        self.assertTrue(all(
            via_model._single_stage_return_point_allowed(
                point, dimensions, start.name, end.name
            )
            for point in accepted
        ))

    def test_invalid_routes_and_dimensions_are_rejected(self):
        invalid = (
            (via_model.DifferentialViaConfig(route_layers=["L2"]), "exactly two"),
            (via_model.DifferentialViaConfig(route_layers=["L2", "L2"]), "different"),
            (via_model.DifferentialViaConfig(route_layers=["PP_L2", "L4"]), "copper"),
            (via_model.DifferentialViaConfig(route_layers=["L2", "L4", "L6"]), "exactly two"),
            (via_model.DifferentialViaConfig(via_pad_radius="0.05mm"), "pad_radius"),
            (via_model.DifferentialViaConfig(via_antipad_x="0mm"), "via_antipad_x"),
            (via_model.DifferentialViaConfig(
                route_layers=["L2", "L7"], mechanical_via_enabled=True,
                mechanical_start_layer="L6",
                end_line=via_model.DifferentialLineEndConfig(
                    upper_reference_layer_name="L6", lower_reference_layer_name="L8",
                ),
            ), "mechanical_start_layer"),
            (via_model.DifferentialViaConfig(
                route_layers=["L2", "L7"], mechanical_via_enabled=True,
                mechanical_start_layer="L3", mechanical_pad_radius="2mil",
                end_line=via_model.DifferentialLineEndConfig(
                    upper_reference_layer_name="L6", lower_reference_layer_name="L8",
                ),
            ), "mechanical_pad_radius"),
            (via_model.DifferentialViaConfig(
                layer_antipads={"L2": {"radius": "4mil", "x": "10mil"}},
            ), "via_antipad_radius_L2"),
        )
        for config, message in invalid:
            with self.subTest(config=config):
                with self.assertRaisesRegex(ValueError, message):
                    via_model._validate_config(self.stackup, config)

    def test_coplanar_unite_guard_rejects_via_columns(self):
        modeler = _Modeler()
        with self.assertRaisesRegex(RuntimeError, "VIA columns must remain separate"):
            via_model._unite_coplanar_signal(
                modeler, ["TRACE_P", "SIG_VIA_P_COLUMN"], "test path"
            )
        self.assertEqual([], modeler.unions)

    def test_existing_project_is_not_overwritten(self):
        path = Path("existing.aedt")
        with patch.object(Path, "exists", return_value=True):
            with self.assertRaises(FileExistsError):
                via_model.build_differential_via_project(self.stackup, self.config, path)

    def test_builder_reuses_desktop_by_default_and_detaches_safely(self):
        desktop_calls = []
        hfss_calls = []
        release_calls = []

        class FakeDesktop:
            def __init__(self, **kwargs):
                desktop_calls.append(kwargs)
                self.aedt_process_id = 1234

            def release_desktop(self, **kwargs):
                release_calls.append(kwargs)
                return True

        class FakeHfss(_Hfss):
            def __init__(self, **kwargs):
                super().__init__()
                hfss_calls.append(kwargs)

            def save_project(self, path, overwrite=False):
                return True

        with (
            patch.object(Path, "exists", return_value=False),
            patch.object(via_model, "Desktop", FakeDesktop),
            patch.object(via_model, "Hfss", FakeHfss),
            patch.object(via_model, "_build_geometry"),
            patch.object(via_model, "create_hfss_analysis"),
        ):
            via_model.build_differential_via_project(
                self.stackup, self.config, Path("new.aedt"),
                keep_desktop_open=False,
            )

        self.assertFalse(desktop_calls[0]["new_desktop"])
        self.assertEqual(1234, hfss_calls[0]["aedt_process_id"])
        self.assertEqual(
            [{"close_projects": False, "close_on_exit": False}], release_calls,
        )

    def test_explicit_new_desktop_can_be_closed_without_wrong_keyword(self):
        release_calls = []

        class FakeDesktop:
            def __init__(self, **kwargs):
                self.arguments = kwargs
                self.aedt_process_id = 1234

            def release_desktop(self, **kwargs):
                release_calls.append(kwargs)
                return True

        class FakeHfss(_Hfss):
            def __init__(self, **kwargs):
                super().__init__()

            def save_project(self, path, overwrite=False):
                return True

        with (
            patch.object(Path, "exists", return_value=False),
            patch.object(via_model, "Desktop", FakeDesktop),
            patch.object(via_model, "Hfss", FakeHfss),
            patch.object(via_model, "_build_geometry"),
            patch.object(via_model, "create_hfss_analysis"),
        ):
            via_model.build_differential_via_project(
                self.stackup, self.config, Path("new.aedt"),
                keep_desktop_open=False, new_desktop=True,
            )

        self.assertEqual(
            [{"close_projects": True, "close_on_exit": True}], release_calls,
        )


if __name__ == "__main__":
    unittest.main()
