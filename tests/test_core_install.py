import copy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from install_core import FILES, digest, normalized, plan, apply_upgrade


class CoreInstallationTests(unittest.TestCase):
    def fixture(self, root):
        source, target, backup = root / 'source', root / 'target', root / 'backup'
        manifest = {'plugin_version': '1.1.24', 'files': []}
        for directory in (source, target):
            directory.mkdir()
            (directory / 'package.json').write_text(json.dumps({'name': 'dsh-aurabot-qq', 'version': '1.1.24'}), 'utf-8')
        for i, name in enumerate(FILES):
            original = f'// old file {i}\r\n'.encode()
            changed = f'// new file {i}\n'.encode()
            for directory, data in ((source, changed), (target, original)):
                dest = directory / name; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)
            manifest['files'].append({'path': name, 'before_sha256': digest(normalized(original)), 'after_sha256': digest(changed)})
        return source, target, backup, manifest

    def test_planning_is_read_only_and_rejects_independent_changes_before_backup(self):
        with tempfile.TemporaryDirectory(prefix='persona-core-plan-') as folder:
            source, target, backup, manifest = self.fixture(Path(folder))
            result = plan(source, target, manifest)
            self.assertEqual(len(result['files']), 5)
            self.assertFalse(backup.exists())
            first = (target / FILES[0]).read_bytes()
            (target / FILES[-1]).write_text('// independent change', 'utf-8')
            with self.assertRaises(ValueError):
                apply_upgrade(source, target, manifest, backup)
            self.assertEqual((target / FILES[0]).read_bytes(), first)
            self.assertFalse(backup.exists())

    def test_atomic_install_preserves_shared_hardlink_contents_and_verified_backups(self):
        with tempfile.TemporaryDirectory(prefix='persona-core-link-') as folder:
            root = Path(folder); source, target, backup, manifest = self.fixture(root)
            shared = root / 'shared-package-store.js'
            os.link(target / FILES[1], shared)
            original = shared.read_bytes()
            mode = stat.S_IMODE((target / FILES[1]).stat().st_mode)
            result = apply_upgrade(source, target, manifest, backup)
            self.assertEqual(result['status'], 'installed')
            self.assertEqual(shared.read_bytes(), original)
            self.assertEqual((backup / FILES[1]).read_bytes(), original)
            self.assertEqual(stat.S_IMODE((target / FILES[1]).stat().st_mode), mode)
            for name in FILES:
                self.assertEqual((target / name).read_bytes(), (source / name).read_bytes())

    def test_partial_install_failure_restores_previously_replaced_files(self):
        with tempfile.TemporaryDirectory(prefix='persona-core-rollback-') as folder:
            source, target, backup, manifest = self.fixture(Path(folder))
            (target / FILES[0]).unlink()
            manifest['files'][0]['before_sha256'] = None
            originals = {name: (target / name).read_bytes() if (target / name).exists() else None for name in FILES}
            replace = os.replace; calls = 0
            def fail_once(src, dst):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError('simulated replacement failure')
                return replace(src, dst)
            with patch('install_core.os.replace', side_effect=fail_once):
                with self.assertRaises(OSError):
                    apply_upgrade(source, target, manifest, backup)
            self.assertEqual({name: (target / name).read_bytes() if (target / name).exists() else None for name in FILES}, originals)
            self.assertEqual(json.loads((backup / 'core-upgrade.json').read_text('utf-8'))['status'], 'rolled_back_after_failure')


if __name__ == '__main__':
    unittest.main()
