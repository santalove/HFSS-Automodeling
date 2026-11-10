"""AEDT-free structural tests for :mod:`gf_inner_model`."""

from __future__ import annotations

import unittest

import gf_inner_model as inner_model
from gf_gssg_model import GSSGConfig
from hfss_stackup_builder import eight_layer_example


class _Object:
    def __init__(self, name: str, bounding_box=None):
        self.name = name
        self.bounding_box = bounding_box or [-2.0, 0.0, -10.0, 4.0, 5.0, -9.0]
        self.display_wireframe = False
        self.color = None
        self.transparency = None


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
        self.objects = {}
        self.created = []
        self.subtractions = []
        self.rectangle_args = {}
        self.cylinder_args = {}
        self.unions = []
        self.box_args = {}

    def _add(self, name, bounding_box=None):
        obj = _Object(name, bounding_box)
        self.objects[name] = obj
        self.created.append(name)
        return obj

    def create_box(self, origin, sizes, name, material):
        boxes = {
            "GND_L1": [-2.0, 0.0, 4.1, 4.0, 5.0, 4.2],
            "GND_L2": [-2.0, 0.0, 3.0, 4.0, 5.0, 4.0],
            "GND_L3": [-2.0, 0.0, 2.2, 4.0, 5.0, 2.8],
        }
        self.box_args[name] = (origin, sizes, material)
        return self._add(name, boxes.get(name))

    def create_rectangle(self, plane, origin, sizes, name):
        self.rectangle_args[name] = (plane, origin, sizes)
        bbox = [-2.0, 1.0, 2.1, -2.0, 3.0, 4.2] if name == "INNER_WAVE_PORT_SHEET" else None
        return self._add(name, bbox)

    def create_polyline(self, points, cover_surface, close_surface, name, material):
        return self._add(name)

    def sweep_along_vector(self, assignment, vector):
        return assignment

    def create_cylinder(self, axis, origin, radius, height, name, material):
        self.cylinder_args[name] = (axis, origin, radius, height)
        return self._add(name)

    def subtract(self, blank, tool, keep_originals=False):
        blank_name = blank.name if hasattr(blank, "name") else str(blank)
        tool_name = tool.name if hasattr(tool, "name") else str(tool)
        self.subtractions.append((blank_name, tool_name))
        return True

    def unite(self, assignments):
        self.unions.append(list(assignments))
        return True


class _Hfss:
    def __init__(self):
        self.variables = {}
        self.variable_order = []
        self.modeler = _Modeler()
        self.materials = _Materials()
        self.wave_ports = []
        self.lumped_ports = []
        self.pairs = []
        self.open_regions = []
        self.setups = []

    def __setitem__(self, key, value):
        self.variables[key] = value
        self.variable_order.append(key)

    def __getitem__(self, key):
        return self.variables[key]

    def assign_perfect_e(self, assignment, name):
        return True

    def lumped_port(self, sheet, **kwargs):
        self.lumped_ports.append((sheet.name, kwargs))
        return True

    def wave_port(self, sheet, **kwargs):
        self.wave_ports.append((sheet.name, kwargs))
        return True

    def set_differential_pair(self, **kwargs):
        self.pairs.append(kwargs)
        return True

    def create_open_region(self, **kwargs):
        self.open_regions.append(kwargs)
        return True

    def create_setup(self, **kwargs):
        setup = _Setup(kwargs)
        self.setups.append(setup)
        return setup


class _Sweep:
    def __init__(self, arguments):
        self.arguments = arguments
        self.props = {}
        self.updated = False

    def update(self):
        self.updated = True
        return True


class _Setup(_Sweep):
    def __init__(self, arguments):
        super().__init__(arguments)
        self.sweeps = []

    def add_sweep(self, **kwargs):
        sweep = _Sweep(kwargs)
        self.sweeps.append(sweep)
        return sweep


