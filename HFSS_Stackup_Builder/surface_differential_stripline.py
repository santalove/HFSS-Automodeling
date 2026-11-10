"""Create a parameterized surface differential transmission line in HFSS.

The script creates geometry, ports, a Radiation open region, Setup1, and an
interpolating sweep. It saves the AEDT project but never starts a solve.
"""

# Developer: 39004628 / Luxshare
# Copyright © 2026 39004628 / Luxshare. All rights reserved.

from __future__ import annotations

from pathlib import Path

from pyaedt import Desktop, Hfss

from hfss_stackup_builder import create_hfss_analysis


# User configuration.
AEDT_VERSION = "2025.2"
NON_GRAPHICAL = False
KEEP_DESKTOP_OPEN = False
OVERWRITE_PROJECT = False

PROJECT_PATH = Path(__file__).with_name("surface_differential_stripline.aedt")
DESIGN_NAME = "SurfaceDifferentialStripline"

# Coordinate convention: x is transverse, y is propagation, and z is stackup.
BOARD_WIDTH = "0.9mm"
BOARD_LENGTH = "1.1mm"
L1_H = "0.05mm"
L2_H = "0.05mm"

# Differential-pair dimensions. S_LINE is the edge-to-edge spacing.
S_LINE = "40um"
W_LINE = "20um"
G_LINE = "40um"

DIELECTRIC_NAME = "Ideal_Dielectric_Er3p5"
PP_L1_H = "0.1mm"
DIELECTRIC_ER = 3.5
DIELECTRIC_LOSS_TANGENT = 0.0

# Analysis objects are generated, but analyze_setup/analyze is never called.
OPEN_REGION_FREQUENCY = "60GHz"
SWEEP_START = "0.01GHz"
SWEEP_STOP = "60GHz"
SWEEP_POINTS = 401


def add_design_variables(hfss: Hfss) -> None:
    """Expose the primary geometry in the AEDT variable manager."""
    hfss["BOARD_WIDTH"] = BOARD_WIDTH
    hfss["BOARD_LENGTH"] = BOARD_LENGTH
    hfss["L1_H"] = L1_H
    hfss["L2_H"] = L2_H
    hfss["S_LINE"] = S_LINE
    hfss["W_LINE"] = W_LINE
    hfss["G_LINE"] = G_LINE
    hfss["PP_L1_H"] = PP_L1_H
    hfss["PORT_X"] = "6*G_LINE+4*W_LINE+S_LINE"
    hfss["PORT_Z"] = "8*PP_L1_H"


def add_dielectric_material(hfss: Hfss) -> str:
    """Create or update the ideal dielectric material."""
    material = hfss.materials.add_material(DIELECTRIC_NAME)
    if not material:
        material = hfss.materials[DIELECTRIC_NAME]
    material.permittivity = DIELECTRIC_ER
    material.dielectric_loss_tangent = DIELECTRIC_LOSS_TANGENT
    if not material.update():
        raise RuntimeError(f"Unable to update material {DIELECTRIC_NAME}.")
    return DIELECTRIC_NAME


