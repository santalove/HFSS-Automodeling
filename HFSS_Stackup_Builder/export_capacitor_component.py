"""Export the reusable body of the SC04S0J104M capacitor as an A3D component.

The source project is copied to a temporary directory before it is opened, so
the vendor/source project can remain open in AEDT and is never modified.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from ansys.aedt.core import Hfss


COMPONENT_NAME = "SC04S0J104M_0p1uF"
REFERENCE_CS = "CAP_COMPONENT_REFERENCE_CS"


def _component_objects(object_names: list[str]) -> list[str]:
    """Return only the package, terminals, dielectric, and inner electrodes."""
    exact = {
        "Sn_3",
        "Sn_4",
        "Cu_electrode_5",
        "Cu_electrode_6",
        "Ni_electrode_9",
        "Ni_electrode_10",
        "Ni_electrode_11",
        "Ni_electrode_12",
        "dielectric_14",
    }
    selected = []
    for name in object_names:
        if name in exact or name.startswith("Inner_electrode_7") or name.startswith("Inner_electrode_8"):
            selected.append(name)
    return selected


def export_component(
    source_project: Path,
    output_file: Path,
    design_name: str = "HFSSDesign2",
    aedt_version: str = "2025.2",
    process_id: int | None = None,
    port: int = 0,
) -> Path:
    source_project = source_project.resolve()
    output_file = output_file.resolve()
    if not source_project.is_file():
        raise FileNotFoundError(f"Source AEDT project not found: {source_project}")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cap_a3d_export_") as temp_dir:
        copied_project = Path(temp_dir) / "SC04S0J104M_component_export.aedt"
        shutil.copy2(source_project, copied_project)
        hfss = Hfss(
            project=str(copied_project),
            design=design_name,
            version=aedt_version,
            new_desktop=False,
            close_on_exit=False,
            aedt_process_id=process_id,
            port=port,
            remove_lock=False,
        )
        try:
            selected = _component_objects(list(hfss.modeler.object_names))
            if len(selected) < 10:
                raise RuntimeError(
                    "The expected capacitor solids were not found in the source design. "
                    f"Found only: {selected}"
                )

            # Remove ports/boundaries only from the disposable project copy.
            # This keeps test-board excitations out of the exported component.
            for boundary in list(hfss.boundaries):
                if not boundary.delete():
                    raise RuntimeError(f"Unable to remove copied boundary {boundary.name}.")

            reference = hfss.modeler.create_coordinate_system(
                origin=["-0.001mm", "0mm", "0mm"],
                name=REFERENCE_CS,
                mode="axis",
                x_pointing=[0, 1, 0],
                y_pointing=[-1, 0, 0],
                reference_cs="Global",
            )
            if not reference:
                raise RuntimeError("Unable to create the capacitor component reference system.")

            if output_file.exists():
                output_file.unlink()
            ok = hfss.modeler.create_3dcomponent(
                input_file=str(output_file),
                name=COMPONENT_NAME,
                variables_to_include=[],
                assignment=selected,
                boundaries=[],
                excitations=[],
                coordinate_systems=[REFERENCE_CS],
                reference_coordinate_system=REFERENCE_CS,
                component_outline="BoundingBox",
            )
            if not ok or not output_file.is_file():
                raise RuntimeError(f"AEDT did not create the component file: {output_file}")
        finally:
            # Close only the temporary copy; keep the user's AEDT session and
            # original source project untouched.
            hfss.close_project(name=hfss.project_name, save=False)
    return output_file


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_project", type=Path)
    parser.add_argument("output_file", type=Path)
    parser.add_argument("--design", default="HFSSDesign2")
    parser.add_argument("--version", default="2025.2")
    parser.add_argument("--process-id", type=int)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    result = export_component(
        args.source_project,
        args.output_file,
        design_name=args.design,
        aedt_version=args.version,
        process_id=args.process_id,
        port=args.port,
    )
    print(result)


if __name__ == "__main__":
    main()
