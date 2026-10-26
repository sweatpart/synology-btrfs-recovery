import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from patch_upstream import patch_text
from synology_ro import regex_for, SafetyError, scan, load_config
import re, json

class TestPaths(unittest.TestCase):
    def test_nested(self):
        r=re.compile(regex_for('myuser/Photos/MobileBackup'))
        for p in ['/','/myuser','/myuser/Photos','/myuser/Photos/MobileBackup','/myuser/Photos/MobileBackup/x.jpg']:
            self.assertTrue(r.fullmatch(p),p)
        self.assertFalse(r.fullmatch('/myuser/Photos/Moments/x'))
    def test_invalid(self):
        for p in ('','/x','x/','x/../z','x//z'):
            with self.assertRaises(SafetyError):regex_for(p)

class TestPatching(unittest.TestCase):
    def test_pinned_layout_idempotent(self):
        s='const u64 valid_root_flags = BTRFS_ROOT_SUBVOL_RDONLY |\n BTRFS_ROOT_SUBVOL_DEAD;\n if (flags & ~BTRFS_INODE_FLAG_MASK) return 1;'
        out=patch_text(s)
        self.assertIn('(1ULL << 34)',out)
        self.assertIn('(1U << 30)',out)
        self.assertEqual(patch_text(out),out)
    def test_fail_closed(self):
        with self.assertRaises(ValueError): patch_text('unexpected upstream text')

class TestAudit(unittest.TestCase):
    def test_audit_detects_zero_media_and_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d); (p/'photos').mkdir(); (p/'photos'/'a.jpg').touch(); (p/'photos'/'b.jpg').write_bytes(b'abc')
            out=p/'audit.jsonl'; r=scan(p/'photos',out,True)
            self.assertEqual((r['files'],r['zero_files'],r['zero_by_extension']['.jpg']),(2,1,1))
            self.assertEqual(len([json.loads(x) for x in out.read_text().splitlines()]),2)
            self.assertFalse(r['source_comparison'])

if __name__=='__main__':unittest.main()

class TestExtraSafety(unittest.TestCase):
    def test_zero_media_and_symlink_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp); src=p/'source'; src.mkdir()
            (src/'zero.mp4').touch()
            (src/'real.txt').write_text('content')
            (src/'external').symlink_to('/etc/passwd')
            (src/'dirlink').symlink_to('/etc', target_is_directory=True)
            out=p/'results.jsonl'
            r=scan(src,out,False)
            self.assertEqual(r['files'],2)
            self.assertEqual(r['zero_by_extension']['.mp4'],1)
            self.assertEqual(r['skipped_symlinks'],2)
            self.assertIn('zero.mp4',r['examples_zero_media'])
    def test_path_rejects_dot_components(self):
        for x in ('../foo','foo/./x','foo/../bar'):
            with self.assertRaises(SafetyError): regex_for(x)
