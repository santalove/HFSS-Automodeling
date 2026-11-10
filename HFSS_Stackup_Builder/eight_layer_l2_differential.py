"""使用 PyAEDT 建立八层板 L2 差分走线模型。

运行环境：
    C:\\Users\\39004628\\conda_envs\\hfss_env\\python.exe

本脚本只创建模型、端口和求解设置，不自动求解。叠层厚度、材料 DK/DF、
信号层和 W/S/G 均集中在文件开头，便于后续修改。
"""

# Developer: 39004628 / Luxshare
# Copyright © 2026 39004628 / Luxshare. All rights reserved.

from pathlib import Path

from pyaedt import Desktop, Hfss


# -----------------------------------------------------------------------------
# AEDT 与工程配置
# -----------------------------------------------------------------------------
AEDT_VERSION = "2025.2"
NON_GRAPHICAL = False
KEEP_DESKTOP_OPEN = False
OVERWRITE_PROJECT = False

PROJECT_PATH = Path(__file__).with_name("eight_layer_l2_differential_diffpair.aedt")
DESIGN_NAME = "EightLayerL2Differential"


# -----------------------------------------------------------------------------
# 平面尺寸与信号层配置
# -----------------------------------------------------------------------------
# SIGNAL_LAYER 控制差分线所在铜层。当前图片要求信号从 L2 出线。
SIGNAL_LAYER = 2

# y 方向为传输方向。板宽由端口宽度加左右余量自动计算。
BOARD_LENGTH = "100mil"
BOARD_MARGIN_X = "10mil"

# W/S/G 顺序：线宽、差分线边到边间距、信号线到同层地的间隙。
W_LINE = "4.04mil"
S_LINE = "5.96mil"
G_LINE = "4.26mil"

# 差分对参考阻抗。共模阻抗按差模阻抗的 1/4 自动计算。
DIFF_REF_Z = 93.0
COMMON_REF_Z = DIFF_REF_Z / 4.0


# -----------------------------------------------------------------------------
# 八层铜厚，单位来自叠层图片
# -----------------------------------------------------------------------------
COPPER_THICKNESS = {
    "L1": "1.7mil",
    "L2": "1.23mil",
    "L3": "1.4mil",
    "L4": "1.2mil",
    "L5": "1.2mil",
    "L6": "1.4mil",
    "L7": "1.23mil",
    "L8": "1.7mil",
}


# -----------------------------------------------------------------------------
# 介质厚度和材料参数
# -----------------------------------------------------------------------------
# 材料按 DK/DF 组合复用；厚度属于叠层参数，不是材料身份的一部分。
# 因此 DK=2.84、DF=0.0018 的所有 PP 层共用同一种材料。
MATERIAL_FAMILY = "EM_890K"
DIELECTRIC_SPECS = {
    "PP_L1": {
        "height_var": "PP_L1_H",
        "height": "3.3mil",
        "dk": 2.84,
        "df": 0.0018,
    },
    "PP_L2": {
        "height_var": "PP_L2_H",
        "height": "3.34mil",
        "dk": 2.84,
        "df": 0.0018,
    },
    "PP_L3": {
        "height_var": "PP_L3_H",
        "height": "3.37mil",
        "dk": 2.84,
        "df": 0.0018,
    },
    # 图片中的 CORE 位于 L4 和 L5 之间。变量名使用 PP_L4_H_CORE；
    # 它对应你提出的 PP_L4_H(core)，并避免在 AEDT 变量名中使用括号。
    "PP_L4_CORE": {
        "height_var": "PP_L4_H_CORE",
        "height": "8mil",
        "dk": 2.99,
        "df": 0.0019,
    },
    "PP_L5": {
        "height_var": "PP_L5_H",
        "height": "3.37mil",
        "dk": 2.84,
        "df": 0.0018,
    },
    "PP_L6": {
        "height_var": "PP_L6_H",
        "height": "3.34mil",
        "dk": 2.84,
        "df": 0.0018,
    },
    "PP_L7": {
        "height_var": "PP_L7_H",
        "height": "3.3mil",
        "dk": 2.84,
        "df": 0.0018,
    },
}


