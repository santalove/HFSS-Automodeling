"""AEDT-free structural tests for :mod:`cap_pad_model`."""

from __future__ import annotations

import unittest

import cap_pad_model as cap_model
from hfss_stackup_builder import eight_layer_example


class _Object:
    def __init__(self, name: str):
        self.name = name
        self.bounding_box = [-20.0, -20.0, -20.0, 20.0, 20.0, 20.0]
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
        self.sweep_args = {}
        self.rectangle_args = {}
        self.subtractions = []
        self.unions = []
        self.coordinate_system_args = {}
        self.inserted_components = []
        self.working_coordinate_system = "Global"

    def _add(self, name):
        self.created.append(name)
        return _Object(name)

    def create_box(self, origin, sizes, name, material):
        self.box_args[name] = (origin, sizes, material)
        return self._add(name)

    def create_cylinder(self, axis, origin, radius, height, name, material):
        self.cylinder_args[name] = (axis, origin, radius, height, material)
        return self._add(name)

    def create_polyline(
        self, points, cover_surface=False, close_surface=False, name=None,
        material=None, segment_type=None,
    ):
        self.polyline_args[name] = (
            points, cover_surface, close_surface, material, segment_type,
        )
        return self._add(name)

    def sweep_along_vector(self, assignment, vector):
        self.sweep_args[assignment.name] = vector
        return assignment

    def create_rectangle(self, plane, origin, sizes, name, material=None):
        self.rectangle_args[name] = (plane, origin, sizes, material)
        return self._add(name)

    def subtract(self, blank, tool, keep_originals=False):
        self.subtractions.append((blank.name, tool.name, keep_originals))
        return True

    def unite(self, assignments):
        self.unions.append(list(assignments))
        return True

    def create_coordinate_system(self, **kwargs):
        self.coordinate_system_args[kwargs["name"]] = kwargs
        self.working_coordinate_system = kwargs["name"]
        return object()

    def set_working_coordinate_system(self, name):
        self.working_coordinate_system = name
        return True

    def insert_3d_component(self, input_file, coordinate_system="Global", name=None):
        self.inserted_components.append((input_file, coordinate_system, name))
        return object()

    def fit_all(self):
        return True


class _Hfss:
    def __init__(self):
        self.variables = {}
        self.modeler = _Modeler()
        self.materials = _Materials()
        self.wave_ports = []
        self.pairs = []
        self.lumped_rlcs = []
        self.axis_directions = type("AxisDirections", (), {"XNeg": 0})

    def __setitem__(self, key, value):
        self.variables[key] = value

    def __getitem__(self, key):
        return self.variables[key]

    def wave_port(self, sheet, **kwargs):
        self.wave_ports.append((sheet.name, kwargs))
        return True

    def set_differential_pair(self, **kwargs):
        self.pairs.append(kwargs)
        return True

    def _create_boundary(self, name, props, boundary_type):
        self.lumped_rlcs.append((name, props, boundary_type))
        return True


