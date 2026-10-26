# 从 DSM 故障到数据备份、系统恢复：安全操作手册

> **先判断是否真的需要恢复工具。** 如果 DSM 可登录、File Station 可读、存储池仅降级，优先在 DSM 内完成备份、安全排查和官方修复；不要为了使用本工具拆盘。以下离线流程用于 DSM/SMB 无法正常访问、数据不可替代、需要从原盘抢救的情况。
>
> **风险边界：** 第 1–7 节为只读抢救流程；第 8 节起 DSM 启动与 RAID Repair **会写入原盘**。两者不可混用。任何不确定情况请停止并咨询专业恢复人员。

## 0. 决策树和停止条件

```text
DSM / SMB 无法访问
├─ LAN 网络不通 → 检查 IP、网线、电源、NAS 状态灯；不要先动 RAID
├─ DSM 能登录且数据卷可访问 → 在 DSM/外盘复制数据，再排查服务/安全
├─ DSM 无法用，数据关键且备份不完整
│  ├─ 磁盘 SMART/读取报错 → 优先完整盘镜像 / 专业服务，勿反复扫盘
│  └─ RAID1 单成员可读 → 保留另一成员离线；只读组装 → 数据恢复 → 审计
└─ 数据已经核验并准备修复 NAS → 隔离公网 → DSM 系统日志 → 单盘受控启动 → 官方 Repair
```

**立即停止：** 盘身份或容量对不上；`mdadm --examine` UUID/Role 不符合预期；阵列显示 resync/recovery；原盘被 RW 挂载；`blockdev --getro` 不为 1；备份目标不是独立硬盘；出现坏扇区/I/O 失败；恢复中出现持续异常；DSM 提示初始化/创建池/清空来源盘。

## 1. 准备清单

- 一台 Linux（Ubuntu 示例），独立的、容量足够的 **备份目标盘**；另一原 RAID 成员离线保留。
- 电源稳定，USB 外置盒支持单盘直通。双盘盒的 `SINGLE` 不足以保证 Linux 不会自动组 RAID。
- 记录原盘槽位/序列号、备份盘序列号；禁止混用 `/dev/sdX` 的旧值。
- 备份盘的文件系统需在这版工具中为 `ext4`，且精确挂载到配置指定的目录；推荐最少预留 100GiB 空间。
- 先关掉直接暴露 DSM 的公网端口映射、反向代理入口、UPnP/DMZ，再继续系统修复。不要混淆 DDNS 名称与真正的公开入口。

## 2. 识别源盘与 RAID 证据（只读）

```bash
lsblk -o NAME,SIZE,MODEL,SERIAL,FSTYPE,UUID,MOUNTPOINTS
cat /proc/mdstat
sudo mdadm --examine /dev/sdX5           # 注意替换成核对过的分区
sudo smartctl -a /dev/sdX                # SMART 是健康证据，不保证无故障
```

`/dev/sdX5` 是本案示例，不是通用布局。群晖 DSM 系统 RAID 可以是 **0.90 swapped**，数据阵列可能是 1.2：检查输出的 metadata/version/UUID 后才能判断。RAID `Events` 差异可能只是事后单盘启动造成，不能直接推断数据损坏或自行手调 Events。对故障盘优先先做位级镜像而不是直接恢复。

## 3. 单成员 RAID1/LVM 只读准备（专家操作）

> 以下命令仅适用于你已经通过 `mdadm --examine` 确认目标是 **RAID1 数据阵列的单个正确成员**，且它 **不属于任何活动阵列** 的情况。不会自动识别用户真实盘号，**不可照抄运行**。不同 RAID 等级、损毁超级块、混合 SHR 布局不适用。

```bash
# 先记录输出；这一命令仅显示计划，不组装
sudo mdadm --examine /dev/sdX5
cat /proc/mdstat

# 仅在核对正确阵列、确认其它成员离线后，选择空闲 md 设备号只读组装
sudo blockdev --setro /dev/sdX      # 明确源物理盘只读；仍无法替代硬件写保护
sudo blockdev --getro /dev/sdX    # 必须 1
sudo mdadm --assemble --readonly --run /dev/md127 /dev/sdX5

# 立刻核对结果，必须 read-only、RAID1、一个正确的成员
cat /proc/mdstat
sudo mdadm --detail /dev/md127
sudo blockdev --getro /dev/sdX      # 1
sudo blockdev --getro /dev/md127    # 1

# 确认前一步完整正确后，先阻止 md 块设备写入（通常 readonly 已经是 1）
sudo blockdev --setro /dev/md127

# 激活 LVM，注意发行版不同可用选项；不要更新 PV/VG 元数据
sudo vgchange -ay vg1000
# 必须立即确保逻辑卷块设备只读；如自动激活设备先前可能写入，停止使用并寻求专家指导
sudo blockdev --setro /dev/vg1000/lv
sudo blockdev --getro /dev/vg1000/lv  # 1
```