# 从板底 L8 向板顶 L1 建模。每一项为：对象名、类型、厚度变量名。
STACK_BOTTOM_TO_TOP = [
    ("L8", "copper", "L8_H"),
    ("PP_L7", "dielectric", "PP_L7_H"),
    ("L7", "copper", "L7_H"),
    ("PP_L6", "dielectric", "PP_L6_H"),
    ("L6", "copper", "L6_H"),
    ("PP_L5", "dielectric", "PP_L5_H"),
    ("L5", "copper", "L5_H"),
    ("PP_L4_CORE", "dielectric", "PP_L4_H_CORE"),
    ("L4", "copper", "L4_H"),
    ("PP_L3", "dielectric", "PP_L3_H"),
    ("L3", "copper", "L3_H"),
    ("PP_L2", "dielectric", "PP_L2_H"),
    ("L2", "copper", "L2_H"),
    ("PP_L1", "dielectric", "PP_L1_H"),
    ("L1", "copper", "L1_H"),
]


# -----------------------------------------------------------------------------
# 求解设置
# -----------------------------------------------------------------------------
OPEN_REGION_FREQUENCY = "60GHz"
SWEEP_START = "0.01GHz"
SWEEP_STOP = "60GHz"
SWEEP_POINTS = 401


def _sum_expression(items: list[str]) -> str:
    """把 AEDT 厚度变量组合成一个参数表达式。"""
    return "+".join(items) if items else "0mil"


def _layer_origin_expression(layer_name: str) -> str:
    """返回指定层底面的参数化 z 坐标。"""
    heights_below = []
    for name, _, height_var in STACK_BOTTOM_TO_TOP:
        if name == layer_name:
            return _sum_expression(heights_below)
        heights_below.append(height_var)
    raise ValueError(f"Unknown stack layer: {layer_name}")


def add_design_variables(hfss: Hfss) -> None:
    """将厚度、WSG、信号位置和端口尺寸写入 AEDT 变量管理器。"""
    # 当前端口算法适用于有上下相邻参考层的内层走线，因此信号层必须在
    # L2~L7。以 L2 为例，上方参考层是 L1，下方参考层是 L3。
    if SIGNAL_LAYER not in range(2, 8):
        raise ValueError("For an internal wave port, SIGNAL_LAYER must be from 2 to 7.")

    hfss["W_LINE"] = W_LINE
    hfss["S_LINE"] = S_LINE
    hfss["G_LINE"] = G_LINE

    for layer_name, thickness in COPPER_THICKNESS.items():
        hfss[f"{layer_name}_H"] = thickness

    for spec in DIELECTRIC_SPECS.values():
        hfss[spec["height_var"]] = spec["height"]

    all_heights = [item[2] for item in STACK_BOTTOM_TO_TOP]
    signal_name = f"L{SIGNAL_LAYER}"
    signal_origin = _layer_origin_expression(signal_name)
    upper_reference = f"L{SIGNAL_LAYER - 1}"
    lower_reference = f"L{SIGNAL_LAYER + 1}"

    # 端口下边沿与下方参考地的顶面重合；端口上边沿与上方参考地的底面
    # 重合。L2 情况下：PORT_Z0=L3 顶面，PORT_Z1=L1 底面。
    lower_reference_top = (
        f"({_layer_origin_expression(lower_reference)})+{lower_reference}_H"
    )
    upper_reference_bottom = _layer_origin_expression(upper_reference)

    hfss["STACK_H"] = _sum_expression(all_heights)
    hfss["PORT_X"] = "6*G_LINE+4*W_LINE+S_LINE"
    hfss["SIGNAL_Z"] = f"({signal_origin})+{signal_name}_H/2"
    hfss["PORT_Z0"] = lower_reference_top
    hfss["PORT_Z1"] = upper_reference_bottom
    hfss["PORT_Z"] = "PORT_Z1-PORT_Z0"
    hfss["BOARD_MARGIN_X"] = BOARD_MARGIN_X
    hfss["BOARD_WIDTH"] = "PORT_X+2*BOARD_MARGIN_X"
    hfss["BOARD_LENGTH"] = BOARD_LENGTH


def add_dielectric_materials(hfss: Hfss) -> dict[str, str]:
    """按 DK/DF 去重创建材料，并返回每个介质层对应的材料名称。"""
    layer_materials = {}
    material_cache = {}

    for layer_name, spec in DIELECTRIC_SPECS.items():
        material_key = (float(spec["dk"]), float(spec["df"]))

        if material_key not in material_cache:
            dk_token = str(spec["dk"]).replace(".", "p")
            df_token = str(spec["df"]).replace(".", "p")
            material_name = f"{MATERIAL_FAMILY}_DK{dk_token}_DF{df_token}"

            material = hfss.materials.add_material(material_name)
            if not material:
                material = hfss.materials[material_name]
            material.permittivity = spec["dk"]
            material.dielectric_loss_tangent = spec["df"]
            material.update()
            material_cache[material_key] = material_name

        layer_materials[layer_name] = material_cache[material_key]

    return layer_materials