class CapPadModelTests(unittest.TestCase):
    def setUp(self):
        self.stackup = eight_layer_example()

    def _build(self, config=None):
        hfss = _Hfss()
        cap_model._build_geometry(hfss, self.stackup, config or cap_model.CapPadConfig())
        return hfss

    def test_default_creates_four_separate_l1_pads_and_two_physical_capacitors(self):
        hfss = self._build()
        names = set(hfss.modeler.created)
        self.assertTrue({
            "CAP_P_LEFT_PAD", "CAP_P_RIGHT_PAD",
            "CAP_N_LEFT_PAD", "CAP_N_RIGHT_PAD",
        } <= names)
        self.assertFalse(hfss.lumped_rlcs)
        self.assertEqual(2, len(hfss.modeler.inserted_components))
        for side, (_, coordinate_system, name) in zip(
            ("P", "N"), hfss.modeler.inserted_components
        ):
            self.assertEqual(f"CAP_{side}_ASSEMBLY_CS", coordinate_system)
            self.assertEqual(f"CAP_{side}_SC04S0J104M_0P1UF", name)
        self.assertEqual(2, len(hfss.wave_ports))
        self.assertEqual(2, len(hfss.pairs))

    def test_ideal_rlc_mode_creates_two_capacitive_sheets(self):
        hfss = self._build(cap_model.CapPadConfig(
            real_component_enabled=False, lumped_rlc_enabled=True
        ))
        names = set(hfss.modeler.created)
        self.assertTrue({"CAP_P_RLC_SHEET", "CAP_N_RLC_SHEET"} <= names)
        self.assertEqual(2, len(hfss.lumped_rlcs))
        for branch, (name, props, boundary_type) in zip(("P", "N"), hfss.lumped_rlcs):
            self.assertEqual(f"CAP_{branch}_LUMPED_RLC", name)
            self.assertEqual("Lumped RLC", boundary_type)
            self.assertEqual([f"CAP_{branch}_RLC_SHEET"], props["Objects"])
            self.assertEqual("Serial", props["RLC Type"])
            self.assertFalse(props["UseResist"])
            self.assertFalse(props["UseInduct"])
            self.assertTrue(props["UseCap"])
            self.assertEqual("CAP_RLC_CAPACITANCE", props["Capacitance"])
            self.assertEqual(
                ["-20mm", "0mm"],
                props["CurrentLine"]["Start"][:2],
            )
            self.assertEqual(
                ["20mm", "0mm"],
                props["CurrentLine"]["End"][:2],
            )
        self.assertEqual("0.327mm", hfss.variables["CAP_RLC_SHEET_LENGTH"])
        self.assertEqual("0.203mm", hfss.variables["CAP_RLC_SHEET_WIDTH"])
        self.assertEqual("0ohm", hfss.variables["CAP_RLC_RESISTANCE"])
        self.assertEqual("0H", hfss.variables["CAP_RLC_INDUCTANCE"])
        self.assertEqual("1e-07farad", hfss.variables["CAP_RLC_CAPACITANCE"])
        self.assertEqual(
            "CAP_LEFT_PAD_CENTER_X",
            hfss.modeler.rectangle_args["CAP_P_RLC_SHEET"][1][0],
        )
        self.assertEqual(
            "(CAP_BOARD_THICKNESS)+CAP_SOLDER_HEIGHT",
            hfss.modeler.rectangle_args["CAP_P_RLC_SHEET"][1][2],
        )

    def test_custom_mode_impedances_are_used_by_both_ports(self):
        self.stackup.differential_impedance = 99.0
        self.stackup.common_impedance = 27.0
        hfss = self._build()
        for pair in hfss.pairs:
            self.assertEqual(99.0, pair["differential_reference"])
            self.assertEqual(27.0, pair["common_reference"])

    def test_default_uses_independent_l1_to_l3_and_l1_to_l5_via_stacks(self):
        hfss = self._build()
        names = set(hfss.modeler.created)
        self.assertTrue({
            "CAP_INPUT_VIA_P_L1_L2_COLUMN",
            "CAP_INPUT_VIA_P_L2_L3_COLUMN",
            "CAP_OUTPUT_VIA_N_L1_L2_COLUMN",
            "CAP_OUTPUT_VIA_N_L2_L3_COLUMN",
            "CAP_OUTPUT_VIA_N_L3_L4_COLUMN",
            "CAP_OUTPUT_VIA_N_L4_L5_COLUMN",
        } <= names)
        self.assertNotIn("CAP_INPUT_VIA_P_L3_L4_COLUMN", names)

    def test_top_mounted_cap_can_route_directly_on_l1(self):
        config = cap_model.CapPadConfig(
            route_layers=["L1", "L5"],
            input_line=cap_model.DifferentialLineEndConfig(
                upper_reference_layer_name="",
                lower_reference_layer_name="L2",
            ),
        )
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        self.assertIn("CAP_INPUT_TRACE_P", names)
        self.assertIn("CAP_INPUT_VIA_P_LANDING_PAD", names)
        self.assertNotIn("CAP_INPUT_VIA_P_L1_L2_COLUMN", names)
        self.assertEqual("L1", cap_model._validate(self.stackup, config)[1].name)

    def test_all_aedt_variables_are_cap_namespaced(self):
        hfss = self._build()
        self.assertTrue(hfss.variables)
        self.assertTrue(all(name.startswith("CAP_") for name in hfss.variables))
        self.assertEqual("L3", cap_model.CapPadConfig().route_layers[0])
        self.assertEqual("L5", cap_model.CapPadConfig().route_layers[1])

    def test_project_variable_expression_uses_shared_cap_references(self):
        self.assertEqual(
            "$CAP_LEFT_PAD_CENTER_X-$CAP_INPUT_TRACE_LENGTH",
            cap_model._project_cap_expression(
                "CAP_LEFT_PAD_CENTER_X-CAP_INPUT_TRACE_LENGTH"
            ),
        )
        self.assertEqual(
            "$CAP_BOARD_THICKNESS+3mil",
            cap_model._project_cap_expression("$CAP_BOARD_THICKNESS+3mil"),
        )

    def test_component_coordinate_systems_are_at_gap_centres_on_board_top(self):
        hfss = self._build()
        systems = hfss.modeler.coordinate_system_args
        self.assertEqual({
            "CAP_P_COMPONENT_CS", "CAP_N_COMPONENT_CS",
            "CAP_P_ASSEMBLY_CS", "CAP_N_ASSEMBLY_CS",
        }, set(systems))
        self.assertEqual(
            ["0mm", "CAP_P_Y", "CAP_BOARD_THICKNESS"],
            systems["CAP_P_COMPONENT_CS"]["origin"],
        )
        self.assertEqual(
            ["0mm", "CAP_N_Y", "CAP_BOARD_THICKNESS"],
            systems["CAP_N_COMPONENT_CS"]["origin"],
        )
        self.assertEqual(
            ["0mm", "CAP_P_Y", "CAP_BOARD_THICKNESS+CAP_SOLDER_HEIGHT"],
            systems["CAP_P_ASSEMBLY_CS"]["origin"],
        )
        self.assertEqual("Global", hfss.modeler.working_coordinate_system)

    def test_bottom_mount_builds_upward_stacks_and_bottom_component_axes(self):
        config = cap_model.CapPadConfig(component_side="bottom")
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        self.assertIn("CAP_INPUT_VIA_P_L8_L7_COLUMN", names)
        self.assertIn("CAP_INPUT_VIA_P_L4_L3_COLUMN", names)
        self.assertIn("CAP_OUTPUT_VIA_N_L6_L5_COLUMN", names)
        self.assertIn("CAP_L8_PAD_GROUP_VOID", names)
        self.assertIn("CAP_L7_PAD_GROUP_VOID", names)
        system = hfss.modeler.coordinate_system_args["CAP_P_COMPONENT_CS"]
        self.assertEqual(["0mm", "CAP_P_Y", "0mm"], system["origin"])
        self.assertEqual([0, -1, 0], system["y_pointing"])
        assembly = hfss.modeler.coordinate_system_args["CAP_P_ASSEMBLY_CS"]
        self.assertEqual(["0mm", "CAP_P_Y", "-CAP_SOLDER_HEIGHT"], assembly["origin"])
        self.assertEqual([0, -1, 0], assembly["y_pointing"])
        self.assertEqual(
            "-CAP_SOLDER_HEIGHT",
            hfss.modeler.polyline_args["CAP_P_LEFT_TIN"][0][0][2],
        )
        self.assertEqual(
            "CAP_P_ASSEMBLY_CS", hfss.modeler.inserted_components[0][1]
        )
        self.assertEqual(
            "-CAP_SOLDERMASK_COPPER_THICKNESS",
            hfss.modeler.box_args["CAP_SOLDERMASK_COPPER_COVER"][0][2],
        )
        self.assertEqual(
            "-CAP_SOLDERMASK_COPPER_THICKNESS",
            hfss.modeler.polyline_args["CAP_SOLDERMASK_EDGE_TRANSITION"][0][0][2],
        )

    def test_default_surface_process_creates_four_tin_solids_and_two_pair_windows(self):
        config = cap_model.CapPadConfig()
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        self.assertTrue({
            "CAP_P_LEFT_TIN", "CAP_P_RIGHT_TIN",
            "CAP_N_LEFT_TIN", "CAP_N_RIGHT_TIN",
            "CAP_SOLDERMASK_GAP_FILL", "CAP_SOLDERMASK_COPPER_COVER",
            "CAP_SOLDERMASK_EDGE_TRANSITION",
            "CAP_SOLDERMASK_EDGE_TRANSITION_INNER",
            "CAP_P_SOLDERMASK_PAIR_WINDOW", "CAP_N_SOLDERMASK_PAIR_WINDOW",
        } <= names)
        for side in ("P", "N"):
            for column in ("LEFT", "RIGHT"):
                self.assertEqual(
                    "tin", hfss.modeler.polyline_args[f"CAP_{side}_{column}_TIN"][3]
                )
        self.assertEqual("3mil", hfss.variables["CAP_SOLDER_HEIGHT"])
        self.assertEqual("15um", hfss.variables["CAP_SOLDERMASK_COPPER_THICKNESS"])
        self.assertEqual("25um", hfss.variables["CAP_SOLDERMASK_GAP_THICKNESS"])
        self.assertEqual("10um", hfss.variables["CAP_SOLDERMASK_TRANSITION_WIDTH"])
        self.assertEqual("0.03318mm", hfss.variables["CAP_SOLDERMASK_TRANSITION_HEIGHT"])
        self.assertEqual("0.1um", hfss.variables["CAP_SOLDERMASK_BOOLEAN_OVERLAP"])
        self.assertEqual(
            "CAP_SOLDERMASK_TRANSITION_HEIGHT+CAP_SOLDERMASK_BOOLEAN_OVERLAP",
            hfss.variables["CAP_SOLDERMASK_TRANSITION_SWEEP_HEIGHT"],
        )
        self.assertEqual("-0.3158mm", hfss.variables["CAP_SOLDERMASK_WINDOW_X0"])
        self.assertEqual("0.6316mm", hfss.variables["CAP_SOLDERMASK_WINDOW_LENGTH"])
        self.assertEqual("0.3046mm", hfss.variables["CAP_SOLDERMASK_WINDOW_WIDTH"])
        self.assertEqual("0.1008mm", hfss.variables["CAP_SOLDERMASK_WINDOW_RADIUS"])
        mask = hfss.materials["CAP_SolderMask_DK3p3_DF0p02"]
        self.assertEqual(3.3, mask.permittivity)
        self.assertEqual(0.02, mask.dielectric_loss_tangent)
        self.assertTrue({
            ("CAP_SOLDERMASK_EDGE_TRANSITION", "CAP_SOLDERMASK_EDGE_TRANSITION_INNER", False),
            ("CAP_SOLDERMASK_COPPER_COVER", "CAP_P_SOLDERMASK_PAIR_WINDOW", False),
            ("CAP_SOLDERMASK_COPPER_COVER", "CAP_N_SOLDERMASK_PAIR_WINDOW", False),
        } <= set(hfss.modeler.subtractions))
        final_mask_union = next(
            group for group in hfss.modeler.unions
            if "CAP_SOLDERMASK_COPPER_COVER" in group
        )
        self.assertTrue({
            "CAP_SOLDERMASK_COPPER_COVER", "CAP_SOLDERMASK_GAP_FILL",
            "CAP_SOLDERMASK_EDGE_TRANSITION",
        } <= set(final_mask_union))
        self.assertIn([
            "CAP_SOLDERMASK_EDGE_TRANSITION",
            "CAP_INPUT_OUTER_SOLDERMASK_TRANSITION",
        ], hfss.modeler.unions)
        self.assertIn([
            "CAP_SOLDERMASK_EDGE_TRANSITION_INNER",
            "CAP_INPUT_OUTER_SOLDERMASK_TRANSITION_INNER",
        ], hfss.modeler.unions)
        self.assertTrue({
            "CAP_INPUT_OUTER_SOLDERMASK_GAP",
            "CAP_OUTPUT_OUTER_SOLDERMASK_GAP",
            "CAP_INPUT_OUTER_SOLDERMASK_COVER_VOID",
            "CAP_OUTPUT_OUTER_SOLDERMASK_COVER_VOID",
        } <= names)

    def test_surface_process_can_be_disabled(self):
        config = cap_model.CapPadConfig(
            solder_enabled=False, solder_mask_enabled=False,
            real_component_enabled=False, lumped_rlc_enabled=True,
        )
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        self.assertFalse(any("_TIN" in name or "SOLDERMASK" in name for name in names))
        self.assertNotIn("CAP_P_ASSEMBLY_CS", hfss.modeler.coordinate_system_args)
        self.assertEqual(
            "CAP_BOARD_THICKNESS",
            hfss.modeler.rectangle_args["CAP_P_RLC_SHEET"][1][2],
        )

    def test_lumped_rlc_can_be_disabled_to_restore_open_pad_gaps(self):
        hfss = self._build(cap_model.CapPadConfig(lumped_rlc_enabled=False))
        self.assertFalse(hfss.lumped_rlcs)
        self.assertFalse(any("RLC_SHEET" in name for name in hfss.modeler.created))

    def test_physical_and_ideal_electrical_models_are_mutually_exclusive(self):
        with self.assertRaisesRegex(ValueError, "cannot be enabled together"):
            cap_model._validate(
                self.stackup,
                cap_model.CapPadConfig(
                    real_component_enabled=True, lumped_rlc_enabled=True
                ),
            )

    def test_physical_component_uses_board_surface_when_solder_is_disabled(self):
        hfss = self._build(cap_model.CapPadConfig(solder_enabled=False))
        self.assertEqual(
            ["CAP_P_COMPONENT_CS", "CAP_N_COMPONENT_CS"],
            [item[1] for item in hfss.modeler.inserted_components],
        )

    def test_lumped_capacitance_units_and_validation(self):
        config = cap_model.CapPadConfig(
            real_component_enabled=False, lumped_rlc_enabled=True,
            lumped_capacitance="10nF",
        )
        hfss = self._build(config)
        self.assertEqual("CAP_RLC_CAPACITANCE", hfss.lumped_rlcs[0][1]["Capacitance"])
        self.assertEqual("1e-08farad", hfss.variables["CAP_RLC_CAPACITANCE"])
        with self.assertRaisesRegex(ValueError, "F, mF, uF, nF, or pF"):
            cap_model._validate(
                self.stackup, cap_model.CapPadConfig(
                    real_component_enabled=False, lumped_rlc_enabled=True,
                    lumped_capacitance="0.01mm",
                )
            )

    def test_fitted_series_resistance_and_inductance_are_enabled(self):
        config = cap_model.CapPadConfig(
            real_component_enabled=False,
            lumped_rlc_enabled=True,
            lumped_resistance="94.4mohm",
            lumped_inductance="212.8pH",
            lumped_capacitance="85.85nF",
        )
        hfss = self._build(config)
        props = hfss.lumped_rlcs[0][1]
        self.assertTrue(props["UseResist"])
        self.assertTrue(props["UseInduct"])
        self.assertEqual("CAP_RLC_RESISTANCE", props["Resistance"])
        self.assertEqual("CAP_RLC_INDUCTANCE", props["Inductance"])
        self.assertEqual("0.0944ohm", hfss.variables["CAP_RLC_RESISTANCE"])
        self.assertEqual("2.128e-10H", hfss.variables["CAP_RLC_INDUCTANCE"])
        self.assertEqual("8.585e-08farad", hfss.variables["CAP_RLC_CAPACITANCE"])

    def test_pair_window_encloses_unequal_pad_dimensions(self):
        config = cap_model.CapPadConfig(
            left_pad_length="180um", right_pad_length="220um",
            left_pad_width="200um", right_pad_width="240um",
            left_pad_corner_radius="40um", right_pad_corner_radius="60um",
        )
        dimensions = cap_model._validate(self.stackup, config)[3]
        self.assertAlmostEqual(-0.3043, dimensions["solder_mask_window_x0"])
        self.assertAlmostEqual(0.6286, dimensions["solder_mask_window_length"])
        self.assertAlmostEqual(0.3416, dimensions["solder_mask_window_width"])
        self.assertAlmostEqual(0.1108, dimensions["solder_mask_window_radius"])

    def test_return_vias_include_rows_beside_both_lines(self):
        config = cap_model.CapPadConfig()
        dimensions = cap_model._validate(self.stackup, config)[3]
        local_only = cap_model._return_fence_points(dimensions)
        line_points = cap_model._line_return_points(dimensions)
        unfiltered = cap_model._all_return_points(dimensions)
        all_points = cap_model._all_return_points(dimensions, config)
        self.assertTrue(line_points)
        self.assertGreater(len(all_points), len(local_only))
        self.assertLess(len(all_points), len(unfiltered))
        self.assertTrue(all(
            not cap_model._return_point_intersects_void(point, dimensions, config)
            for point in all_points
        ))
        self.assertTrue(all(
            cap_model._return_point_has_board_edge_margin(point, dimensions)
            for point in all_points
        ))
        pad_pitch = dimensions["pad_center_pitch"]
        board_x0 = (
            -pad_pitch / 2 + dimensions["left_via_x_offset"]
            - dimensions["input_fanout_length"]
            - dimensions["input_trace_length"]
        )
        board_x1 = (
            pad_pitch / 2 + dimensions["right_via_x_offset"]
            + dimensions["output_fanout_length"]
            + dimensions["output_trace_length"]
        )
        required_inset = (
            dimensions["return_column_radius"]
            + dimensions["return_via_clearance"]
        )
        self.assertGreaterEqual(min(x for x, _ in all_points), board_x0 + required_inset)
        self.assertLessEqual(max(x for x, _ in all_points), board_x1 - required_inset)
        left_via_x = -dimensions["pad_center_pitch"] / 2 + dimensions["left_via_x_offset"]
        right_via_x = dimensions["pad_center_pitch"] / 2 + dimensions["right_via_x_offset"]
        self.assertTrue(any(x < left_via_x for x, _ in line_points))
        self.assertTrue(any(x > right_via_x for x, _ in line_points))

    def test_primary_pads_are_never_united_with_via_columns(self):
        hfss = self._build()
        for union in hfss.modeler.unions:
            if any(name in union for name in ("CAP_P_LEFT_PAD", "CAP_P_RIGHT_PAD", "CAP_N_LEFT_PAD", "CAP_N_RIGHT_PAD")):
                self.assertFalse(any(name.endswith("_COLUMN") for name in union))

    def test_return_fence_can_be_disabled(self):
        hfss = self._build(cap_model.CapPadConfig(return_vias_enabled=False))
        self.assertFalse(any(name.startswith("CAP_RETURN_VIA_") for name in hfss.modeler.created))

    def test_config_round_trip_preserves_lines_and_layers(self):
        original = cap_model.CapPadConfig(
            route_layers=["L2", "L6"],
            input_line=cap_model.DifferentialLineEndConfig(w_line="80um"),
            output_line=cap_model.DifferentialLineEndConfig(w_line="120um"),
            pad_gap="0.25mm",
            real_component_file="components/SC04S0J104M_0p1uF.a3dcomp",
            return_vias_enabled=False,
        )
        restored = cap_model.CapPadConfig.from_dict(original.to_dict())
        self.assertEqual(["L2", "L6"], restored.route_layers)
        self.assertEqual("80um", restored.input_line.w_line)
        self.assertEqual("120um", restored.output_line.w_line)
        self.assertEqual("0.25mm", restored.pad_gap)
        self.assertFalse(restored.return_vias_enabled)
        self.assertTrue(restored.solder_enabled)
        self.assertTrue(restored.solder_mask_enabled)
        self.assertTrue(restored.real_component_enabled)
        self.assertEqual(
            "components/SC04S0J104M_0p1uF.a3dcomp",
            restored.real_component_file,
        )
        self.assertFalse(restored.lumped_rlc_enabled)
        self.assertEqual("0ohm", restored.lumped_resistance)
        self.assertEqual("0nH", restored.lumped_inductance)
        self.assertEqual("10MHz", restored.rlc_fit_start)
        self.assertEqual("3GHz", restored.rlc_fit_stop)
        self.assertFalse(restored.comparison_designs_enabled)
        self.assertEqual("0.1uF", restored.lumped_capacitance)
        self.assertTrue(restored.input_via.follow_solder_mask_antipad)
        self.assertTrue(restored.output_via.follow_solder_mask_antipad)
        self.assertEqual("3mil", restored.solder_height)
        self.assertEqual("10um", restored.solder_mask_transition_width)
        self.assertEqual("2mil", restored.solder_mask_opening_expansion)

    def test_via_pairs_use_independent_symmetric_center_pitches(self):
        config = cap_model.CapPadConfig(
            pair_pitch="373um", input_d_via="400um", output_d_via="420um"
        )
        hfss = self._build(config)
        self.assertEqual("400um", hfss.variables["CAP_INPUT_D_VIA"])
        self.assertEqual("420um", hfss.variables["CAP_OUTPUT_D_VIA"])
        self.assertEqual(
            "CAP_BOARD_CENTER_Y-CAP_INPUT_D_VIA/2",
            hfss.variables["CAP_INPUT_P_VIA_Y"],
        )
        self.assertEqual(
            "CAP_BOARD_CENTER_Y+CAP_INPUT_D_VIA/2",
            hfss.variables["CAP_INPUT_N_VIA_Y"],
        )
        self.assertEqual(
            "CAP_BOARD_CENTER_Y-CAP_OUTPUT_D_VIA/2",
            hfss.variables["CAP_OUTPUT_P_VIA_Y"],
        )
        self.assertEqual(
            "CAP_BOARD_CENTER_Y+CAP_OUTPUT_D_VIA/2",
            hfss.variables["CAP_OUTPUT_N_VIA_Y"],
        )

        legacy = cap_model.CapPadConfig.from_dict({
            "pair_pitch": "410um",
            "left_via_y_offset": "20um",
            "right_via_y_offset": "-20um",
        })
        self.assertEqual("410um", legacy.input_d_via)
        self.assertEqual("410um", legacy.output_d_via)
        self.assertNotIn("left_via_y_offset", legacy.to_dict())

        with self.assertRaisesRegex(ValueError, "input_d_via"):
            cap_model._validate(
                self.stackup, cap_model.CapPadConfig(input_d_via="700um")
            )

    def test_invalid_solder_mask_transition_geometry_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "transition_width"):
            cap_model._validate(
                self.stackup,
                cap_model.CapPadConfig(solder_mask_transition_width="4mil"),
            )
        with self.assertRaisesRegex(ValueError, "copper-cover mask thickness"):
            cap_model._validate(
                self.stackup,
                cap_model.CapPadConfig(
                    solder_mask_copper_thickness="5um",
                    solder_mask_gap_thickness="100um",
                ),
            )

    def test_legacy_json_without_surface_keys_keeps_old_geometry(self):
        restored = cap_model.CapPadConfig.from_dict({
            "route_layers": ["L3", "L5"], "pad_center_pitch": "327um"
        })
        self.assertFalse(restored.solder_enabled)
        self.assertFalse(restored.solder_mask_enabled)
        self.assertFalse(restored.real_component_enabled)
        self.assertFalse(restored.lumped_rlc_enabled)

    def test_legacy_via_json_does_not_silently_add_surface_mask_following(self):
        via = cap_model.CapViaConfig.from_dict({
            "column_radius": "30um", "pad_radius": "50um",
            "antipad_radius": "100um", "antipad_x": "100um",
        })
        self.assertFalse(via.follow_solder_mask_antipad)

    def test_outer_via_mask_following_is_independent_per_side(self):
        config = cap_model.CapPadConfig()
        config.output_via.follow_solder_mask_antipad = False
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        self.assertIn("CAP_INPUT_OUTER_SOLDERMASK_GAP", names)
        self.assertIn("CAP_INPUT_OUTER_SOLDERMASK_TRANSITION", names)
        self.assertNotIn("CAP_OUTPUT_OUTER_SOLDERMASK_GAP", names)
        self.assertNotIn("CAP_OUTPUT_OUTER_SOLDERMASK_TRANSITION", names)

    def test_measured_pad_pitch_and_independent_mechanical_span(self):
        via = cap_model.CapViaConfig(
            column_radius="30um", pad_radius="50um", antipad_radius="100um",
            layer_antipads={"L3": "150um"},
        )
        mechanical = cap_model.CapViaConfig(
            column_radius="30um", pad_radius="50um", antipad_radius="100um",
            mechanical_enabled=True, mechanical_start_layer="L2", mechanical_end_layer="L4",
            mechanical_column_radius="35um", mechanical_pad_radius="70um",
        )
        config = cap_model.CapPadConfig(
            pad_center_pitch="327um", left_pad_length="203um", right_pad_length="203um",
            left_pad_width="203um", right_pad_width="203um",
            left_pad_corner_radius="50um", right_pad_corner_radius="50um",
            left_via_x_offset="0um", right_via_x_offset="0um",
            input_via=via, output_via=mechanical,
        )
        self.assertAlmostEqual(0.124, cap_model._validate(self.stackup, config)[3]["pad_center_pitch"] - 0.203)
        hfss = self._build(config)
        self.assertEqual("0.327mm", hfss.variables["CAP_PAD_CENTER_PITCH"])
        self.assertEqual("0.203mm", hfss.variables["CAP_LEFT_PAD_LENGTH"])
        self.assertEqual("150um", hfss.variables["CAP_INPUT_VIA_ANTIPAD_RADIUS_L3"])
        pad = hfss.modeler.polyline_args["CAP_P_RIGHT_PAD"]
        self.assertEqual(["Line", "Arc", "Line", "Arc", "Line", "Arc", "Line", "Arc"], pad[4])
        self.assertEqual(["0mm", "0mm", "CAP_L1_H"], hfss.modeler.sweep_args["CAP_P_RIGHT_PAD"])
        names = set(hfss.modeler.created)
        self.assertIn("CAP_OUTPUT_VIA_N_L2_L4_COLUMN", names)
        self.assertIn("CAP_OUTPUT_VIA_N_L4_L5_COLUMN", names)
        self.assertNotIn("CAP_OUTPUT_VIA_N_L2_L3_COLUMN", names)
        self.assertNotIn("CAP_OUTPUT_VIA_N_L3_PAD", names)
        self.assertFalse(any("CAP_P_LEFT_PAD" in group and "CAP_P_RIGHT_PAD" in group for group in hfss.modeler.unions))
        restored = cap_model.CapPadConfig.from_dict(config.to_dict())
        self.assertTrue(restored.output_via.mechanical_enabled)
        self.assertEqual("150um", restored.input_via.layer_antipads["L3"]["radius"])
        self.assertEqual("0.254mm", restored.input_via.layer_antipads["L3"]["x"])

    def test_default_measured_pads_group_voids_and_per_layer_slots(self):
        config = cap_model.CapPadConfig()
        self.assertEqual(("203um", "203um", "50um"), (
            config.left_pad_length, config.left_pad_width, config.left_pad_corner_radius,
        ))
        self.assertEqual(("327um", "373um"), (config.pad_center_pitch, config.pair_pitch))
        self.assertTrue(config.layer_pad_voids["L1"]["enabled"])
        self.assertTrue(config.layer_pad_voids["L2"]["enabled"])
        self.assertEqual("4mil", config.layer_pad_voids["L1"]["radius"])
        config.input_via.layer_antipads["L2"] = {"radius": "140um", "x": "130um"}
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        self.assertIn("CAP_L1_PAD_GROUP_VOID", names)
        self.assertIn("CAP_L2_PAD_GROUP_VOID", names)
        self.assertNotIn("CAP_L3_PAD_GROUP_VOID", names)
        self.assertIn("CAP_INPUT_L2_SIG_SLOT_ANTIPAD", names)
        self.assertIn("CAP_OUTPUT_L5_SIG_SLOT_ANTIPAD", names)
        self.assertEqual("140um", hfss.variables["CAP_INPUT_VIA_ANTIPAD_RADIUS_L2"])
        self.assertEqual("130um", hfss.variables["CAP_INPUT_VIA_ANTIPAD_X_L2"])

    def test_separated_references_clear_skipped_copper_on_both_lines(self):
        config = cap_model.CapPadConfig()
        config.input_line.upper_reference_layer_name = "L1"
        config.input_line.lower_reference_layer_name = "L5"
        config.output_line.upper_reference_layer_name = "L3"
        config.output_line.lower_reference_layer_name = "L7"
        config.output_via.layer_antipads["L6"] = {
            "radius": "180um", "x": "170um",
        }

        hfss = self._build(config)
        subtractions = {
            (blank, tool) for blank, tool, _ in hfss.modeler.subtractions
        }
        self.assertIn(
            ("CAP_GND_L2", "CAP_INPUT_SKIPPED_REF_L2_TRACE_CLEARANCE"),
            subtractions,
        )
        self.assertIn(
            ("CAP_GND_L4", "CAP_INPUT_SKIPPED_REF_L4_FANOUT_CLEARANCE"),
            subtractions,
        )
        self.assertIn(
            ("CAP_GND_L4", "CAP_OUTPUT_SKIPPED_REF_L4_TRACE_CLEARANCE"),
            subtractions,
        )
        self.assertIn(
            ("CAP_GND_L6", "CAP_OUTPUT_SKIPPED_REF_L6_FANOUT_CLEARANCE"),
            subtractions,
        )
        self.assertNotIn(
            "CAP_OUTPUT_SKIPPED_REF_L3_TRACE_CLEARANCE",
            hfss.modeler.created,
        )
        self.assertNotIn(
            "CAP_OUTPUT_SKIPPED_REF_L7_TRACE_CLEARANCE",
            hfss.modeler.created,
        )
        self.assertEqual(
            "180um", hfss.variables["CAP_OUTPUT_VIA_ANTIPAD_RADIUS_L6"]
        )
        self.assertNotIn("CAP_OUTPUT_L6_SIG_SLOT_ANTIPAD", hfss.modeler.created)

    def test_measured_pad_is_top_landing_pad_and_negative_gap_is_rejected(self):
        measured = cap_model.CapPadConfig(
            pad_center_pitch="327um", left_pad_length="203um", right_pad_length="203um",
            left_pad_width="203um", right_pad_width="203um",
            left_via_x_offset="0um", right_via_x_offset="0um",
        )
        dimensions = cap_model._validate(self.stackup, measured)[3]
        self.assertEqual(0.127, dimensions["input_pad_radius"])
        self.assertEqual(0.057, dimensions["input_column_radius"])
        measured.pad_center_pitch = "190um"
        with self.assertRaisesRegex(ValueError, "positive copper gap"):
            cap_model._validate(self.stackup, measured)

    def test_measured_pad_rejects_only_an_oversized_or_offset_top_column(self):
        measured = cap_model.CapPadConfig(
            pad_center_pitch="327um", left_pad_length="203um", right_pad_length="203um",
            left_pad_width="203um", right_pad_width="203um",
            left_via_x_offset="50um", right_via_x_offset="0um",
        )
        with self.assertRaisesRegex(ValueError, "copper column inside the component pad length"):
            cap_model._validate(self.stackup, measured)

    def test_invalid_pad_and_via_geometry_is_rejected(self):
        cases = (
            (cap_model.CapPadConfig(pad_corner_radius="0.30mm"), "pad_corner_radius"),
            (cap_model.CapPadConfig(pair_pitch="0.20mm"), "pair_pitch"),
            (cap_model.CapPadConfig(via_pad_radius="0.05mm"), "via_pad_radius"),
            (cap_model.CapPadConfig(via_inset="0.05mm", left_via_x_offset=""), "via_inset"),
            (
                cap_model.CapPadConfig(
                    component_side="bottom",
                    route_layers=["L8", "L5"],
                ),
                "Bottom-mounted CAP route layers",
            ),
        )
        for config, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    cap_model._validate(self.stackup, config)


if __name__ == "__main__":
    unittest.main()