LVM 激活可能带来自动扫描/自动激活与短暂写入窗口；**上面的步骤不能保证自第一毫秒起只读**。对高度敏感原盘，推荐先对整个来源设备设置 Linux block read-only，禁用自动发现/自动挂载，或直接使用只读块设备镜像。若不了解 LVM 自动激活行为，请由专业人员准备只读映射。上述过程 **不会在源数据卷上执行 mount 或 fsck**。如果系统已经自动组装数据 RAID，先核对实际设备而不是再次运行 `mdadm --assemble`。

## 4. 构建工具（只影响本地编译环境）

```bash
sudo apt update
sudo apt install -y git build-essential autoconf automake pkg-config libtool \
  libblkid-dev libuuid1 uuid-dev libzstd-dev liblz4-dev zlib1g-dev \
  libudev-dev libmount-dev libacl1-dev libattr1-dev libext2fs-dev python3
./build.sh
python3 -m unittest discover -s tests -v
```

只下载官方标记为 v6.17.1 的 `btrfs-progs` 并在本目录局部编译，不安装内核模块、不覆盖系统 btrfs。`patch_upstream.py` **只绕过观察到的标志检查**，不理解专有字段；构建失败请保存 `build.log`，不要随机修改源码。

## 5. 识别根 ID、先小批后全量

```bash
cp config.example.json config.json
# 修改配置：源盘、单个 RAID 成员、md、LV、目标盘、两个序列号、目标挂载点
python3 synology_ro.py --config config.json doctor
python3 synology_ro.py --config config.json roots
# 检查 logs/roots-*.log，并用独立工具或安全元数据枚举明确子卷映射
python3 synology_ro.py regex --dir 'someuser/Photos/MobileBackup'
# 先用最小可用的目标目录作为测试批次；每次创建独立输出目录
python3 synology_ro.py --config config.json extract --root-id ROOT_ID --dir 'someuser/Photos/MobileBackup' --yes
```

**ROOT_ID 不能照搬案例值。** 本案示例中 `homes` root 259，`photo` root 261；不是所有设备一致。`roots` 输出列出候选 root 不一定能唯一确定共享目录所属，必要时借助只读 metadata 检查或 UFS Explorer 等独立浏览器确认。`regex` 只生成筛选表达式，**不是恢复预览**。文件名中有换行、符号链接或专有路径行为的场景尚未充分验证。

## 6. 分批备份策略

先导出可独立验证的一张 JPG 和一个较大的 MOV，确认能够打开。再根据源目录及目标盘空间按批次导出，例如个人 MobileBackup、PhotoLibrary、Moments 和共享 photo 单独 root。每批结束至少核对源自工具的日志 `EXIT_CODE`、磁盘剩余空间、零文件数、样本完整性。**退出码为 0 不能确认没有跳过/损坏文件。** 不提供原地断点续传，失败重跑会建立新目录。

## 7. 检查导出质量、留存备份

```bash
python3 synology_ro.py audit --input '/mnt/target/Synology_Recovery/BATCH' \
  --output-dir "$HOME/recovery-audits"
# 若确实需要校验备份盘文件后续是否改变；读盘开销可能很大
python3 synology_ro.py audit --input '/mnt/target/Synology_Recovery/BATCH' \
  --output-dir "$HOME/recovery-audits" --sha256
```

审计生成 `.jsonl` 和 `.summary.json`。必须检查 `zero_by_extension`、`examples_zero_media`、`read_errors`、`hash_errors`。空的 JPEG/HEIC/MOV/MP4 优先排查，不要把零文件全部视为缓存。进一步用图片解码软件、`ffprobe` 或 `ffmpeg` 检查媒体文件；核查不同日期/文件夹及独立软件目录清单。**文件哈希只有恢复目标内部校验意义，不证明与原盘同一字节。** 最好另建独立备份副本。

