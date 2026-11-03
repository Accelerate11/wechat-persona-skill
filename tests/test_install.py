import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def test_plan_does_not_write_and_apply_swaps_a_complete_bundle(self):
        with tempfile.TemporaryDirectory(prefix='wechat-persona-test-') as folder:
            root = Path(folder).resolve()
            self.assertEqual(root.parent, Path(tempfile.gettempdir()).resolve())
            home, base = root / 'dsh-home', root / 'aurabot-data'
            plugin = home / 'profiles/desktop/node_modules/dsh-aurabot-qq'
            (plugin / 'src/core').mkdir(parents=True)
            (plugin / 'src/modules/memory').mkdir(parents=True)
            (plugin / 'package.json').write_text('{"type":"module"}', 'utf-8')
            (plugin / 'src/core/config.js').write_text(
                'export const DEFAULTS={snowluma:{},memory:{},bridge:{},profilePerms:{},modules:{}};'
                'export function normalize(x){return x}', 'utf-8')
            workspace = root / 'project'
            output = workspace / 'output'
            output.mkdir(parents=True)
            cfg = {'name': '测试角色', 'persona_id': 'fixture', 'target_username': 'wxid_demo_target',
                'owner_qq': '8' * 6, 'bot_qq': '9' * 6, 'model': 'fixture'}
            profile = {'id': 'fixture', 'display_name': cfg['name'], 'source_identity': {'username': cfg['target_username']},
                'owner_qq': cfg['owner_qq'], 'bot_qq': cfg['bot_qq'], 'evidence_audited': True}
            project = workspace / 'project.json'
            project.write_text(json.dumps(cfg), 'utf-8')
            (output / 'profile.json').write_text(json.dumps(profile), 'utf-8')
            for name in ('memories.json', 'examples.json', 'episodes.json'):
                (output / name).write_text('[]', 'utf-8')
            (output / 'persona.md').write_text('你是测试模拟角色。', 'utf-8')
            env = {**os.environ, 'DSH_HOME': str(home), 'AURABOT_DATA_DIR': str(base)}
            command = ['node', str(ROOT / 'scripts/install-aurabot.mjs'), '--project', str(project)]
            def run(extra=()):
                return json.loads(subprocess.check_output(command + list(extra), env=env, text=True, encoding='utf-8'))
            self.assertFalse(run()['plan']['apply'])
            self.assertFalse(base.exists())
            result = run(['--apply'])
            self.assertTrue(result['installed'])
            config = json.loads((base / 'config.json').read_text('utf-8'))
            self.assertFalse(config['enabled'])
            self.assertTrue(config['dryRun'])
            self.assertEqual(config['ownerLevel'], 'chat')
            self.assertTrue((base / 'modules/wechat-persona/index.mjs').exists())
            for name in ('profile.json', 'memories.json', 'episodes.json', 'examples.json', 'persona.md'):
                self.assertTrue((base / 'modules/wechat-persona' / name).exists())
            run(['--apply'])
            backups = list((base / 'module-backups').iterdir())
            self.assertEqual(len(backups), 1)
            self.assertTrue((backups[0] / 'profile.json').exists())
            self.assertTrue(list((workspace / 'data').glob('aurabot-config-backup-*.json')))


if __name__ == '__main__':
    unittest.main()
