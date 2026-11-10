"""Fit a simple series RLC model to a two-port capacitor Touchstone file."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import cos, hypot, pi, sin, sqrt
from pathlib import Path
import argparse
import json
import re


_FREQUENCY_FACTORS = {
    "hz": 1.0,
    "khz": 1e3,
    "mhz": 1e6,
    "ghz": 1e9,
}


@dataclass(frozen=True)
class SeriesRLCFit:
    resistance_ohm: float
    inductance_h: float
    capacitance_f: float
    rms_error_ohm: float
    point_count: int
    fit_start_hz: float
    fit_stop_hz: float
    source_file: str

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def resistance_text(self) -> str:
        return f"{self.resistance_ohm:.6g}ohm"

    @property
    def inductance_text(self) -> str:
        return f"{self.inductance_h * 1e9:.6g}nH"

    @property
    def capacitance_text(self) -> str:
        return f"{self.capacitance_f * 1e6:.6g}uF"


def parse_frequency(value: str) -> float:
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*"
        r"(Hz|kHz|MHz|GHz)\s*",
        str(value), re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"Invalid frequency {value!r}; use Hz, kHz, MHz, or GHz.")
    result = float(match.group(1)) * _FREQUENCY_FACTORS[match.group(2).lower()]
    if result <= 0:
        raise ValueError("Fit frequencies must be positive.")
    return result


def _complex_pair(first: float, second: float, data_format: str) -> complex:
    if data_format == "ri":
        return complex(first, second)
    angle = second * pi / 180.0
    magnitude = 10 ** (first / 20.0) if data_format == "db" else first
    return magnitude * complex(cos(angle), sin(angle))


def read_touchstone_2port(path: str | Path) -> tuple[list[float], list[tuple[complex, complex, complex, complex]], float]:
    """Read an S2P file as ``(frequency, (S11,S21,S12,S22), Z0)`` data."""
    source = Path(path)
    if source.suffix.lower() != ".s2p" or not source.is_file():
        raise FileNotFoundError(f"Touchstone .s2p file not found: {source}")
    frequency_factor, data_format, reference = 1e9, "ma", 50.0
    numeric_tokens: list[float] = []
    for raw_line in source.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.split("!", 1)[0].strip()
        if not line:
            continue
        if line.startswith("#"):
            tokens = line[1:].lower().split()
            for token in tokens:
                if token in _FREQUENCY_FACTORS:
                    frequency_factor = _FREQUENCY_FACTORS[token]
                elif token in {"db", "ma", "ri"}:
                    data_format = token
            if "r" in tokens:
                reference = float(tokens[tokens.index("r") + 1])
            if "s" not in tokens:
                raise ValueError("Only S-parameter Touchstone files are supported.")
            continue
        numeric_tokens.extend(float(token) for token in line.split())
    if len(numeric_tokens) % 9:
        raise ValueError("The S2P numeric data is incomplete or uses an unsupported layout.")
    frequencies: list[float] = []
    matrices: list[tuple[complex, complex, complex, complex]] = []
    for index in range(0, len(numeric_tokens), 9):
        row = numeric_tokens[index:index + 9]
        frequencies.append(row[0] * frequency_factor)
        matrices.append(tuple(
            _complex_pair(row[column], row[column + 1], data_format)
            for column in (1, 3, 5, 7)
        ))
    if not frequencies:
        raise ValueError("The S2P file does not contain any data points.")
    return frequencies, matrices, reference


def _series_impedance_from_s(
    s11: complex, s21: complex, s12: complex, s22: complex, reference: float
) -> complex:
    """Return ABCD-B, the series impedance of an approximately series DUT."""
    if abs(s21) < 1e-15:
        raise ValueError("S21 is too small to convert this point to ABCD parameters.")
    return reference * ((1 + s11) * (1 + s22) - s12 * s21) / (2 * s21)


def fit_series_rlc(
    path: str | Path,
    fit_start: str | float,
    fit_stop: str | float,
) -> SeriesRLCFit:
    """Least-squares fit ``Z = R + jwL + 1/(jwC)`` over one frequency band."""
    start_hz = parse_frequency(fit_start) if isinstance(fit_start, str) else float(fit_start)
    stop_hz = parse_frequency(fit_stop) if isinstance(fit_stop, str) else float(fit_stop)
    if stop_hz <= start_hz:
        raise ValueError("RLC fit stop frequency must exceed its start frequency.")
    frequencies, matrices, reference = read_touchstone_2port(path)
    samples = [
        (frequency, _series_impedance_from_s(*matrix, reference))
        for frequency, matrix in zip(frequencies, matrices)
        if start_hz <= frequency <= stop_hz
    ]
    if len(samples) < 3:
        raise ValueError(
            "The selected RLC fit band contains fewer than three S2P points. "
            "Choose a wider band or a denser Touchstone file."
        )

    # Scale the two regressors so the normal equations remain well-conditioned.
    # Coefficients are L[pH] and 1/C[uF], respectively.
    x_rows = []
    y_values = []
    for frequency, impedance in samples:
        omega = 2 * pi * frequency
        x_rows.append((omega * 1e-12, -1.0 / (omega * 1e-6)))
        y_values.append(impedance.imag)
    aa = sum(row[0] * row[0] for row in x_rows)
    ab = sum(row[0] * row[1] for row in x_rows)
    bb = sum(row[1] * row[1] for row in x_rows)
    ay = sum(row[0] * value for row, value in zip(x_rows, y_values))
    by = sum(row[1] * value for row, value in zip(x_rows, y_values))
    determinant = aa * bb - ab * ab
    if abs(determinant) < 1e-30:
        raise ValueError("The selected S2P points cannot determine both L and C.")
    inductance_ph = (ay * bb - by * ab) / determinant
    inverse_capacitance_uf = (aa * by - ab * ay) / determinant
    if inductance_ph <= 0 or inverse_capacitance_uf <= 0:
        raise ValueError(
            "The selected band does not produce a passive positive series L/C fit."
        )
    inductance_h = inductance_ph * 1e-12
    capacitance_f = (1.0 / inverse_capacitance_uf) * 1e-6

    # A median is deliberately used because measured high-frequency loss is
    # frequency dependent and a few resonant points can dominate a mean.
    resistances = sorted(max(0.0, impedance.real) for _, impedance in samples)
    middle = len(resistances) // 2
    resistance_ohm = (
        resistances[middle]
        if len(resistances) % 2
        else (resistances[middle - 1] + resistances[middle]) / 2
    )
    squared_error = 0.0
    for frequency, impedance in samples:
        omega = 2 * pi * frequency
        fitted = complex(
            resistance_ohm,
            omega * inductance_h - 1.0 / (omega * capacitance_f),
        )
        squared_error += abs(impedance - fitted) ** 2
    return SeriesRLCFit(
        resistance_ohm=resistance_ohm,
        inductance_h=inductance_h,
        capacitance_f=capacitance_f,
        rms_error_ohm=sqrt(squared_error / len(samples)),
        point_count=len(samples),
        fit_start_hz=start_hz,
        fit_stop_hz=stop_hz,
        source_file=str(Path(path).resolve()),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("s2p_file", type=Path)
    parser.add_argument("--start", default="10MHz")
    parser.add_argument("--stop", default="3GHz")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = fit_series_rlc(args.s2p_file, args.start, args.stop)
    payload = json.dumps(result.to_dict(), indent=2, ensure_ascii=False)
    if args.json:
        args.json.write_text(payload, encoding="utf-8")
    print(payload)
    print(result.resistance_text, result.inductance_text, result.capacitance_text)


if __name__ == "__main__":
    main()
