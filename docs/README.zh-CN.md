# 群晖 Btrfs 数据只读恢复与 DSM 故障修复手册

- **第一次遇到故障：** 从 [现场操作手册](runbook.zh-CN.md) 第 0 节开始。不要因为 DSM 登录失败就先改 RAID。
- **想快速定位：** [故障决策树](troubleshooting.zh-CN.md)。
- **想看真实成功/未决细节：** [脱敏完整事故复盘](case-study.zh-CN.md)。
- **想运行工具：** 仔细阅读根目录 [README](../README.md)；先 `doctor`，后 `roots`、小样本 `extract`，最后 `audit`。

## 工具边界

工具定位为实验性 **只读数据导出**，不是通用 DSM 修复程序。不会替你设置只读 RAID/LVM，也不会自动覆盖旧成员。只能在严格符合已观察标志的部分 Synology Btrfs 数据上尝试恢复，并不保证完整。自动构建官方 `btrfs-progs v6.17.1` 局部补丁，恢复日志与审计清单由用户保存在 Linux 本地文件系统。

## 事故启示

单次案例中备份导出关键照片后，发现根 DSM/SMB 故障伴随公网失败登录、进程爆发和多次 OOM。DSM 隔离公网后受控单盘启动，原 SHR 池为降级且照片可读，最终由用户发起官方 Repair。**这是两条独立恢复路线，不能把只读文件导出工具当作已经“自动解决 DSM 故障”。**

## 首次安装与 Python 虚拟环境

在 Ubuntu 的项目根目录，以普通用户运行：

```bash
./setup.sh --system
./setup.sh --build
source .venv/bin/activate
python synology_ro.py --help
```

`--system` 会提示 `sudo`，仅安装系统依赖；`--build` 下载固定版本的上游 Btrfs 源码并本地构建。Python 脚本无第三方 pip 依赖，因此 `requirements.txt` 不包含运行时包。**在 DSM 正在修复阵列期间不要连接源盘进行测试。**