def _create_signal_layer(hfss: Hfss, layer_name: str, z_origin: str, height_var: str) -> dict[str, object]:
    """在指定铜层开中心槽，并创建同层差分线 SIG_P/SIG_N。"""
    modeler = hfss.modeler

    ground = modeler.create_box(
        ["0mil", "0mil", z_origin],
        ["BOARD_WIDTH", "BOARD_LENGTH", height_var],
        name=f"GND_{layer_name}",
        material="copper",
    )

    # 槽宽 = S + 2W + 2G；槽内包含两根信号线及其到同层地的间隙。
    clearance = modeler.create_box(
        ["BOARD_WIDTH/2-(S_LINE/2+W_LINE+G_LINE)", "0mil", z_origin],
        ["S_LINE+2*W_LINE+2*G_LINE", "BOARD_LENGTH", height_var],
        name=f"{layer_name}_Clearance",
        material="vacuum",
    )
    if not modeler.subtract(ground, clearance, keep_originals=False):
        raise RuntimeError(f"Unable to create clearance on {layer_name}.")

    signal_positive = modeler.create_box(
        ["BOARD_WIDTH/2+S_LINE/2", "0mil", z_origin],
        ["W_LINE", "BOARD_LENGTH", height_var],
        name=f"SIG_P_{layer_name}",
        material="copper",
    )
    signal_negative = modeler.create_box(
        ["BOARD_WIDTH/2-S_LINE/2-W_LINE", "0mil", z_origin],
        ["W_LINE", "BOARD_LENGTH", height_var],
        name=f"SIG_N_{layer_name}",
        material="copper",
    )
    return {
        "ground": ground,
        "signal_positive": signal_positive,
        "signal_negative": signal_negative,
    }


def build_stack(hfss: Hfss, layer_materials: dict[str, str]) -> dict[str, object]:
    """按照图片顺序生成完整八层叠层、L2 差分线和两个端口面。"""
    modeler = hfss.modeler
    modeler.model_units = "mil"

    geometry = {}
    ground_objects = []
    z_origin = "0mil"
    signal_name = f"L{SIGNAL_LAYER}"

    for layer_name, layer_type, height_var in STACK_BOTTOM_TO_TOP:
        if layer_type == "dielectric":
            obj = modeler.create_box(
                ["0mil", "0mil", z_origin],
                ["BOARD_WIDTH", "BOARD_LENGTH", height_var],
                name=layer_name,
                material=layer_materials[layer_name],
            )
            # 介质实体仅显示框架，便于在 AEDT 中观察内部铜层和走线。
            obj.display_wireframe = True
            geometry[layer_name] = obj
        elif layer_name == signal_name:
            signal_geometry = _create_signal_layer(hfss, layer_name, z_origin, height_var)
            geometry.update(signal_geometry)
            ground_objects.append(signal_geometry["ground"])
        else:
            ground = modeler.create_box(
                ["0mil", "0mil", z_origin],
                ["BOARD_WIDTH", "BOARD_LENGTH", height_var],
                name=f"GND_{layer_name}",
                material="copper",
            )
            geometry[f"ground_{layer_name}"] = ground
            ground_objects.append(ground)

        z_origin = f"({z_origin})+{height_var}"

    # 对 XZ 平面，PyAEDT sizes[0] 映射到 z，sizes[1] 映射到 x。
    # 对 L2：端口从 L3 顶面 PORT_Z0 延伸到 L1 底面 PORT_Z1，因此：
    #   PORT_Z = PP_L2_H + L2_H + PP_L1_H
    # 切换 SIGNAL_LAYER 后，上下相邻参考层和端口高度会自动重新计算。
    port_x_start = "BOARD_WIDTH/2-PORT_X/2"
    port_w1 = modeler.create_rectangle(
        "XZ",
        [port_x_start, "0mil", "PORT_Z0"],
        ["PORT_Z", "PORT_X"],
        name="PortSheet_W1",
    )
    port_w2 = modeler.create_rectangle(
        "XZ",
        [port_x_start, "BOARD_LENGTH", "PORT_Z0"],
        ["PORT_Z", "PORT_X"],
        name="PortSheet_W2",
    )
    geometry["port_w1"] = port_w1
    geometry["port_w2"] = port_w2
    geometry["ground_objects"] = ground_objects
    return geometry


