"""PySide6 GUI for shared stackup editing and three HFSS model generators.

The stackup table/material editor is shared by both tabs.  The differential
stripline, surface GSSG, inner-layer GF, and differential-VIA builders receive the current
table-derived configuration and create a new AEDT project; no existing project
is opened or reused.  The eight-layer template is only the initial/default
configuration; JSON import is the supported persisted stackup input.
"""

# Developer: 39004628 / Luxshare
# Copyright © 2026 39004628 / Luxshare. All rights reserved.

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
import traceback

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGraphicsScene,
    QGraphicsView, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QToolBar, QVBoxLayout, QWidget, QScrollArea,
)

from hfss_stackup_builder import Layer, StackupConfig, build_aedt_project, create_stackup_tdr_report, eight_layer_example, layer_material_groups
from gf_gssg_model import GSSGConfig, build_gssg_project
from gf_inner_model import InnerGFConfig, build_inner_gf_project
from differential_via_model import (
    DifferentialLineEndConfig,
    DifferentialViaConfig,
    build_differential_via_project,
)
from differential_multistage_via_model import (
    MultiStageDifferentialViaConfig,
    build_multistage_differential_via_project,
)
from cap_pad_model import CapPadConfig, CapViaConfig, build_cap_pad_project, _validate as validate_cap_pad
from capacitor_s2p_fit import fit_series_rlc
from differential_via_model import _literal_mm
from tool_metadata import COPYRIGHT, DEVELOPER


LAYER_COLUMNS = ["Layer", "Type", "Role", "Thickness", "DK", "DF", "Material override", "Copper type"]