def build_geometry(hfss: Hfss, dielectric_material: str) -> dict[str, object]:
    """Create dielectric, grounds, signals, and the two wave-port sheets."""
    modeler = hfss.modeler
    modeler.model_units = "mm"

    # Bottom-to-top stackup:
    # GND_L2: -L2_H..0; PP_L1: 0..PP_L1_H; L1 copper above PP_L1.
    ground_lower = modeler.create_box(
        ["0mm", "0mm", "-L2_H"],
        ["BOARD_WIDTH", "BOARD_LENGTH", "L2_H"],
        name="GND_L2",
        material="copper",
    )
    dielectric = modeler.create_box(
        ["0mm", "0mm", "0mm"],
        ["BOARD_WIDTH", "BOARD_LENGTH", "PP_L1_H"],
        name="PP_L1",
        material=dielectric_material,
    )
    ground_upper = modeler.create_box(
        ["0mm", "0mm", "PP_L1_H"],
        ["BOARD_WIDTH", "BOARD_LENGTH", "L1_H"],
        name="GND_L1",
        material="copper",
    )
    if not all((ground_lower, dielectric, ground_upper)):
        raise RuntimeError("Unable to create the stackup bodies.")

    clearance = modeler.create_box(
        ["BOARD_WIDTH/2-(S_LINE/2+W_LINE+G_LINE)", "0mm", "PP_L1_H"],
        ["S_LINE+2*W_LINE+2*G_LINE", "BOARD_LENGTH", "L1_H"],
        name="GND_L1_Clearance",
        material="vacuum",
    )
    if not clearance or not modeler.subtract(
        ground_upper, clearance, keep_originals=False
    ):
        raise RuntimeError("Unable to create the upper-ground clearance.")

    signal_positive = modeler.create_box(
        ["BOARD_WIDTH/2+S_LINE/2", "0mm", "PP_L1_H"],
        ["W_LINE", "BOARD_LENGTH", "L1_H"],
        name="SIG_P",
        material="copper",
    )
    signal_negative = modeler.create_box(
        ["BOARD_WIDTH/2-S_LINE/2-W_LINE", "0mm", "PP_L1_H"],
        ["W_LINE", "BOARD_LENGTH", "L1_H"],
        name="SIG_N",
        material="copper",
    )
    if not signal_positive or not signal_negative:
        raise RuntimeError("Unable to create the differential conductors.")

    # PyAEDT maps XZ rectangle sizes as [z size, x size]. The sheet starts at
    # the bottom of L2 and uses the established surface-port height 8*PP_L1_H.
    port_x_start = "BOARD_WIDTH/2-PORT_X/2"
    port_w1 = modeler.create_rectangle(
        "XZ",
        [port_x_start, "0mm", "-L2_H"],
        ["PORT_Z", "PORT_X"],
        name="PortSheet_W1",
    )
    port_w2 = modeler.create_rectangle(
        "XZ",
        [port_x_start, "BOARD_LENGTH", "-L2_H"],
        ["PORT_Z", "PORT_X"],
        name="PortSheet_W2",
    )
    if not port_w1 or not port_w2:
        raise RuntimeError("Unable to create the wave-port sheets.")

    return {
        "ground_lower": ground_lower,
        "ground_upper": ground_upper,
        "dielectric": dielectric,
        "signal_positive": signal_positive,
        "signal_negative": signal_negative,
        "port_w1": port_w1,
        "port_w2": port_w2,
    }


def assign_ports(hfss: Hfss, geometry: dict[str, object]) -> None:
    """Assign one terminal wave port to each propagation-end sheet."""
    references = [
        geometry["ground_upper"].name,
        geometry["ground_lower"].name,
    ]
    for port_name, sheet_name in (("w1", "port_w1"), ("w2", "port_w2")):
        if not hfss.wave_port(
            geometry[sheet_name],
            reference=references,
            create_port_sheet=False,
            modes=1,
            impedance=50,
            name=port_name,
            terminals_rename=True,
        ):
            raise RuntimeError(f"Unable to assign port {port_name}.")


def create_simulation_setup(hfss: Hfss) -> None:
    """Create the common Radiation region, Setup1, and Sweep without solving."""
    create_hfss_analysis(
        hfss,
        open_region_frequency=OPEN_REGION_FREQUENCY,
        sweep_start=SWEEP_START,
        sweep_stop=SWEEP_STOP,
        sweep_points=SWEEP_POINTS,
    )


def build_project() -> Path:
    """Create, configure, save, and optionally close an AEDT project."""
    if PROJECT_PATH.exists() and not OVERWRITE_PROJECT:
        raise FileExistsError(
            f"Project already exists: {PROJECT_PATH}. "
            "Set OVERWRITE_PROJECT = True to replace it."
        )

    desktop = None
    try:
        desktop = Desktop(
            version=AEDT_VERSION,
            non_graphical=NON_GRAPHICAL,
            new_desktop=True,
            close_on_exit=False,
        )
        hfss = Hfss(
            project=str(PROJECT_PATH),
            design=DESIGN_NAME,
            solution_type="Terminal",
            version=AEDT_VERSION,
            new_desktop=False,
            close_on_exit=False,
        )
        add_design_variables(hfss)
        dielectric_material = add_dielectric_material(hfss)
        geometry = build_geometry(hfss, dielectric_material)
        assign_ports(hfss, geometry)
        create_simulation_setup(hfss)

        if not hfss.save_project(PROJECT_PATH, overwrite=OVERWRITE_PROJECT):
            raise RuntimeError(f"Unable to save project to {PROJECT_PATH}.")
        hfss.modeler.fit_all()
        print(f"Project created successfully: {PROJECT_PATH}")
        return PROJECT_PATH
    finally:
        if desktop and not KEEP_DESKTOP_OPEN:
            desktop.release_desktop(close_projects=True, close_on_exit=True)


if __name__ == "__main__":
    build_project()