## 8. 如果恢复后还要修 DSM（会写原盘）

1. 先留存 DSM 系统日志及证据，确保目标盘备份可打开，原阵列另一个成员保持离线。DSM 系统分区常见独立 RAID1/ext4，但不能默认 `/dev/sdX1` 是直接可写 ext4；只读检查 `dumpe2fs -h /dev/sdX1`。若需要挂载，必须 `mount -t ext4 -o ro,noload,nosuid,nodev,noexec ...`，且原设备不可有写入权限。`ro` 单独使用可能重放 ext4 日志；不能运行写入式 `fsck`。
2. 可从 `/var/log/messages`、`auth.log`、`nginx/`、`samba/` 排查 OOM、认证、内存、网络和 SATA。观察到的密码猜测不等于已确认登录入侵；须另查成功登录、未知账户/任务、令牌。
3. 在可信 **局域网且公网入口隔离** 后，仅将选定来源盘放回原槽位；先退出 Ubuntu 的恢复工具并停用挂载、LVM、md，然后安全断开：`sudo vgchange -an vg1000` → `sudo mdadm --stop /dev/md127`（仅在依赖已释放、检查成功后）→ `udisksctl power-off -b /dev/sdX`。无法停用时不要强制，可正常关闭 Ubuntu 后取盘。
4. 单盘 NAS 启动 **会写入来源盘**。Synology Assistant 报 `Ready` 不是卷健康证明；测试 LAN IP、DSM 登录和 File Station；DSM 可能只因镜像少一盘而鸣叫。
5. 若 DSM 能登录：先查看内存/Swap、日志/安全账户，再看存储管理器是否只是 `Degraded`。**不自动推断 Btrfs 正常/数据完整。**
6. 若 DSM 报 `Crashed`、初始化、迁移、系统丢失：停止，不执行自动修复。官方 Mode 1/Mode 2 重置会改变配置，后者涉及 DSM 重装；确认完整备份和影响后才考虑。

## 9. RAID 镜像恢复（仅 DSM 官方操作，会覆盖目标盘）

在 DSM 可正常登录、数据卷可访问、存储池状态确认为 `Degraded`、外置备份核验且账号安全加固后，选择容量/兼容性合格且健康的目标硬盘。在关机情况下插入较为稳妥；若使用**旧的 RAID1 成员**，其超级块可能被 DSM 识别为旧池的一部分，不能保证直接成为可选目标。先核对序列号和 DSM HDD/SSD 状态；若提示自动在线组装、迁移、新建池、初始化或选择来源盘清除，请停止。

只有确定当前在线盘是唯一的**数据来源**、另外一块是**可以被覆盖的目标**时，才进入 Storage Manager → 存储池 → Repair。修复会产生大量读写，过程中勿关机。最终核对 `Healthy`、两块成员均加入、文件抽查和 SMART。**RAID1 不等于离线备份。**

## 10. 常见报错与决策

| 现象 | 不应采取 | 推荐行动 |
|---|---|---|
| `unknown root flags 0x400000000` | 直接 `btrfs check --repair` | 使用局部构建补丁、只读恢复，小样本验证 |
| `unknown inode flags 0x40000000` | 修改内核或原盘 | 确认局部编译带两处补丁 |
| `preview -D` 成功却未列文件 | 当作恢复成功 | 真实恢复小样本，检查实际大小与内容 |
| `vgchange -an` 显示 in use | `--force` | 查挂载、`dmsetup info` Open count 和 fuser；等待或正常关机 |
| RAID Events 不一致 | 直接 `--force` 两盘组装 | 排除单盘启动写入历史，保留另一盘离线 |
| 大量 OOM/登录失败 | 立刻重建 RAID | 先隔离公网，查日志、内存、账号，评估服务修复 |
| DSM 存储池 `Degraded` | 直接认定损毁 | 确认 File Station/数据卷、备份、择机 Repair |
| Btrfs 导出返回 0 但空文件多 | 删除源盘/原文件 | 按扩展名核查，独立恢复或比较原目录清单 |

## 11. 求助时安全分享什么

只共享脱敏的 RAID level/version、flags 报错、脚本退出码、清除序列号/IP/用户路径之后的日志和匿名化的统计汇总。**不要上传完整 DSM auth.log、证书、令牌、盘镜像、个人照片或账户数据库。**
