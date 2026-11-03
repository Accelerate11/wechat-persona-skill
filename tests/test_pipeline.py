import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'skills/wechat-persona/scripts'))
from build import render_persona
from configuration import load_project
from demo import generate_demo
from chat import reply
from check_public import scan_files, scan_index
from import_jsonl import import_rows
from secret_store import deepseek_key


class PipelineTests(unittest.TestCase):
    def test_demo_is_isolated_and_works_without_network(self):
        with tempfile.TemporaryDirectory(prefix='wechat-persona-test-') as folder:
            self.assertEqual(Path(folder).resolve().parent, Path(tempfile.gettempdir()).resolve())
            with patch('urllib.request.urlopen', side_effect=AssertionError('demo attempted networking')):
                project = generate_demo(Path(folder) / 'demo')
                result = reply(project, 'Coffee', [], offline=True)
            self.assertEqual(result['mode'], 'retrieval_only_no_network')
            self.assertIn('demo-coffee', result['memory_ids'])
            self.assertTrue(result['episode_ids'])
            self.assertFalse(load_project(project)['external_analysis_authorized'])
            with self.assertRaises(RuntimeError):
                load_project(project, cloud=True)
            evidence = json.loads((project.parent / 'data/evidence.json').read_text('utf-8'))
            episodes = json.loads((project.parent / 'output/episodes.json').read_text('utf-8'))
            self.assertTrue(any(r['partition'] == 'holdout' for r in evidence.values()))
            for episode in episodes:
                self.assertTrue(all(evidence[e]['partition'] == 'training' for e in episode['evidence_ids']))

    def test_demo_refuses_to_replace_a_real_project(self):
        with tempfile.TemporaryDirectory(prefix='wechat-persona-test-') as folder:
            path = Path(folder)
            existing = path / 'project.json'
            existing.write_text('{"synthetic_demo": false}', 'utf-8')
            with self.assertRaises(RuntimeError):
                generate_demo(path)
            self.assertEqual(json.loads(existing.read_text('utf-8')), {'synthetic_demo': False})

    def test_import_recomputes_sender_and_filters_group_rows(self):
        with tempfile.TemporaryDirectory(prefix='wechat-persona-test-') as folder:
            root = Path(folder)
            config = {'name': '虚构角色', 'persona_id': 'fixture', 'target_remark': '虚构原型',
                      'source_account': 'wxid_demo_owner', 'target_username': 'wxid_demo_target',
                      'include_group_target_messages': True}
            project = root / 'project.json'
            project.write_text(json.dumps(config), 'utf-8')
            records = [
                {'id': '1', 'conversation': 'wxid_demo_target', 'sender': 'wxid_demo_target',
                 'timestamp': 1700000000, 'text': '喜欢盆栽', 'is_target': False},
                {'id': '2', 'conversation': 'group@chatroom', 'sender': 'wxid_demo_other',
                 'timestamp': 1700000001, 'text': '不是目标发言', 'is_target': True},
                {'id': '3', 'conversation': 'group@chatroom', 'sender': 'wxid_demo_target',
                 'timestamp': 1700000002, 'text': '目标群发言', 'is_target': False},
            ]
            source = root / 'input.jsonl'
            source.write_text('\n'.join(json.dumps(r) for r in records), 'utf-8')
            report = import_rows(project, source)
            result = [json.loads(s) for s in (root / 'data/messages.jsonl').read_text('utf-8').splitlines()]
            self.assertEqual(report['skipped_rows'], 1)
            self.assertEqual([r['id'] for r in result], ['1', '3'])
            self.assertTrue(all(r['is_target'] for r in result))

    def test_names_are_configurable_without_rewriting_prompts(self):
        with tempfile.TemporaryDirectory(prefix='wechat-persona-test-') as folder:
            project = generate_demo(Path(folder) / 'demo')
            profile = json.loads((project.parent / 'output/profile.json').read_text('utf-8'))
            second = copy.deepcopy(profile)
            second['display_name'] = '纸舟（虚构）'
            second['source_identity']['remark'] = '另一个虚构原型'
            text = render_persona(second)
            self.assertIn('你叫纸舟（虚构）', text)
            self.assertIn('不是另一个虚构原型本人', text)
            self.assertNotIn(profile['display_name'], text)

    def test_dsh_credential_reuse_is_not_implicit(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch('secret_store.Path.exists', side_effect=AssertionError('unexpected credential lookup')):
                with self.assertRaises(RuntimeError):
                    deepseek_key({'use_dsh_credentials': False})

    def test_public_check_reports_position_without_echoing_a_secret(self):
        with tempfile.TemporaryDirectory(prefix='wechat-persona-test-') as folder:
            root = Path(folder)
            token = 'sk' + '-' + 'x' * 32
            (root / 'leak.txt').write_text(token, 'utf-8')
            (root / 'project.json').write_text('{}', 'utf-8')
            findings = scan_files(root, ['leak.txt', 'project.json'])
            self.assertTrue(any(f['rule'] == 'api-key-shaped token' for f in findings))
            self.assertTrue(any(f['rule'] == 'private runtime artifact' for f in findings))
            self.assertNotIn(token, repr(findings))

    def test_public_check_reads_staged_bytes_not_unstaged_replacements(self):
        with tempfile.TemporaryDirectory(prefix='wechat-persona-test-') as folder:
            root = Path(folder)
            subprocess.run(['git', 'init', '--quiet', str(root)], check=True, capture_output=True)
            file = root / 'fixture.txt'
            file.write_text('sk' + '-' + 'x' * 32, 'utf-8')
            subprocess.run(['git', '-C', str(root), 'add', 'fixture.txt'], check=True, capture_output=True)
            file.write_text('safe unstaged working copy', 'utf-8')
            names, findings = scan_index(root)
            self.assertEqual(names, ['fixture.txt'])
            self.assertTrue(any(f['rule'] == 'api-key-shaped token' for f in findings))


if __name__ == '__main__':
    unittest.main()
