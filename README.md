# HFSS 通用叠层建模工具

基于 PySide6 + PyAEDT 的 HFSS 自动建模工具：在图形界面里编辑 PCB 叠层，一键生成叠层差分线、GF（GSSG）、差分过孔和电容焊盘模型，直接落到 Ansys Electronics Desktop 工程里。

Developer: **Yetaikunle**
Copyright © 2026 Yetaikunle. All rights reserved.

## 主要能力

- **叠层编辑**：Copper / PP / Core 层可增删、排序、改厚度与材料，内置八层模板，支持 JSON 导入导出。
- **叠层差分线 / TDR**：两端差分线加波端口，统一 deembed，可选用求解后创建 `TDRZt(Diff1)` 阻抗曲线。
- **GF（GSSG）**：按出线层自动选择模型——`L1` 生成表层 GF，其他内层生成 L1 GF Pad + VIA + 内层差分线，含参考铜避让与逐层捞空。
- **差分过孔**：单级与多级两种，支持"多级激光叠孔—机械孔—多级激光叠孔—出线"结构，激光孔逐级建盘、机械孔只在起止层建盘。
- **电容焊盘（CAP）**：顶装/底装、四焊盘独立、逐层反焊盘、可选机械段、breakout 出线、回流孔围栏、阻焊开窗；可插入 `.a3dcomp` 实体电容或等效 Lumped RLC，并支持两者成对生成做快慢对照。CAP 的过孔支持"狗腿（dogleg）"结构：激光段在焊盘轴上钻到某内层，该层横拉一小段铜，机械段从偏移后的轴上继续往下钻，激光轴与机械轴各自独立、反焊盘按所在段自动选轴。

生成过程只建模型、边界、Setup 和 Sweep，**不会自动求解**，也不会覆盖已有工程。

## 快速开始

### 方式一：直接用发布包

1. 解压 `HFSS_Stackup_Builder_20261120.zip`，得到 `HFSS_Stackup_Builder\` 文件夹。
2. **整个文件夹一起拷走**，不能只复制里面的 exe（依赖都在同级的 `_internal\`）。
3. 双击 `HFSS_Stackup_Builder.exe`。

目标机器只需要 Windows x64 + 已安装并可正常授权运行的 Ansys Electronics Desktop 2025 R2，不需要装 Python 或 PyAEDT。GUI 里 `AEDT version` 留空时自动用已安装的最新 AEDT，也可显式填 `2025.2`。

### 方式二：跑源码

```powershell
pip install PySide6 pyaedt==1.4.0
cd HFSS_Stackup_Builder
python hfss_stackup_gui.py
```

## 目录结构

```
HFSS_Stackup_Builder/
  hfss_stackup_gui.py                  GUI 入口（三个标签页）
  hfss_stackup_builder.py              叠层数据结构与基础建模、JSON 读写
  gf_gssg_model.py                     表层 GF（GSSG）
  gf_inner_model.py                    内层 GF：L1 GF Pad + VIA + 内层差分线
  differential_via_model.py            单级差分过孔
  differential_multistage_via_model.py 多级差分过孔（激光/机械组合）
  cap_pad_model.py                     电容焊盘与反焊盘（CAP）
  capacitor_s2p_fit.py                 从 S2P 拟合 ESR/ESL/C
  export_capacitor_component.py        导出 .a3dcomp 组件
  surface_differential_stripline.py    表面前差分带状线
  eight_layer_l2_differential.py       八层 L2 差分线批量建模示例
  tool_metadata.py                     署名与版权常量
  test_*.py                            单元测试（用假 Hfss 对象，无需 AEDT）
  components/SC04S0J104M_0p1uF.a3dcomp  内置电容 3D 组件
  README_GUI.md                        叠层 / GF / 过孔的细节说明
  README_CAP_PCB.md                    CAP 页与 TDR 工作流的细节说明
packaging/HFSS_Stackup_Builder.spec    PyInstaller 打包配置
```

生成结果默认写到程序同级目录的 `outputs\`，不会写进 `_internal`，所以发布包体积不会随使用增长。

## 单元测试

```powershell
cd HFSS_Stackup_Builder
python -m unittest discover -s . -p "test_*.py"
```

共 **124 个用例**，当前基线是 **5 个失败**：4 个针对阻焊旧行为的断言、1 个 `2mil` 与 `4mil` 的口径差异。改代码后以这 5 个作为对照，出现新的失败才说明引入了回归。测试用假 Hfss 对象驱动，不需要装 AEDT、也不占用授权。

## 自行打包

```powershell
# 仓库根目录执行；spec 里的相对路径以 packaging/ 为基准
pyinstaller packaging\HFSS_Stackup_Builder.spec
```

产物是 `dist\HFSS_Stackup_Builder\`（onedir：exe + `_internal`）。

**推荐 onedir 而不是 onefile**：onedir 冷启动约 2.5 秒，onefile 每次启动都要把 90 MB 解压到临时目录，通常 15 秒以上；排障时 onedir 还能直接替换 `_internal` 里的单个文件。

**conda 环境打包的坑**：构建前必须把 `Library\bin` 加进 PATH，否则打出的 exe 启动闪退，控制台报 `ImportError: DLL load failed while importing pyexpat`。原因是 conda 把 `pyexpat.pyd` 放在 `DLLs`，它依赖的 `libexpat.dll` 在 `Library\bin`，冻结后该目录不在 DLL 搜索路径。

```powershell
$env:PATH = "$env:CONDA_PREFIX;$env:CONDA_PREFIX\Library\bin;$env:PATH"
pyinstaller packaging\HFSS_Stackup_Builder.spec
```

体积参考：onedir 解压后约 225 MB（PyAEDT 及其依赖占绝大部分），exe 本体 12.5 MB；onefile 单个 exe 约 90 MB。

## 已知限制

- 生成后需要在 AEDT 里手动求解；TDR 报告要在求解完成后再点刷新按钮创建。
- AEDT 2025 R2 要求创建 Lumped RLC 边界时电流线坐标为数值：R/L/C 与布线变量可以安全扫参，但改动会移动或改变电容焊盘间隙的变量后，需要重新生成工程。
- 内置 `SC04S0J104M` 的 S2P 只有 10 MHz–3 GHz 六个采样点，拟合值适合当快速模型的初值，定稿前应换成更密的实测或厂商模型。
- 回流孔是规则近似阵列，不是 BRD 里回流孔坐标的复制。

## 关于署名

源码中的作者与版权文字只用于标示开发归属，不构成授权校验或防复制机制。如需主张权利，建议同时保留 Git 历史、发布包哈希与设计记录，并按需要办理软件著作权登记。
