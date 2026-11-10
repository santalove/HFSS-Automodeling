"""AEDT-free tests for configurable stackup differential references."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hfss_stackup_builder as stack_model
from test_differential_via_model import _Hfss


class StackupReferenceTests(unittest.TestCase):
    def test_post_solve_tdr_is_diff1_only_and_does_not_solve(self):
        calls = []
        class FakeReportSetup:
            names = []
            def GetAllReportNames(self):
                return self.names
            def CreateReport(self, *args):
                calls.append(args)
                self.names.append(args[0])
            def DeleteReports(self, names):
                self.names = [name for name in self.names if name not in names]
        class FakePost:
            def export_report_to_csv(self, directory, name):
                path = Path(directory) / (name + ".csv")
                path.write_text('"Time [ps]","TDRZt(Diff1) []"\n' +
                                "".join(f"{index * 0.8},92\n" for index in range(501)))
                return str(path)
        class FakeHfss:
            post = FakePost()
            oreportsetup = FakeReportSetup()
            def get_setup(self, name):
                self._solved = getattr(self, "_solved", False)
                return SimpleNamespace(sweeps=[SimpleNamespace(name="Sweep", is_solved=self._solved)])
            def save_project(self):
                calls.append("saved")
        hfss = FakeHfss()
        with self.assertRaisesRegex(ValueError, "not solved"):
            stack_model.create_stackup_tdr_report(hfss)
        hfss._solved = True
        self.assertEqual("Auto TDR Diff1", stack_model.create_stackup_tdr_report(hfss))
        self.assertEqual(["TDRZt(Diff1)"], calls[0][-1][-1])
        self.assertEqual("Differential Pairs", calls[0][4][1])
        self.assertEqual("Time", calls[0][4][3])
        self.assertEqual(1e-11, calls[0][4][7])
        self.assertEqual(8e-13, calls[0][4][9])
        self.assertEqual(4e-10, calls[0][4][-1])
        self.assertEqual("saved", calls[1])

    def test_tdr_rejects_all_nan_even_when_aedt_created_a_report(self):
        class FakeReportSetup:
            names = []
            def GetAllReportNames(self):
                return self.names
            def CreateReport(self, *args):
                self.names.append(args[0])
            def DeleteReports(self, names):
                self.names = [name for name in self.names if name not in names]
        class FakePost:
            def export_report_to_csv(self, directory, name):
                path = Path(directory) / (name + ".csv")
                path.write_text('"Time [ps]","TDRZt(Diff1) []"\n' +
                                "".join(f"{index * 0.8},nan\n" for index in range(501)))
                return str(path)
        hfss = SimpleNamespace(
            oreportsetup=FakeReportSetup(), post=FakePost(),
            get_setup=lambda name: SimpleNamespace(sweeps=[SimpleNamespace(name="Sweep", is_solved=True)]),
        )
        with self.assertRaisesRegex(RuntimeError, "finite"):
            stack_model.create_stackup_tdr_report(hfss)
        self.assertEqual([], hfss.oreportsetup.GetAllReportNames())

    def test_reference_fields_round_trip_and_old_json_stays_blank(self):
        config = stack_model.eight_layer_example()
        restored = stack_model.StackupConfig.from_dict(config.to_dict())
        self.assertEqual("L1", restored.upper_reference_layer_name)
        self.assertEqual("L3", restored.lower_reference_layer_name)
        self.assertEqual(93.0, restored.differential_impedance)
        self.assertEqual(23.25, restored.common_impedance)
        self.assertEqual("-5mm", restored.port_deembed_distance)
        self.assertTrue(restored.create_tdr_report)

        legacy = config.to_dict()
        legacy.pop("upper_reference_layer_name")
        legacy.pop("lower_reference_layer_name")
        legacy.pop("common_impedance")
        legacy.pop("port_deembed_distance")
        legacy.pop("create_tdr_report")
        restored_legacy = stack_model.StackupConfig.from_dict(legacy)
        self.assertEqual("", restored_legacy.upper_reference_layer_name)
        self.assertEqual("-5mm", restored_legacy.port_deembed_distance)
        self.assertTrue(restored_legacy.create_tdr_report)
        self.assertEqual("", restored_legacy.lower_reference_layer_name)
        self.assertEqual(23.25, restored_legacy.common_impedance)

        legacy["differential_impedance"] = 100.0
        self.assertEqual(
            25.0, stack_model.StackupConfig.from_dict(legacy).common_impedance
        )

    def test_references_are_explicit_ground_copper_and_bracket_signal(self):
        cases = []
        missing = stack_model.eight_layer_example()
        missing.upper_reference_layer_name = ""
        cases.append((missing, "upper reference layer must be explicitly selected"))

        dielectric = stack_model.eight_layer_example()
        dielectric.upper_reference_layer_name = "PP_L1"
        cases.append((dielectric, "must be a copper layer"))

        signal = stack_model.eight_layer_example()
        signal.upper_reference_layer_name = "L2"
        cases.append((signal, "must be a ground copper layer"))

        same_side = stack_model.eight_layer_example()
        same_side.upper_reference_layer_name = "L3"
        same_side.lower_reference_layer_name = "L4"
        cases.append((same_side, "must be above route layer L2"))

        invalid_differential = stack_model.eight_layer_example()
        invalid_differential.differential_impedance = 0
        cases.append((invalid_differential, "Differential-mode impedance"))

        invalid_common = stack_model.eight_layer_example()
        invalid_common.common_impedance = 0
        cases.append((invalid_common, "Common-mode impedance"))

        for config, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    stack_model._validate(config)

    def test_separated_references_drive_clearance_ports_and_return_vias(self):
        config = stack_model.eight_layer_example()
        for layer in config.layers:
            if layer.kind == "copper":
                layer.role = "signal" if layer.name == "L4" else "ground"
        config.upper_reference_layer_name = "L1"
        config.lower_reference_layer_name = "L7"
        config.create_open_region = False
        config.create_setup = False
        config.create_sweep = False
        config.create_tdr_report = False

        desktop_calls = []
        release_calls = []
        hfss_instances = []

        class FakeDesktop:
            def __init__(self, **kwargs):
                desktop_calls.append(kwargs)
                self.aedt_process_id = 4321

            def release_desktop(self, **kwargs):
                release_calls.append(kwargs)
                return True

        class FakeHfss(_Hfss):
            def __init__(self, **kwargs):
                super().__init__()
                self.arguments = kwargs
                hfss_instances.append(self)

            def save_project(self, path, overwrite=False):
                return True

            def value_with_units(self, value):
                return value

            def wave_port(self, sheet, **kwargs):
                super().wave_port(sheet, **kwargs)
                from types import SimpleNamespace
                return SimpleNamespace(props={"DoDeembed": True, "DeembedDist": kwargs["deembed"]})

        output = Path("separated_stackup_test.aedt")
        with (
            patch.object(Path, "exists", return_value=False),
            patch.object(stack_model, "Desktop", FakeDesktop),
            patch.object(stack_model, "Hfss", FakeHfss),
        ):
            stack_model.build_aedt_project(
                config, output, keep_desktop_open=False,
            )

        hfss = hfss_instances[0]
        names = set(hfss.modeler.created)
        for layer in ("L2", "L3", "L5", "L6"):
            self.assertIn(f"SKIPPED_REF_{layer}_TRACE_CLEARANCE", names)
        self.assertFalse(any(name.startswith("SKIPPED_REF_L1_") for name in names))
        self.assertFalse(any(name.startswith("SKIPPED_REF_L7_") for name in names))
        self.assertEqual("1", hfss.variables["UPPER_REFERENCE_LAYER"])
        self.assertEqual("7", hfss.variables["LOWER_REFERENCE_LAYER"])
        self.assertEqual(
            [
                "GND_L7", "GND_L6", "GND_L5", "GND_L4",
                "GND_L3", "GND_L2", "GND_L1",
            ],
            hfss.wave_ports[0][1]["reference"],
        )
        self.assertEqual(["-5mm", "-5mm"], [port[1]["deembed"] for port in hfss.wave_ports])
        return_via = hfss.modeler.cylinder_args["GND_VIA_P_001"]
        self.assertEqual(hfss.variables["LOWER_REF_Z"], return_via[1][2])
        self.assertEqual(
            f"({hfss.variables['UPPER_REF_Z']})-({hfss.variables['LOWER_REF_Z']})",
            return_via[3],
        )
        self.assertEqual(4321, hfss.arguments["aedt_process_id"])
        self.assertFalse(desktop_calls[0]["new_desktop"])
        self.assertEqual(
            [{"close_projects": False, "close_on_exit": False}], release_calls,
        )


if __name__ == "__main__":
    unittest.main()