def app_directory() -> Path:
    """Folder that owns the running application.

    When frozen by PyInstaller, ``__file__`` resolves into ``_internal``; the
    EXE folder is what the user sees, so that is where generated projects go.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def default_output_directory() -> Path:
    """Keep generated AEDT projects beside the application, never inside ``_internal``."""
    outputs = app_directory() / "outputs"
    outputs.mkdir(parents=True, exist_ok=True)
    return outputs


ZH_CN_TRANSLATIONS = {
    "HFSS Stackup / GF / Differential VIA Generator": "HFSS 叠层 / GF / 差分过孔生成器",
    "File": "文件",
    "New": "新建",
    "Load example": "加载示例",
    "Import JSON": "导入 JSON",
    "Export JSON": "导出 JSON",
    "About": "关于",
    "Language": "语言",
    "Stackup differential": "叠层差分线",
    "Differential VIA": "差分过孔",
    "Stackup (top to bottom)": "叠层（从上到下）",
    "+ Copper": "+ 铜层",
    "+ PP": "+ PP",
    "+ Core": "+ Core",
    "Delete": "删除",
    "Move up": "上移",
    "Move down": "下移",
    "Differential stripline settings": "差分带状线设置",
    "Signal layer": "信号层",
    "Upper reference copper": "上参考铜层",
    "Lower reference copper": "下参考铜层",
    "Differential impedance (ohm)": "差分阻抗（ohm）",
    "Common impedance (ohm)": "共模阻抗（ohm）",
    "Differential-mode impedance (ohm)": "差模阻抗（ohm）",
    "Common-mode impedance (ohm)": "公模阻抗（ohm）",
    "AEDT version": "AEDT 版本",
    "Board length": "板长",
    "X margin": "X 方向边距",
    "Return vias": "回流过孔",
    "Enable two-sided return vias": "启用两侧回流过孔",
    "Via diameter": "过孔直径",
    "Via edge offset": "过孔边缘偏移",
    "Via pitch": "过孔间距",
    "Radiation / analysis generation": "辐射边界 / 分析设置",
    "Create open Radiation region": "创建开放辐射区域",
    "Create adaptive Setup1": "创建自适应 Setup1",
    "Create interpolating Sweep": "创建插值扫频",
    "Radiation frequency": "辐射边界频率",
    "Sweep start": "扫频起点",
    "Sweep stop / adaptive high": "扫频终点 / 自适应高频点",
    "Sweep points": "扫频点数",
    "Stackup preview": "叠层预览",
    "Materials (same DK/DF is merged)": "材料（相同 DK/DF 自动合并）",
    "Material": "材料",
    "Layers": "所属层",
    "Layer": "层名",
    "Type": "类型",
    "Role": "角色",
    "Thickness": "厚度",
    "Material override": "材料名称覆盖",
    "Copper type": "铜箔类型",
    "GF routing mode": "GF 出线模式",
    "GF pad layer": "GF 焊盘层",
    "GF breakout layer": "GF 出线层",
    "Detected model": "识别的模型",
    "GSSG gold-finger geometry": "GSSG 金手指几何参数",
    "GND pad length": "GND 焊盘长度",
    "GND pad width": "GND 焊盘宽度",
    "Signal pad length": "信号焊盘长度",
    "Signal pad width": "信号焊盘宽度",
    "G-S gap": "G-S 间距",
    "S-S gap": "S-S 间距",
    "Fanout length": "Fanout 长度",
    "Trace length": "走线长度",
    "Fanout pad width": "Fanout 焊盘宽度",
    "Fanout trace width": "Fanout 走线宽度",
    "Pad overlap": "焊盘重叠量",
    "Model length": "模型长度",
    "Side margin": "侧边距",
    "MARK1_X (middle)": "MARK1_X（中间点）",
    "MARK1_Y (middle)": "MARK1_Y（中间点）",
    "MARK2_X (Pad side)": "MARK2_X（焊盘侧）",
    "MARK2_Y (Pad side)": "MARK2_Y（焊盘侧）",
    "Inner breakout VIA parameters": "内层出线过孔参数",
    "Pad radius (R2)": "焊盘半径（R2）",
    "Solid column radius (R1)": "实心铜柱半径（R1）",
    "Signal anti-pad radius (R3)": "信号反焊盘半径（R3）",
    "Default anti-pad +/-X": "默认反焊盘 +/-X",
    "P/N via center spacing": "P/N 过孔中心距",
    "Via-to-pad-center X distance": "过孔中心到焊盘中心的 X 距离",
    "GND return via pitch": "GND 回流过孔间距",
    "GND return vias / pad": "每个焊盘的 GND 回流过孔数",
    "GF pad underlay clearance": "GF 焊盘下方捞空",
    "X1 beyond signal-pad end": "X1（右侧，向 GND/走线方向拓宽）",
    "Y toward GND pads": "Y（向两侧 GND 拓宽）",
    "X2 outside signal-pad edge": "X2（左侧，向信号盘外拓宽）",
    "Clear copper through layer (blank = disabled)": "铜层捞空到达层（留空=关闭）",
    "X1 is the right/GND-side expansion; X2 is the left/outside expansion. Selecting L3 clears reference copper on L1-L3; dielectric, signal pads, and VIA copper remain.": "X1 是右侧（向 GND/走线方向）的拓宽，X2 是左侧（向信号盘外）的拓宽。选择 L3 时捞空 L1-L3 的参考铜；介质、信号焊盘和过孔铜保留。",
    "Optional mechanical VIA": "可选机械过孔",
    "Enable mechanical VIA": "启用机械过孔",
    "Mechanical start layer": "机械过孔起始层",
    "Mechanical end layer": "机械过孔终止层",
    "Laser stacks are generated before the mechanical start and after the mechanical end. Select the breakout layer as the end for direct mechanical route-out.": "机械孔起始层之前、终止层之后会逐层生成激光叠孔；若机械孔直接到出线层，终止层选择出线层即可。",
    "Mechanical column radius": "机械过孔铜柱半径",
    "Mechanical pad radius": "机械过孔焊盘半径",
    "GF stackup preview": "GF 叠层预览",
    "VIA topology": "过孔拓扑",
    "Mode": "模式",
    "Single-stage VIA": "单级过孔",
    "Two-stage VIA": "两级过孔",
    "Single-stage route layers": "单级过孔出线层",
    "Left route layer": "左侧出线层",
    "Right route layer": "右侧出线层",
    "Left line": "左侧走线",
    "Right line": "右侧走线",
    "W line": "走线宽度 W",
    "S line": "线间距 S",
    "G line": "对地间距 G",
    "Single-stage VIA / slot anti-pad / return fence": "单级过孔 / 槽形反焊盘 / 回流围栏",
    "P/N via spacing": "P/N 过孔间距",
    "Laser column radius (R1)": "激光孔铜柱半径（R1）",
    "Laser landing-pad radius (R2)": "激光孔焊盘半径（R2）",
    "Default anti-pad radius": "默认反焊盘半径",
    "Return-column radius": "回流铜柱半径",
    "Line return pitch": "走线回流孔间距",
    "Line return edge offset": "走线回流孔边缘偏移",
    "Local return max pitch": "局部回流孔最大间距",
    "Local return clearance": "局部回流孔净距",
    "Two-stage route layers": "两级过孔层设置",
    "Input route layer": "输入出线层",
    "Stage-1 endpoint / transfer layer": "第一级终点 / 转接层",
    "Mechanical endpoint": "机械过孔终点",
    "Final output layer": "最终输出层",
    "Result": "结果",
    "Two-stage laser / bridge / mechanical VIA / return fence": "两级激光孔 / 桥接 / 机械过孔 / 回流围栏",
    "Stage-1 P/N via spacing": "第一级 P/N 过孔间距",
    "Stage-2 P/N via spacing": "第二级 P/N 过孔间距",
    "Bridge pad-edge clear length": "桥接至焊盘边缘净距",
    "Bridge width": "桥接线宽",
    "Laser column radius": "激光孔铜柱半径",
    "Laser landing-pad radius": "激光孔焊盘半径",
    "Shared stackup used by differential VIA": "差分过孔使用的共享叠层",
    "Browse": "浏览",
    "Generate and open AEDT": "生成并打开 AEDT",
    "Output project": "输出工程",
    "Build log": "生成日志",
    "Save AEDT project": "保存 AEDT 工程",
    "Import configuration": "导入配置",
    "Export configuration": "导出配置",
    "Import failed": "导入失败",
    "Export failed": "导出失败",
    "Unable to generate": "无法生成",
    "AEDT generation failed": "AEDT 生成失败",
    "About HFSS Automodeling": "关于 HFSS 自动建模工具",
    "Choose an output AEDT project path.": "请选择 AEDT 工程输出路径。",
    "Choose L1 or a valid internal copper breakout layer.": "请选择 L1 或有效的内层铜出线层。",
    "Choose all four two-stage VIA route layers.": "请选择两级过孔的全部四个层。",
    "Choose both differential VIA route layers.": "请选择差分过孔的两个出线层。",
    "Differential VIA route layers must be different.": "差分过孔的两个出线层不能相同。",
    "Select an upper reference copper layer for Inner GF.": "请选择 Inner GF 的上参考铜层。",
    "Select a lower reference copper layer for Inner GF.": "请选择 Inner GF 的下参考铜层。",
    "Create interpolating Sweep requires adaptive Setup1.": "创建插值扫频需要启用自适应 Setup1。",
    "Sweep points must be at least 2.": "扫频点数至少为 2。",
    "Unknown error": "未知错误",
    "Inner GF + VIA": "内层 GF + 过孔",
    "Surface GF on L1": "L1 表层 GF",
    "The current stackup does not contain enough ordered copper layers.": "当前叠层没有足够的有序铜层。",
    "The selected breakout copper is marked SIGNAL in this preview.\nThe generated project uses the current shared stackup table.": "预览中所选出线铜层标记为 SIGNAL。\n生成工程使用当前共享叠层表。",
    "Both route-layer choices come from the current copper layers.\nLayer role metadata does not constrain this generator.": "两个出线层均从当前铜层中选择。\n层角色元数据不限制此生成器。",
    "Signal columns always remain independent solids.\nOnly coplanar Trace + Fanout + Landing Pad / transfer bridge are united.\nLaser stacks have a pad on every copper layer; a mechanical span has pads only at its two ends.\nEach copper layer has independent VIA_ANTIPAD_RADIUS_<layer> and VIA_ANTIPAD_X_<layer> variables.": "信号铜柱始终保持为独立实体。\n仅合并同层的走线、Fanout、落地焊盘或转接桥。\n激光孔在经过的每层铜上均有焊盘；机械孔仅在两端有焊盘。\n每个铜层都有独立的 VIA_ANTIPAD_RADIUS_<层名> 和 VIA_ANTIPAD_X_<层名> 变量。",
}

ZH_CN_TRANSLATIONS.update({
    "CAP": "电容",
    "Component mounting side": "电容安装面",
    "Top": "Top（顶层）",
    "Bottom": "Bottom（底层）",
    "Both wave-port deembed distances": "两端 Wave Port 去嵌距离",
    "Enable post-solve TDRZt(Diff1) report": "启用求解后差分 TDRZt(Diff1) 报告",
    "TDR report": "差分 TDR 报告",
    "Create/refresh Diff1 TDR after manual solve": "手动求解后生成/刷新 Diff1 TDR",
    "CAP route and pad geometry": "电容出线层与焊盘尺寸",
    "Left route copper": "左侧出线层",
    "Right route copper": "右侧出线层",
    "Pad center-to-center X": "两焊盘中心距 X",
    "Left pad length X": "左焊盘长度 X",
    "Right pad length X": "右焊盘长度 X",
    "Left pad width Y": "左焊盘宽度 Y",
    "Right pad width Y": "右焊盘宽度 Y",
    "Left pad corner radius": "左焊盘圆角半径",
    "Right pad corner radius": "右焊盘圆角半径",
    "P/N component center pitch Y": "上下电容中心距 Y",
    "Left P/N VIA center pitch D": "左侧 P/N 孔中心距 D",
    "Right P/N VIA center pitch D": "右侧 P/N 孔中心距 D",
    "Pad-to-ground clearance": "焊盘到地铜净距",
    "Left via X offset from pad center": "左孔到焊盘中心 X 偏移",
    "Right via X offset from pad center": "右孔到焊盘中心 X 偏移",
    "Left breakout length (pad edge to via center)": "左侧短线长度（焊盘边缘到孔中心）",
    "Right breakout length (pad edge to via center)": "右侧短线长度（焊盘边缘到孔中心）",
    "Left breakout width": "左侧短线宽度",
    "Right breakout width": "右侧短线宽度",
    "Left via Y offset from pad center": "左孔到焊盘中心 Y 偏移",
    "Right via Y offset from pad center": "右孔到焊盘中心 Y 偏移",
    "Enable one cross-layer mechanical span": "启用跨层机械孔",
    "Generate regular return-VIA fence": "生成规则回流孔围栏",
    "Approximate return-VIA fence (not BRD coordinates)": "规则回流孔近似模型（非 BRD 坐标）",
    "Per-layer anti-pad radii (blank = that side's default).": "逐层槽孔参数（留空=该侧默认值）",
    "Copper layer": "铜层",
    "Enabled": "启用",
    "Void X": "捞空 X",
    "Void Y": "捞空 Y",
    "Corner radius": "圆角半径",
    "Left radius": "左侧半径",
    "Left +/-X": "左侧 ±X",
    "Right radius": "右侧半径",
    "Right +/-X": "右侧 ±X",
    "Anti-pad +/-X": "反焊盘 ±X",
    "CAP pad-group voids: one rounded rectangle centered on all four pads per enabled copper layer.": "电容焊盘整体捞空：每个启用铜层均以四焊盘整体中心建立一个圆角矩形。",
    "CAP-specific stackup / void preview": "电容专用叠层 / 捞空预览",
    "CAP surface process": "电容表面工艺",
    "Enable tin solder": "启用 Tin 焊料",
    "Solder material": "焊料材料",
    "Solder height": "焊料高度",
    "Enable solder mask": "启用绿油",
    "Solder-mask DK": "绿油 DK",
    "Solder-mask DF": "绿油 DF",
    "Mask thickness over copper": "铜上绿油厚度",
    "Mask thickness in gaps": "间隙绿油厚度",
    "Mask edge transition width": "绿油边缘过渡宽度",
    "CAP pair-window expansion": "CAP 通窗外扩",
    "CAP electrical model": "电容电气模型",
    "Enable ideal Lumped RLC connection": "启用理想 Lumped RLC 连接",
    "Capacitance per P/N branch": "每条 P/N 支路的电容量",
    "P/N use two independent ideal Lumped RLC sheets by default. Only C=0.1uF is enabled; component ESR/ESL and package parasitics are not included. Disable the RLC option to restore open PCB pad gaps.": "P/N 默认使用两个独立的理想 Lumped RLC 矩形连接；仅启用 C=0.1uF，不包含器件 ESR、ESL 和封装寄生。关闭该选项可恢复 PCB 焊盘开路。",
    "Opening mode": "开窗模式",
    "Pair open window": "左右焊盘开通窗",
    "CAP GROUP VOID is the per-layer rounded-rectangle void for all four pads; ROUTE VOID is the W/S/G trace clearance.\nLEFT/RIGHT VIA SLOT uses each stack's independent per-layer R/+/-X and remains separate from the group void.": "CAP GROUP VOID 是逐层独立的电容四焊盘整体圆角矩形捞空；ROUTE VOID 是 W/S/G 出线避让。\nLEFT/RIGHT VIA SLOT 是两侧过孔各自逐层的槽孔 R/±X，不与电容整体捞空合并。",
    "PCB-only: two independent L1 capacitor gaps remain OPEN. The 203 x 203 um pads, 50 um corners, X=327 um and Y=373 um are current BRD defaults; via and void dimensions still require independent BRD checks.": "仅 PCB：两组 L1 电容间隙保持开路。203×203 µm 焊盘、50 µm 圆角、X=327 µm、Y=373 µm 为当前 BRD 默认值；孔与捞空尺寸仍需分别核对 BRD。",
    "PCB-only: two independent L1 capacitor gaps remain OPEN. Example dimensions are NOT verified BRD data; S21/TDR cannot describe the complete capacitor.": "仅 PCB：L1 电容间隙保持开路；默认尺寸尚未经 BRD 核实，S21/TDR 不能代表完整电容链路。",
    "Copper edge gap: pending geometry": "铜边间隙：等待输入尺寸",
    "Copper edge gap: enter measured pad dimensions": "铜边间隙：请输入实测焊盘尺寸",
})
ZH_CN_TRANSLATIONS.update({
    "Use packaged physical 0.1 uF A3D capacitor": "使用内置的 0.1 uF 实体 A3D 电容",
    "Physical capacitor file": "实体电容文件",
    "Choose A3D capacitor": "选择 A3D 电容",
    "Bundled component is used when blank": "留空时使用软件内置电容模型",
    "The packaged physical 0.1 uF capacitor is used by default. Ideal Lumped RLC is an alternative and the two modes cannot be enabled together.": "默认使用内置的 0.1 uF 实体电容。理想 Lumped RLC 是替代模式，两种模式不能同时启用。",
    "Generate paired RLC + A3D designs": "生成一对 RLC + A3D 对比 Design",
    "Series resistance": "串联电阻 ESR",
    "Series inductance": "串联电感 ESL",
    "RLC fit start": "RLC 拟合起始频率",
    "RLC fit stop": "RLC 拟合终止频率",
    "Fit RLC from S2P...": "从 S2P 拟合 RLC...",
    "RLC source S2P": "RLC 来源 S2P",
    "RLC fit complete": "RLC 拟合完成",
    "RLC fit failed": "RLC 拟合失败",
    "Choose S2P capacitor": "选择电容 S2P",
})
ZH_CN_REVERSE = {value: key for key, value in ZH_CN_TRANSLATIONS.items()}


class StackPreview(QGraphicsView):
    COLORS = {"copper": QColor("#e58b22"), "pp": QColor("#b9e5aa"), "core": QColor("#f2dd55")}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setMinimumHeight(260)
        self.setRenderHint(QPainter.Antialiasing)

    def update_layers(
        self, layers: list[Layer], annotations: dict[str, list[str]] | None = None
    ) -> None:
        self.scene.clear()
        if not layers:
            return
        annotations = annotations or {}
        width, row_height = 520 if annotations else 270, max(24, 360 // len(layers))
        for index, layer in enumerate(layers):
            y = index * row_height
            color = self.COLORS.get(layer.kind, QColor("#dddddd"))
            self.scene.addRect(0, y, width, row_height - 2, brush=color)
            label = f"{layer.name} | {layer.kind.upper()} | {layer.thickness}"
            if layer.role == "signal":
                label += " | SIGNAL"
            if annotations.get(layer.name):
                label += " | " + " / ".join(annotations[layer.name])
            text = self.scene.addText(label)
            text.setPos(6, y + 2)
        self.scene.setSceneRect(0, 0, width, len(layers) * row_height)
        self.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)


class BuildWorker(QObject):
    log = Signal(str)
    success = Signal(str)
    failed = Signal(str)
    finished = Signal()

    def __init__(
        self,
        mode: str,
        stackup: StackupConfig,
        output_path: str,
        gssg: GSSGConfig | None = None,
        inner_gf: InnerGFConfig | None = None,
        differential_via: DifferentialViaConfig | None = None,
        multistage_via: MultiStageDifferentialViaConfig | None = None,
        cap_pad: CapPadConfig | None = None,
    ):
        super().__init__()
        self.mode = mode
        self.stackup = stackup
        self.output_path = output_path
        self.gssg = gssg
        self.inner_gf = inner_gf
        self.differential_via = differential_via
        self.multistage_via = multistage_via
        self.cap_pad = cap_pad

    def run(self) -> None:
        try:
            if self.mode == "stackup_tdr":
                from pyaedt import Hfss
                hfss = Hfss(
                    project=self.output_path, design=self.stackup.design_name,
                    version=self.stackup.aedt_version.strip() or None,
                    new_desktop=False, close_on_exit=False,
                )
                try:
                    report_name = create_stackup_tdr_report(hfss)
                    self.log.emit(f"Post-solve report ready: {report_name}")
                finally:
                    hfss.release_desktop(close_projects=False, close_desktop=False)
                path = Path(self.output_path)
            elif self.mode == "inner_gf":
                if self.gssg is None or self.inner_gf is None:
                    raise ValueError("Inner GF configuration is missing.")
                path = build_inner_gf_project(
                    self.stackup, self.gssg, self.inner_gf, self.output_path,
                    keep_desktop_open=False, log_callback=self.log.emit,
                )
            elif self.mode == "differential_via":
                if self.differential_via is None:
                    raise ValueError("Differential VIA configuration is missing.")
                path = build_differential_via_project(
                    self.stackup, self.differential_via, self.output_path,
                    keep_desktop_open=False, log_callback=self.log.emit,
                )
            elif self.mode == "multistage_via":
                if self.multistage_via is None:
                    raise ValueError("Two-stage differential VIA configuration is missing.")
                path = build_multistage_differential_via_project(
                    self.stackup, self.multistage_via, self.output_path,
                    keep_desktop_open=False, log_callback=self.log.emit,
                )
            elif self.mode == "gssg":
                if self.gssg is None:
                    raise ValueError("GSSG configuration is missing.")
                path = build_gssg_project(self.stackup, self.gssg, self.output_path,
                                          keep_desktop_open=False, log_callback=self.log.emit)
            elif self.mode == "cap_pad":
                if self.cap_pad is None:
                    raise ValueError("CAP pad configuration is missing.")
                path = build_cap_pad_project(self.stackup, self.cap_pad, self.output_path,
                                             keep_desktop_open=False, log_callback=self.log.emit)
            else:
                path = build_aedt_project(self.stackup, self.output_path,
                                          keep_desktop_open=False, log_callback=self.log.emit)
            self.success.emit(str(path))
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            self.finished.emit()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._language = "en"
        self.setWindowTitle("HFSS Stackup / GF / Differential VIA Generator")
        self.resize(1400, 900)
        self._loading = False
        self._material_members: dict[str, list[str]] = {}
        self._material_rows: list[str] = []
        self._thread: QThread | None = None
        self._worker: BuildWorker | None = None
        self.config = eight_layer_example()
        self.gssg_config = GSSGConfig(signal_layer_name="L1")
        self.inner_gf_config = InnerGFConfig()
        self.differential_via_config = DifferentialViaConfig()
        self.multistage_via_config = MultiStageDifferentialViaConfig()
        self.cap_pad_config = CapPadConfig()
        self._active_via_mode = "single"
        self._build_ui()
        self.load_config_into_ui(
            self.config, self.gssg_config, self.inner_gf_config,
            self.differential_via_config, self.multistage_via_config,
            self.cap_pad_config,
        )

    def _ui_text(self, text: str) -> str:
        """Translate one canonical English UI string without touching model data."""
        if self._language == "zh_CN":
            return ZH_CN_TRANSLATIONS.get(text, text)
        return text

    @staticmethod
    def _canonical_ui_text(text: str) -> str:
        return ZH_CN_REVERSE.get(text, text)

    def _apply_language(self) -> None:
        """Retranslate existing widgets while preserving layer/config values."""
        self.setWindowTitle(self._ui_text(
            "HFSS Stackup / GF / Differential VIA Generator"
        ))
        for label in self.findChildren(QLabel):
            source = self._canonical_ui_text(label.text())
            label.setText(self._ui_text(source))
        for button in self.findChildren(QAbstractButton):
            source = self._canonical_ui_text(button.text())
            button.setText(self._ui_text(source))
        for group in self.findChildren(QGroupBox):
            source = self._canonical_ui_text(group.title())
            group.setTitle(self._ui_text(source))
        for action in self.findChildren(QAction):
            source = self._canonical_ui_text(action.text())
            action.setText(self._ui_text(source))
        for index in range(self.tabs.count()):
            source = self._canonical_ui_text(self.tabs.tabText(index))
            self.tabs.setTabText(index, self._ui_text(source))
        self.layer_table.setHorizontalHeaderLabels([
            self._ui_text(text) for text in LAYER_COLUMNS
        ])
        self.material_table.setHorizontalHeaderLabels([
            self._ui_text(text) for text in ("Material", "DK", "DF", "Layers")
        ])
        self.cap_antipad_table.setHorizontalHeaderLabels([
            self._ui_text(text) for text in
            ("Copper layer", "Left radius", "Left +/-X", "Right radius", "Right +/-X")
        ])
        self.cap_void_table.setHorizontalHeaderLabels([
            self._ui_text(text) for text in
            ("Copper layer", "Enabled", "Void X", "Void Y", "Corner radius")
        ])
        self.log_view.setPlaceholderText(self._ui_text("Build log"))
        self.via_mode.blockSignals(True)
        for index in range(self.via_mode.count()):
            source = "Single-stage VIA" if self.via_mode.itemData(index) == "single" else "Two-stage VIA"
            self.via_mode.setItemText(index, self._ui_text(source))
        self.via_mode.blockSignals(False)
        self.cap_component_side.blockSignals(True)
        for index, source in enumerate(("Top", "Bottom")):
            self.cap_component_side.setItemText(index, self._ui_text(source))
        self.cap_component_side.blockSignals(False)
        self.cap_mask_opening_mode.blockSignals(True)
        self.cap_mask_opening_mode.setItemText(0, self._ui_text("Pair open window"))
        self.cap_mask_opening_mode.blockSignals(False)
        self.cap_real_component_file.setPlaceholderText(
            self._ui_text("Bundled component is used when blank")
        )

    def _on_language_changed(self, index: int) -> None:
        selected = self.language_combo.itemData(index)
        if selected not in {"en", "zh_CN"}:
            return
        self._language = selected
        self.refresh_views()

    def _localized_message(self, message: str) -> str:
        """Translate GUI-owned validation messages; retain technical details."""
        if self._language != "zh_CN":
            return message
        if message in ZH_CN_TRANSLATIONS:
            return ZH_CN_TRANSLATIONS[message]
        suffixes = {
            ": choose a valid copper route layer.": "：请选择有效的铜出线层。",
            ": select an upper reference copper layer.": "：请选择上参考铜层。",
            ": select a lower reference copper layer.": "：请选择下参考铜层。",
        }
        for suffix, translated in suffixes.items():
            if message.endswith(suffix):
                return message[:-len(suffix)] + translated
        return message

    # ---------- common widgets and stackup tab ----------
    def _combo(self, values: list[str], current: str) -> QComboBox:
        combo = QComboBox()
        combo.addItems(values)
        combo.setCurrentText(current)
        combo.currentTextChanged.connect(self.on_editor_changed)
        return combo

    def _build_analysis_group(self, prefix: str) -> QGroupBox:
        """Create one independent Radiation/Setup/Sweep editor for a tab."""
        group = QGroupBox("Radiation / analysis generation")
        form = QFormLayout(group)
        checkboxes = {
            "create_open_region": QCheckBox("Create open Radiation region"),
            "create_setup": QCheckBox("Create adaptive Setup1"),
            "create_sweep": QCheckBox("Create interpolating Sweep"),
        }
        for checkbox in checkboxes.values():
            checkbox.toggled.connect(self.on_editor_changed)
            form.addRow(checkbox)
        fields: dict[str, QLineEdit] = {}
        for label, key in (
            ("Radiation frequency", "open_region_frequency"),
            ("Sweep start", "sweep_start"),
            ("Sweep stop / adaptive high", "sweep_stop"),
            ("Sweep points", "sweep_points"),
        ):
            edit = QLineEdit()
            edit.textChanged.connect(self.on_editor_changed)
            fields[key] = edit
            form.addRow(label, edit)
        setattr(self, f"{prefix}_analysis_checks", checkboxes)
        setattr(self, f"{prefix}_analysis_fields", fields)
        return group

    def _load_analysis_options(self, prefix: str, config: object) -> None:
        checks = getattr(self, f"{prefix}_analysis_checks")
        fields = getattr(self, f"{prefix}_analysis_fields")
        for key, checkbox in checks.items():
            checkbox.setChecked(bool(getattr(config, key)))
        for key, edit in fields.items():
            edit.setText(str(getattr(config, key)))

    def _analysis_options_from_ui(self, prefix: str) -> dict[str, object]:
        checks = getattr(self, f"{prefix}_analysis_checks")
        fields = getattr(self, f"{prefix}_analysis_fields")
        values: dict[str, object] = {
            key: checkbox.isChecked() for key, checkbox in checks.items()
        }
        values.update({key: edit.text().strip() for key, edit in fields.items()})
        values["sweep_points"] = int(str(values["sweep_points"]))
        if values["create_sweep"] and not values["create_setup"]:
            raise ValueError("Create interpolating Sweep requires adaptive Setup1.")
        if values["create_sweep"] and int(values["sweep_points"]) < 2:
            raise ValueError("Sweep points must be at least 2.")
        return values

    def _build_ui(self) -> None:
        toolbar = QToolBar("File")
        self.addToolBar(toolbar)
        for text, slot in (("New", self.new_config), ("Load example", self.load_example),
                           ("Import JSON", self.import_json), ("Export JSON", self.export_json)):
            action = QAction(text, self)
            action.triggered.connect(slot)
            toolbar.addAction(action)
        toolbar.addSeparator()
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        toolbar.addAction(about_action)
        toolbar.addSeparator()
        self.language_label = QLabel("Language")
        toolbar.addWidget(self.language_label)
        self.language_combo = QComboBox()
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("中文", "zh_CN")
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        toolbar.addWidget(self.language_combo)

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs, 1)
        self._build_stackup_tab()
        self._build_gssg_tab()
        self._build_differential_via_tab()
        self._build_cap_pad_tab()
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(500)
        self.log_view.setPlaceholderText("Build log")
        root_layout.addWidget(self.log_view, 0)
        self.copyright_label = QLabel(f"Developer: {DEVELOPER}    {COPYRIGHT}")
        self.copyright_label.setAlignment(Qt.AlignCenter)
        root_layout.addWidget(self.copyright_label)

    def _build_stackup_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Stackup (top to bottom)"))
        self.layer_table = QTableWidget(0, len(LAYER_COLUMNS))
        self.layer_table.setHorizontalHeaderLabels(LAYER_COLUMNS)
        self.layer_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.layer_table.itemChanged.connect(self.on_editor_changed)
        left_layout.addWidget(self.layer_table, 1)
        buttons = QHBoxLayout()
        for text, kind in (("+ Copper", "copper"), ("+ PP", "pp"), ("+ Core", "core")):
            b = QPushButton(text)
            b.clicked.connect(lambda checked=False, k=kind: self.add_layer(k))
            buttons.addWidget(b)
        for text, slot in (("Delete", self.delete_layer), ("Move up", lambda: self.move_layer(-1)),
                           ("Move down", lambda: self.move_layer(1))):
            b = QPushButton(text)
            b.clicked.connect(slot)
            buttons.addWidget(b)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        group = QGroupBox("Differential stripline settings")
        form = QFormLayout(group)
        self.signal_layer = QComboBox()
        self.signal_layer.currentTextChanged.connect(self.on_signal_layer_selected)
        self.stackup_upper_reference = QComboBox()
        self.stackup_lower_reference = QComboBox()
        self.stackup_upper_reference.currentTextChanged.connect(self.on_editor_changed)
        self.stackup_lower_reference.currentTextChanged.connect(self.on_editor_changed)
        self.w_line, self.s_line, self.g_line = QLineEdit(), QLineEdit(), QLineEdit()
        self.diff_z, self.aedt_version = QLineEdit(), QLineEdit()
        self.board_length, self.board_margin = QLineEdit(), QLineEdit()
        self.return_vias_enabled = QCheckBox("Enable two-sided return vias")
        self.return_via_diameter, self.return_via_offset, self.return_via_pitch = QLineEdit(), QLineEdit(), QLineEdit()
        self.common_z = QLineEdit()
        self.stackup_deembed = QLineEdit()
        self.stackup_tdr_report = QCheckBox("Enable post-solve TDRZt(Diff1) report")
        for c in (self.w_line, self.s_line, self.g_line, self.diff_z, self.aedt_version,
                  self.board_length, self.board_margin, self.return_via_diameter,
                  self.return_via_offset, self.return_via_pitch, self.common_z,
                  self.stackup_deembed):
            c.textChanged.connect(self.on_editor_changed)
        self.return_vias_enabled.toggled.connect(self.on_editor_changed)
        self.stackup_tdr_report.toggled.connect(self.on_editor_changed)
        for label, control in (("Signal layer", self.signal_layer),
                               ("Upper reference copper", self.stackup_upper_reference),
                               ("Lower reference copper", self.stackup_lower_reference),
                               ("W", self.w_line), ("S", self.s_line),
                               ("G", self.g_line), ("Differential-mode impedance (ohm)", self.diff_z),
                               ("Common-mode impedance (ohm)", self.common_z), ("AEDT version", self.aedt_version),
                               ("Board length", self.board_length), ("X margin", self.board_margin),
                               ("Return vias", self.return_vias_enabled), ("Via diameter", self.return_via_diameter),
                               ("Via edge offset", self.return_via_offset), ("Via pitch", self.return_via_pitch),
                               ("Both wave-port deembed distances", self.stackup_deembed),
                               ("TDR report", self.stackup_tdr_report)):
            form.addRow(label, control)
        right_layout.addWidget(group)
        right_layout.addWidget(self._build_analysis_group("stackup"))
        right_layout.addWidget(QLabel("Stackup preview"))
        self.preview = StackPreview()
        right_layout.addWidget(self.preview, 1)
        right_layout.addWidget(QLabel("Materials (same DK/DF is merged)"))
        self.material_table = QTableWidget(0, 4)
        self.material_table.setHorizontalHeaderLabels(["Material", "DK", "DF", "Layers"])
        self.material_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.material_table.cellChanged.connect(self.on_material_name_changed)
        right_layout.addWidget(self.material_table, 1)
        splitter.addWidget(right)
        splitter.setSizes([850, 550])
        layout.addWidget(splitter, 1)
        output, browse, build = self._output_row("generated_stackup")
        self.stackup_output = output
        self.stackup_build = build
        build.clicked.connect(lambda: self.generate_project("stackup"))
        layout.addLayout(self._row_with_widgets(output, browse, build))
        self.stackup_tdr_build = QPushButton("Create/refresh Diff1 TDR after manual solve")
        self.stackup_tdr_build.clicked.connect(lambda: self.generate_project("stackup_tdr"))
        layout.addWidget(self.stackup_tdr_build)
        self.tabs.addTab(tab, "Stackup differential")

    # ---------- Unified surface/inner GF tab ----------
    def _build_gssg_tab(self) -> None:
        tab = QWidget(); layout = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Horizontal)
        controls = QWidget(); controls_layout = QVBoxLayout(controls)

        route_group = QGroupBox("GF routing mode")
        route_form = QFormLayout(route_group)
        self.gssg_layer = QComboBox()
        self.gssg_layer.currentTextChanged.connect(self.on_gssg_layer_selected)
        self.gf_mode = QLineEdit(); self.gf_mode.setReadOnly(True)
        self.inner_gf_layer = QLineEdit("L1"); self.inner_gf_layer.setReadOnly(True)
        self.inner_upper_reference = QComboBox()
        self.inner_lower_reference = QComboBox()
        self.inner_upper_reference.currentTextChanged.connect(self.on_editor_changed)
        self.inner_lower_reference.currentTextChanged.connect(self.on_editor_changed)
        route_form.addRow("GF pad layer", self.inner_gf_layer)
        route_form.addRow("GF breakout layer", self.gssg_layer)
        route_form.addRow("Detected model", self.gf_mode)
        route_form.addRow("Upper reference copper", self.inner_upper_reference)
        route_form.addRow("Lower reference copper", self.inner_lower_reference)
        controls_layout.addWidget(route_group)

        group = QGroupBox("GSSG gold-finger geometry")
        form = QFormLayout(group)
        self.gssg_fields: dict[str, QLineEdit] = {}
        fields = (
            ("GND pad length", "gnd_pad_length"), ("GND pad width", "gnd_pad_width"),
            ("Signal pad length", "signal_pad_length"), ("Signal pad width", "signal_pad_width"),
            ("G-S gap", "gs_gap"), ("S-S gap", "ss_gap"), ("Fanout length", "fanout_length"),
            ("Trace length", "trace_length"), ("W_LINE", "w_line"), ("S_LINE", "s_line"),
            ("G_LINE", "g_line"),
            ("Fanout pad width", "fanout_pad_width"), ("Fanout trace width", "fanout_trace_width"),
            ("Pad overlap", "pad_overlap"), ("Model length", "model_length"), ("Side margin", "side_margin"),
        )
        for label, key in fields:
            edit = QLineEdit(); self.gssg_fields[key] = edit
            edit.textChanged.connect(self.on_editor_changed)
            form.addRow(label, edit)
        # MARK1 controls the intermediate fan-out point; MARK2 controls the
        # Pad-side point.  The same four variables are used for P and N.
        self.mark1_x, self.mark1_y = QLineEdit(), QLineEdit()
        self.mark2_x, self.mark2_y = QLineEdit(), QLineEdit()
        for label, control in (("MARK1_X (middle)", self.mark1_x), ("MARK1_Y (middle)", self.mark1_y),
                               ("MARK2_X (Pad side)", self.mark2_x), ("MARK2_Y (Pad side)", self.mark2_y)):
            control.textChanged.connect(self.on_editor_changed)
            form.addRow(label, control)
        controls_layout.addWidget(group)

        self.inner_options_group = QGroupBox("Inner breakout VIA parameters")
        inner_form = QFormLayout(self.inner_options_group)
        self.inner_gf_fields: dict[str, QLineEdit] = {}
        inner_fields = (
            ("Pad radius (R2)", "via_pad_radius"),
            ("Solid column radius (R1)", "via_column_radius"),
            ("Signal anti-pad radius (R3)", "via_antipad_radius"),
            ("Default anti-pad +/-X", "via_antipad_x"),
            ("P/N via center spacing", "d_via"),
            ("Via-to-pad-center X distance", "via_x_offset"),
            ("GND return via pitch", "gnd_return_via_pitch"),
        )
        for label, key in inner_fields:
            edit = QLineEdit(); self.inner_gf_fields[key] = edit
            edit.textChanged.connect(self.on_editor_changed)
            inner_form.addRow(label, edit)
        self.gnd_return_via_count = QLineEdit()
        self.gnd_return_via_count.textChanged.connect(self.on_editor_changed)
        inner_form.addRow("GND return vias / pad", self.gnd_return_via_count)
        controls_layout.addWidget(self.inner_options_group)

        self.inner_pad_void_group = QGroupBox("GF pad underlay clearance")
        pad_void_form = QFormLayout(self.inner_pad_void_group)
        self.inner_pad_void_fields: dict[str, QLineEdit] = {}
        for label, key in (
            ("X1 beyond signal-pad end", "pad_void_x1"),
            ("Y toward GND pads", "pad_void_y"),
            ("X2 outside signal-pad edge", "pad_void_x2"),
        ):
            edit = QLineEdit()
            edit.textChanged.connect(self.on_editor_changed)
            self.inner_pad_void_fields[key] = edit
            pad_void_form.addRow(label, edit)
        self.inner_pad_void_end_layer = QComboBox()
        self.inner_pad_void_end_layer.currentTextChanged.connect(
            self.on_editor_changed
        )
        pad_void_form.addRow(
            "Clear copper through layer (blank = disabled)",
            self.inner_pad_void_end_layer,
        )
        pad_void_help = QLabel(
            "X1 is the right/GND-side expansion; X2 is the left/outside expansion. "
            "Selecting L3 clears reference copper on L1-L3; dielectric, signal pads, "
            "and VIA copper remain."
        )
        pad_void_help.setWordWrap(True)
        pad_void_form.addRow(pad_void_help)
        controls_layout.addWidget(self.inner_pad_void_group)

        self.inner_mechanical_group = QGroupBox("Optional mechanical VIA")
        mechanical_form = QFormLayout(self.inner_mechanical_group)
        self.inner_mechanical_via_enabled = QCheckBox("Enable mechanical VIA")
        self.inner_mechanical_start_layer = QComboBox()
        self.inner_mechanical_end_layer = QComboBox()
        self.inner_mechanical_column_radius = QLineEdit()
        self.inner_mechanical_pad_radius = QLineEdit()
        self.inner_mechanical_via_enabled.toggled.connect(
            self.on_inner_mechanical_option_changed
        )
        self.inner_mechanical_start_layer.currentTextChanged.connect(
            self.on_inner_mechanical_layer_selected
        )
        self.inner_mechanical_end_layer.currentTextChanged.connect(
            self.on_editor_changed
        )
        self.inner_mechanical_column_radius.textChanged.connect(self.on_editor_changed)
        self.inner_mechanical_pad_radius.textChanged.connect(self.on_editor_changed)
        mechanical_form.addRow(self.inner_mechanical_via_enabled)
        mechanical_form.addRow(
            "Mechanical start layer", self.inner_mechanical_start_layer
        )
        mechanical_form.addRow(
            "Mechanical end layer", self.inner_mechanical_end_layer
        )
        inner_mechanical_help = QLabel(
            "Laser stacks are generated before the mechanical start and after the "
            "mechanical end. Select the breakout layer as the end for direct "
            "mechanical route-out."
        )
        inner_mechanical_help.setWordWrap(True)
        mechanical_form.addRow(inner_mechanical_help)
        mechanical_form.addRow(
            "Mechanical column radius", self.inner_mechanical_column_radius
        )
        mechanical_form.addRow(
            "Mechanical pad radius", self.inner_mechanical_pad_radius
        )
        controls_layout.addWidget(self.inner_mechanical_group)
        controls_layout.addWidget(self._build_analysis_group("gssg"))
        self.gf_mode_help = QLabel()
        self.gf_mode_help.setWordWrap(True)
        controls_layout.addWidget(self.gf_mode_help)
        controls_layout.addStretch(1)
        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setWidget(controls)
        splitter.addWidget(controls_scroll)

        preview_panel = QWidget(); preview_layout = QVBoxLayout(preview_panel)
        preview_layout.addWidget(QLabel("GF stackup preview"))
        self.gssg_preview = StackPreview(); preview_layout.addWidget(self.gssg_preview, 1)
        preview_layout.addWidget(QLabel(
            "The selected breakout copper is marked SIGNAL in this preview.\n"
            "The generated project uses the current shared stackup table."
        ))
        splitter.addWidget(preview_panel)
        splitter.setSizes([850, 550]); layout.addWidget(splitter, 1)

        output, browse, build = self._output_row("generated_gf")
        self.gssg_output = output
        self.gssg_build = build
        build.clicked.connect(lambda: self.generate_project("gf"))
        layout.addLayout(self._row_with_widgets(output, browse, build))
        self.tabs.addTab(tab, "GF")

    # ---------- Differential VIA tab ----------
    def _build_differential_via_tab(self) -> None:
        tab = QWidget(); layout = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Horizontal)

        controls = QWidget(); controls_layout = QVBoxLayout(controls)
        mode_group = QGroupBox("VIA topology")
        mode_form = QFormLayout(mode_group)
        self.via_mode = QComboBox()
        self.via_mode.addItem("Single-stage VIA", "single")
        self.via_mode.addItem("Two-stage VIA", "multistage")
        self.via_mode.currentIndexChanged.connect(self.on_via_mode_changed)
        mode_form.addRow("Mode", self.via_mode)
        controls_layout.addWidget(mode_group)

        layer_group = QGroupBox("Single-stage route layers")
        self.single_via_layer_group = layer_group
        layer_form = QFormLayout(layer_group)
        self.via_start_layer = QComboBox()
        self.via_end_layer = QComboBox()
        self.via_start_layer.currentTextChanged.connect(self.on_via_route_layer_selected)
        self.via_end_layer.currentTextChanged.connect(self.on_via_route_layer_selected)
        layer_form.addRow("Left route layer", self.via_start_layer)
        layer_form.addRow("Right route layer", self.via_end_layer)
        controls_layout.addWidget(layer_group)

        line_row = QHBoxLayout()
        self.via_start_line_fields: dict[str, QLineEdit] = {}
        self.via_end_line_fields: dict[str, QLineEdit] = {}
        self.via_reference_combos: dict[str, dict[str, QComboBox]] = {
            "start": {}, "end": {},
        }
        for title, prefix, fields in (
            ("Left line", "start", self.via_start_line_fields),
            ("Right line", "end", self.via_end_line_fields),
        ):
            group = QGroupBox(title); form = QFormLayout(group)
            for label, key in (
                ("Trace length", "trace_length"),
                ("Fanout length", "fanout_length"),
                ("W line", "w_line"),
                ("S line", "s_line"),
                ("G line", "g_line"),
            ):
                edit = QLineEdit(); fields[key] = edit
                edit.textChanged.connect(self.on_editor_changed)
                form.addRow(label, edit)
            for label, side in (
                ("Upper reference copper", "upper"),
                ("Lower reference copper", "lower"),
            ):
                combo = QComboBox()
                combo.currentTextChanged.connect(self.on_editor_changed)
                self.via_reference_combos[prefix][side] = combo
                form.addRow(label, combo)
            line_row.addWidget(group)
        controls_layout.addLayout(line_row)

        via_group = QGroupBox("Single-stage VIA / slot anti-pad / return fence")
        self.single_via_geometry_group = via_group
        via_form = QFormLayout(via_group)
        self.differential_via_fields: dict[str, QLineEdit] = {}
        for label, key in (
            ("P/N via spacing", "d_via"),
            ("Laser column radius (R1)", "via_column_radius"),
            ("Laser landing-pad radius (R2)", "via_pad_radius"),
            ("Default anti-pad radius", "via_antipad_radius"),
            ("Default anti-pad +/-X", "via_antipad_x"),
            ("Return-column radius", "return_column_radius"),
            ("Line return pitch", "line_return_pitch"),
            ("Line return edge offset", "line_return_edge_offset"),
            ("Local return max pitch", "local_return_pitch"),
            ("Local return clearance", "local_return_clearance"),
            ("Side margin", "side_margin"),
        ):
            edit = QLineEdit(); self.differential_via_fields[key] = edit
            edit.textChanged.connect(self.on_editor_changed)
            via_form.addRow(label, edit)
        controls_layout.addWidget(via_group)

        mechanical_group = QGroupBox("Optional mechanical VIA")
        self.single_via_mechanical_group = mechanical_group
        mechanical_form = QFormLayout(mechanical_group)
        self.mechanical_via_enabled = QCheckBox("Enable mechanical VIA")
        self.mechanical_start_layer = QComboBox()
        self.mechanical_end_layer = QComboBox()
        self.mechanical_column_radius = QLineEdit()
        self.mechanical_pad_radius = QLineEdit()
        self.mechanical_via_enabled.toggled.connect(
            self.on_via_mechanical_option_changed
        )
        self.mechanical_start_layer.currentTextChanged.connect(
            self.on_via_mechanical_layer_selected
        )
        self.mechanical_end_layer.currentTextChanged.connect(self.on_editor_changed)
        self.mechanical_column_radius.textChanged.connect(self.on_editor_changed)
        self.mechanical_pad_radius.textChanged.connect(self.on_editor_changed)
        mechanical_form.addRow(self.mechanical_via_enabled)
        mechanical_form.addRow("Mechanical start layer", self.mechanical_start_layer)
        mechanical_form.addRow("Mechanical end layer", self.mechanical_end_layer)
        via_mechanical_help = QLabel(
            "Laser stacks are generated before the mechanical start and after the "
            "mechanical end. Select the breakout layer as the end for direct "
            "mechanical route-out."
        )
        via_mechanical_help.setWordWrap(True)
        mechanical_form.addRow(via_mechanical_help)
        mechanical_form.addRow("Mechanical column radius", self.mechanical_column_radius)
        mechanical_form.addRow("Mechanical pad radius", self.mechanical_pad_radius)
        controls_layout.addWidget(mechanical_group)

        multistage_layers = QGroupBox("Two-stage route layers")
        self.multistage_via_layer_group = multistage_layers
        multistage_layer_form = QFormLayout(multistage_layers)
        self.multistage_layer_combos: list[QComboBox] = []
        for label in (
            "Input route layer",
            "Stage-1 endpoint / transfer layer",
            "Mechanical endpoint",
            "Final output layer",
        ):
            combo = QComboBox()
            combo.currentTextChanged.connect(self.on_multistage_layer_selected)
            self.multistage_layer_combos.append(combo)
            multistage_layer_form.addRow(label, combo)
        self.multistage_route_status = QLabel()
        self.multistage_route_status.setWordWrap(True)
        multistage_layer_form.addRow("Result", self.multistage_route_status)
        controls_layout.addWidget(multistage_layers)

        multistage_geometry = QGroupBox(
            "Two-stage laser / bridge / mechanical VIA / return fence"
        )
        self.multistage_via_geometry_group = multistage_geometry
        multistage_form = QFormLayout(multistage_geometry)
        self.multistage_via_fields: dict[str, QLineEdit] = {}
        for label, key in (
            ("Stage-1 P/N via spacing", "stage1_d_via"),
            ("Stage-2 P/N via spacing", "stage2_d_via"),
            ("Bridge pad-edge clear length", "bridge_clear_length"),
            ("Bridge width", "bridge_width"),
            ("Laser column radius", "via_column_radius"),
            ("Laser landing-pad radius", "via_pad_radius"),
            ("Mechanical column radius", "mechanical_column_radius"),
            ("Mechanical pad radius", "mechanical_pad_radius"),
            ("Default anti-pad radius", "via_antipad_radius"),
            ("Default anti-pad +/-X", "via_antipad_x"),
            ("Return-column radius", "return_column_radius"),
            ("Line return pitch", "line_return_pitch"),
            ("Line return edge offset", "line_return_edge_offset"),
            ("Local return max pitch", "local_return_pitch"),
            ("Local return clearance", "local_return_clearance"),
            ("Side margin", "side_margin"),
        ):
            edit = QLineEdit()
            edit.textChanged.connect(self.on_editor_changed)
            self.multistage_via_fields[key] = edit
            multistage_form.addRow(label, edit)
        controls_layout.addWidget(multistage_geometry)

        controls_layout.addWidget(self._build_analysis_group("via"))
        controls_layout.addWidget(QLabel(
            "Signal columns always remain independent solids.\n"
            "Only coplanar Trace + Fanout + Landing Pad / transfer bridge are united.\n"
            "Laser stacks have a pad on every copper layer; a mechanical span has pads only at its two ends.\n"
            "Each copper layer has independent VIA_ANTIPAD_RADIUS_<layer> and VIA_ANTIPAD_X_<layer> variables."
        ))
        controls_layout.addStretch(1)
        via_controls_scroll = QScrollArea()
        via_controls_scroll.setWidgetResizable(True)
        via_controls_scroll.setWidget(controls)
        splitter.addWidget(via_controls_scroll)

        preview_panel = QWidget(); preview_layout = QVBoxLayout(preview_panel)
        preview_layout.addWidget(QLabel("Shared stackup used by differential VIA"))
        self.differential_via_preview = StackPreview()
        preview_layout.addWidget(self.differential_via_preview, 1)
        preview_layout.addWidget(QLabel(
            "Both route-layer choices come from the current copper layers.\n"
            "Layer role metadata does not constrain this generator."
        ))
        splitter.addWidget(preview_panel)
        splitter.setSizes([850, 550]); layout.addWidget(splitter, 1)

        output, browse, build = self._output_row("generated_differential_via")
        self.differential_via_output = output
        self.differential_via_build = build
        build.clicked.connect(lambda: self.generate_project("differential_via"))
        layout.addLayout(self._row_with_widgets(output, browse, build))
        self.tabs.addTab(tab, "Differential VIA")
        self._update_via_mode_visibility()

    # ---------- Open-circuit PCB capacitor footprint ----------
    def _build_cap_pad_tab(self) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        splitter = QSplitter(Qt.Horizontal)
        controls = QWidget()
        body = QVBoxLayout(controls)
        cap_warning = QLabel(
            "The packaged physical 0.1 uF capacitor is used by default. "
            "Ideal Lumped RLC is an alternative and the two modes cannot be enabled together."
        )
        cap_warning.setWordWrap(True)
        body.addWidget(cap_warning)
        layers = QGroupBox("CAP route and pad geometry")
        form = QFormLayout(layers)
        self.cap_component_side = QComboBox()
        self.cap_component_side.addItem("Top", "top")
        self.cap_component_side.addItem("Bottom", "bottom")
        self.cap_component_side.currentIndexChanged.connect(
            self._on_cap_component_side_changed
        )
        form.addRow("Component mounting side", self.cap_component_side)
        self.cap_layer_combos = {}
        for side in ("input", "output"):
            combo = QComboBox()
            combo.currentTextChanged.connect(self._refresh_cap_route_choices)
            self.cap_layer_combos[side] = combo
            form.addRow(f"{'Left' if side == 'input' else 'Right'} route copper", combo)
        self.cap_fields = {}
        for label, key in (
            ("Pad center-to-center X", "pad_center_pitch"),
            ("Left pad length X", "left_pad_length"), ("Left pad width Y", "left_pad_width"),
            ("Left pad corner radius", "left_pad_corner_radius"),
            ("Right pad length X", "right_pad_length"), ("Right pad width Y", "right_pad_width"),
            ("Right pad corner radius", "right_pad_corner_radius"),
            ("P/N component center pitch Y", "pair_pitch"),
            ("Left P/N VIA center pitch D", "input_d_via"),
            ("Right P/N VIA center pitch D", "output_d_via"),
            ("Left via X offset from pad center", "left_via_x_offset"),
            ("Right via X offset from pad center", "right_via_x_offset"),
            ("Left breakout length (pad edge to via center)", "left_breakout_length"),
            ("Left breakout width", "left_breakout_width"),
            ("Right breakout length (pad edge to via center)", "right_breakout_length"),
            ("Right breakout width", "right_breakout_width"),
            ("Pad-to-ground clearance", "pad_clearance"),
        ):
            edit = QLineEdit()
            edit.textChanged.connect(self.on_editor_changed)
            self.cap_fields[key] = edit
            form.addRow(label, edit)
        self.cap_gap_label = QLabel("Copper edge gap: pending geometry")
        form.addRow(self.cap_gap_label)
        body.addWidget(layers)

        surface = QGroupBox("CAP surface process")
        surface_form = QFormLayout(surface)
        self.cap_solder_enabled = QCheckBox("Enable tin solder")
        self.cap_solder_enabled.toggled.connect(self.on_editor_changed)
        surface_form.addRow(self.cap_solder_enabled)
        self.cap_surface_fields = {}
        for label, key in (
            ("Solder material", "solder_material"),
            ("Solder height", "solder_height"),
        ):
            edit = QLineEdit()
            edit.textChanged.connect(self.on_editor_changed)
            self.cap_surface_fields[key] = edit
            surface_form.addRow(label, edit)
        self.cap_mask_enabled = QCheckBox("Enable solder mask")
        self.cap_mask_enabled.toggled.connect(self.on_editor_changed)
        surface_form.addRow(self.cap_mask_enabled)
        for label, key in (
            ("Solder-mask DK", "solder_mask_dk"),
            ("Solder-mask DF", "solder_mask_df"),
            ("Mask thickness over copper", "solder_mask_copper_thickness"),
            ("Mask thickness in gaps", "solder_mask_gap_thickness"),
            ("Mask edge transition width", "solder_mask_transition_width"),
            ("CAP pair-window expansion", "solder_mask_opening_expansion"),
        ):
            edit = QLineEdit()
            edit.textChanged.connect(self.on_editor_changed)
            self.cap_surface_fields[key] = edit
            surface_form.addRow(label, edit)
        self.cap_mask_opening_mode = QComboBox()
        self.cap_mask_opening_mode.addItem("Pair open window", "pair_window")
        self.cap_mask_opening_mode.currentIndexChanged.connect(self.on_editor_changed)
        surface_form.addRow("Opening mode", self.cap_mask_opening_mode)
        body.addWidget(surface)

        electrical = QGroupBox("CAP electrical model")
        electrical_form = QFormLayout(electrical)
        self.cap_comparison_enabled = QCheckBox(
            "Generate paired RLC + A3D designs"
        )
        self.cap_comparison_enabled.toggled.connect(
            self._on_cap_comparison_changed
        )
        electrical_form.addRow(self.cap_comparison_enabled)
        self.cap_real_component_enabled = QCheckBox(
            "Use packaged physical 0.1 uF A3D capacitor"
        )
        self.cap_real_component_enabled.toggled.connect(
            lambda checked: self._on_cap_electrical_mode_changed("real", checked)
        )
        electrical_form.addRow(self.cap_real_component_enabled)
        self.cap_real_component_file = QLineEdit()
        self.cap_real_component_file.setPlaceholderText(
            "Bundled component is used when blank"
        )
        self.cap_real_component_file.textChanged.connect(self.on_editor_changed)
        self.cap_real_component_browse = QPushButton("Browse")
        self.cap_real_component_browse.clicked.connect(self.choose_cap_component)
        component_row = QHBoxLayout()
        component_row.addWidget(self.cap_real_component_file, 1)
        component_row.addWidget(self.cap_real_component_browse)
        electrical_form.addRow("Physical capacitor file", component_row)
        self.cap_rlc_enabled = QCheckBox("Enable ideal Lumped RLC connection")
        self.cap_rlc_enabled.toggled.connect(
            lambda checked: self._on_cap_electrical_mode_changed("rlc", checked)
        )
        electrical_form.addRow(self.cap_rlc_enabled)
        self.cap_rlc_capacitance = QLineEdit()
        self.cap_rlc_capacitance.textChanged.connect(self.on_editor_changed)
        electrical_form.addRow("Capacitance per P/N branch", self.cap_rlc_capacitance)
        self.cap_rlc_resistance = QLineEdit()
        self.cap_rlc_resistance.textChanged.connect(self.on_editor_changed)
        electrical_form.addRow("Series resistance", self.cap_rlc_resistance)
        self.cap_rlc_inductance = QLineEdit()
        self.cap_rlc_inductance.textChanged.connect(self.on_editor_changed)
        electrical_form.addRow("Series inductance", self.cap_rlc_inductance)
        self.cap_rlc_fit_start = QLineEdit()
        self.cap_rlc_fit_start.textChanged.connect(self.on_editor_changed)
        electrical_form.addRow("RLC fit start", self.cap_rlc_fit_start)
        self.cap_rlc_fit_stop = QLineEdit()
        self.cap_rlc_fit_stop.textChanged.connect(self.on_editor_changed)
        electrical_form.addRow("RLC fit stop", self.cap_rlc_fit_stop)
        self.cap_rlc_source = QLineEdit()
        self.cap_rlc_source.setReadOnly(True)
        electrical_form.addRow("RLC source S2P", self.cap_rlc_source)
        self.cap_rlc_fit_button = QPushButton("Fit RLC from S2P...")
        self.cap_rlc_fit_button.clicked.connect(self.fit_cap_rlc_from_s2p)
        electrical_form.addRow(self.cap_rlc_fit_button)
        body.addWidget(electrical)

        body.addWidget(QLabel(
            "CAP pad-group voids: one rounded rectangle centered on all four pads per enabled copper layer."
        ))
        self.cap_void_table = QTableWidget(0, 5)
        self.cap_void_table.setHorizontalHeaderLabels(
            ["Copper layer", "Enabled", "Void X", "Void Y", "Corner radius"]
        )
        self.cap_void_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cap_void_table.itemChanged.connect(self.on_editor_changed)
        self.cap_void_table.setMaximumHeight(230)
        body.addWidget(self.cap_void_table)
        self.cap_line_fields = {}
        self.cap_via_fields = {}
        self.cap_reference_combos = {}
        self.cap_mechanical_checks = {}
        self.cap_mechanical_combos = {}
        for side, title in (("input", "Left / L3"), ("output", "Right / L5")):
            group = QGroupBox(f"{title} line and signal VIA")
            side_form = QFormLayout(group)
            line_fields, via_fields = {}, {}
            for key, label in (("trace_length", "Trace length"), ("fanout_length", "Fanout length"),
                               ("w_line", "W"), ("s_line", "S"), ("g_line", "G")):
                edit = QLineEdit(); edit.textChanged.connect(self.on_editor_changed)
                line_fields[key] = edit; side_form.addRow(label, edit)
            refs = {}
            for direction in ("upper", "lower"):
                combo = QComboBox(); combo.currentTextChanged.connect(self.on_editor_changed)
                refs[direction] = combo; side_form.addRow(f"{direction.title()} reference copper", combo)
            for key, label in (("column_radius", "Laser copper-column radius"),
                               ("pad_radius", "Laser landing-pad radius"),
                               ("antipad_radius", "Anti-pad radius"),
                               ("antipad_x", "Anti-pad +/-X"),
                               ("mechanical_column_radius", "Mechanical column radius"),
                               ("mechanical_pad_radius", "Mechanical pad radius")):
                edit = QLineEdit(); edit.textChanged.connect(self.on_editor_changed)
                via_fields[key] = edit; side_form.addRow(label, edit)
            enabled = QCheckBox("Enable one cross-layer mechanical span")
            enabled.toggled.connect(self.on_editor_changed)
            self.cap_mechanical_checks[side] = enabled
            side_form.addRow(enabled)
            stages = {}
            for position in ("start", "end"):
                combo = QComboBox(); combo.currentTextChanged.connect(self.on_editor_changed)
                stages[position] = combo
                side_form.addRow(f"Mechanical {position} copper", combo)
            self.cap_line_fields[side] = line_fields
            self.cap_reference_combos[side] = refs
            self.cap_via_fields[side] = via_fields
            self.cap_mechanical_combos[side] = stages
            body.addWidget(group)
        body.addWidget(QLabel("Per-layer anti-pad radii (blank = that side's default)."))
        self.cap_antipad_table = QTableWidget(0, 5)
        self.cap_antipad_table.setHorizontalHeaderLabels(
            ["Copper layer", "Left radius", "Left +/-X", "Right radius", "Right +/-X"]
        )
        self.cap_antipad_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.cap_antipad_table.itemChanged.connect(self.on_editor_changed)
        self.cap_antipad_table.setMaximumHeight(230)
        body.addWidget(self.cap_antipad_table)
        returns = QGroupBox("Approximate return-VIA fence (not BRD coordinates)")
        return_form = QFormLayout(returns)
        self.cap_return_enabled = QCheckBox("Generate regular return-VIA fence")
        self.cap_return_enabled.toggled.connect(self.on_editor_changed)
        return_form.addRow(self.cap_return_enabled)
        for key, label in (("return_column_radius", "Return-column radius"),
                           ("return_via_pitch", "Return-VIA maximum pitch"),
                           ("return_via_clearance", "Return-VIA clearance"),
                           ("side_margin", "Board side margin")):
            edit = QLineEdit(); edit.textChanged.connect(self.on_editor_changed)
            self.cap_fields[key] = edit; return_form.addRow(label, edit)
        body.addWidget(returns)
        body.addWidget(self._build_analysis_group("cap"))
        body.addStretch(1)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(controls)
        splitter.addWidget(scroll)
        preview_panel = QWidget(); preview_layout = QVBoxLayout(preview_panel)
        preview_layout.addWidget(QLabel("CAP-specific stackup / void preview"))
        self.cap_preview = StackPreview()
        preview_layout.addWidget(self.cap_preview, 1)
        cap_preview_note = QLabel(
            "CAP GROUP VOID is the per-layer rounded-rectangle void for all four pads; ROUTE VOID is the W/S/G trace clearance.\n"
            "LEFT/RIGHT VIA SLOT uses each stack's independent per-layer R/+/-X and remains separate from the group void."
        )
        cap_preview_note.setWordWrap(True)
        preview_layout.addWidget(cap_preview_note)
        splitter.addWidget(preview_panel)
        splitter.setSizes([900, 520])
        layout.addWidget(splitter, 1)
        output, browse, build = self._output_row("generated_cap_pcb")
        self.cap_output, self.cap_build = output, build
        build.clicked.connect(lambda: self.generate_project("cap_pad"))
        layout.addLayout(self._row_with_widgets(output, browse, build))
        self.tabs.addTab(tab, "CAP")

    def _output_row(self, prefix: str):
        edit = QLineEdit(self._timestamp_path(prefix))
        browse = QPushButton("Browse")
        browse.clicked.connect(lambda: self.choose_output(edit))
        build = QPushButton("Generate and open AEDT")
        return edit, browse, build

    @staticmethod
    def _timestamp_path(prefix: str) -> str:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(default_output_directory() / f"{prefix}_{stamp}.aedt")

    @staticmethod
    def _row_with_widgets(*widgets) -> QHBoxLayout:
        row = QHBoxLayout(); row.addWidget(QLabel("Output project"))
        for widget in widgets:
            row.addWidget(widget, 1 if isinstance(widget, QLineEdit) else 0)
        return row

    # ---------- configuration synchronization ----------
    def load_config_into_ui(
        self,
        config: StackupConfig,
        gssg: GSSGConfig | None = None,
        inner_gf: InnerGFConfig | None = None,
        differential_via: DifferentialViaConfig | None = None,
        multistage_via: MultiStageDifferentialViaConfig | None = None,
        cap_pad: CapPadConfig | None = None,
    ) -> None:
        self._loading = True
        self.config = config
        if gssg is not None:
            self.gssg_config = gssg
        if inner_gf is not None:
            self.inner_gf_config = inner_gf
        if differential_via is not None:
            self.differential_via_config = differential_via
        if multistage_via is not None:
            self.multistage_via_config = multistage_via
        if cap_pad is not None:
            self.cap_pad_config = cap_pad
        self.layer_table.setRowCount(0)
        for layer in config.layers:
            row = self.layer_table.rowCount(); self.layer_table.insertRow(row)
            self.layer_table.setItem(row, 0, QTableWidgetItem(layer.name))
            self.layer_table.setCellWidget(row, 1, self._combo(["copper", "pp", "core"], layer.kind))
            self.layer_table.setCellWidget(row, 2, self._combo(["ground", "signal"], layer.role))
            for col, value in ((3, layer.thickness), (4, "" if layer.dk is None else str(layer.dk)),
                               (5, "" if layer.df is None else str(layer.df)), (6, layer.material_name), (7, layer.copper_type)):
                self.layer_table.setItem(row, col, QTableWidgetItem(value))
        self.w_line.setText(config.w_line); self.s_line.setText(config.s_line); self.g_line.setText(config.g_line)
        self.diff_z.setText(str(config.differential_impedance))
        self.common_z.setText(str(config.common_impedance))
        self.aedt_version.setText(config.aedt_version)
        self.board_length.setText(config.board_length); self.board_margin.setText(config.board_margin_x)
        self.return_vias_enabled.setChecked(config.return_vias_enabled)
        self.return_via_diameter.setText(config.return_via_diameter); self.return_via_offset.setText(config.return_via_ground_edge_offset)
        self.return_via_pitch.setText(config.return_via_pitch)
        self.stackup_deembed.setText(config.port_deembed_distance)
        self.stackup_tdr_report.setChecked(config.create_tdr_report)
        self._set_combo_choices(
            self.stackup_upper_reference,
            ["", config.upper_reference_layer_name] if config.upper_reference_layer_name else [""],
            config.upper_reference_layer_name,
        )
        self._set_combo_choices(
            self.stackup_lower_reference,
            ["", config.lower_reference_layer_name] if config.lower_reference_layer_name else [""],
            config.lower_reference_layer_name,
        )
        self._load_analysis_options("stackup", config)
        self._load_gssg_fields(self.gssg_config)
        self._load_inner_gf_fields(self.inner_gf_config)
        self._load_differential_via_fields(
            self.differential_via_config, load_shared=self._active_via_mode == "single"
        )
        self._load_multistage_via_fields(
            self.multistage_via_config,
            load_shared=self._active_via_mode == "multistage",
        )
        self._load_cap_pad_fields(self.cap_pad_config)
        self._loading = False
        self._update_via_mode_visibility()
        self.refresh_views()

    def _load_cap_pad_fields(self, config: CapPadConfig) -> None:
        self.cap_antipad_table.setRowCount(0)
        self.cap_void_table.setRowCount(0)
        self.cap_component_side.blockSignals(True)
        side_index = self.cap_component_side.findData(config.component_side)
        self.cap_component_side.setCurrentIndex(max(0, side_index))
        self.cap_component_side.blockSignals(False)
        for key, edit in self.cap_fields.items():
            edit.setText(str(getattr(config, key)))
        for key, edit in self.cap_surface_fields.items():
            edit.setText(str(getattr(config, key)))
        self.cap_solder_enabled.setChecked(config.solder_enabled)
        self.cap_mask_enabled.setChecked(config.solder_mask_enabled)
        self.cap_comparison_enabled.blockSignals(True)
        self.cap_real_component_enabled.blockSignals(True)
        self.cap_rlc_enabled.blockSignals(True)
        self.cap_comparison_enabled.setChecked(config.comparison_designs_enabled)
        self.cap_real_component_enabled.setChecked(config.real_component_enabled)
        self.cap_rlc_enabled.setChecked(config.lumped_rlc_enabled)
        self.cap_comparison_enabled.blockSignals(False)
        self.cap_real_component_enabled.blockSignals(False)
        self.cap_rlc_enabled.blockSignals(False)
        self.cap_real_component_file.setText(config.real_component_file)
        self.cap_rlc_resistance.setText(config.lumped_resistance)
        self.cap_rlc_inductance.setText(config.lumped_inductance)
        self.cap_rlc_capacitance.setText(config.lumped_capacitance)
        self.cap_rlc_source.setText(config.rlc_source_s2p)
        self.cap_rlc_fit_start.setText(config.rlc_fit_start)
        self.cap_rlc_fit_stop.setText(config.rlc_fit_stop)
        self._update_cap_electrical_controls()
        opening_index = self.cap_mask_opening_mode.findData(config.solder_mask_opening_mode)
        self.cap_mask_opening_mode.setCurrentIndex(max(0, opening_index))
        self.cap_return_enabled.setChecked(config.return_vias_enabled)
        self._load_analysis_options("cap", config)
        copper = [layer.name for layer in self.config.layers if layer.kind == "copper"]
        for index, side in enumerate(("input", "output")):
            chosen = config.route_layers[index] if index < len(config.route_layers) else ""
            self._set_combo_choices(self.cap_layer_combos[side], copper, chosen)
            line = getattr(config, f"{side}_line")
            via = getattr(config, f"{side}_via")
            for key, edit in self.cap_line_fields[side].items():
                edit.setText(str(getattr(line, key)))
            for key, edit in self.cap_via_fields[side].items():
                edit.setText(str(getattr(via, key)))
            self.cap_mechanical_checks[side].setChecked(via.mechanical_enabled)
            for position in ("start", "end"):
                self._set_combo_choices(
                    self.cap_mechanical_combos[side][position], ["", via.__dict__.get(f"mechanical_{position}_layer", "")],
                    getattr(via, f"mechanical_{position}_layer"),
                )
            for direction in ("upper", "lower"):
                value = getattr(line, f"{direction}_reference_layer_name")
                self._set_combo_choices(self.cap_reference_combos[side][direction], ["", value], value)

    def _refresh_cap_route_choices(self, *args) -> None:
        if self._loading:
            return
        copper = [layer.name for layer in self.config.layers if layer.kind == "copper"]
        component_side = self.cap_component_side.currentData() or "top"
        # A top-mounted capacitor may fan out directly on its mounting copper
        # (L1 in the normal stackup). Bottom-mounted parts still route away
        # from their mounting copper.
        route_choices = (
            list(copper)
            if component_side == "top"
            else [name for name in copper if name != copper[-1]]
        )
        for index, side in enumerate(("input", "output")):
            current = self.cap_layer_combos[side].currentText()
            saved = self.cap_pad_config.route_layers[index] if index < len(self.cap_pad_config.route_layers) else ""
            route = self._set_combo_choices(
                self.cap_layer_combos[side], route_choices,
                current if current in route_choices else saved,
            )
            position = copper.index(route) if route in copper else -1
            if position < 0:
                path = []
            elif component_side == "top":
                path = copper[:position + 1]
            else:
                path = list(reversed(copper[position:]))
            line, via = getattr(self.cap_pad_config, f"{side}_line"), getattr(self.cap_pad_config, f"{side}_via")
            for direction, choices in (("upper", copper[:position]), ("lower", copper[position + 1:])):
                combo = self.cap_reference_combos[side][direction]
                value = combo.currentText() or getattr(line, f"{direction}_reference_layer_name")
                self._set_combo_choices(combo, [""] + choices, value)
            for stage in ("start", "end"):
                combo = self.cap_mechanical_combos[side][stage]
                value = combo.currentText() or getattr(via, f"mechanical_{stage}_layer")
                self._set_combo_choices(combo, [""] + path, value)
                combo.setEnabled(self.cap_mechanical_checks[side].isChecked())
        self._refresh_cap_void_table(copper)
        self._refresh_cap_antipad_table(copper)
        try:
            left = _literal_mm(self.cap_fields["left_pad_length"].text() or self.cap_pad_config.pad_length, "left_pad_length")
            right = _literal_mm(self.cap_fields["right_pad_length"].text() or self.cap_pad_config.pad_length, "right_pad_length")
            raw_pitch = self.cap_fields["pad_center_pitch"].text()
            pitch = _literal_mm(raw_pitch, "pad_center_pitch") if raw_pitch else _literal_mm(self.cap_pad_config.pad_length, "pad_length") + _literal_mm(self.cap_pad_config.pad_gap, "pad_gap")
            label = "铜边间隙" if self._language == "zh_CN" else "Copper edge gap"
            self.cap_gap_label.setText(f"{label}: {(pitch - (left + right) / 2) * 1000:.1f} um")
        except ValueError:
            self.cap_gap_label.setText(self._ui_text("Copper edge gap: enter measured pad dimensions"))
        try:
            self.cap_pad_config = self.cap_pad_config_from_ui()
            self._refresh_cap_preview(self.config_from_ui().layers)
        except (TypeError, ValueError):
            pass

    def _on_cap_component_side_changed(self, *args) -> None:
        if self._loading:
            return
        try:
            current = self.cap_pad_config_from_ui()
        except (TypeError, ValueError):
            current = self.cap_pad_config
        current.component_side = self.cap_component_side.currentData() or "top"
        copper = [layer.name for layer in self.config.layers if layer.kind == "copper"]
        if len(copper) >= 2:
            targets = copper[:2] if self.cap_component_side.currentData() == "top" else copper[-2:]
            previous = current.layer_pad_voids
            fallback = next(iter(previous.values()), {
                "enabled": True, "x": "730um", "y": "776um", "radius": "4mil"
            })
            current.layer_pad_voids = {
                layer: {
                    "enabled": True,
                    "x": str(previous.get(layer, fallback).get("x") or "730um"),
                    "y": str(previous.get(layer, fallback).get("y") or "776um"),
                    "radius": str(previous.get(layer, fallback).get("radius") or "4mil"),
                }
                for layer in targets
            }
        self.cap_pad_config = current
        self.cap_void_table.setRowCount(0)
        self.refresh_views()

    def _update_cap_electrical_controls(self) -> None:
        comparison = self.cap_comparison_enabled.isChecked()
        physical = comparison or self.cap_real_component_enabled.isChecked()
        ideal = comparison or self.cap_rlc_enabled.isChecked()
        self.cap_real_component_enabled.setEnabled(not comparison)
        self.cap_rlc_enabled.setEnabled(not comparison)
        self.cap_real_component_file.setEnabled(physical)
        self.cap_real_component_browse.setEnabled(physical)
        self.cap_rlc_capacitance.setEnabled(ideal)
        self.cap_rlc_resistance.setEnabled(ideal)
        self.cap_rlc_inductance.setEnabled(ideal)
        self.cap_rlc_fit_start.setEnabled(ideal)
        self.cap_rlc_fit_stop.setEnabled(ideal)
        self.cap_rlc_fit_button.setEnabled(ideal)

    def _on_cap_comparison_changed(self, checked: bool) -> None:
        self._update_cap_electrical_controls()
        self.on_editor_changed()

    def _on_cap_electrical_mode_changed(self, mode: str, checked: bool) -> None:
        if checked:
            other = (
                self.cap_rlc_enabled
                if mode == "real" else self.cap_real_component_enabled
            )
            other.blockSignals(True)
            other.setChecked(False)
            other.blockSignals(False)
        self._update_cap_electrical_controls()
        self.on_editor_changed()

    def fit_cap_rlc_from_s2p(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self._ui_text("Choose S2P capacitor"),
            self.cap_rlc_source.text(), "Touchstone 2-Port (*.s2p)",
        )
        if not path:
            return
        try:
            result = fit_series_rlc(
                path,
                self.cap_rlc_fit_start.text().strip(),
                self.cap_rlc_fit_stop.text().strip(),
            )
        except Exception as error:
            QMessageBox.critical(
                self, self._ui_text("RLC fit failed"), str(error)
            )
            return
        self.cap_rlc_source.setText(path)
        self.cap_rlc_resistance.setText(result.resistance_text)
        self.cap_rlc_inductance.setText(result.inductance_text)
        self.cap_rlc_capacitance.setText(result.capacitance_text)
        if not self.cap_comparison_enabled.isChecked():
            self.cap_rlc_enabled.setChecked(True)
        QMessageBox.information(
            self,
            self._ui_text("RLC fit complete"),
            (
                f"R={result.resistance_text}\n"
                f"L={result.inductance_text}\n"
                f"C={result.capacitance_text}\n"
                f"Points={result.point_count}\n"
                f"RMS impedance error={result.rms_error_ohm:.6g} ohm"
            ),
        )

    def _refresh_cap_antipad_table(self, copper: list[str]) -> None:
        """Refresh independent per-layer R/+/-X slot settings for both stacks."""
        table = self.cap_antipad_table
        previous = {}
        for row in range(table.rowCount()):
            layer_item = table.item(row, 0)
            if layer_item:
                for column in (1, 2, 3, 4):
                    item = table.item(row, column)
                    if item and item.text().strip() and item.text().strip() != "--":
                        previous[(layer_item.text(), column)] = item.text().strip()
        table.blockSignals(True)
        table.setRowCount(len(copper))
        for row, layer in enumerate(copper):
            layer_item = QTableWidgetItem(layer)
            layer_item.setFlags(layer_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, 0, layer_item)
            for column, side, key in (
                (1, "input", "radius"), (2, "input", "x"),
                (3, "output", "radius"), (4, "output", "x"),
            ):
                selected = self.cap_layer_combos[side].currentText()
                component_side = self.cap_component_side.currentData() or "top"
                active_layers: set[str] = set()
                if selected in copper:
                    route_index = copper.index(selected)
                    active_layers.update(
                        copper[:route_index + 1]
                        if component_side == "top"
                        else copper[route_index:]
                    )
                    line = getattr(self.cap_pad_config, f"{side}_line")
                    upper = (
                        self.cap_reference_combos[side]["upper"].currentText()
                        or line.upper_reference_layer_name
                    )
                    lower = (
                        self.cap_reference_combos[side]["lower"].currentText()
                        or line.lower_reference_layer_name
                    )
                    if upper in copper and copper.index(upper) < route_index:
                        active_layers.update(copper[copper.index(upper) + 1:route_index])
                    if lower in copper and route_index < copper.index(lower):
                        active_layers.update(copper[route_index + 1:copper.index(lower)])
                active = layer in active_layers
                stored = getattr(self.cap_pad_config, f"{side}_via").layer_antipads.get(layer, {}).get(key, "")
                item = QTableWidgetItem(str(previous.get((layer, column), stored)) if active else "--")
                if not active:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(row, column, item)
        table.blockSignals(False)

    def _refresh_cap_void_table(self, copper: list[str]) -> None:
        """Refresh the independently enabled rounded group void on each copper layer."""
        table = self.cap_void_table
        previous: dict[tuple[str, int], object] = {}
        for row in range(table.rowCount()):
            layer_item = table.item(row, 0)
            if not layer_item:
                continue
            layer = layer_item.text()
            enabled = table.item(row, 1)
            if enabled:
                previous[(layer, 1)] = enabled.checkState() == Qt.Checked
            for column in (2, 3, 4):
                item = table.item(row, column)
                if item and item.text().strip():
                    previous[(layer, column)] = item.text().strip()
        table.blockSignals(True)
        table.setRowCount(len(copper))
        for row, layer in enumerate(copper):
            layer_item = QTableWidgetItem(layer)
            layer_item.setFlags(layer_item.flags() & ~Qt.ItemIsEditable)
            table.setItem(row, 0, layer_item)
            stored = self.cap_pad_config.layer_pad_voids.get(layer, {})
            checked = bool(previous.get((layer, 1), stored.get("enabled", False)))
            component_side = self.cap_component_side.currentData() or "top"
            component_row = 0 if component_side == "top" else len(copper) - 1
            enabled = QTableWidgetItem()
            enabled.setFlags((enabled.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
            enabled.setCheckState(Qt.Checked if checked or row == component_row else Qt.Unchecked)
            if row == component_row:
                enabled.setFlags(enabled.flags() & ~Qt.ItemIsEnabled)
            table.setItem(row, 1, enabled)
            for column, key in ((2, "x"), (3, "y"), (4, "radius")):
                value = previous.get((layer, column), stored.get(key, ""))
                item = QTableWidgetItem(str(value))
                if not checked and row != component_row:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                table.setItem(row, column, item)
        table.blockSignals(False)

    def _refresh_cap_preview(self, layers: list[Layer]) -> None:
        """Show CAP-specific routing and copper-removal roles on the shared stackup."""
        if not hasattr(self, "cap_preview"):
            return
        copper = [layer.name for layer in layers if layer.kind == "copper"]
        annotations: dict[str, list[str]] = {name: [] for name in copper}
        if not copper:
            self.cap_preview.update_layers(layers)
            return
        component_side = self.cap_component_side.currentData() or "top"
        component_layer = copper[0] if component_side == "top" else copper[-1]
        annotations[component_layer].append(f"{component_side.upper()} CAP PADS")
        if self.cap_solder_enabled.isChecked():
            annotations[component_layer].append(
                f"TIN {self.cap_surface_fields['solder_height'].text().strip()}"
            )
        if self.cap_mask_enabled.isChecked():
            annotations[component_layer].append(
                "MASK "
                f"CU={self.cap_surface_fields['solder_mask_copper_thickness'].text().strip()} "
                f"GAP={self.cap_surface_fields['solder_mask_gap_thickness'].text().strip()} "
                f"EDGE={self.cap_surface_fields['solder_mask_transition_width'].text().strip()} "
                f"PAIR WINDOW +{self.cap_surface_fields['solder_mask_opening_expansion'].text().strip()}"
            )
        if self.cap_rlc_enabled.isChecked() or self.cap_comparison_enabled.isChecked():
            annotations[component_layer].append(
                "2x SERIAL LUMPED RLC "
                f"R={self.cap_rlc_resistance.text().strip()} "
                f"L={self.cap_rlc_inductance.text().strip()} "
                f"C={self.cap_rlc_capacitance.text().strip()}"
            )
        if self.cap_real_component_enabled.isChecked() or self.cap_comparison_enabled.isChecked():
            annotations[component_layer].append("2x PHYSICAL A3D CAP 0.1uF")
        for row in range(self.cap_void_table.rowCount()):
            layer_item = self.cap_void_table.item(row, 0)
            enabled_item = self.cap_void_table.item(row, 1)
            if not layer_item or not enabled_item or enabled_item.checkState() != Qt.Checked:
                continue
            layer_name = layer_item.text()
            if layer_name in annotations:
                x = self.cap_void_table.item(row, 2).text().strip()
                y = self.cap_void_table.item(row, 3).text().strip()
                radius = self.cap_void_table.item(row, 4).text().strip()
                annotations[layer_name].append(f"CAP GROUP VOID X={x} Y={y} R={radius}")
        for side, label in (("input", "LEFT"), ("output", "RIGHT")):
            route = self.cap_layer_combos[side].currentText()
            if route not in copper:
                continue
            route_index = copper.index(route)
            annotations[route].append(f"{label} ROUTE + ROUTE VOID")
            via_path = (copper[:route_index + 1] if component_side == "top"
                        else copper[route_index:])
            for layer_name in via_path:
                row = next((row for row in range(self.cap_antipad_table.rowCount())
                            if self.cap_antipad_table.item(row, 0)
                            and self.cap_antipad_table.item(row, 0).text() == layer_name), None)
                radius_column, x_column = (1, 2) if side == "input" else (3, 4)
                item = self.cap_antipad_table.item(row, radius_column) if row is not None else None
                x_item = self.cap_antipad_table.item(row, x_column) if row is not None else None
                radius = (item.text().strip() if item and item.text().strip() not in ("", "--")
                          else self.cap_via_fields[side]["antipad_radius"].text().strip())
                x_value = (x_item.text().strip() if x_item and x_item.text().strip() not in ("", "--")
                           else self.cap_via_fields[side]["antipad_x"].text().strip())
                annotations[layer_name].append(f"{label} VIA SLOT R={radius} X={x_value}")
            for direction, suffix in (("upper", "UPPER REF"), ("lower", "LOWER REF")):
                reference = self.cap_reference_combos[side][direction].currentText()
                if reference in annotations:
                    annotations[reference].append(f"{label} {suffix}")
            if self.cap_mechanical_checks[side].isChecked():
                start = self.cap_mechanical_combos[side]["start"].currentText()
                end = self.cap_mechanical_combos[side]["end"].currentText()
                if start in copper and end in copper:
                    first, last = sorted((copper.index(start), copper.index(end)))
                    for layer_name in copper[first:last + 1]:
                        annotations[layer_name].append(f"{label} MECH SPAN")
        preview_layers = [Layer.from_dict(vars(layer)) for layer in layers]
        for layer in preview_layers:
            if layer.kind == "copper":
                layer.role = "ground"
        self.cap_preview.update_layers(
            preview_layers, {name: tags for name, tags in annotations.items() if tags}
        )

    def _load_gssg_fields(self, config: GSSGConfig) -> None:
        copper = [layer.name for layer in self.config.layers if layer.kind == "copper"]
        selected = config.signal_layer_name if config.signal_layer_name in copper else ""
        if not selected:
            selected = next((layer.name for layer in self.config.layers
                             if layer.kind == "copper" and layer.role == "signal"), "")
        if not selected and copper:
            selected = copper[0]
        self.gssg_layer.setCurrentText(selected)
        if selected:
            config.signal_layer_name = selected
        for key, edit in self.gssg_fields.items():
            edit.setText(str(getattr(config, key)))
        self.mark1_x.setText(config.mark1_x); self.mark1_y.setText(config.mark1_y)
        self.mark2_x.setText(config.mark2_x); self.mark2_y.setText(config.mark2_y)
        self._load_analysis_options("gssg", config)

    def _load_inner_gf_fields(self, config: InnerGFConfig) -> None:
        self.inner_gf_layer.setText(config.gf_layer_name)
        # Reset the selectors before refresh_views repopulates their legal
        # candidates.  This prevents values from the previously loaded file
        # leaking into an older JSON document that has no reference fields.
        self._set_combo_choices(self.inner_upper_reference, [""], "")
        self._set_combo_choices(self.inner_lower_reference, [""], "")
        for key, edit in self.inner_gf_fields.items():
            edit.setText(str(getattr(config, key)))
        for key, edit in self.inner_pad_void_fields.items():
            edit.setText(str(getattr(config, key)))
        self._set_combo_choices(self.inner_pad_void_end_layer, [""], "")
        self.gnd_return_via_count.setText(str(config.gnd_return_via_count))
        self.inner_mechanical_via_enabled.setChecked(config.mechanical_via_enabled)
        self.inner_mechanical_column_radius.setText(config.mechanical_column_radius)
        self.inner_mechanical_pad_radius.setText(config.mechanical_pad_radius)

    def _load_differential_via_fields(
        self, config: DifferentialViaConfig, load_shared: bool = True
    ) -> None:
        copper = [layer.name for layer in self.config.layers if layer.kind == "copper"]
        start = config.route_layers[0] if len(config.route_layers) == 2 else ""
        end = config.route_layers[1] if len(config.route_layers) == 2 else ""
        for combo, selected in ((self.via_start_layer, start), (self.via_end_layer, end)):
            combo.blockSignals(True); combo.clear(); combo.addItems(copper)
            combo.setCurrentText(selected if selected in copper else "")
            combo.blockSignals(False)
        if self.via_start_layer.currentText() == "" and copper:
            self.via_start_layer.setCurrentText(copper[0])
        if self.via_end_layer.currentText() == "" and len(copper) > 1:
            self.via_end_layer.setCurrentText(copper[min(3, len(copper) - 1)])
        self.mechanical_via_enabled.setChecked(config.mechanical_via_enabled)
        self._refresh_mechanical_start_layers(
            config.mechanical_start_layer, config.mechanical_end_layer
        )
        self.mechanical_column_radius.setText(config.mechanical_column_radius)
        self.mechanical_pad_radius.setText(config.mechanical_pad_radius)
        if load_shared:
            for key, edit in self.via_start_line_fields.items():
                edit.setText(str(getattr(config.start_line, key)))
            for key, edit in self.via_end_line_fields.items():
                edit.setText(str(getattr(config.end_line, key)))
            self._load_via_reference_values(config.start_line, config.end_line)
        for key, edit in self.differential_via_fields.items():
            edit.setText(str(getattr(config, key)))
        if load_shared:
            self._load_analysis_options("via", config)

    def _load_multistage_via_fields(
        self, config: MultiStageDifferentialViaConfig, load_shared: bool = True
    ) -> None:
        self._refresh_multistage_layer_choices(config.route_layers)
        for key, edit in self.multistage_via_fields.items():
            edit.setText(str(getattr(config, key)))
        if load_shared:
            for key, edit in self.via_start_line_fields.items():
                edit.setText(str(getattr(config.start_line, key)))
            for key, edit in self.via_end_line_fields.items():
                edit.setText(str(getattr(config.end_line, key)))
            self._load_via_reference_values(config.start_line, config.end_line)
            self._load_analysis_options("via", config)

    def _load_via_reference_values(
        self,
        start_line: DifferentialLineEndConfig,
        end_line: DifferentialLineEndConfig,
    ) -> None:
        for prefix, line in (("start", start_line), ("end", end_line)):
            for side in ("upper", "lower"):
                value = getattr(line, f"{side}_reference_layer_name")
                self._set_combo_choices(
                    self.via_reference_combos[prefix][side],
                    ["", value] if value else [""],
                    value,
                )

    @staticmethod
    def _set_combo_choices(combo: QComboBox, choices: list[str], selected: str) -> str:
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(choices)
        if selected in choices:
            combo.setCurrentText(selected)
        elif choices:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)
        return combo.currentText()

    def _refresh_multistage_layer_choices(
        self, preferred: list[str] | None = None
    ) -> None:
        """Filter the four two-stage selectors in physical shallow-to-deep order."""
        copper = [layer.name for layer in self.config.layers if layer.kind == "copper"]
        current = [combo.currentText() for combo in self.multistage_layer_combos]
        desired = list(preferred or current)
        desired += [""] * (4 - len(desired))

        input_choices = copper[:-2]
        input_name = self._set_combo_choices(
            self.multistage_layer_combos[0], input_choices, desired[0]
        )
        input_index = copper.index(input_name) if input_name in copper else -1

        transfer_choices = copper[input_index + 1:-1] if input_index >= 0 else []
        transfer_name = self._set_combo_choices(
            self.multistage_layer_combos[1], transfer_choices, desired[1]
        )
        transfer_index = copper.index(transfer_name) if transfer_name in copper else -1

        mechanical_choices = copper[transfer_index + 1:] if transfer_index >= 0 else []
        mechanical_name = self._set_combo_choices(
            self.multistage_layer_combos[2], mechanical_choices, desired[2]
        )
        mechanical_index = copper.index(mechanical_name) if mechanical_name in copper else -1

        output_choices = copper[mechanical_index:] if mechanical_index >= 0 else []
        output_name = self._set_combo_choices(
            self.multistage_layer_combos[3], output_choices, desired[3]
        )
        if mechanical_name and output_name:
            if mechanical_name == output_name:
                status = (
                    f"机械过孔终止于 {mechanical_name}；直接从该层出线。"
                    if self._language == "zh_CN" else
                    f"Mechanical VIA ends on {mechanical_name}; direct route-out on that layer."
                )
            else:
                status = (
                    f"最终同心激光孔叠层：{mechanical_name} -> {output_name}。"
                    if self._language == "zh_CN" else
                    f"Final same-center laser stack: {mechanical_name} -> {output_name}."
                )
        else:
            status = self._ui_text(
                "The current stackup does not contain enough ordered copper layers."
            )
        self.multistage_route_status.setText(status)

    def _update_via_mode_visibility(self) -> None:
        multistage = self._active_via_mode == "multistage"
        for widget in (
            self.single_via_layer_group,
            self.single_via_geometry_group,
            self.single_via_mechanical_group,
        ):
            widget.setVisible(not multistage)
        self.multistage_via_layer_group.setVisible(multistage)
        self.multistage_via_geometry_group.setVisible(multistage)

    def _refresh_mechanical_start_layers(
        self, preferred_start: str = "", preferred_end: str = ""
    ) -> None:
        copper = [layer.name for layer in self.config.layers if layer.kind == "copper"]
        start, end = self.via_start_layer.currentText(), self.via_end_layer.currentText()
        path: list[str] = []
        if start in copper and end in copper and start != end:
            start_index, end_index = copper.index(start), copper.index(end)
            step = 1 if end_index > start_index else -1
            path = copper[start_index:end_index + step:step]
        start_choices = path[1:-1]
        current_start = (
            preferred_start
            or self.mechanical_start_layer.currentText()
            or self.differential_via_config.mechanical_start_layer
        )
        self.mechanical_start_layer.blockSignals(True)
        self.mechanical_start_layer.clear()
        self.mechanical_start_layer.addItems(start_choices)
        if current_start in start_choices:
            self.mechanical_start_layer.setCurrentText(current_start)
        self.mechanical_start_layer.blockSignals(False)
        selected_start = self.mechanical_start_layer.currentText()
        selected_index = path.index(selected_start) if selected_start in path else -1
        end_choices = path[selected_index + 1:] if selected_index >= 0 else []
        legacy_end = path[-2] if len(path) >= 4 else (path[-1] if end_choices else "")
        current_end = (
            preferred_end
            or self.mechanical_end_layer.currentText()
            or self.differential_via_config.mechanical_end_layer
            or legacy_end
        )
        self.mechanical_end_layer.blockSignals(True)
        self.mechanical_end_layer.clear()
        self.mechanical_end_layer.addItems(end_choices)
        if current_end in end_choices:
            self.mechanical_end_layer.setCurrentText(current_end)
        elif legacy_end in end_choices:
            self.mechanical_end_layer.setCurrentText(legacy_end)
        self.mechanical_end_layer.blockSignals(False)
        enabled = bool(start_choices) and self.mechanical_via_enabled.isChecked()
        self.mechanical_start_layer.setEnabled(enabled)
        self.mechanical_end_layer.setEnabled(enabled and bool(end_choices))

    def _refresh_inner_mechanical_start_layers(
        self, preferred_start: str = "", preferred_end: str = ""
    ) -> None:
        copper = [layer.name for layer in self.config.layers if layer.kind == "copper"]
        breakout = self.gssg_layer.currentText()
        path: list[str] = []
        if copper and copper[0] == "L1" and breakout in copper:
            path = copper[:copper.index(breakout) + 1]
        start_choices = path[1:-1]
        current_start = (
            preferred_start
            or self.inner_mechanical_start_layer.currentText()
            or self.inner_gf_config.mechanical_start_layer
        )
        self.inner_mechanical_start_layer.blockSignals(True)
        self.inner_mechanical_start_layer.clear()
        self.inner_mechanical_start_layer.addItems(start_choices)
        if current_start in start_choices:
            self.inner_mechanical_start_layer.setCurrentText(current_start)
        self.inner_mechanical_start_layer.blockSignals(False)
        selected_start = self.inner_mechanical_start_layer.currentText()
        selected_index = path.index(selected_start) if selected_start in path else -1
        end_choices = path[selected_index + 1:] if selected_index >= 0 else []
        legacy_end = path[-2] if len(path) >= 4 else (path[-1] if end_choices else "")
        current_end = (
            preferred_end
            or self.inner_mechanical_end_layer.currentText()
            or self.inner_gf_config.mechanical_end_layer
            or legacy_end
        )
        self.inner_mechanical_end_layer.blockSignals(True)
        self.inner_mechanical_end_layer.clear()
        self.inner_mechanical_end_layer.addItems(end_choices)
        if current_end in end_choices:
            self.inner_mechanical_end_layer.setCurrentText(current_end)
        elif legacy_end in end_choices:
            self.inner_mechanical_end_layer.setCurrentText(legacy_end)
        self.inner_mechanical_end_layer.blockSignals(False)
        enabled = bool(start_choices) and self.inner_mechanical_via_enabled.isChecked()
        self.inner_mechanical_start_layer.setEnabled(enabled)
        self.inner_mechanical_end_layer.setEnabled(enabled and bool(end_choices))

    def _refresh_inner_reference_layers(
        self,
        preferred_upper: str = "",
        preferred_lower: str = "",
    ) -> None:
        """Offer only explicit ground references that bracket the breakout layer."""
        breakout = self.gssg_layer.currentText()
        layers = self.config.layers
        upper_choices = [""]
        lower_choices = [""]
        if breakout and breakout != "L1":
            signal_index = next(
                (index for index, layer in enumerate(layers) if layer.name == breakout),
                -1,
            )
            if signal_index >= 0:
                # Inner-GF generation makes the selected breakout the sole
                # signal copper, so every other copper layer is an effective
                # Ground Copper candidate.
                upper_choices += [
                    layer.name for layer in layers[:signal_index]
                    if layer.kind == "copper"
                ]
                lower_choices += [
                    layer.name for layer in layers[signal_index + 1:]
                    if layer.kind == "copper"
                ]

        current_upper = (
            preferred_upper
            or self.inner_upper_reference.currentText()
            or self.inner_gf_config.upper_reference_layer_name
        )
        current_lower = (
            preferred_lower
            or self.inner_lower_reference.currentText()
            or self.inner_gf_config.lower_reference_layer_name
        )
        selected_upper = self._set_combo_choices(
            self.inner_upper_reference, upper_choices, current_upper
        )
        selected_lower = self._set_combo_choices(
            self.inner_lower_reference, lower_choices, current_lower
        )
        self.inner_gf_config.upper_reference_layer_name = selected_upper
        self.inner_gf_config.lower_reference_layer_name = selected_lower

    def _refresh_inner_pad_void_layers(self, preferred: str = "") -> None:
        """Offer every copper layer as an inclusive L1-down undercut endpoint."""
        copper = [layer.name for layer in self.config.layers if layer.kind == "copper"]
        current = (
            preferred
            or self.inner_pad_void_end_layer.currentText()
            or self.inner_gf_config.pad_void_end_layer_name
        )
        selected = self._set_combo_choices(
            self.inner_pad_void_end_layer, [""] + copper, current
        )
        self.inner_gf_config.pad_void_end_layer_name = selected

    def _refresh_stackup_reference_layers(self) -> None:
        signal = self.signal_layer.currentText()
        layers = self.config.layers
        signal_index = next(
            (index for index, layer in enumerate(layers) if layer.name == signal), -1
        )
        upper_choices = [""]
        lower_choices = [""]
        if signal_index >= 0:
            upper_choices += [
                layer.name for layer in layers[:signal_index]
                if layer.kind == "copper" and layer.role == "ground"
            ]
            lower_choices += [
                layer.name for layer in layers[signal_index + 1:]
                if layer.kind == "copper" and layer.role == "ground"
            ]
        upper = (
            self.stackup_upper_reference.currentText()
            or self.config.upper_reference_layer_name
        )
        lower = (
            self.stackup_lower_reference.currentText()
            or self.config.lower_reference_layer_name
        )
        self.config.upper_reference_layer_name = self._set_combo_choices(
            self.stackup_upper_reference, upper_choices, upper
        )
        self.config.lower_reference_layer_name = self._set_combo_choices(
            self.stackup_lower_reference, lower_choices, lower
        )

    def _refresh_via_reference_layers(self) -> None:
        copper = [layer.name for layer in self.config.layers if layer.kind == "copper"]
        if self._active_via_mode == "multistage":
            routes = [
                self.multistage_layer_combos[0].currentText(),
                self.multistage_layer_combos[3].currentText(),
            ]
            lines = (
                self.multistage_via_config.start_line,
                self.multistage_via_config.end_line,
            )
        else:
            routes = [self.via_start_layer.currentText(), self.via_end_layer.currentText()]
            lines = (
                self.differential_via_config.start_line,
                self.differential_via_config.end_line,
            )

        for prefix, route, line in zip(("start", "end"), routes, lines):
            route_index = copper.index(route) if route in copper else -1
            upper_choices = [""] + (copper[:route_index] if route_index >= 0 else [])
            lower_choices = [""] + (copper[route_index + 1:] if route_index >= 0 else [])
            upper_combo = self.via_reference_combos[prefix]["upper"]
            lower_combo = self.via_reference_combos[prefix]["lower"]
            upper = upper_combo.currentText() or line.upper_reference_layer_name
            lower = lower_combo.currentText() or line.lower_reference_layer_name
            line.upper_reference_layer_name = self._set_combo_choices(
                upper_combo, upper_choices, upper
            )
            line.lower_reference_layer_name = self._set_combo_choices(
                lower_combo, lower_choices, lower
            )

    def config_from_ui(self) -> StackupConfig:
        layers = []
        for row in range(self.layer_table.rowCount()):
            text = lambda col: self.layer_table.item(row, col).text().strip() if self.layer_table.item(row, col) else ""
            kind = self.layer_table.cellWidget(row, 1).currentText(); role = self.layer_table.cellWidget(row, 2).currentText()
            dk, df = text(4), text(5)
            layers.append(Layer(text(0), kind, text(3), float(dk) if dk else None, float(df) if df else None,
                                text(6), text(7), role))
        analysis = self._analysis_options_from_ui("stackup")
        return StackupConfig(layers=layers, board_length=self.board_length.text().strip(), board_margin_x=self.board_margin.text().strip(),
                             w_line=self.w_line.text().strip(), s_line=self.s_line.text().strip(), g_line=self.g_line.text().strip(),
                             upper_reference_layer_name=self.stackup_upper_reference.currentText(),
                             lower_reference_layer_name=self.stackup_lower_reference.currentText(),
                             differential_impedance=float(self.diff_z.text().strip() or "0"),
                             common_impedance=float(self.common_z.text().strip() or "0"),
                             return_vias_enabled=self.return_vias_enabled.isChecked(),
                             return_via_diameter=self.return_via_diameter.text().strip(), return_via_ground_edge_offset=self.return_via_offset.text().strip(),
                             return_via_pitch=self.return_via_pitch.text().strip(), aedt_version=self.aedt_version.text().strip(),
                             design_name=self.config.design_name,
                             port_deembed_distance=self.stackup_deembed.text().strip(),
                             create_tdr_report=self.stackup_tdr_report.isChecked(), **analysis)

    def gssg_config_from_ui(self) -> GSSGConfig:
        values = {key: edit.text().strip() for key, edit in self.gssg_fields.items()}
        values["signal_layer_name"] = self.gssg_layer.currentText()
        values["mark1_x"] = self.mark1_x.text().strip(); values["mark1_y"] = self.mark1_y.text().strip()
        values["mark2_x"] = self.mark2_x.text().strip(); values["mark2_y"] = self.mark2_y.text().strip()
        values.update(self._analysis_options_from_ui("gssg"))
        return GSSGConfig(**values)

    def cap_pad_config_from_ui(self) -> CapPadConfig:
        values = self.cap_pad_config.to_dict()
        values["component_side"] = self.cap_component_side.currentData() or "top"
        values.update({key: edit.text().strip() for key, edit in self.cap_fields.items()})
        values.update({key: edit.text().strip() for key, edit in self.cap_surface_fields.items()})
        values["solder_enabled"] = self.cap_solder_enabled.isChecked()
        values["solder_mask_enabled"] = self.cap_mask_enabled.isChecked()
        values["comparison_designs_enabled"] = self.cap_comparison_enabled.isChecked()
        values["real_component_enabled"] = self.cap_real_component_enabled.isChecked()
        values["real_component_file"] = self.cap_real_component_file.text().strip()
        values["lumped_rlc_enabled"] = self.cap_rlc_enabled.isChecked()
        values["lumped_resistance"] = self.cap_rlc_resistance.text().strip()
        values["lumped_inductance"] = self.cap_rlc_inductance.text().strip()
        values["lumped_capacitance"] = self.cap_rlc_capacitance.text().strip()
        values["rlc_source_s2p"] = self.cap_rlc_source.text().strip()
        values["rlc_fit_start"] = self.cap_rlc_fit_start.text().strip()
        values["rlc_fit_stop"] = self.cap_rlc_fit_stop.text().strip()
        values["solder_mask_opening_mode"] = (
            self.cap_mask_opening_mode.currentData() or "pair_window"
        )
        values["route_layers"] = [self.cap_layer_combos[side].currentText() for side in ("input", "output")]
        values["return_vias_enabled"] = self.cap_return_enabled.isChecked()
        values.update(self._analysis_options_from_ui("cap"))
        for side in ("input", "output"):
            line = {key: edit.text().strip() for key, edit in self.cap_line_fields[side].items()}
            for direction in ("upper", "lower"):
                line[f"{direction}_reference_layer_name"] = self.cap_reference_combos[side][direction].currentText()
            values[f"{side}_line"] = line
            via = {key: edit.text().strip() for key, edit in self.cap_via_fields[side].items()}
            via["follow_solder_mask_antipad"] = False
            via["mechanical_enabled"] = self.cap_mechanical_checks[side].isChecked()
            for position in ("start", "end"):
                via[f"mechanical_{position}_layer"] = self.cap_mechanical_combos[side][position].currentText()
            radius_col, x_col = (1, 2) if side == "input" else (3, 4)
            via["layer_antipads"] = {
                self.cap_antipad_table.item(row, 0).text(): {
                    "radius": self.cap_antipad_table.item(row, radius_col).text().strip()
                              or via["antipad_radius"],
                    "x": self.cap_antipad_table.item(row, x_col).text().strip()
                         or via["antipad_x"],
                }
                for row in range(self.cap_antipad_table.rowCount())
                if self.cap_antipad_table.item(row, radius_col)
                and self.cap_antipad_table.item(row, x_col)
                and (self.cap_antipad_table.item(row, radius_col).text().strip() not in ("", "--")
                     or self.cap_antipad_table.item(row, x_col).text().strip() not in ("", "--"))
            }
            values[f"{side}_via"] = via
        values["layer_pad_voids"] = {
            self.cap_void_table.item(row, 0).text(): {
                "enabled": self.cap_void_table.item(row, 1).checkState() == Qt.Checked,
                "x": self.cap_void_table.item(row, 2).text().strip(),
                "y": self.cap_void_table.item(row, 3).text().strip(),
                "radius": self.cap_void_table.item(row, 4).text().strip(),
            }
            for row in range(self.cap_void_table.rowCount())
            if self.cap_void_table.item(row, 0)
        }
        return CapPadConfig.from_dict(values)

    def inner_gf_config_from_ui(self) -> InnerGFConfig:
        values = {key: edit.text().strip() for key, edit in self.inner_gf_fields.items()}
        values.update({
            key: edit.text().strip()
            for key, edit in self.inner_pad_void_fields.items()
        })
        values.update(self._analysis_options_from_ui("gssg"))
        values["gf_layer_name"] = "L1"
        selected = self.gssg_layer.currentText()
        values["inner_signal_layer_name"] = (
            selected if selected and selected != "L1"
            else self.inner_gf_config.inner_signal_layer_name
        )
        values["upper_reference_layer_name"] = self.inner_upper_reference.currentText()
        values["lower_reference_layer_name"] = self.inner_lower_reference.currentText()
        values["pad_void_end_layer_name"] = self.inner_pad_void_end_layer.currentText()
        values["gnd_return_via_count"] = int(self.gnd_return_via_count.text().strip())
        values["mechanical_via_enabled"] = self.inner_mechanical_via_enabled.isChecked()
        values["mechanical_start_layer"] = self.inner_mechanical_start_layer.currentText()
        values["mechanical_end_layer"] = self.inner_mechanical_end_layer.currentText()
        values["mechanical_column_radius"] = (
            self.inner_mechanical_column_radius.text().strip()
        )
        values["mechanical_pad_radius"] = self.inner_mechanical_pad_radius.text().strip()
        values["layer_antipads"] = {
            layer: dict(settings)
            for layer, settings in self.inner_gf_config.layer_antipads.items()
        }
        return InnerGFConfig(**values)

    def differential_via_config_from_ui(self) -> DifferentialViaConfig:
        start_values = {
            key: edit.text().strip() for key, edit in self.via_start_line_fields.items()
        }
        end_values = {
            key: edit.text().strip() for key, edit in self.via_end_line_fields.items()
        }
        for prefix, values in (("start", start_values), ("end", end_values)):
            values["upper_reference_layer_name"] = self.via_reference_combos[prefix]["upper"].currentText()
            values["lower_reference_layer_name"] = self.via_reference_combos[prefix]["lower"].currentText()
        values = {
            key: edit.text().strip() for key, edit in self.differential_via_fields.items()
        }
        values["route_layers"] = [
            self.via_start_layer.currentText(), self.via_end_layer.currentText()
        ]
        values["start_line"] = DifferentialLineEndConfig(**start_values)
        values["end_line"] = DifferentialLineEndConfig(**end_values)
        values["mechanical_via_enabled"] = self.mechanical_via_enabled.isChecked()
        values["mechanical_start_layer"] = self.mechanical_start_layer.currentText()
        values["mechanical_end_layer"] = self.mechanical_end_layer.currentText()
        values["mechanical_column_radius"] = self.mechanical_column_radius.text().strip()
        values["mechanical_pad_radius"] = self.mechanical_pad_radius.text().strip()
        values["layer_antipads"] = {
            layer: dict(settings)
            for layer, settings in self.differential_via_config.layer_antipads.items()
        }
        values.update(self._analysis_options_from_ui("via"))
        return DifferentialViaConfig(**values)

    def multistage_via_config_from_ui(self) -> MultiStageDifferentialViaConfig:
        start_values = {
            key: edit.text().strip() for key, edit in self.via_start_line_fields.items()
        }
        end_values = {
            key: edit.text().strip() for key, edit in self.via_end_line_fields.items()
        }
        for prefix, values in (("start", start_values), ("end", end_values)):
            values["upper_reference_layer_name"] = self.via_reference_combos[prefix]["upper"].currentText()
            values["lower_reference_layer_name"] = self.via_reference_combos[prefix]["lower"].currentText()
        values = {
            key: edit.text().strip() for key, edit in self.multistage_via_fields.items()
        }
        values["route_layers"] = [
            combo.currentText() for combo in self.multistage_layer_combos
        ]
        values["start_line"] = DifferentialLineEndConfig(**start_values)
        values["end_line"] = DifferentialLineEndConfig(**end_values)
        values["layer_antipads"] = {
            layer: dict(settings)
            for layer, settings in self.multistage_via_config.layer_antipads.items()
        }
        values.update(self._analysis_options_from_ui("via"))
        return MultiStageDifferentialViaConfig(**values)

    @staticmethod
    def _set_signal_role(layers: list[Layer], signal_name: str) -> None:
        for layer in layers:
            if layer.kind == "copper":
                layer.role = "signal" if layer.name == signal_name else "ground"

    @staticmethod
    def _require_reference_selections(
        layers: list[Layer],
        route_name: str,
        upper_name: str,
        lower_name: str,
        label: str,
    ) -> None:
        copper = [layer.name for layer in layers if layer.kind == "copper"]
        if route_name not in copper:
            raise ValueError(f"{label}: choose a valid copper route layer.")
        index = copper.index(route_name)
        if index > 0 and not upper_name:
            raise ValueError(f"{label}: select an upper reference copper layer.")
        if index < len(copper) - 1 and not lower_name:
            raise ValueError(f"{label}: select a lower reference copper layer.")

    def refresh_views(self) -> None:
        if self._loading:
            return
        try:
            config = self.config_from_ui(); self.config = config
            copper = [x.name for x in config.layers if x.kind == "copper"]
            current = self.signal_layer.currentText(); self.signal_layer.blockSignals(True)
            self.signal_layer.clear(); self.signal_layer.addItems(copper)
            selected = next((x.name for x in config.layers if x.kind == "copper" and x.role == "signal"), current)
            self.signal_layer.setCurrentText(selected); self.signal_layer.blockSignals(False)
            self._refresh_stackup_reference_layers()
            gf_layers = ([copper[0]] + copper[1:-1]) if copper else []
            self.gssg_layer.blockSignals(True); gcurrent = self.gssg_layer.currentText(); self.gssg_layer.clear(); self.gssg_layer.addItems(gf_layers)
            gssg_selected = self.gssg_config.signal_layer_name if self.gssg_config.signal_layer_name in gf_layers else ""
            if not gssg_selected:
                gssg_selected = gcurrent if gcurrent in gf_layers else ""
            if not gssg_selected and gf_layers:
                gssg_selected = gf_layers[0]
            self.gssg_layer.setCurrentText(gssg_selected)
            self.gssg_layer.blockSignals(False)
            if gssg_selected:
                self.gssg_config.signal_layer_name = gssg_selected

            inner_selected = gssg_selected if gssg_selected != "L1" else ""
            is_inner = bool(inner_selected)
            if is_inner:
                self.inner_gf_config.inner_signal_layer_name = inner_selected
            self.gf_mode.setText(self._ui_text(
                "Inner GF + VIA" if is_inner else "Surface GF on L1"
            ))
            self.inner_options_group.setVisible(is_inner)
            self.inner_pad_void_group.setVisible(is_inner)
            self.inner_mechanical_group.setVisible(is_inner)
            if self._language == "zh_CN":
                self.gf_mode_help.setText(
                    (
                        f"内层模式：L1 放置 GF 焊盘；P/N 信号及回流过孔结构转换到 {inner_selected}。"
                    )
                    if is_inner else
                    "表层模式：GF 焊盘、Fanout 和差分走线均位于 L1。"
                )
            else:
                self.gf_mode_help.setText(
                    (
                        "Inner mode: L1 contains the GF pads; P/N and return VIA structures "
                        f"transition to {inner_selected}."
                    )
                    if is_inner else
                    "Surface mode: GF pads, fanout, and differential traces are all on L1."
                )
            self._refresh_inner_mechanical_start_layers()
            self._refresh_inner_reference_layers()
            self._refresh_inner_pad_void_layers()

            via_layers = self.differential_via_config.route_layers
            for combo, configured in (
                (self.via_start_layer, via_layers[0] if len(via_layers) > 0 else ""),
                (self.via_end_layer, via_layers[1] if len(via_layers) > 1 else ""),
            ):
                previous = combo.currentText()
                combo.blockSignals(True); combo.clear(); combo.addItems(copper)
                selected_via_layer = configured if configured in copper else previous
                combo.setCurrentText(selected_via_layer if selected_via_layer in copper else "")
                combo.blockSignals(False)
            self._refresh_multistage_layer_choices()
            self._refresh_via_reference_layers()
            self._refresh_cap_route_choices()
            self._refresh_cap_preview(config.layers)

            inner_preview_layers = [Layer.from_dict(item) for item in config.to_dict()["layers"]]
            self._set_signal_role(inner_preview_layers, inner_selected)
            self.preview.update_layers(config.layers)
            self.gssg_preview.update_layers(inner_preview_layers)
            self.differential_via_preview.update_layers(config.layers)
            self.refresh_materials(config)
        except (ValueError, TypeError):
            self.material_table.setRowCount(0)
        self._apply_language()

    def refresh_materials(self, config: StackupConfig) -> None:
        mapping = layer_material_groups(config); rows = {}
        for layer in config.layers:
            if layer.name in mapping:
                rows.setdefault(mapping[layer.name], []).append(layer)
        self._material_members = {name: [x.name for x in members] for name, members in rows.items()}; self._material_rows = list(rows)
        self.material_table.blockSignals(True); self.material_table.setRowCount(len(rows))
        for row, (name, members) in enumerate(rows.items()):
            self.material_table.setItem(row, 0, QTableWidgetItem(name))
            for col, value in enumerate((str(members[0].dk), str(members[0].df), ", ".join(x.name for x in members)), 1):
                item = QTableWidgetItem(value); item.setFlags(item.flags() & ~Qt.ItemIsEditable); self.material_table.setItem(row, col, item)
        self.material_table.blockSignals(False)

    # ---------- file/edit/build actions ----------
    def on_material_name_changed(self, row: int, column: int) -> None:
        if self._loading or column != 0 or row >= len(self._material_rows): return
        new = self.material_table.item(row, 0).text().strip(); old = self._material_rows[row]
        if not new or new == old: return
        config = self.config_from_ui()
        for layer in config.layers:
            if layer.name in self._material_members.get(old, []): layer.material_name = new
        self.load_config_into_ui(config, self.gssg_config)

    def on_editor_changed(self, *args) -> None:
        if self._loading:
            return
        # Keep mode-specific field edits alive when the shared layer table is
        # subsequently reordered or rebuilt.
        try:
            self.gssg_config = self.gssg_config_from_ui()
            self.inner_gf_config = self.inner_gf_config_from_ui()
            if self._active_via_mode == "multistage":
                self.multistage_via_config = self.multistage_via_config_from_ui()
            else:
                self.differential_via_config = self.differential_via_config_from_ui()
            self.cap_pad_config = self.cap_pad_config_from_ui()
        except (TypeError, ValueError):
            pass
        self.refresh_views()

    def on_signal_layer_selected(self, name: str) -> None:
        if self._loading or not name: return
        self._loading = True
        for row in range(self.layer_table.rowCount()):
            layer_name = self.layer_table.item(row, 0).text().strip() if self.layer_table.item(row, 0) else ""
            if self.layer_table.cellWidget(row, 1).currentText() == "copper":
                self.layer_table.cellWidget(row, 2).setCurrentText("signal" if layer_name == name else "ground")
        self._loading = False; self.refresh_views()

    def on_gssg_layer_selected(self, name: str) -> None:
        """Select surface GF on L1 or Inner GF + VIA on another route layer."""
        if not self._loading and name:
            self.gssg_config.signal_layer_name = name
            if name != "L1":
                self.inner_gf_config.inner_signal_layer_name = name
            self.refresh_views()

    def on_inner_mechanical_option_changed(self, *args) -> None:
        """Enable valid Inner GF mechanical endpoints and persist the option."""
        if self._loading:
            return
        self._refresh_inner_mechanical_start_layers()
        self.on_editor_changed()

    def on_inner_mechanical_layer_selected(self, *args) -> None:
        """Keep the GF mechanical endpoint deeper than its selected start."""
        if self._loading:
            return
        self._refresh_inner_mechanical_start_layers()
        self.on_editor_changed()

    def on_via_mechanical_option_changed(self, *args) -> None:
        """Enable valid Differential VIA mechanical endpoints."""
        if self._loading:
            return
        self._refresh_mechanical_start_layers()
        self.on_editor_changed()

    def on_via_mechanical_layer_selected(self, *args) -> None:
        """Keep the Differential VIA mechanical endpoint after its start."""
        if self._loading:
            return
        self._refresh_mechanical_start_layers()
        self.on_editor_changed()

    def on_via_route_layer_selected(self, *args) -> None:
        """Keep the valid mechanical-start choices inside the selected span."""
        if self._loading:
            return
        self._refresh_mechanical_start_layers()
        self.on_editor_changed()

    def on_multistage_layer_selected(self, *args) -> None:
        if self._loading:
            return
        self._refresh_multistage_layer_choices()
        self.on_editor_changed()

    def on_via_mode_changed(self, *args) -> None:
        if self._loading:
            return
        selected = self.via_mode.currentData()
        if selected not in {"single", "multistage"}:
            return
        try:
            if self._active_via_mode == "multistage":
                self.multistage_via_config = self.multistage_via_config_from_ui()
            else:
                self.differential_via_config = self.differential_via_config_from_ui()
        except (TypeError, ValueError):
            pass
        self._active_via_mode = selected
        self._loading = True
        if selected == "multistage":
            self._load_multistage_via_fields(self.multistage_via_config, load_shared=True)
        else:
            self._load_differential_via_fields(self.differential_via_config, load_shared=True)
        self._loading = False
        self._update_via_mode_visibility()
        self.refresh_views()

    def add_layer(self, kind: str) -> None:
        idx = self.layer_table.rowCount() + 1
        layer = Layer(f"{kind.upper()}_{idx}", kind, "1mil", 2.84 if kind != "copper" else None, 0.0018 if kind != "copper" else None)
        config = self.config_from_ui(); config.layers.append(layer); self.load_config_into_ui(config, self.gssg_config)

    def delete_layer(self) -> None:
        row = self.layer_table.currentRow()
        if row >= 0: self.layer_table.removeRow(row); self.refresh_views()

    def move_layer(self, direction: int) -> None:
        row, target = self.layer_table.currentRow(), self.layer_table.currentRow() + direction
        if row < 0 or target < 0 or target >= self.layer_table.rowCount(): return
        config = self.config_from_ui(); config.layers[row], config.layers[target] = config.layers[target], config.layers[row]
        self.load_config_into_ui(config, self.gssg_config); self.layer_table.selectRow(target)

    def new_config(self) -> None:
        self.load_config_into_ui(
            StackupConfig(), GSSGConfig(), InnerGFConfig(), DifferentialViaConfig(),
            MultiStageDifferentialViaConfig(), CapPadConfig(),
        )

    def load_example(self) -> None:
        self.load_config_into_ui(
            eight_layer_example(), GSSGConfig(signal_layer_name="L1"),
            InnerGFConfig(), DifferentialViaConfig(), MultiStageDifferentialViaConfig(), CapPadConfig(),
        )

    def choose_output(self, edit: QLineEdit) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, self._ui_text("Save AEDT project"), edit.text(),
            "AEDT Project (*.aedt)",
        )
        if path: edit.setText(path)

    def choose_cap_component(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self._ui_text("Choose A3D capacitor"),
            self.cap_real_component_file.text(), "AEDT 3D Component (*.a3dcomp)",
        )
        if path:
            self.cap_real_component_file.setText(path)

    def import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, self._ui_text("Import configuration"), "", "JSON (*.json)"
        )
        if not path: return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            stack = StackupConfig.from_dict(data["stackup"])
            gssg = GSSGConfig.from_dict(data["gssg"])
            inner_gf = InnerGFConfig.from_dict(data.get("inner_gf", {}))
            differential_via = DifferentialViaConfig.from_dict(
                data.get("differential_via", {})
            )
            multistage_via = MultiStageDifferentialViaConfig.from_dict(
                data.get("differential_multistage_via", {})
            )
            cap_pad = CapPadConfig.from_dict(data.get("cap_pad", {}))
            self.load_config_into_ui(
                stack, gssg, inner_gf, differential_via, multistage_via, cap_pad
            )
            self.append_log(f"Imported: {path}")
        except Exception as error:
            QMessageBox.critical(
                self, self._ui_text("Import failed"),
                self._localized_message(str(error)),
            )

    def export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, self._ui_text("Export configuration"),
            "stackup_gssg_config.json", "JSON (*.json)",
        )
        if not path: return
        try:
            if self._active_via_mode == "multistage":
                self.multistage_via_config = self.multistage_via_config_from_ui()
            else:
                self.differential_via_config = self.differential_via_config_from_ui()
            data = {
                "stackup": self.config_from_ui().to_dict(),
                "gssg": self.gssg_config_from_ui().to_dict(),
                "inner_gf": self.inner_gf_config_from_ui().to_dict(),
                "differential_via": self.differential_via_config.to_dict(),
                "differential_multistage_via": self.multistage_via_config.to_dict(),
                "cap_pad": self.cap_pad_config_from_ui().to_dict(),
            }
            Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self.append_log(f"Exported: {path}")
        except Exception as error:
            QMessageBox.critical(
                self, self._ui_text("Export failed"),
                self._localized_message(str(error)),
            )

    def append_log(self, message: str) -> None: self.log_view.appendPlainText(message)

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            self._ui_text("About HFSS Automodeling"),
            (
                f"HFSS 自动建模工具\n\n开发者：{DEVELOPER}\n{COPYRIGHT}"
                if self._language == "zh_CN" else
                f"HFSS Automodeling\n\nDeveloper: {DEVELOPER}\n{COPYRIGHT}"
            ),
        )

    def generate_project(self, mode: str) -> None:
        try:
            stack = self.config_from_ui()
            worker_mode = mode
            gssg = None
            inner_gf = None
            differential_via = None
            multistage_via = None
            cap_pad = None
            ui_gssg = None
            if mode in ("stackup", "stackup_tdr"):
                if mode == "stackup" and stack.create_tdr_report and not (stack.create_setup and stack.create_sweep):
                    raise ValueError("TDR report requires both Setup1 and Sweep.")
                self._set_signal_role(stack.layers, self.signal_layer.currentText())
                self._require_reference_selections(
                    stack.layers,
                    self.signal_layer.currentText(),
                    stack.upper_reference_layer_name,
                    stack.lower_reference_layer_name,
                    "Stackup differential",
                )
                output = self.stackup_output.text().strip()
            elif mode == "gf":
                output = self.gssg_output.text().strip()
                ui_gssg = self.gssg_config_from_ui()
                breakout = ui_gssg.signal_layer_name
                if breakout == "L1":
                    worker_mode = "gssg"
                    gssg = ui_gssg
                else:
                    copper_layers = [
                        layer.name for layer in stack.layers if layer.kind == "copper"
                    ]
                    internal = copper_layers[1:-1]
                    if breakout not in internal:
                        raise ValueError("Choose L1 or a valid internal copper breakout layer.")
                    worker_mode = "inner_gf"
                    inner_gf = self.inner_gf_config_from_ui()
                    inner_gf.inner_signal_layer_name = breakout
                    if not inner_gf.upper_reference_layer_name:
                        raise ValueError("Select an upper reference copper layer for Inner GF.")
                    if not inner_gf.lower_reference_layer_name:
                        raise ValueError("Select a lower reference copper layer for Inner GF.")
                    self._set_signal_role(stack.layers, breakout)
                    gssg = GSSGConfig.from_dict(ui_gssg.to_dict())
                    gssg.signal_layer_name = inner_gf.gf_layer_name
            elif mode == "differential_via":
                output = self.differential_via_output.text().strip()
                if self._active_via_mode == "multistage":
                    worker_mode = "multistage_via"
                    multistage_via = self.multistage_via_config_from_ui()
                    if any(not name for name in multistage_via.route_layers):
                        raise ValueError("Choose all four two-stage VIA route layers.")
                    for label, route, line in (
                        ("VIA input", multistage_via.route_layers[0], multistage_via.start_line),
                        ("VIA output", multistage_via.route_layers[3], multistage_via.end_line),
                    ):
                        self._require_reference_selections(
                            stack.layers, route,
                            line.upper_reference_layer_name,
                            line.lower_reference_layer_name,
                            label,
                        )
                else:
                    differential_via = self.differential_via_config_from_ui()
                    if any(not name for name in differential_via.route_layers):
                        raise ValueError("Choose both differential VIA route layers.")
                    if differential_via.route_layers[0] == differential_via.route_layers[1]:
                        raise ValueError("Differential VIA route layers must be different.")
                    for label, route, line in (
                        ("VIA left", differential_via.route_layers[0], differential_via.start_line),
                        ("VIA right", differential_via.route_layers[1], differential_via.end_line),
                    ):
                        self._require_reference_selections(
                            stack.layers, route,
                            line.upper_reference_layer_name,
                            line.lower_reference_layer_name,
                            label,
                        )
            elif mode == "cap_pad":
                output = self.cap_output.text().strip()
                cap_pad = self.cap_pad_config_from_ui()
                validate_cap_pad(stack, cap_pad)
            else:
                raise ValueError(f"Unknown generation mode: {mode}")
            # Persist the exact snapshots handed to the worker so both tabs
            # continue to reflect the same table-derived stackup/configuration.
            self.config = stack
            if ui_gssg is not None:
                self.gssg_config = ui_gssg
            if inner_gf is not None:
                self.inner_gf_config = inner_gf
            if differential_via is not None:
                self.differential_via_config = differential_via
            if multistage_via is not None:
                self.multistage_via_config = multistage_via
            if cap_pad is not None:
                self.cap_pad_config = cap_pad
            if not output: raise ValueError("Choose an output AEDT project path.")
            if mode == "stackup_tdr" and not Path(output).is_file():
                raise ValueError("Select an existing, manually solved AEDT project first.")
            if mode != "stackup_tdr" and Path(output).exists():
                original = Path(output)
                candidate = original.with_name(original.stem + "_" + datetime.now().strftime("%H%M%S") + original.suffix)
                index = 1
                while candidate.exists():
                    candidate = original.with_name(original.stem + "_" + datetime.now().strftime("%H%M%S") + f"_{index}" + original.suffix)
                    index += 1
                output = str(candidate)
                self.append_log(f"Existing path detected; using {output}")
            if mode == "stackup":
                self.stackup_output.setText(output)
            self.build_button_for(mode).setEnabled(False)
            self.append_log(
                f"Starting GF model generation ({'surface L1' if worker_mode == 'gssg' else worker_mode})..."
                if mode == "gf" else f"Starting {worker_mode} model generation..."
            )
            self._thread = QThread(self)
            self._worker = BuildWorker(
                mode=worker_mode,
                stackup=stack,
                output_path=output,
                gssg=gssg,
                inner_gf=inner_gf,
                differential_via=differential_via,
                multistage_via=multistage_via,
                cap_pad=cap_pad,
            )
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run); self._worker.log.connect(self.append_log)
            self._worker.success.connect(lambda path: self.append_log(
                f"TDR report ready in: {path}" if mode == "stackup_tdr" else f"Completed; AEDT opened: {path}"
            ))
            self._worker.failed.connect(self.on_build_failed); self._worker.finished.connect(self._thread.quit)
            self._worker.finished.connect(self._worker.deleteLater); self._thread.finished.connect(self._thread.deleteLater)
            self._thread.finished.connect(lambda: self.build_button_for(mode).setEnabled(True)); self._thread.start()
        except Exception as error:
            QMessageBox.warning(
                self, self._ui_text("Unable to generate"),
                self._localized_message(str(error)),
            )

    def build_button_for(self, mode: str) -> QPushButton:
        return {
            "stackup": self.stackup_build,
            "stackup_tdr": self.stackup_tdr_build,
            "gf": self.gssg_build,
            "differential_via": self.differential_via_build,
            "cap_pad": self.cap_build,
        }[mode]

    def on_build_failed(self, details: str) -> None:
        self.append_log(details)
        message = details.splitlines()[-1] if details else "Unknown error"
        QMessageBox.critical(
            self, self._ui_text("AEDT generation failed"),
            self._localized_message(message),
        )


def main() -> int:
    app = QApplication(sys.argv); window = MainWindow(); window.show(); return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
