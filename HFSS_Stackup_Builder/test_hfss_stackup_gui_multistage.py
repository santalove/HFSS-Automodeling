"""Offscreen GUI checks for the two-stage Differential VIA integration."""

from __future__ import annotations

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from differential_multistage_via_model import MultiStageDifferentialViaConfig
from differential_via_model import DifferentialViaConfig
from gf_gssg_model import GSSGConfig
from gf_inner_model import InnerGFConfig
from hfss_stackup_builder import StackupConfig, eight_layer_example
from hfss_stackup_gui import BuildWorker, MainWindow
from cap_pad_model import CapPadConfig


class MultiStageViaGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = MainWindow()

    def tearDown(self) -> None:
        self.window.close()
        self.app.processEvents()

    def _select_two_stage(self) -> None:
        self.window.via_mode.setCurrentIndex(
            self.window.via_mode.findData("multistage")
        )
        self.app.processEvents()

    def test_tabs_mode_visibility_and_default_layers(self) -> None:
        self.assertEqual(
            ["Stackup differential", "GF", "Differential VIA", "CAP"],
            [
                self.window.tabs.tabText(index)
                for index in range(self.window.tabs.count())
            ],
        )
        self.assertEqual("single", self.window.via_mode.currentData())
        self._select_two_stage()
        self.assertFalse(self.window.multistage_via_layer_group.isHidden())
        self.assertTrue(self.window.single_via_layer_group.isHidden())
        self.assertEqual(
            ["L2", "L4", "L7", "L7"],
            [combo.currentText() for combo in self.window.multistage_layer_combos],
        )

    def test_line_deembed_and_cap_config_are_independent_and_round_trip(self) -> None:
        self.assertEqual("-5mm", self.window.stackup_deembed.text())
        self.assertTrue(self.window.stackup_tdr_report.isChecked())
        self.window.stackup_deembed.setText("-6mm")
        line = self.window.config_from_ui()
        self.assertEqual("-6mm", StackupConfig.from_dict(line.to_dict()).port_deembed_distance)
        self.window.cap_fields["pad_center_pitch"].setText("327um")
        self.window.cap_fields["input_d_via"].setText("390um")
        self.window.cap_fields["output_d_via"].setText("410um")
        for key in ("left_pad_length", "left_pad_width", "right_pad_length", "right_pad_width"):
            self.window.cap_fields[key].setText("203um")
        self.window.cap_mechanical_checks["output"].setChecked(True)
        self.window.cap_mechanical_combos["output"]["start"].setCurrentText("L2")
        self.window.cap_mechanical_combos["output"]["end"].setCurrentText("L4")
        for row in range(self.window.cap_antipad_table.rowCount()):
            if self.window.cap_antipad_table.item(row, 0).text() == "L3":
                self.window.cap_antipad_table.item(row, 1).setText("150um")
        config = self.window.cap_pad_config_from_ui()
        self.assertEqual("327um", config.pad_center_pitch)
        self.assertEqual("390um", config.input_d_via)
        self.assertEqual("410um", config.output_d_via)
        self.assertNotIn("left_via_y_offset", self.window.cap_fields)
        self.assertTrue(config.output_via.mechanical_enabled)
        self.assertEqual("L4", config.output_via.mechanical_end_layer)
        self.assertEqual("150um", config.input_via.layer_antipads["L3"]["radius"])
        self.assertEqual("0.254mm", config.input_via.layer_antipads["L3"]["x"])
        self.assertEqual("203um", config.left_pad_length)
        self.assertEqual("50um", config.left_pad_corner_radius)
        self.assertEqual("373um", config.pair_pitch)
        self.assertEqual("4mil", config.layer_pad_voids["L1"]["radius"])
        self.assertTrue(config.layer_pad_voids["L2"]["enabled"])
        self.assertTrue(config.solder_enabled)
        self.assertEqual("tin", config.solder_material)
        self.assertEqual("3mil", config.solder_height)
        self.assertTrue(config.solder_mask_enabled)
        self.assertTrue(config.real_component_enabled)
        self.assertEqual("", config.real_component_file)
        self.assertFalse(config.lumped_rlc_enabled)
        self.assertEqual("0ohm", config.lumped_resistance)
        self.assertEqual("0nH", config.lumped_inductance)
        self.assertEqual("10MHz", config.rlc_fit_start)
        self.assertEqual("3GHz", config.rlc_fit_stop)
        self.assertFalse(config.comparison_designs_enabled)
        self.assertEqual("0.1uF", config.lumped_capacitance)
        self.assertEqual("3.3", config.solder_mask_dk)
        self.assertEqual("0.02", config.solder_mask_df)
        self.assertEqual("15um", config.solder_mask_copper_thickness)
        self.assertEqual("25um", config.solder_mask_gap_thickness)
        self.assertEqual("10um", config.solder_mask_transition_width)
        self.assertEqual("2mil", config.solder_mask_opening_expansion)
        self.assertEqual("pair_window", config.solder_mask_opening_mode)
        self.assertTrue(config.input_via.follow_solder_mask_antipad)
        self.assertTrue(config.output_via.follow_solder_mask_antipad)
        self.assertEqual(5, self.window.cap_antipad_table.columnCount())
        self.assertEqual(5, self.window.cap_void_table.columnCount())
        self.assertEqual(config.to_dict(), type(config).from_dict(config.to_dict()).to_dict())

    def test_cap_physical_and_ideal_modes_are_mutually_exclusive_in_ui(self) -> None:
        self.assertTrue(self.window.cap_real_component_enabled.isChecked())
        self.assertFalse(self.window.cap_rlc_enabled.isChecked())
        self.window.cap_comparison_enabled.setChecked(True)
        self.app.processEvents()
        self.assertFalse(self.window.cap_real_component_enabled.isEnabled())
        self.assertFalse(self.window.cap_rlc_enabled.isEnabled())
        self.assertTrue(
            self.window.cap_pad_config_from_ui().comparison_designs_enabled
        )

    def test_cap_s2p_fit_populates_series_rlc_fields(self) -> None:
        result = SimpleNamespace(
            resistance_text="0.0944ohm",
            inductance_text="0.2128nH",
            capacitance_text="0.08585uF",
            point_count=6,
            rms_error_ohm=0.065,
        )
        with patch(
            "hfss_stackup_gui.QFileDialog.getOpenFileName",
            return_value=("measured.s2p", ""),
        ), patch(
            "hfss_stackup_gui.fit_series_rlc", return_value=result
        ) as fit, patch("hfss_stackup_gui.QMessageBox.information"):
            self.window.fit_cap_rlc_from_s2p()
        fit.assert_called_once_with("measured.s2p", "10MHz", "3GHz")
        self.assertEqual("0.0944ohm", self.window.cap_rlc_resistance.text())
        self.assertEqual("0.2128nH", self.window.cap_rlc_inductance.text())
        self.assertEqual("0.08585uF", self.window.cap_rlc_capacitance.text())
        self.assertEqual("measured.s2p", self.window.cap_rlc_source.text())
        self.assertTrue(self.window.cap_rlc_enabled.isChecked())
        self.assertFalse(self.window.cap_real_component_enabled.isChecked())
        self.window.cap_rlc_enabled.setChecked(True)
        self.app.processEvents()
        self.assertFalse(self.window.cap_real_component_enabled.isChecked())
        self.assertTrue(self.window.cap_rlc_enabled.isChecked())
        self.window.cap_real_component_enabled.setChecked(True)
        self.app.processEvents()
        self.assertTrue(self.window.cap_real_component_enabled.isChecked())
        self.assertFalse(self.window.cap_rlc_enabled.isChecked())

    def test_legacy_json_cap_defaults_and_route_dependent_choices(self) -> None:
        legacy_stack = eight_layer_example().to_dict()
        legacy_stack.pop("port_deembed_distance", None)
        legacy_stack.pop("create_tdr_report", None)
        self.window.load_config_into_ui(
            StackupConfig.from_dict(legacy_stack), GSSGConfig(), InnerGFConfig(),
            DifferentialViaConfig(), MultiStageDifferentialViaConfig(),
            CapPadConfig.from_dict({}),
        )
        self.assertEqual("-5mm", self.window.stackup_deembed.text())
        self.assertEqual(["L3", "L5"], [
            self.window.cap_layer_combos[side].currentText()
            for side in ("input", "output")
        ])
        self.assertIn("L1", [
            self.window.cap_layer_combos["input"].itemText(index)
            for index in range(self.window.cap_layer_combos["input"].count())
        ])
        self.assertFalse(self.window.cap_solder_enabled.isChecked())
        self.assertFalse(self.window.cap_mask_enabled.isChecked())
        self.window.cap_layer_combos["input"].setCurrentText("L4")
        self.app.processEvents()
        self.assertIn("L3", [
            self.window.cap_mechanical_combos["input"]["start"].itemText(index)
            for index in range(self.window.cap_mechanical_combos["input"]["start"].count())
        ])
        self.assertIn("L5", [
            self.window.cap_reference_combos["input"]["lower"].itemText(index)
            for index in range(self.window.cap_reference_combos["input"]["lower"].count())
        ])

    def test_cap_skipped_reference_antipad_is_editable_and_round_trips(self) -> None:
        output_refs = self.window.cap_reference_combos["output"]
        output_refs["upper"].setCurrentText("L3")
        output_refs["lower"].setCurrentText("L7")
        self.app.processEvents()

        rows = {
            self.window.cap_antipad_table.item(row, 0).text(): row
            for row in range(self.window.cap_antipad_table.rowCount())
        }
        l6_row = rows["L6"]
        l7_row = rows["L7"]
        self.assertNotEqual(
            "--", self.window.cap_antipad_table.item(l6_row, 3).text()
        )
        self.assertEqual(
            "--", self.window.cap_antipad_table.item(l7_row, 3).text()
        )

        self.window.cap_antipad_table.item(l6_row, 3).setText("180um")
        self.window.cap_antipad_table.item(l6_row, 4).setText("170um")
        rebuilt = self.window.cap_pad_config_from_ui()
        self.assertEqual(
            {"radius": "180um", "x": "170um"},
            rebuilt.output_via.layer_antipads["L6"],
        )

    def test_cap_mounting_side_switches_default_voids_to_bottom_two_layers(self) -> None:
        self.window.cap_component_side.setCurrentIndex(
            self.window.cap_component_side.findData("bottom")
        )
        self.app.processEvents()
        config = self.window.cap_pad_config_from_ui()
        self.assertEqual("bottom", config.component_side)
        enabled = {layer for layer, settings in config.layer_pad_voids.items() if settings["enabled"]}
        self.assertEqual({"L7", "L8"}, enabled)
        self.assertEqual("730um", config.layer_pad_voids["L8"]["x"])
        self.assertEqual("4mil", config.layer_pad_voids["L7"]["radius"])
        self.assertNotIn("L8", [
            self.window.cap_layer_combos["input"].itemText(index)
            for index in range(self.window.cap_layer_combos["input"].count())
        ])

    def test_language_selector_switches_chinese_without_changing_config_data(self) -> None:
        before = self.window.config_from_ui().to_dict()
        self.window.language_combo.setCurrentIndex(
            self.window.language_combo.findData("zh_CN")
        )
        self.app.processEvents()
        self.assertEqual("叠层差分线", self.window.tabs.tabText(0))
        self.assertEqual("差分过孔", self.window.tabs.tabText(2))
        self.assertEqual("生成并打开 AEDT", self.window.stackup_build.text())
        self.assertEqual("单级过孔", self.window.via_mode.currentText())
        self.assertEqual("single", self.window.via_mode.currentData())
        self.assertEqual(before, self.window.config_from_ui().to_dict())

        self.window.language_combo.setCurrentIndex(
            self.window.language_combo.findData("en")
        )
        self.app.processEvents()
        self.assertEqual("Stackup differential", self.window.tabs.tabText(0))
        self.assertEqual("Generate and open AEDT", self.window.stackup_build.text())

    def test_custom_differential_and_common_impedance_round_trip(self) -> None:
        self.window.diff_z.setText("101.5")
        self.window.common_z.setText("28.75")
        self.app.processEvents()
        config = self.window.config_from_ui()
        self.assertEqual(101.5, config.differential_impedance)
        self.assertEqual(28.75, config.common_impedance)
        restored = StackupConfig.from_dict(config.to_dict())
        self.assertEqual(101.5, restored.differential_impedance)
        self.assertEqual(28.75, restored.common_impedance)

    def test_gf_g_line_is_editable_and_round_trips(self) -> None:
        self.assertIn("g_line", self.window.gssg_fields)
        self.assertEqual("40um", self.window.gssg_fields["g_line"].text())

        self.window.gssg_fields["g_line"].setText("75um")
        rebuilt = self.window.gssg_config_from_ui()
        self.assertEqual("75um", rebuilt.g_line)

        imported = GSSGConfig(g_line="88um")
        self.window.load_config_into_ui(
            eight_layer_example(),
            imported,
            InnerGFConfig(),
            DifferentialViaConfig(),
            MultiStageDifferentialViaConfig(),
        )
        self.assertEqual("88um", self.window.gssg_fields["g_line"].text())
        self.assertEqual("88um", self.window.gssg_config_from_ui().g_line)

    def test_gf_pad_underlay_fields_and_end_layer_round_trip(self) -> None:
        self.window.gssg_layer.setCurrentText("L5")
        self.app.processEvents()
        self.assertEqual(
            ["", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"],
            [
                self.window.inner_pad_void_end_layer.itemText(index)
                for index in range(self.window.inner_pad_void_end_layer.count())
            ],
        )
        self.window.inner_pad_void_fields["pad_void_x1"].setText("150um")
        self.window.inner_pad_void_fields["pad_void_y"].setText("122um")
        self.window.inner_pad_void_fields["pad_void_x2"].setText("111um")
        self.window.inner_pad_void_end_layer.setCurrentText("L3")
        rebuilt = self.window.inner_gf_config_from_ui()
        restored = InnerGFConfig.from_dict(rebuilt.to_dict())
        self.assertEqual("150um", restored.pad_void_x1)
        self.assertEqual("122um", restored.pad_void_y)
        self.assertEqual("111um", restored.pad_void_x2)
        self.assertEqual("L3", restored.pad_void_end_layer_name)

        self.window.language_combo.setCurrentIndex(
            self.window.language_combo.findData("zh_CN")
        )
        self.app.processEvents()
        labels = {label.text() for label in self.window.inner_pad_void_group.findChildren(type(self.window.gf_mode_help))}
        self.assertIn("铜层捞空到达层（留空=关闭）", labels)

    def test_gf_and_single_via_mechanical_end_layers_are_selectable(self) -> None:
        self.window.gssg_layer.setCurrentText("L7")
        self.window.inner_mechanical_via_enabled.setChecked(True)
        self.app.processEvents()
        self.window.inner_mechanical_start_layer.setCurrentText("L3")
        self.app.processEvents()
        self.assertEqual(
            ["L4", "L5", "L6", "L7"],
            [
                self.window.inner_mechanical_end_layer.itemText(index)
                for index in range(self.window.inner_mechanical_end_layer.count())
            ],
        )
        self.window.inner_mechanical_end_layer.setCurrentText("L5")
        self.assertEqual("L5", self.window.inner_gf_config_from_ui().mechanical_end_layer)

        self.window.via_start_layer.setCurrentText("L2")
        self.window.via_end_layer.setCurrentText("L8")
        self.window.mechanical_via_enabled.setChecked(True)
        self.app.processEvents()
        self.window.mechanical_start_layer.setCurrentText("L3")
        self.app.processEvents()
        self.assertEqual(
            ["L4", "L5", "L6", "L7", "L8"],
            [
                self.window.mechanical_end_layer.itemText(index)
                for index in range(self.window.mechanical_end_layer.count())
            ],
        )
        self.window.mechanical_end_layer.setCurrentText("L5")
        self.assertEqual(
            "L5", self.window.differential_via_config_from_ui().mechanical_end_layer
        )

    def test_dynamic_output_filter_and_status(self) -> None:
        self._select_two_stage()
        output = self.window.multistage_layer_combos[3]
        self.assertEqual(
            ["L7", "L8"], [output.itemText(index) for index in range(output.count())]
        )
        self.assertIn("direct route-out", self.window.multistage_route_status.text())
        output.setCurrentText("L8")
        self.app.processEvents()
        self.assertIn("L7 -> L8", self.window.multistage_route_status.text())

    def test_custom_layer_name_is_available_in_physical_order(self) -> None:
        stackup = eight_layer_example()
        next(layer for layer in stackup.layers if layer.name == "L7").name = "L10"
        config = MultiStageDifferentialViaConfig(
            route_layers=["L2", "L4", "L10", "L10"]
        )
        self.window.load_config_into_ui(
            stackup,
            GSSGConfig(signal_layer_name="L1"),
            InnerGFConfig(),
            DifferentialViaConfig(),
            config,
        )
        self._select_two_stage()
        self.assertEqual(
            ["L2", "L4", "L10", "L10"],
            [combo.currentText() for combo in self.window.multistage_layer_combos],
        )

    def test_hidden_layer_antipads_survive_ui_and_json_round_trip(self) -> None:
        config = MultiStageDifferentialViaConfig(
            layer_antipads={"L4": {"radius": "12mil", "x": "14mil"}}
        )
        self.window.load_config_into_ui(
            eight_layer_example(),
            GSSGConfig(signal_layer_name="L1"),
            InnerGFConfig(),
            DifferentialViaConfig(),
            config,
        )
        self._select_two_stage()
        rebuilt = self.window.multistage_via_config_from_ui()
        restored = MultiStageDifferentialViaConfig.from_dict(rebuilt.to_dict())
        self.assertEqual(
            {"L4": {"radius": "12mil", "x": "14mil"}},
            restored.layer_antipads,
        )

    def test_switching_modes_preserves_independent_shared_line_values(self) -> None:
        self.window.via_start_line_fields["trace_length"].setText("1.7mm")
        self._select_two_stage()
        self.window.via_start_line_fields["trace_length"].setText("2.3mm")
        self.window.via_mode.setCurrentIndex(self.window.via_mode.findData("single"))
        self.app.processEvents()
        self.assertEqual(
            "1.7mm", self.window.via_start_line_fields["trace_length"].text()
        )
        self._select_two_stage()
        self.assertEqual(
            "2.3mm", self.window.via_start_line_fields["trace_length"].text()
        )

    def test_stackup_reference_choices_follow_signal_and_legacy_json_is_blank(self) -> None:
        self.assertEqual(
            ["", "L1"],
            [
                self.window.stackup_upper_reference.itemText(index)
                for index in range(self.window.stackup_upper_reference.count())
            ],
        )
        self.assertEqual("L1", self.window.stackup_upper_reference.currentText())
        self.assertEqual("L3", self.window.stackup_lower_reference.currentText())

        self.window.signal_layer.setCurrentText("L4")
        self.app.processEvents()
        self.assertEqual(
            ["", "L1", "L2", "L3"],
            [
                self.window.stackup_upper_reference.itemText(index)
                for index in range(self.window.stackup_upper_reference.count())
            ],
        )
        self.assertEqual(
            ["", "L5", "L6", "L7", "L8"],
            [
                self.window.stackup_lower_reference.itemText(index)
                for index in range(self.window.stackup_lower_reference.count())
            ],
        )
        self.assertEqual("L1", self.window.stackup_upper_reference.currentText())
        self.assertEqual("", self.window.stackup_lower_reference.currentText())

        legacy_data = eight_layer_example().to_dict()
        legacy_data.pop("upper_reference_layer_name")
        legacy_data.pop("lower_reference_layer_name")
        self.window.load_config_into_ui(
            StackupConfig.from_dict(legacy_data),
            GSSGConfig(signal_layer_name="L1"),
            InnerGFConfig(),
            DifferentialViaConfig(),
            MultiStageDifferentialViaConfig(),
        )
        self.assertEqual("", self.window.stackup_upper_reference.currentText())
        self.assertEqual("", self.window.stackup_lower_reference.currentText())

    def test_via_reference_choices_preserve_valid_values_and_clear_invalid_values(self) -> None:
        start = self.window.via_reference_combos["start"]
        self.assertEqual("L1", start["upper"].currentText())
        self.assertEqual("L3", start["lower"].currentText())

        self.window.via_start_layer.setCurrentText("L4")
        self.app.processEvents()
        self.assertEqual("L1", start["upper"].currentText())
        self.assertEqual("", start["lower"].currentText())
        self.assertEqual(
            ["", "L5", "L6", "L7", "L8"],
            [start["lower"].itemText(index) for index in range(start["lower"].count())],
        )

        start["upper"].setCurrentText("L2")
        start["lower"].setCurrentText("L6")
        self.window.via_start_layer.setCurrentText("L5")
        self.app.processEvents()
        self.assertEqual("L2", start["upper"].currentText())
        self.assertEqual("L6", start["lower"].currentText())
        self.window.via_start_layer.setCurrentText("L2")
        self.app.processEvents()
        self.assertEqual("", start["upper"].currentText())
        self.assertEqual("L6", start["lower"].currentText())

    def test_legacy_via_json_does_not_auto_select_references(self) -> None:
        legacy_via = DifferentialViaConfig.from_dict({
            "route_layers": ["L2", "L4"],
            "start_line": {"trace_length": "1.5mm"},
            "end_line": {"trace_length": "1.5mm"},
        })
        self.window.load_config_into_ui(
            eight_layer_example(),
            GSSGConfig(signal_layer_name="L1"),
            InnerGFConfig(),
            legacy_via,
            MultiStageDifferentialViaConfig(),
        )
        for prefix in ("start", "end"):
            self.assertEqual(
                "", self.window.via_reference_combos[prefix]["upper"].currentText()
            )
            self.assertEqual(
                "", self.window.via_reference_combos[prefix]["lower"].currentText()
            )

    def test_stackup_and_via_generation_require_explicit_references(self) -> None:
        self.window.stackup_upper_reference.setCurrentText("")
        self.app.processEvents()
        with patch("hfss_stackup_gui.QMessageBox.warning") as warning:
            self.window.generate_project("stackup")
        self.assertIn("upper reference", warning.call_args.args[2])
        self.assertIsNone(self.window._worker)

        self.window.via_reference_combos["start"]["upper"].setCurrentText("")
        self.app.processEvents()
        with patch("hfss_stackup_gui.QMessageBox.warning") as warning:
            self.window.generate_project("differential_via")
        self.assertIn("upper reference", warning.call_args.args[2])
        self.assertIsNone(self.window._worker)

    def test_inner_reference_choices_are_blank_filtered_and_recomputed(self) -> None:
        self.assertEqual([""], [
            self.window.inner_upper_reference.itemText(index)
            for index in range(self.window.inner_upper_reference.count())
        ])
        self.window.gssg_layer.setCurrentText("L4")
        self.app.processEvents()
        self.assertEqual(
            ["", "L1", "L2", "L3"],
            [
                self.window.inner_upper_reference.itemText(index)
                for index in range(self.window.inner_upper_reference.count())
            ],
        )
        self.assertEqual(
            ["", "L5", "L6", "L7", "L8"],
            [
                self.window.inner_lower_reference.itemText(index)
                for index in range(self.window.inner_lower_reference.count())
            ],
        )
        self.assertEqual("", self.window.inner_upper_reference.currentText())
        self.assertEqual("", self.window.inner_lower_reference.currentText())

        self.window.inner_upper_reference.setCurrentText("L2")
        self.window.inner_lower_reference.setCurrentText("L6")
        self.window.gssg_layer.setCurrentText("L5")
        self.app.processEvents()
        self.assertEqual("L2", self.window.inner_upper_reference.currentText())
        self.assertEqual("L6", self.window.inner_lower_reference.currentText())
        self.window.gssg_layer.setCurrentText("L2")
        self.app.processEvents()
        self.assertEqual("", self.window.inner_upper_reference.currentText())
        self.assertEqual("L6", self.window.inner_lower_reference.currentText())

    def test_inner_reference_config_load_and_round_trip(self) -> None:
        configured = InnerGFConfig(
            inner_signal_layer_name="L4",
            upper_reference_layer_name="L2",
            lower_reference_layer_name="L6",
        )
        self.window.load_config_into_ui(
            eight_layer_example(),
            GSSGConfig(signal_layer_name="L4"),
            configured,
            DifferentialViaConfig(),
            MultiStageDifferentialViaConfig(),
        )
        rebuilt = self.window.inner_gf_config_from_ui()
        restored = InnerGFConfig.from_dict(rebuilt.to_dict())
        self.assertEqual("L2", restored.upper_reference_layer_name)
        self.assertEqual("L6", restored.lower_reference_layer_name)

        self.window.load_config_into_ui(
            eight_layer_example(),
            GSSGConfig(signal_layer_name="L4"),
            InnerGFConfig.from_dict({}),
            DifferentialViaConfig(),
            MultiStageDifferentialViaConfig(),
        )
        self.assertEqual("", self.window.inner_upper_reference.currentText())
        self.assertEqual("", self.window.inner_lower_reference.currentText())

    def test_inner_generation_requires_explicit_references(self) -> None:
        self.window.gssg_layer.setCurrentText("L2")
        self.app.processEvents()
        with patch("hfss_stackup_gui.QMessageBox.warning") as warning:
            self.window.generate_project("gf")
        warning.assert_called_once()
        self.assertIn("upper reference", warning.call_args.args[2])
        self.assertIsNone(self.window._worker)

    def test_worker_dispatches_two_stage_builder(self) -> None:
        config = MultiStageDifferentialViaConfig()
        worker = BuildWorker(
            mode="multistage_via",
            stackup=eight_layer_example(),
            output_path="two_stage.aedt",
            multistage_via=config,
        )
        completed: list[str] = []
        failures: list[str] = []
        worker.success.connect(completed.append)
        worker.failed.connect(failures.append)
        with patch(
            "hfss_stackup_gui.build_multistage_differential_via_project",
            return_value="two_stage.aedt",
        ) as build:
            worker.run()
        self.assertFalse(failures)
        self.assertEqual(["two_stage.aedt"], completed)
        build.assert_called_once_with(
            worker.stackup,
            config,
            "two_stage.aedt",
            keep_desktop_open=False,
            log_callback=worker.log.emit,
        )

    def test_worker_dispatches_cap_pcb_without_component_or_solver(self) -> None:
        cap = CapPadConfig()
        worker = BuildWorker(
            mode="cap_pad", stackup=eight_layer_example(),
            output_path="cap_test.aedt", cap_pad=cap,
        )
        completed, failures = [], []
        worker.success.connect(completed.append)
        worker.failed.connect(failures.append)
        with patch("hfss_stackup_gui.build_cap_pad_project", return_value="cap_test.aedt") as build:
            worker.run()
        self.assertFalse(failures)
        self.assertEqual(["cap_test.aedt"], completed)
        build.assert_called_once_with(
            worker.stackup, cap, "cap_test.aedt",
            keep_desktop_open=False, log_callback=worker.log.emit,
        )


if __name__ == "__main__":
    unittest.main()
