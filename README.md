# Synology Btrfs Recovery Toolkit — v0.3-beta (experimental)

[中文入口 / Chinese guide](docs/README.zh-CN.md) · [现场安全手册](docs/runbook.zh-CN.md) · [故障决策树](docs/troubleshooting.zh-CN.md) · [完整脱敏案例](docs/case-study.zh-CN.md)

**Protect data first. This is a read-only *data extraction* toolkit, not a DSM / RAID / Btrfs repair program.** The accompanying guides show how a real incident was diagnosed and resolved through a separate, vendor-controlled DSM repair pathway. **Do not run it on the original disks while DSM is rebuilding an array.**

## Who should use this?

Experienced Linux operators whose Synology DSM/SMB is unavailable, with a verified RAID1 member, a *separately assembled read-only* degraded md array and read-only LVM, a physically distinct ext4 backup target, and a Btrfs restore error related to observed Synology flags. RAID5/6, encrypted disks, multiple extent layouts, physical unreadable disks or unknown metadata layouts are **outside the validated scope**.

## Safety guarantees and non-guarantees

- `doctor` verifies configured serials, source member vs source disk, exact one RAID member, read-only source physical disk plus md/LV, no source mount, precise destination mount and serial, distinct source/destination devices and minimum backup space. Do not override failures.
- This tool never runs `mount`, `fsck`, `mdadm --create/--add`, `btrfs check --repair`, metadata update, or RAID resynchronization. **You must configure your read-only source environment separately** following the safety manual, and bear in mind external auto-mount/auto-assemble policies.
- Each extraction creates a fresh directory on the backup disk. No in-place resume, no silent merging; source files never overwritten by the script. Root IDs must be confirmed per device.
- The local `btrfs-progs v6.17.1` tree checker patch narrowly relaxes observed root flag bits 33/34 and inode flag bit 30. **No semantics or full compatibility is implemented**; behavior is experimental.
- Exit code 0 does **not** mean all files recovered. Audit read errors, zero-byte media and compare independent inventories and decoded samples. SHA-256 hashes of destination files are not source correctness proofs.
- Diagnostic snapshots, especially auth logs, may contain usernames, IPs, secrets or personal paths. Don't publish them or include photos/images in public reports.

## Build on Ubuntu

```bash
sudo apt update
sudo apt install -y git build-essential autoconf automake pkg-config libtool \
  libblkid-dev libuuid1 uuid-dev libzstd-dev liblz4-dev zlib1g-dev libudev-dev \
  libmount-dev libacl1-dev libattr1-dev libext2fs-dev python3
./build.sh
python3 -m unittest discover -s tests -v
```

The build uses the official pinned upstream source, `--disable-python` to avoid missing Python version pkg-config packages, and never installs the resulting binary globally. Review `synology-compat-generated.patch` after building. Upstream licensing remains separate from this repo.

## Usage

```bash
cp config.example.json config.json
# Verify disk names and serial numbers every session before editing config.json
python3 synology_ro.py --config config.json doctor
python3 synology_ro.py --config config.json roots
# Root IDs are device-specific, not 259/261 by default
python3 synology_ro.py regex --dir 'someuser/Photos/MobileBackup'
python3 synology_ro.py --config config.json extract --root-id ROOT_ID \
  --dir 'someuser/Photos/MobileBackup' --yes
python3 synology_ro.py audit --input '/actual/backup/batch' --output-dir "$HOME/recovery-audits"
# Expensive optional checksums of recovered destinations:
python3 synology_ro.py audit --input '/actual/backup/batch' --output-dir "$HOME/recovery-audits" --sha256
```

`audit` writes unique JSONL + summary JSON files to a local output directory, excluding symlinks, reports zero-byte media examples and read errors, and returns nonzero on encountered read/hash errors. Run `mkdir -p "$HOME/recovery-audits"` first. **The audit does not detect missing source files or verify image/video decoding.**

## Known limits / stop conditions

- Never use `mdadm --force`, `mdadm --create`, `--zero-superblock`, `btrfs check --repair`, or write-mount the source as a workaround.
- No per-file checkpoints or guaranteed resume. Retry to a *new* batch directory and manually compare.
- `roots` does not prove which subvolume contains an arbitrary shared folder; separately confirm subvolume relations.
- There is no verified full test against multiple DSM models/versions or damaged physical disks. Do not treat the observed one-device success as broad certification.
- RAID Repair is a separate **destructive-to-target** action under Synology DSM; see runbook §9. A case where DSM failed because of OOM and external password guessing does not imply that other DSM failures have the same cause.

## Tests and contribution

`python3 -m unittest discover -s tests -v` runs logic-only local tests. A clean upstream fetch/compile and real-device end-to-end restore **must be validated separately**. Never share personal NAS log data, disk identifiers, credentials, or source file content in issues. See `LICENSE` (project code MIT). This repository is not affiliated with Synology.


**Documented incident environment:** Synology **DS218+**, 2 × 4 TB drives, **SHR-1 / RAID1**, **DSM 7.2.2-72806 Update 10**. This is case metadata, not a formal compatibility guarantee.
