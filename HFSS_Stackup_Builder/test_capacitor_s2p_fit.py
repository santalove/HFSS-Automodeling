"""Unit tests for capacitor S2P parsing and series-RLC fitting."""

from __future__ import annotations

from math import pi
from pathlib import Path
import tempfile
import unittest

from capacitor_s2p_fit import fit_series_rlc, parse_frequency, read_touchstone_2port


class CapacitorS2PFitTests(unittest.TestCase):
    def _synthetic_file(self) -> Path:
        resistance, inductance, capacitance, z0 = 0.035, 220e-12, 0.1e-6, 50.0
        rows = ["# Hz S RI R 50"]
        for frequency in (10e6, 30e6, 100e6, 300e6, 1e9, 3e9):
            omega = 2 * pi * frequency
            impedance = complex(
                resistance, omega * inductance - 1 / (omega * capacitance)
            )
            s11 = impedance / (2 * z0 + impedance)
            s21 = 2 * z0 / (2 * z0 + impedance)
            rows.append(
                " ".join(str(value) for value in (
                    frequency,
                    s11.real, s11.imag,
                    s21.real, s21.imag,
                    s21.real, s21.imag,
                    s11.real, s11.imag,
                ))
            )
        directory = Path(tempfile.mkdtemp(prefix="cap_s2p_test_"))
        path = directory / "synthetic.s2p"
        path.write_text("\n".join(rows), encoding="utf-8")
        return path

    def test_frequency_parser(self):
        self.assertEqual(10e6, parse_frequency("10MHz"))
        self.assertEqual(3e9, parse_frequency("3 GHz"))
        with self.assertRaisesRegex(ValueError, "use Hz"):
            parse_frequency("10mm")

    def test_series_rlc_is_recovered_from_touchstone(self):
        result = fit_series_rlc(self._synthetic_file(), "10MHz", "3GHz")
        self.assertAlmostEqual(0.035, result.resistance_ohm, places=9)
        self.assertAlmostEqual(220e-12, result.inductance_h, places=18)
        self.assertAlmostEqual(0.1e-6, result.capacitance_f, places=14)
        self.assertLess(result.rms_error_ohm, 1e-10)
        self.assertEqual(6, result.point_count)

    def test_fit_band_requires_three_points(self):
        path = self._synthetic_file()
        with self.assertRaisesRegex(ValueError, "fewer than three"):
            fit_series_rlc(path, "10MHz", "30MHz")
        frequencies, matrices, reference = read_touchstone_2port(path)
        self.assertEqual(6, len(frequencies))
        self.assertEqual(6, len(matrices))
        self.assertEqual(50.0, reference)


if __name__ == "__main__":
    unittest.main()