def _ground_references_on_port(geometry: dict[str, object]) -> list[str]:
    """只选择在端口 x/z 范围内实际相交的地导体作为参考导体。"""
    port_box = geometry["port_w1"].bounding_box
    references = []
    tolerance = 1e-9

    for ground in geometry["ground_objects"]:
        box = ground.bounding_box
        overlaps_x = box[0] <= port_box[3] + tolerance and box[3] >= port_box[0] - tolerance
        overlaps_z = box[2] <= port_box[5] + tolerance and box[5] >= port_box[2] - tolerance
        if overlaps_x and overlaps_z:
            references.append(ground.name)

    if not references:
        raise RuntimeError("No ground conductors intersect the wave-port range.")
    return references


def assign_ports(hfss: Hfss, geometry: dict[str, object]) -> None:
    """为两端端口面分配 Terminal Wave Port。"""
    references = _ground_references_on_port(geometry)

    for port_name, sheet_key in (("w1", "port_w1"), ("w2", "port_w2")):
        port = hfss.wave_port(
            geometry[sheet_key],
            reference=references,
            create_port_sheet=False,
            modes=1,
            impedance=50,
            name=port_name,
            terminals_rename=True,
        )
        if not port:
            raise RuntimeError(f"Unable to assign port {port_name}.")


def assign_differential_pairs(hfss: Hfss) -> None:
    """把两个物理端口的 T1/T2 终端组合成差模和共模端口。"""
    for port_index in (1, 2):
        result = hfss.set_differential_pair(
            assignment=f"w{port_index}_T1",
            reference=f"w{port_index}_T2",
            common_mode=f"Comm{port_index}",
            differential_mode=f"Diff{port_index}",
            common_reference=COMMON_REF_Z,
            differential_reference=DIFF_REF_Z,
            active=True,
            matched=False,
        )
        if not result:
            raise RuntimeError(f"Unable to create differential pair for w{port_index}.")


def create_simulation_setup(hfss: Hfss) -> None:
    """创建开放区域、宽带自适应设置和插值扫频，不启动求解。"""
    if not hfss.create_open_region(
        frequency=OPEN_REGION_FREQUENCY,
        boundary="Radiation",
        apply_infinite_ground=False,
    ):
        raise RuntimeError("Unable to create the open radiation region.")

    setup = hfss.create_setup(name="Setup1", setup_type="HFSSDriven")
    setup.props["SolveType"] = "Broadband"
    setup.props["MultipleAdaptiveFreqsSetup"] = {
        "Low": SWEEP_START,
        "High": SWEEP_STOP,
    }
    setup.props["MaxDeltaS"] = 0.02
    setup.props["MaximumPasses"] = 12
    setup.props["MinimumPasses"] = 1
    setup.props["MinimumConvergedPasses"] = 1
    if not setup.update():
        raise RuntimeError("Unable to update Setup1.")

    sweep = setup.add_sweep(name="Sweep", sweep_type="Interpolating")
    sweep.props["RangeType"] = "LinearCount"
    sweep.props["RangeStart"] = SWEEP_START
    sweep.props["RangeEnd"] = SWEEP_STOP
    sweep.props["RangeCount"] = SWEEP_POINTS
    sweep.props["SaveFields"] = False
    sweep.props["SaveRadFields"] = False
    sweep.props["InterpTolerance"] = 0.5
    sweep.props["InterpMaxSolns"] = 250
    sweep.props["EnforcePassivity"] = True
    if not sweep.update():
        raise RuntimeError("Unable to update Sweep.")


def build_project() -> Path:
    """创建并保存八层板工程。"""
    if PROJECT_PATH.exists() and not OVERWRITE_PROJECT:
        raise FileExistsError(
            f"Project already exists: {PROJECT_PATH}. "
            "Set OVERWRITE_PROJECT = True or choose a new PROJECT_PATH."
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
        materials = add_dielectric_materials(hfss)
        geometry = build_stack(hfss, materials)
        assign_ports(hfss, geometry)
        assign_differential_pairs(hfss)
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
