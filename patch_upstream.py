#!/usr/bin/env python3
"""Fail-closed compatibility patch for *pinned* btrfs-progs v6.17.1.

Allows observed Synology root flags 33/34 and inode flag 30 through checker.
This is NOT a generic feature implementation or a source-disk repair.
"""
import argparse
from pathlib import Path
import re

ROOT_RE = re.compile(r'(const u64 valid_root_flags\s*=\s*BTRFS_ROOT_SUBVOL_RDONLY\s*\|)(\s*)(BTRFS_ROOT_SUBVOL_DEAD\s*;)')
INODE_OLD = 'flags & ~BTRFS_INODE_FLAG_MASK'
INODE_NEW = 'flags & ~(BTRFS_INODE_FLAG_MASK | (1U << 30))'

def patch_text(source: str) -> str:
    if '(1ULL << 33)' in source and '(1ULL << 34)' in source:
        root_done = True
    else:
        root_done = False
        if len(ROOT_RE.findall(source)) != 1:
            raise ValueError('Root checker layout mismatch; refuse to patch')
        source = ROOT_RE.sub(r'\g<1>\n\t\t\t(1ULL << 33) | /* Synology observed */\n\t\t\t(1ULL << 34) | /* Synology observed */\n\t\t\t\g<3>', source, count=1)
    if INODE_NEW not in source:
        if source.count(INODE_OLD) != 1:
            raise ValueError('Inode checker layout mismatch; refuse to patch')
        source = source.replace(INODE_OLD, INODE_NEW, 1)
    elif source.count(INODE_NEW) != 1:
        raise ValueError('Inode checker appears multiply patched')
    return source

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    p.add_argument('file',type=Path)
    a=p.parse_args()
    if a.file.name != 'tree-checker.c' or a.file.parent.name != 'kernel-shared':
        p.error('Only kernel-shared/tree-checker.c')
    s=a.file.read_text()
    out=patch_text(s)
    a.file.write_text(out) if out!=s else None
    print('Compatible checker masks installed (root bits 33/34, inode bit 30); no devices touched')
