# HFSS 通用叠层建模工具

Developer: **Yetaikunle**  
Copyright © 2026 Yetaikunle. All rights reserved.

使用已安装 PyAEDT 的环境启动 GUI：

```powershell
C:\Users\39004628\conda_envs\hfss_env\python.exe "E:\PYTHON\Automodeling\HFSS_Stackup_Builder\hfss_stackup_gui.py"
```

## EXE 发布包

目标电脑需要 Windows x64、已安装并可正常授权运行的 Ansys Electronics Desktop 2025 R2。目标电脑不需要另外安装 Python 或 PyAEDT。

解压发布 ZIP 后必须保留整个 `HFSS_Stackup_Builder` 文件夹，不能只复制其中的 EXE。双击 `HFSS_Stackup_Builder.exe` 启动。GUI 的 `AEDT version` 留空时自动使用已安装的最新 AEDT；也可以明确填写 `2025.2`。

GUI 启动时加载八层叠层模板。用户可以编辑、增删和移动 Copper、PP、Core 层，也可通过 `Import JSON` 恢复叠层、GF 和 Differential VIA 配置。三个生成标签页共享当前叠层表格。

GF 标签页通过出线层自动选择模型：选择 `L1` 时生成表层 GF；选择其他有效内层时生成 L1 GF Pad + VIA + 内层差分线。内层 GF 与单级 Differential VIA 均可分别选择机械孔起始层和终止层，从而支持“多级激光叠孔—机械孔—多级激光叠孔—出线”以及机械孔直接到出线层的结构。激光孔在相邻铜层之间逐级建立，并在经过的每层铜上创建孔盘；机械跨度只在起止铜层创建孔盘。信号 VIA 铜柱始终保持为独立物体，只合并出线层的 Trace、Fanout 和 Landing Pad。每层独立的 `VIA_ANTIPAD_RADIUS_<层名>` 与 `VIA_ANTIPAD_X_<层名>` 会写入 AEDT 工程，但 GUI 仅显示全局默认值。旧 JSON 若不含机械终止层，仍默认将机械孔终止于出线层的上一铜层。

内层 GF 的参考铜避让由连续的 W/S/G Trace clearance 和 VIA 槽形反焊盘组成，不再单独建立 Fanout clearance。`GF 焊盘下方捞空`中的 X1、Y、X2 分别对应信号焊盘右侧（向 GND/走线方向）、上下两侧和左侧（向信号盘外）的外扩量；选择到达层后，相同矩形会从 L1 到该层逐层挖去参考铜，留空则关闭该功能。X1 的最小允许值为 `150um`。

Differential VIA 闭合回流围栏距反焊盘的距离由 `Local return clearance` 控制。Inner GF 线侧回流孔的起止偏移由 Stackup 页的 `Via edge offset` 控制。

生成操作会建立模型、空气边界、Setup 和 Sweep（按各页选项），但不会自动求解，也不会覆盖已有工程。生成的 AEDT 工程默认保存在程序同级目录下的 `outputs\` 文件夹（EXE 运行时为 EXE 同级的 `outputs\`），不会写进 `_internal`，因此发布包体积不会随使用增长。

本项目中的作者与版权文字用于标示开发归属，不构成授权校验或防复制机制。建议同时保留 Git 历史、发布包哈希、设计记录，并按需要办理软件著作权登记。