class InnerGFModelTests(unittest.TestCase):
    def setUp(self):
        self.stackup = eight_layer_example()
        self.gssg = GSSGConfig(signal_layer_name="L1")
        self.inner = self.inner_config()

    @staticmethod
    def inner_config(**overrides):
        values = {
            "upper_reference_layer_name": "L1",
            "lower_reference_layer_name": "L3",
        }
        values.update(overrides)
        return inner_model.InnerGFConfig(**values)

    def test_default_build_structure(self):
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, self.gssg, self.inner)
        names = set(hfss.modeler.created)

        self.assertTrue({"GND_PAD_L", "SIG_PAD_P", "SIG_PAD_N", "GND_PAD_R"} <= names)
        self.assertFalse({"FANOUT_P", "FANOUT_N", "TRACE_P", "TRACE_N"} & names)
        self.assertTrue({"INNER_FANOUT_P", "INNER_FANOUT_N", "INNER_TRACE_P", "INNER_TRACE_N"} <= names)
        self.assertTrue(
            {
                "SIG_VIA_P_LASER_L1_L2_COLUMN",
                "SIG_VIA_N_LASER_L1_L2_COLUMN",
                "GND_VIA_L_001_COLUMN", "GND_VIA_L_002_COLUMN", "GND_VIA_L_003_COLUMN",
                "GND_VIA_R_001_COLUMN", "GND_VIA_R_002_COLUMN", "GND_VIA_R_003_COLUMN",
            }
            <= {name for name in names if name.endswith("_COLUMN")}
        )
        inner_return_columns = {
            name for name in names if name.startswith("INNER_RETURN_VIA_") and name.endswith("_COLUMN")
        }
        self.assertEqual(34, len(inner_return_columns))
        self.assertIn("INNER_RETURN_VIA_L_017_COLUMN", inner_return_columns)
        self.assertIn("GND_L1", names)
        self.assertFalse(any(name.startswith("L1_") and name.endswith("_CLEARANCE") for name in names))
        self.assertEqual(
            (["BOARD_X0", "0mm", hfss.modeler.box_args["GND_L1"][0][2]],
             ["-BOARD_X0", "BOARD_WIDTH", "L1_H"], "copper"),
            hfss.modeler.box_args["GND_L1"],
        )
        self.assertFalse({name for name in names if name.endswith("_DRILL")})
        self.assertTrue({"SIG_VIA_P_INNER_PAD", "SIG_VIA_N_INNER_PAD"} <= names)
        self.assertFalse(any(name.startswith("GND_VIA_") and "_PAD" in name for name in names))

        self.assertEqual("2", hfss.variables["INNER_SIGNAL_LAYER"])
        self.assertEqual("SIGNAL_PAD_LENGTH/4", hfss.variables["VIA_X_OFFSET"])
        self.assertEqual(
            "SIGNAL_PAD_LENGTH/2-VIA_X_OFFSET",
            hfss.variables["VIA_X_POSITION"],
        )
        self.assertEqual("0.127mm", hfss.variables["VIA_PAD_RADIUS"])
        self.assertEqual("0.057mm", hfss.variables["VIA_COLUMN_RADIUS"])
        self.assertEqual("10mil", hfss.variables["VIA_ANTIPAD_RADIUS"])
        self.assertEqual("10mil", hfss.variables["VIA_ANTIPAD_X"])
        self.assertEqual("10mil", hfss.variables["VIA_ANTIPAD_RADIUS_L2"])
        self.assertEqual("10mil", hfss.variables["VIA_ANTIPAD_X_L2"])
        self.assertEqual("3mil", hfss.variables["MECHANICAL_VIA_COLUMN_RADIUS"])
        self.assertEqual("6mil", hfss.variables["MECHANICAL_VIA_PAD_RADIUS"])
        self.assertEqual("0.4mm", hfss.variables["GND_RETURN_VIA_PITCH"])
        self.assertEqual("INNER_PORT_Z1-INNER_PORT_Z0", hfss.variables["INNER_PORT_Z"])
        self.assertEqual(hfss.variables["LOWER_REF_Z"], hfss.variables["INNER_PORT_Z0"])
        self.assertTrue(hfss.variables["INNER_PORT_Z1"].endswith("+L1_H"))
        self.assertEqual("PP_L1_H", hfss.variables["GF_PORT_WAVE_PP_H"])
        self.assertLess(
            hfss.variable_order.index("GF_PORT_WAVE_PP_H"),
            hfss.variable_order.index("GF_PORT_WAVE_HEIGHT"),
        )
        self.assertEqual(2, len(hfss.lumped_ports))
        self.assertEqual("INNER_WAVE_PORT_SHEET", hfss.wave_ports[0][0])
        self.assertEqual(["GND_L3", "GND_L2", "GND_L1"], hfss.wave_ports[0][1]["reference"])
        self.assertEqual(
            ["GF_PORT_WAVE_WIDTH", "INNER_PORT_Z"],
            hfss.modeler.rectangle_args["INNER_WAVE_PORT_SHEET"][2],
        )
        self.assertEqual(
            "GF_PORT_HEIGHT",
            hfss.modeler.rectangle_args["GF_GND_BRIDGE_CLEARANCE"][2][1],
        )
        self.assertEqual(
            "VIA_X_POSITION-BOARD_X0",
            hfss.modeler.box_args["INNER_GND_L2_TRACE_CLEARANCE"][1][0],
        )
        self.assertFalse(any(
            "FANOUT_CLEARANCE" in name for name in hfss.modeler.created
        ))
        self.assertEqual({"Diff1", "Diff2"}, {pair["differential_mode"] for pair in hfss.pairs})

        antipads = {
            tool for _, tool in hfss.modeler.subtractions
            if tool.startswith("SIG_SLOT_ANTIPAD_")
        }
        self.assertEqual({"SIG_SLOT_ANTIPAD_L2"}, antipads)
        self.assertEqual(
            "VIA_ANTIPAD_RADIUS_L2",
            hfss.modeler.cylinder_args["SIG_SLOT_ANTIPAD_L2"][2],
        )
        self.assertEqual(
            "VIA_COLUMN_RADIUS",
            hfss.modeler.cylinder_args["SIG_VIA_P_LASER_L1_L2_COLUMN"][2],
        )
        self.assertEqual(
            "VIA_PAD_RADIUS",
            hfss.modeler.cylinder_args["SIG_VIA_P_PAD"][2],
        )
        self.assertEqual(
            "VIA_COLUMN_RADIUS",
            hfss.modeler.cylinder_args["INNER_RETURN_VIA_L_001_COLUMN"][2],
        )
        self.assertEqual(
            "BOARD_X0+RETURN_VIA_EDGE_OFFSET+16*RETURN_VIA_PITCH",
            hfss.modeler.cylinder_args["INNER_RETURN_VIA_L_017_COLUMN"][1][0],
        )
        self.assertIn(
            ["INNER_TRACE_P", "INNER_FANOUT_P", "SIG_VIA_P_INNER_PAD"],
            hfss.modeler.unions,
        )
        self.assertIn(
            ["INNER_TRACE_N", "INNER_FANOUT_N", "SIG_VIA_N_INNER_PAD"],
            hfss.modeler.unions,
        )
        self.assertFalse(any(
            name.endswith("_COLUMN")
            or name in {
                "SIG_PAD_P", "SIG_PAD_N", "SIG_VIA_P_PAD", "SIG_VIA_N_PAD",
            }
            for union in hfss.modeler.unions
            for name in union
        ))
        self.assertIn(
            [
                "SIG_SLOT_ANTIPAD_L2",
                "SIG_SLOT_ANTIPAD_L2_N_CIRCLE",
                "SIG_SLOT_ANTIPAD_L2_NECK_NEG_X",
                "SIG_SLOT_ANTIPAD_L2_NECK_POS_X",
            ],
            hfss.modeler.unions,
        )
        self.assertEqual(
            "VIA_X_POSITION+2*GND_RETURN_VIA_PITCH",
            hfss.modeler.cylinder_args["GND_VIA_L_003_COLUMN"][1][0],
        )
        self.assertEqual([{
            "frequency": "60GHz", "boundary": "Radiation", "apply_infinite_ground": False,
        }], hfss.open_regions)
        self.assertEqual(1, len(hfss.setups))
        self.assertEqual(
            {"Low": "0.01GHz", "High": "60GHz"},
            hfss.setups[0].props["MultipleAdaptiveFreqsSetup"],
        )
        self.assertEqual(401, hfss.setups[0].sweeps[0].props["RangeCount"])

    def test_via_x_offset_is_pad_center_to_via_center_distance(self):
        gssg = GSSGConfig(
            signal_layer_name="L1",
            signal_pad_length="1.55mm",
            fanout_length="53.8um",
        )
        config = self.inner_config(
            via_pad_radius="0.0525mm",
            via_column_radius="0.030mm",
            via_x_offset="0.7221mm",
            d_via="0.3276mm",
        )
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, gssg, config)

        self.assertEqual("0.7221mm", hfss.variables["VIA_X_OFFSET"])
        self.assertEqual(
            "SIGNAL_PAD_LENGTH/2-VIA_X_OFFSET",
            hfss.variables["VIA_X_POSITION"],
        )
        self.assertEqual(
            "VIA_X_POSITION",
            hfss.modeler.cylinder_args["SIG_VIA_P_LASER_L1_L2_COLUMN"][1][0],
        )

    def test_via_pad_must_remain_inside_signal_pad(self):
        gssg = GSSGConfig(signal_layer_name="L1", signal_pad_length="1.55mm")
        config = self.inner_config(
            via_pad_radius="0.0525mm",
            via_column_radius="0.030mm",
            via_x_offset="0.73mm",
        )
        with self.assertRaisesRegex(ValueError, "signal-pad left edge"):
            inner_model._validate_inner_config(self.stackup, gssg, config)

    def test_pad_underlay_clearance_uses_x1_y_x2_through_selected_layer(self):
        config = self.inner_config(
            pad_void_x1="150um",
            pad_void_y="120um",
            pad_void_x2="110um",
            pad_void_end_layer_name="L3",
        )
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, self.gssg, config)

        names = set(hfss.modeler.created)
        self.assertTrue({
            "GF_PAD_UNDERCUT_L1",
            "GF_PAD_UNDERCUT_L2",
            "GF_PAD_UNDERCUT_L3",
        } <= names)
        self.assertFalse(any(
            name.startswith("GF_PAD_UNDERCUT_L4") for name in names
        ))
        origin, size, material = hfss.modeler.box_args["GF_PAD_UNDERCUT_L2"]
        self.assertEqual("-PAD_VOID_X2", origin[0])
        self.assertIn("PAD_VOID_Y", origin[1])
        self.assertEqual(
            "PAD_VOID_X2+SIGNAL_PAD_LENGTH+PAD_VOID_X1", size[0]
        )
        self.assertEqual(
            "2*SIGNAL_PAD_WIDTH+SS_GAP+2*PAD_VOID_Y", size[1]
        )
        self.assertEqual("vacuum", material)
        self.assertIn(("GND_L1", "GF_PAD_UNDERCUT_L1"), hfss.modeler.subtractions)
        self.assertIn(("GND_L2", "GF_PAD_UNDERCUT_L2"), hfss.modeler.subtractions)
        self.assertIn(("GND_L3", "GF_PAD_UNDERCUT_L3"), hfss.modeler.subtractions)

    def test_pad_underlay_clearance_is_disabled_when_end_layer_is_blank(self):
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, self.gssg, self.inner)
        self.assertFalse(any(
            name.startswith("GF_PAD_UNDERCUT_") for name in hfss.modeler.created
        ))

    def test_pad_underlay_limits_are_validated(self):
        with self.assertRaisesRegex(ValueError, "at least 150um"):
            inner_model._validate_inner_config(
                self.stackup,
                self.gssg,
                self.inner_config(
                    pad_void_x1="149um", pad_void_end_layer_name="L3"
                ),
            )
        with self.assertRaisesRegex(ValueError, "identify a copper layer"):
            inner_model._validate_inner_config(
                self.stackup,
                self.gssg,
                self.inner_config(pad_void_end_layer_name="PP_L2"),
            )

    def test_all_laser_stack_has_segmented_columns_and_every_layer_pad(self):
        for layer in self.stackup.layers:
            if layer.kind == "copper":
                layer.role = "signal" if layer.name == "L4" else "ground"
        hfss = _Hfss()
        inner_model._build_inner_stack(
            hfss, self.stackup, self.gssg,
            self.inner_config(
                inner_signal_layer_name="L4",
                upper_reference_layer_name="L3",
                lower_reference_layer_name="L5",
            ),
        )
        names = set(hfss.modeler.created)
        for pair in ("L1_L2", "L2_L3", "L3_L4"):
            self.assertIn(f"SIG_VIA_P_LASER_{pair}_COLUMN", names)
            self.assertIn(f"SIG_VIA_N_LASER_{pair}_COLUMN", names)
        self.assertTrue({
            "SIG_VIA_P_PAD", "SIG_VIA_P_L2_LASER_PAD",
            "SIG_VIA_P_L3_LASER_PAD", "SIG_VIA_P_INNER_PAD",
        } <= names)
        self.assertFalse(any(
            name.endswith("_COLUMN") and name in union
            for union in hfss.modeler.unions for name in union
        ))

    def test_mixed_laser_mechanical_laser_topology(self):
        for layer in self.stackup.layers:
            if layer.kind == "copper":
                layer.role = "signal" if layer.name == "L7" else "ground"
        config = self.inner_config(
            inner_signal_layer_name="L7",
            upper_reference_layer_name="L6",
            lower_reference_layer_name="L8",
            mechanical_via_enabled=True,
            mechanical_start_layer="L3",
        )
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, self.gssg, config)
        names = set(hfss.modeler.created)
        self.assertTrue({
            "SIG_VIA_P_LASER_L1_L2_COLUMN",
            "SIG_VIA_P_LASER_L2_L3_COLUMN",
            "SIG_VIA_P_MECHANICAL_L3_L6_COLUMN",
            "SIG_VIA_P_LASER_L6_L7_COLUMN",
        } <= names)
        self.assertTrue({
            "SIG_VIA_P_PAD", "SIG_VIA_P_L2_LASER_PAD",
            "SIG_VIA_P_L3_MECHANICAL_PAD",
            "SIG_VIA_P_L6_MECHANICAL_PAD", "SIG_VIA_P_INNER_PAD",
        } <= names)
        self.assertFalse(any(
            name.startswith("SIG_VIA_P_L4_") or name.startswith("SIG_VIA_P_L5_")
            for name in names
        ))
        self.assertEqual(
            "MECHANICAL_VIA_COLUMN_RADIUS",
            hfss.modeler.cylinder_args["SIG_VIA_P_MECHANICAL_L3_L6_COLUMN"][2],
        )
        self.assertEqual(
            "MECHANICAL_VIA_PAD_RADIUS",
            hfss.modeler.cylinder_args["SIG_VIA_P_L3_MECHANICAL_PAD"][2],
        )
        self.assertEqual(
            hfss.modeler.cylinder_args["SIG_VIA_P_LASER_L2_L3_COLUMN"][1][:2],
            hfss.modeler.cylinder_args["SIG_VIA_P_MECHANICAL_L3_L6_COLUMN"][1][:2],
        )

    def test_selectable_mechanical_end_supports_multiple_final_lasers(self):
        for layer in self.stackup.layers:
            if layer.kind == "copper":
                layer.role = "signal" if layer.name == "L7" else "ground"
        config = self.inner_config(
            inner_signal_layer_name="L7",
            upper_reference_layer_name="L6",
            lower_reference_layer_name="L8",
            mechanical_via_enabled=True,
            mechanical_start_layer="L3",
            mechanical_end_layer="L5",
        )
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, self.gssg, config)
        names = set(hfss.modeler.created)
        self.assertTrue({
            "SIG_VIA_P_MECHANICAL_L3_L5_COLUMN",
            "SIG_VIA_P_LASER_L5_L6_COLUMN",
            "SIG_VIA_P_LASER_L6_L7_COLUMN",
        } <= names)
        self.assertNotIn("SIG_VIA_P_MECHANICAL_L3_L6_COLUMN", names)

    def test_mechanical_end_can_be_the_breakout_layer(self):
        for layer in self.stackup.layers:
            if layer.kind == "copper":
                layer.role = "signal" if layer.name == "L7" else "ground"
        config = self.inner_config(
            inner_signal_layer_name="L7",
            upper_reference_layer_name="L6",
            lower_reference_layer_name="L8",
            mechanical_via_enabled=True,
            mechanical_start_layer="L3",
            mechanical_end_layer="L7",
        )
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, self.gssg, config)
        names = set(hfss.modeler.created)
        self.assertIn("SIG_VIA_P_MECHANICAL_L3_L7_COLUMN", names)
        self.assertFalse(any(
            name.startswith("SIG_VIA_P_LASER_L3_")
            or name.startswith("SIG_VIA_P_LASER_L4_")
            or name.startswith("SIG_VIA_P_LASER_L5_")
            or name.startswith("SIG_VIA_P_LASER_L6_")
            for name in names
        ))

    def test_layer_antipad_override_round_trip_and_slot_variables(self):
        config = inner_model.InnerGFConfig.from_dict({
            "inner_signal_layer_name": "L2",
            "upper_reference_layer_name": "L1",
            "lower_reference_layer_name": "L3",
            "via_antipad_x": "11mil",
            "layer_antipads": {"L2": {"radius": "12mil", "x": "13mil"}},
        })
        restored = inner_model.InnerGFConfig.from_dict(config.to_dict())
        self.assertEqual("L1", restored.upper_reference_layer_name)
        self.assertEqual("L3", restored.lower_reference_layer_name)
        self.assertEqual(
            {"L2": {"radius": "12mil", "x": "13mil"}},
            restored.layer_antipads,
        )
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, self.gssg, restored)
        self.assertEqual("12mil", hfss.variables["VIA_ANTIPAD_RADIUS_L2"])
        self.assertEqual("13mil", hfss.variables["VIA_ANTIPAD_X_L2"])
        neg_origin, neg_size, _ = hfss.modeler.box_args[
            "SIG_SLOT_ANTIPAD_L2_NECK_NEG_X"
        ]
        pos_origin, pos_size, _ = hfss.modeler.box_args[
            "SIG_SLOT_ANTIPAD_L2_NECK_POS_X"
        ]
        self.assertEqual("(VIA_X_POSITION)-VIA_ANTIPAD_X_L2", neg_origin[0])
        self.assertEqual("VIA_ANTIPAD_X_L2", neg_size[0])
        self.assertEqual("VIA_X_POSITION", pos_origin[0])
        self.assertEqual("VIA_ANTIPAD_X_L2", pos_size[0])

    def test_reference_layers_are_mandatory_ground_and_bracketing(self):
        cases = (
            (
                inner_model.InnerGFConfig(lower_reference_layer_name="L3"),
                "upper_reference_layer_name",
            ),
            (
                inner_model.InnerGFConfig(upper_reference_layer_name="L1"),
                "lower_reference_layer_name",
            ),
            (
                self.inner_config(upper_reference_layer_name="PP_L1"),
                "must be a copper layer",
            ),
            (
                self.inner_config(upper_reference_layer_name="L2"),
                "must be a ground copper layer",
            ),
            (
                self.inner_config(
                    upper_reference_layer_name="L3",
                    lower_reference_layer_name="L4",
                ),
                "must bracket",
            ),
            (
                self.inner_config(
                    upper_reference_layer_name="L3",
                    lower_reference_layer_name="L1",
                ),
                "must bracket",
            ),
        )
        for config, message in cases:
            with self.subTest(config=config, message=message):
                with self.assertRaisesRegex(ValueError, message):
                    inner_model._validate_inner_config(
                        self.stackup, self.gssg, config
                    )

    def test_analysis_generation_can_be_disabled(self):
        inner = self.inner_config(
            create_open_region=False, create_setup=False, create_sweep=False,
        )
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, self.gssg, inner)
        self.assertEqual([], hfss.open_regions)
        self.assertEqual([], hfss.setups)

    def test_custom_differential_and_common_impedance_drive_both_ports(self):
        self.stackup.differential_impedance = 102.0
        self.stackup.common_impedance = 29.0
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, self.gssg, self.inner)
        self.assertEqual("102.0", hfss.variables["GF_DIFFERENTIAL_IMPEDANCE"])
        self.assertEqual("29.0", hfss.variables["GF_COMMON_IMPEDANCE"])
        self.assertEqual(2, len(hfss.pairs))
        for pair in hfss.pairs:
            self.assertEqual(102.0, pair["differential_reference"])
            self.assertEqual(29.0, pair["common_reference"])

    def test_gnd_pad_return_via_count_is_configurable(self):
        inner = self.inner_config(
            gnd_return_via_count=5, gnd_return_via_pitch="0.3mm",
        )
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, self.gssg, inner)
        names = {name for name in hfss.modeler.created if name.startswith("GND_VIA_")}
        self.assertEqual(10, len(names))
        self.assertIn("GND_VIA_R_005_COLUMN", names)
        self.assertEqual("0.3mm", hfss.variables["GND_RETURN_VIA_PITCH"])

    def test_inner_trace_return_vias_can_be_disabled(self):
        self.stackup.return_vias_enabled = False
        hfss = _Hfss()
        inner_model._build_inner_stack(hfss, self.stackup, self.gssg, self.inner)
        self.assertFalse(any(
            name.startswith("INNER_RETURN_VIA_") for name in hfss.modeler.created
        ))

    def test_l4_return_vias_follow_selected_references(self):
        for layer in self.stackup.layers:
            if layer.kind == "copper":
                layer.role = "signal" if layer.name == "L4" else "ground"
        hfss = _Hfss()
        inner_model._build_inner_stack(
            hfss, self.stackup, self.gssg,
            self.inner_config(
                inner_signal_layer_name="L4",
                upper_reference_layer_name="L2",
                lower_reference_layer_name="L6",
            ),
        )
        _, origin, _, height = hfss.modeler.cylinder_args["INNER_RETURN_VIA_L_001_COLUMN"]
        self.assertEqual("4", hfss.variables["INNER_SIGNAL_LAYER"])
        self.assertEqual("2", hfss.variables["UPPER_REFERENCE_LAYER"])
        self.assertEqual("6", hfss.variables["LOWER_REFERENCE_LAYER"])
        self.assertEqual(hfss.variables["LOWER_REF_Z"], origin[2])
        self.assertIn("L2_H", height)
        self.assertEqual(
            ["GND_L6", "GND_L5", "GND_L4", "GND_L3", "GND_L2"],
            hfss.wave_ports[0][1]["reference"],
        )
        self.assertEqual(hfss.variables["LOWER_REF_Z"], hfss.variables["INNER_PORT_Z0"])
        self.assertIn("L2_H", hfss.variables["INNER_PORT_Z1"])
        gnd_via = hfss.modeler.cylinder_args["GND_VIA_L_001_COLUMN"]
        self.assertEqual(hfss.variables["LOWER_REF_Z"], gnd_via[1][2])

        names = set(hfss.modeler.created)
        self.assertTrue({
            "SKIPPED_REF_L3_TRACE_CLEARANCE",
            "SKIPPED_REF_L5_TRACE_CLEARANCE",
        } <= names)
        self.assertFalse(any("FANOUT_CLEARANCE" in name for name in names))
        self.assertFalse(any(
            name.startswith("SKIPPED_REF_L2_") or name.startswith("SKIPPED_REF_L6_")
            for name in names
        ))
        self.assertEqual(
            "S_LINE+2*W_LINE+2*G_LINE",
            hfss.modeler.box_args["SKIPPED_REF_L3_TRACE_CLEARANCE"][1][1],
        )
        self.assertEqual(
            "VIA_X_POSITION-BOARD_X0",
            hfss.modeler.box_args["SKIPPED_REF_L5_TRACE_CLEARANCE"][1][0],
        )

    def test_external_inner_layer_is_rejected(self):
        stackup = eight_layer_example()
        for layer in stackup.layers:
            if layer.kind == "copper":
                layer.role = "signal" if layer.name == "L8" else "ground"
        with self.assertRaisesRegex(ValueError, "must not be an external"):
            inner_model._validate_inner_config(
                stackup, self.gssg,
                self.inner_config(inner_signal_layer_name="L8"),
            )

    def test_pad_must_exceed_column(self):
        with self.assertRaisesRegex(ValueError, "must be greater"):
            inner_model._validate_inner_config(
                self.stackup, self.gssg,
                self.inner_config(via_pad_radius="0.05mm", via_column_radius="0.057mm"),
            )

    def test_antipad_must_exceed_pad(self):
        with self.assertRaisesRegex(ValueError, "must be greater"):
            inner_model._validate_inner_config(
                self.stackup, self.gssg,
                self.inner_config(via_pad_radius="0.127mm", via_antipad_radius="0.1mm"),
            )

    def test_sweep_requires_setup(self):
        with self.assertRaisesRegex(ValueError, "requires create_setup"):
            inner_model._validate_inner_config(
                self.stackup, self.gssg,
                self.inner_config(create_setup=False, create_sweep=True),
            )

    def test_invalid_mechanical_span_and_dimensions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one internal copper layer"):
            inner_model._validate_inner_config(
                self.stackup, self.gssg,
                self.inner_config(
                    mechanical_via_enabled=True,
                    mechanical_start_layer="L2",
                ),
            )

        for layer in self.stackup.layers:
            if layer.kind == "copper":
                layer.role = "signal" if layer.name == "L7" else "ground"
        with self.assertRaisesRegex(ValueError, "mechanical_start_layer"):
            inner_model._validate_inner_config(
                self.stackup, self.gssg,
                self.inner_config(
                    inner_signal_layer_name="L7",
                    upper_reference_layer_name="L6",
                    lower_reference_layer_name="L8",
                    mechanical_via_enabled=True,
                    mechanical_start_layer="L6",
                ),
            )
        with self.assertRaisesRegex(ValueError, "mechanical_end_layer"):
            inner_model._validate_inner_config(
                self.stackup, self.gssg,
                self.inner_config(
                    inner_signal_layer_name="L7",
                    upper_reference_layer_name="L6",
                    lower_reference_layer_name="L8",
                    mechanical_via_enabled=True,
                    mechanical_start_layer="L4",
                    mechanical_end_layer="L3",
                ),
            )
        with self.assertRaisesRegex(ValueError, "mechanical_pad_radius"):
            inner_model._validate_inner_config(
                self.stackup, self.gssg,
                self.inner_config(
                    inner_signal_layer_name="L7",
                    upper_reference_layer_name="L6",
                    lower_reference_layer_name="L8",
                    mechanical_via_enabled=True,
                    mechanical_start_layer="L3",
                    mechanical_column_radius="6mil",
                    mechanical_pad_radius="3mil",
                ),
            )

    def test_coplanar_unite_guard_rejects_via_columns(self):
        modeler = _Modeler()
        with self.assertRaisesRegex(RuntimeError, "VIA columns must remain separate"):
            inner_model._unite_coplanar_signal(
                modeler, ["SIG_PAD_P", "SIG_VIA_P_COLUMN"], "test path"
            )
        self.assertEqual([], modeler.unions)

    def test_gnd_pad_return_vias_must_stay_on_pad(self):
        with self.assertRaisesRegex(ValueError, "inside GND_PAD_LENGTH"):
            inner_model._validate_inner_config(
                self.stackup, self.gssg,
                self.inner_config(
                    gnd_return_via_count=10, gnd_return_via_pitch="0.4mm",
                ),
            )


if __name__ == "__main__":
    unittest.main()
