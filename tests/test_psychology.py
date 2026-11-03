import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'skills/wechat-persona/scripts'))
from demo import generate_demo
from psychology import compile_model
from chat import adapter, reply


class PsychologyTests(unittest.TestCase):
    def test_holdout_and_other_speakers_cannot_support_personality(self):
        evidence = {
            'a': {'id': 'a', 'text': '好呀', 'timestamp': 1, 'session_id': 's1', 'is_target': True, 'partition': 'training', 'scope': 'private'},
            'b': {'id': 'b', 'text': '哈哈', 'timestamp': 2, 'session_id': 's2', 'is_target': True, 'partition': 'holdout', 'scope': 'private'},
            'c': {'id': 'c', 'text': '我喜欢Coffee', 'timestamp': 3, 'session_id': 's1', 'is_owner': True, 'partition': 'training', 'scope': 'private'},
        }
        profile = {'id': 'fixture', 'rules': [
            {'condition': '被邀请', 'behavior': '简短回应', 'confidence': 'high', 'evidence_ids': ['a'], 'scope': 'private'},
            {'condition': '玩笑', 'behavior': '会笑', 'evidence_ids': ['b'], 'scope': 'private'},
            {'condition': '聊爱好', 'behavior': '喜欢Coffee', 'evidence_ids': ['c'], 'scope': 'private'},
        ]}
        result = compile_model(profile, [{'id': 'wrong', 'text': '目标喜欢Coffee', 'subject': 'target', 'evidence_ids': ['c']}], evidence)
        self.assertEqual(len(result['conditional_rules']), 1)
        self.assertEqual(result['conditional_rules'][0]['confidence'], 'low')
        self.assertFalse(result['conditional_rules'][0]['counterevidence_reviewed'])
        self.assertEqual(result['autobiographical_timeline'], [])
        self.assertEqual(result['training_target_messages'], 1)
        self.assertFalse(result['holdout_used'])

    def test_offline_followup_uses_history_and_does_not_create_a_journal(self):
        with tempfile.TemporaryDirectory(prefix='persona-behavior-') as folder:
            project = generate_demo(Path(folder) / 'demo')
            result = reply(project, '那后来呢', [{'role': 'user', 'content': 'Coffee温控'}], offline=True)
            self.assertIn('demo-coffee', result['memory_ids'])
            self.assertFalse((project.parent / 'data/conversation-memory').exists())

    def test_new_conversation_survives_new_adapter_process_and_retains_speakers(self):
        with tempfile.TemporaryDirectory(prefix='persona-context-') as folder:
            project = generate_demo(Path(folder) / 'demo')
            messages = []
            for i in range(80):
                messages.extend([{'id': f'user-{i}', 'role': 'user', 'text': '我的Coffee水温约定是八十八度' if i == 10 else f'在讨论盆栽第{i}次'},
                                 {'id': f'assistant-{i}', 'role': 'assistant', 'text': '好的'}])
            adapter(project, {'action': 'record', 'messages': messages})
            response = adapter(project, {'query': 'Coffee水温约定'})
            self.assertIn('八十八度', response['text'])
            self.assertTrue(response['conversation_ids'])
            self.assertLessEqual(sum(len(m['content']) for m in response['history']), 12000)
            denied = adapter(project, {'query': 'Coffee', 'chat': {'kind': 'group', 'userId': 'demo-owner'}})
            self.assertEqual(denied['text'], '')
            self.assertEqual(denied['system'], '')

    def test_pasted_document_does_not_hide_an_adjacent_memory_after_restart(self):
        with tempfile.TemporaryDirectory(prefix='persona-paste-') as folder:
            project = generate_demo(Path(folder) / 'demo')
            messages = [{'id': 'paste', 'role': 'user', 'text': '无关资料' * 4000},
                        {'id': 'fact', 'role': 'user', 'text': 'Coffee温控约定用八十八度'},
                        {'id': 'ack', 'role': 'assistant', 'text': '行'}]
            messages += [{'id': f'filler-{i}', 'role': 'user', 'text': f'盆栽浇水第{i}次'} for i in range(140)]
            adapter(project, {'action': 'record', 'messages': messages})
            response = adapter(project, {'query': 'Coffee温控约定'})
            self.assertIn('八十八度', response['text'])
            self.assertTrue(response['conversation_ids'])


if __name__ == '__main__':
    unittest.main()
