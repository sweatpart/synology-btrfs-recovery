#!/usr/bin/env python3
"""Experimental read-only Synology Btrfs extraction orchestrator.

Source is never mounted/modified. Target is a SEPARATE user-configured disk.
No claims of complete restoration or cryptographic verification against source.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import uuid
import csv

HERE = Path(__file__).resolve().parent
class SafetyError(Exception): pass

def command(args, *, check=True):
    p = subprocess.run(args, capture_output=True, text=True)
    if check and p.returncode: raise SafetyError(f'{args[0]} exited {p.returncode}: {p.stderr.strip()}')
    return p.stdout.strip()

def rootcmd(args):
    return args if os.geteuid()==0 else ['sudo','--',*args]

def real_block(p):
    p=Path(p)
    if not p.exists() or not stat.S_ISBLK(p.stat().st_mode): raise SafetyError(f'Not a block device: {p}')
    return p.resolve()

def serial(p): return command(['lsblk','-dn','-o','SERIAL',str(p)]).strip()

def load_config(file):
    c=json.loads(Path(file).read_text())
    mandatory=('source_disk','source_serial','source_member','raid','volume','backup_device','backup_disk','backup_serial','backup_mount')
    for x in mandatory:
        if not isinstance(c.get(x),str) or not c[x] or 'REPLACE_' in c[x] or '/sdX' in c[x] or '/sdY' in c[x]:
            raise SafetyError(f'Set real value for config field: {x}')
    c['min_free_gib']=int(c.get('min_free_gib',100))
    if c['min_free_gib']<10: raise SafetyError('min_free_gib must be at least 10')
    return c

def has_mount(dev):
    # Check by device major/minor via lsblk: avoids mountinfo alias mistakes.
    return bool(command(['lsblk','-nr','-o','MOUNTPOINTS',str(dev)]).strip())

def doctor(c):
    src=real_block(c['source_disk']); member=real_block(c['source_member']); md=real_block(c['raid']); lv=real_block(c['volume'])
    backup_disk=real_block(c['backup_disk']); target=real_block(c['backup_device'])
    if src==backup_disk: raise SafetyError('Source and backup disks are identical')
    if src == target or backup_disk == member: raise SafetyError('Source / destination block device collision')
    if serial(src)!=c['source_serial'] or serial(backup_disk)!=c['backup_serial']:
        raise SafetyError('Disk serial mismatch: STOP; device names may have changed')
    pk=command(['lsblk','-dn','-o','PKNAME',str(member)]).strip()
    if pk != src.name:
        raise SafetyError('source_member does not belong to source_disk')
    target_parent=command(['lsblk','-dn','-o','PKNAME',str(target)]).strip()
    if target_parent != backup_disk.name:
        raise SafetyError('backup_device does not belong to backup_disk')
    # A second source member would make this a different safety situation.
    slaves=list((Path('/sys/block')/md.name/'slaves').iterdir())
    if len(slaves)!=1 or slaves[0].name!=member.name:
        raise SafetyError('Expected exactly one, explicitly chosen, degraded RAID member')
    if not Path(f'/sys/block/{md.name}/slaves/{member.name}').exists():
        raise SafetyError('RAID does not have expected member; STOP')
    if not Path(f'/sys/block/{lv.name}/slaves/{md.name}').exists():
        raise SafetyError('LVM does not depend on expected RAID; STOP')
    if command(rootcmd(['blockdev','--getro',str(src)]))!='1':
        raise SafetyError('Source physical disk must be block read-only (1)')
    if command(rootcmd(['blockdev','--getro',str(md)]))!='1' or command(rootcmd(['blockdev','--getro',str(lv)]))!='1':
        raise SafetyError('RAID and LV must BOTH be block read-only (1)')
    mdstat=Path('/proc/mdstat').read_text()
    match=re.search(r'^'+re.escape(md.name)+r'\s*:\s*(.*)$',mdstat,re.M)
    if not match or 'read-only' not in match.group(1):
        raise SafetyError('RAID is not explicitly active (read-only)')
    if any(x in Path('/proc/mdstat').read_text() for x in ('resync =','recovery =','reshape =')):
        raise SafetyError('An md array is syncing; stop')
    if has_mount(lv) or has_mount(md) or has_mount(member) or has_mount(src):
        raise SafetyError('Original RAID / volume is mounted; STOP')
    m=Path(c['backup_mount'])
    if not m.is_dir() or m.is_symlink(): raise SafetyError('Backup directory missing or symlink')
    info=command(['findmnt','--mountpoint',str(m),'-n','-o','SOURCE,FSTYPE,OPTIONS']).split(maxsplit=2)
    if len(info)!=3 or not info[0].startswith('/dev/') or real_block(info[0])!=target:
        raise SafetyError('Backup mount does not match backup_device')
    if info[1]!='ext4' or 'rw' not in info[2].split(','):
        raise SafetyError('Backup filesystem must be ext4,rw')
    free=shutil.disk_usage(m).free
    if free<c['min_free_gib']*1024**3: raise SafetyError(f'Low backup free space: {free/1024**3:.1f} GiB')
    return f'PASS source={src} serial={serial(src)} raid={md} ro=1 volume={lv} ro=1 target={target} ext4,rw free={free/1024**3:.1f} GiB'

def regex_for(folder):
    if folder is None: return None
    if not folder or folder.startswith('/') or folder.endswith('/'):
        raise SafetyError('Use relative directory without leading/trailing slash')
    parts=folder.split('/')
    if any(p in ('','.','..') or '\n' in p or '\x00' in p for p in parts):
        raise SafetyError('Unsafe path')
    esc=[re.escape(p) for p in parts]
    out='^/(|'
    for i,p in enumerate(esc): out+=('' if i==0 else '/')+p+'(|'
    return out+'/.*'+')'*len(parts)+')$'

def executable():
    p=HERE/'upstream-btrfs-progs'/'btrfs'
    if not p.is_file() or not os.access(p,os.X_OK): raise SafetyError('Run ./build.sh first')
    return str(p)

def log_cmd(args, log):
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('w') as f:
        os.chmod(log,0o600)
        f.write(f'Start: {datetime.now(timezone.utc).isoformat()}\nCommand: {json.dumps(args,ensure_ascii=False)}\n'); f.flush()
        rc=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT).returncode
        f.write(f'\nEXIT_CODE={rc}\n')
    return rc

def scan(target, output, do_hash):
    target=Path(target)
    if not target.is_dir() or target.is_symlink(): raise SafetyError('Audit target must be real directory')
    total=empty=bytes_total=hash_errors=read_errors=symlinks=0
    zero_ext=Counter(); media_zero=[]
    media_ext={'.jpg','.jpeg','.heic','.heif','.png','.mov','.mp4','.m4v','.avi','.cr2','.nef','.arw','.dng'}
    with Path(output).open('w',encoding='utf8') as stream:
        for dirpath, dirs, files in os.walk(target,followlinks=False):
            symlinks += sum((Path(dirpath)/d).is_symlink() for d in dirs)
            dirs[:]=[d for d in dirs if not (Path(dirpath)/d).is_symlink()]
            for name in files:
                p=Path(dirpath)/name
                try:
                    st=p.lstat()
                    if stat.S_ISLNK(st.st_mode):
                        symlinks+=1
                        continue
                    if not stat.S_ISREG(st.st_mode): continue
                    rel=str(p.relative_to(target)); total+=1; bytes_total+=st.st_size
                    entry={'path':rel,'size':st.st_size,'mtime_ns':st.st_mtime_ns}
                    if st.st_size==0:
                        empty+=1; zero_ext[p.suffix.lower() or '<none>']+=1
                        if p.suffix.lower() in media_ext and len(media_zero)<100: media_zero.append(rel)
                    if do_hash:
                        try:
                            h=hashlib.sha256()
                            with p.open('rb') as src:
                                for chunk in iter(lambda:src.read(4*1024*1024),b''): h.update(chunk)
                            entry['sha256']=h.hexdigest()
                        except OSError as exc:
                            hash_errors+=1; entry['hash_error']=str(exc)
                    stream.write(json.dumps(entry,ensure_ascii=False)+'\n')
                except OSError as exc:
                    read_errors+=1
                    stream.write(json.dumps({'path':str(p),'error':str(exc)},ensure_ascii=False)+'\n')
    summary={'files':total,'bytes':bytes_total,'zero_files':empty,'zero_by_extension':dict(zero_ext.most_common()),'examples_zero_media':media_zero,'hash_errors':hash_errors,'read_errors':read_errors,'skipped_symlinks':symlinks,'manifest':str(output),'source_comparison':False}
    return summary

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='config.json')
    subs=p.add_subparsers(dest='cmd',required=True)
    subs.add_parser('doctor'); subs.add_parser('roots')
    x=subs.add_parser('extract'); x.add_argument('--root-id',type=int,required=True); x.add_argument('--dir',dest='folder'); x.add_argument('--yes',action='store_true')
    a=subs.add_parser('audit'); a.add_argument('--input',required=True); a.add_argument('--sha256',action='store_true'); a.add_argument('--output-dir',default='.')
    a=subs.add_parser('regex'); a.add_argument('--dir',required=True)
    args=p.parse_args()
    try:
        if args.cmd=='regex': print(regex_for(args.dir)); return 0
        if args.cmd=='audit':
            if Path(args.input).is_symlink(): raise SafetyError('Audit source may not be symlink')
            root=Path(args.input).resolve()
            output_dir=Path(args.output_dir).resolve()
            if not output_dir.is_dir(): raise SafetyError('Audit output directory does not exist')
            if output_dir == root or root in output_dir.parents:
                raise SafetyError('Audit output cannot be inside recovered batch')
            out=output_dir/f'audit-{datetime.now().strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}.jsonl'
            with out.open('x'):
                pass
            result=scan(root,out,args.sha256)
            (out.with_suffix('.summary.json')).write_text(json.dumps(result,indent=2,ensure_ascii=False))
            print(json.dumps(result,indent=2,ensure_ascii=False))
            return 3 if result['read_errors'] or result['hash_errors'] else 0
        c=load_config(args.config)
        print(doctor(c),flush=True)
        bin=executable(); stamp=datetime.now().strftime('%Y%m%d-%H%M%S'); logs=HERE/'logs'
        if args.cmd=='roots':
            rc=log_cmd(rootcmd([bin,'restore','-l',c['volume']]),logs/f'roots-{stamp}.log')
            print(f'roots log: {logs}/roots-{stamp}.log rc={rc}'); return rc
        if not args.yes: raise SafetyError('Extraction requires --yes; source is still guarded read-only')
        if not (5<=args.root_id<2**63): raise SafetyError('Invalid root ID')
        rx=regex_for(args.folder)
        # Re-check the source after paths are resolved and before creating an export directory.
        print(doctor(c),flush=True)
        path=Path(c['backup_mount'])/'Synology_Recovery'
        if path.is_symlink(): raise SafetyError('Output root is a symlink')
        path.mkdir(exist_ok=True)
        label=re.sub('[^a-zA-Z0-9_-]','_',args.folder or 'ALL')[:48]
        dest=path/f'root{args.root_id}_{label}_{stamp}_{uuid.uuid4().hex[:8]}'
        dest.mkdir(mode=0o700)
        cmd=[bin,'restore','-r',str(args.root_id)]
        if rx: cmd+=['--path-regex',rx]
        cmd+=[c['volume'],str(dest)]
        logfile=logs/f'extract-{stamp}-{uuid.uuid4().hex[:6]}.log'
        print(f'OUTPUT={dest}\nLOG={logfile}',flush=True)
        rc=log_cmd(rootcmd(cmd),logfile)
        (dest/'_RECOVERY_RUN.json').write_text(json.dumps({'root_id':args.root_id,'folder':args.folder,'exit_code':rc,'log':str(logfile),'note':'EXIT_CODE=0 does not prove full recovery; audit required'},indent=2,ensure_ascii=False))
        print(f'Exit code={rc}. Audit output; no source file hash comparison performed.')
        return rc
    except (SafetyError,OSError,ValueError) as exc:
        print(f'STOP: {exc}',file=sys.stderr); return 2

if __name__=='__main__': sys.exit(main())
