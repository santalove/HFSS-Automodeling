"""AEDT-free tests for :mod:`differential_multistage_via_model`."""

from __future__ import annotations

from math import hypot
import unittest

import differential_multistage_via_model as multi_model
from hfss_stackup_builder import eight_layer_example
from test_differential_via_model import _Hfss


class MultiStageDifferentialViaTests(unittest.TestCase):
    def setUp(self):
        self.stackup = eight_layer_example()
        self.config = multi_model.MultiStageDifferentialViaConfig()

    def _build(self, config=None, stackup=None):
        hfss = _Hfss()
        multi_model._build_geometry(
            hfss, stackup or self.stackup, config or self.config
        )
        return hfss

    def test_default_laser_bridge_mechanical_direct_output(self):
        hfss = self._build()
        names = set(hfss.modeler.created)
        self.assertTrue({
            "STAGE1_VIA_P_LASER_L2_L3_COLUMN",
            "STAGE1_VIA_P_LASER_L3_L4_COLUMN",
            "STAGE1_VIA_N_LASER_L2_L3_COLUMN",
            "STAGE1_VIA_N_LASER_L3_L4_COLUMN",
            "STAGE2_VIA_P_MECHANICAL_L4_L7_COLUMN",
            "STAGE2_VIA_N_MECHANICAL_L4_L7_COLUMN",
        } <= names)
        self.assertTrue({
            "START_VIA_P_PAD", "STAGE1_VIA_P_L3_LASER_PAD",
            "STAGE1_TRANSFER_VIA_P_PAD",
            "STAGE2_TRANSFER_VIA_P_MECHANICAL_PAD",
            "STAGE2_VIA_P_MECHANICAL_END_PAD",
            "TRANSFER_BRIDGE_P", "TRANSFER_BRIDGE_N",
        } <= names)
        self.assertFalse(any(
            name.startswith("STAGE2_VIA_P_L5_") and name.endswith("_PAD")
            for name in names
        ))
        self.assertFalse(any(
            name.startswith("STAGE2_VIA_P_L6_") and name.endswith("_PAD")
            for name in names
        ))
        self.assertEqual(
            "VIA_PAD_RADIUS+BRIDGE_CLEAR_LENGTH+MECHANICAL_VIA_PAD_RADIUS",
            hfss.variables["STAGE2_X"],
        )
        self.assertEqual("0.5mm", hfss.variables["STAGE1_D_VIA"])
        self.assertEqual("0.8mm", hfss.variables["STAGE2_D_VIA"])
        self.assertEqual("0.5mm", hfss.variables["BRIDGE_CLEAR_LENGTH"])
        self.assertEqual("0.1mm", hfss.variables["BRIDGE_WIDTH"])

        signal_unions = [
            union for union in hfss.modeler.unions
            if any("TRACE_" in name or "TRANSFER_BRIDGE_" in name for name in union)
            and not any("CLEARANCE" in name for name in union)
        ]
        self.assertEqual(6, len(signal_unions))
        self.assertIn([
            "STAGE1_TRANSFER_VIA_P_PAD", "TRANSFER_BRIDGE_P",
            "STAGE2_TRANSFER_VIA_P_MECHANICAL_PAD",
        ], signal_unions)
        self.assertIn([
            "END_TRACE_P", "END_FANOUT_P", "STAGE2_VIA_P_MECHANICAL_END_PAD",
        ], signal_unions)
        self.assertFalse(any(
            name.endswith("_COLUMN") for union in signal_unions for name in union
        ))
        self.assertEqual(2, len(hfss.wave_ports))
        self.assertEqual({"Diff1", "Diff2"}, {
            item["differential_mode"] for item in hfss.pairs
        })

    def test_bridge_is_parallelogram_and_clearance_uses_transfer_antipad(self):
        hfss = self._build()
        signal_points = hfss.modeler.polyline_args["TRANSFER_BRIDGE_P"][0]
        clearance_points = hfss.modeler.polyline_args[
            "TRANSFER_BRIDGE_P_CLEARANCE"
        ][0]
        self.assertEqual("0mm", signal_points[0][0])
        self.assertEqual("STAGE2_X", signal_points[2][0])
        self.assertIn("STAGE1_D_VIA", signal_points[0][1])
        self.assertIn("STAGE2_D_VIA", signal_points[2][1])
        self.assertIn("BRIDGE_WIDTH", signal_points[0][1])
        self.assertIn("2*VIA_ANTIPAD_RADIUS_L4", clearance_points[0][1])
        self.assertIn([
            "STAGE1_L4_SIG_SLOT_ANTIPAD",
            "STAGE2_L4_SIG_SLOT_ANTIPAD",
            "TRANSFER_BRIDGE_P_CLEARANCE",
            "TRANSFER_BRIDGE_N_CLEARANCE",
        ], hfss.modeler.unions)
        self.assertIn(
            ("GND_L4", "STAGE1_L4_SIG_SLOT_ANTIPAD"),
            hfss.modeler.subtractions,
        )

    def test_optional_final_laser_stack(self):
        config = multi_model.MultiStageDifferentialViaConfig(
            route_layers=["L2", "L4", "L7", "L8"],
            end_line=multi_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L7", lower_reference_layer_name="",
            ),
        )
        hfss = self._build(config)
        names = set(hfss.modeler.created)
        self.assertTrue({
            "STAGE2_VIA_P_LASER_L7_L8_COLUMN",
            "STAGE2_VIA_N_LASER_L7_L8_COLUMN",
            "END_VIA_P_PAD", "END_VIA_N_PAD",
            "STAGE2_VIA_P_MECHANICAL_END_PAD",
        } <= names)
        self.assertEqual(
            "VIA_PAD_RADIUS",
            hfss.modeler.cylinder_args["END_VIA_P_PAD"][2],
        )
        self.assertEqual(
            "MECHANICAL_VIA_PAD_RADIUS",
            hfss.modeler.cylinder_args["STAGE2_VIA_P_MECHANICAL_END_PAD"][2],
        )
        self.assertIn(
            ["END_TRACE_P", "END_FANOUT_P", "END_VIA_P_PAD"],
            hfss.modeler.unions,
        )

    def test_custom_l10_mechanical_end_and_deeper_output(self):
        stackup = eight_layer_example()
        for layer in stackup.layers:
            if layer.name == "L7":
                layer.name = "L10"
            elif layer.name == "L8":
                layer.name = "L11"
        direct = multi_model.MultiStageDifferentialViaConfig(
            route_layers=["L2", "L4", "L10", "L10"],
            end_line=multi_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L6", lower_reference_layer_name="L11",
            ),
        )
        direct_hfss = self._build(direct, stackup)
        self.assertIn(
            "STAGE2_VIA_P_MECHANICAL_L4_L10_COLUMN",
            direct_hfss.modeler.created,
        )
        extended = multi_model.MultiStageDifferentialViaConfig(
            route_layers=["L2", "L4", "L10", "L11"],
            end_line=multi_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L10", lower_reference_layer_name="",
            ),
        )
        extended_hfss = self._build(extended, stackup)
        self.assertIn(
            "STAGE2_VIA_P_LASER_L10_L11_COLUMN",
            extended_hfss.modeler.created,
        )

    def test_ellipse_points_are_closed_and_respect_max_pitch(self):
        points = multi_model._ellipse_return_points(1.2, 0.7, 0.254)
        self.assertGreaterEqual(len(points), 8)
        chords = [
            hypot(
                points[(index + 1) % len(points)][0] - point[0],
                points[(index + 1) % len(points)][1] - point[1],
            )
            for index, point in enumerate(points)
        ]
        self.assertLessEqual(max(chords), 0.254001)
        for x, y in points:
            self.assertAlmostEqual((x / 1.2) ** 2 + (y / 0.7) ** 2, 1.0, places=4)

    def test_return_fence_full_columns_avoid_all_two_stage_voids(self):
        start, transfer, _, output, dimensions = multi_model._validate_config(
            self.stackup, self.config
        )
        expansion = (
            dimensions["local_return_clearance"]
            + dimensions["return_column_radius"]
        )
        extent = max(
            dimensions["transition_via_antipad_radius"],
            dimensions["transition_via_antipad_x"],
        )
        center_x = dimensions["stage2_x"] / 2
        candidates = [
            (center_x + x, y)
            for x, y in multi_model._ellipse_return_points(
                center_x + extent + expansion,
                dimensions["stage2_d_via"] / 2
                + dimensions["transition_via_antipad_radius"] + expansion,
                dimensions["local_return_pitch"],
            )
        ]
        accepted = [
            point for point in candidates
            if multi_model._multistage_return_point_allowed(
                point, dimensions, start.name, transfer.name, output.name
            )
        ]
        self.assertEqual(8, len(accepted))
        self.assertLess(len(accepted), len(candidates))

    def test_layer_antipad_round_trip_and_variables(self):
        config = multi_model.MultiStageDifferentialViaConfig.from_dict({
            "route_layers": ["L2", "L4", "L7", "L7"],
            "layer_antipads": {"L4": {"radius": "12mil", "x": "13mil"}},
        })
        restored = multi_model.MultiStageDifferentialViaConfig.from_dict(
            config.to_dict()
        )
        self.assertEqual(
            {"L4": {"radius": "12mil", "x": "13mil"}},
            restored.layer_antipads,
        )
        hfss = self._build(restored)
        self.assertEqual("12mil", hfss.variables["VIA_ANTIPAD_RADIUS_L4"])
        self.assertEqual("13mil", hfss.variables["VIA_ANTIPAD_X_L4"])

    def test_separated_output_reference_controls_clearance_port_and_return_span(self):
        config = multi_model.MultiStageDifferentialViaConfig(
            end_line=multi_model.DifferentialLineEndConfig(
                upper_reference_layer_name="L3",
                lower_reference_layer_name="L8",
            ),
        )
        restored = multi_model.MultiStageDifferentialViaConfig.from_dict(
            config.to_dict()
        )
        self.assertEqual("L3", restored.end_line.upper_reference_layer_name)
        self.assertEqual("L8", restored.end_line.lower_reference_layer_name)
        hfss = self._build(restored)
        names = set(hfss.modeler.created)
        for layer in ("L4", "L5", "L6"):
            prefix = f"END_SKIPPED_REF_{layer}"
            self.assertIn(f"{prefix}_TRACE_CLEARANCE", names)
            self.assertIn(f"{prefix}_FANOUT_CLEARANCE", names)
            self.assertIn(f"{prefix}_FANOUT_CLEARANCE_MIRROR", names)
        self.assertFalse(any(name.startswith("END_SKIPPED_REF_L3_") for name in names))
        self.assertFalse(any(name.startswith("END_SKIPPED_REF_L8_") for name in names))
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

    def test_invalid_layer_order_pitch_and_dimensions_are_rejected(self):
        cases = (
            (
                multi_model.MultiStageDifferentialViaConfig(
                    route_layers=["L4", "L2", "L7", "L7"]
                ),
                "Layer order",
            ),
            (
                multi_model.MultiStageDifferentialViaConfig(
                    route_layers=["L2", "L4", "L7"]
                ),
                "exactly four",
            ),
            (
                multi_model.MultiStageDifferentialViaConfig(
                    route_layers=["L2", "L4", "L7", "L7"],
                    stage2_d_via="0.5mm",
                ),
                "greater than stage1",
            ),
            (
                multi_model.MultiStageDifferentialViaConfig(
                    route_layers=["L2", "L4", "L7", "L7"],
                    bridge_width="0mm",
                ),
                "bridge_width must be positive",
            ),
        )
        for config, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    multi_model._validate_config(self.stackup, config)


if __name__ == "__main__":
    unittest.main()
