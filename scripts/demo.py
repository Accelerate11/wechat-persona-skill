"""Generate a fictional, isolated demonstration. No network or real app access."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/wechat-persona/scripts'))
from build import save, prepare, style_stats, make_examples, render_persona
from episodes import generate
from import_jsonl import import_rows
from configuration import configure_console


def generate_demo(directory):
    directory = Path(directory).resolve()
    project = directory / 'project.json'
    if project.exists():
        if json.loads(project.read_text('utf-8')).get('synthetic_demo') is not True:
            raise RuntimeError('演示目录已有非演示项目，拒绝覆盖')
    elif directory.exists() and any(directory.iterdir()):
        raise RuntimeError('演示目录不为空，拒绝覆盖')
    directory.mkdir(parents=True, exist_ok=True)
    config = {'name': '舟舟（虚构演示）', 'persona_id': 'demo', 'target_remark': '林舟（虚构）',
        'target_username': 'wxid_demo_target', 'source_account': 'wxid_demo_owner', 'source_root': '',
        'owner_qq': 'demo-owner', 'bot_qq': 'demo-bot', 'include_group_target_messages': False,
        'external_analysis_authorized': False, 'api_base': 'https://api.deepseek.com',
        'model': 'deepseek-flash', 'use_dsh_credentials': False, 'synthetic_demo': True}
    save(project, config)
    topics = [
        ('手冲Coffee怎么开始练？', '我喜欢手冲Coffee', '先把水温稳定下来'),
        ('盆栽最近没精神', '我养过薄荷盆栽', '先看看盆土干不干'),
        ('这周末准备做什么？', '我计划周末给薄荷换盆', '还没动手呢'),
        ('新配方试起来怎么样？', '今天试过Coffee的低温配方', '比昨天柔和一些'),
    ]
    records = []
    for session in range(24):
        for turn, text in enumerate(topics[session % len(topics)]):
            records.append({'id': f'demo-{session}-{turn}', 'conversation': config['target_username'],
                'sender': config['source_account'] if turn == 0 else config['target_username'],
                'timestamp': 1700000000 + session * 86400 + turn * 20, 'type': 1, 'text': text})
    source = directory / 'synthetic-messages.jsonl'
    source.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in records) + '\n', 'utf-8')
    report = import_rows(project, source)
    normalized = [json.loads(line) for line in (directory / 'data/messages.jsonl').read_text('utf-8').splitlines()]
    evidence, training, holdout = prepare(normalized)
    save(directory / 'data/evidence.json', evidence)
    save(directory / 'data/holdout.json', holdout)
    selected = next(r for r in training if r['is_target'] and '喜欢手冲' in r['text'])
    rule = {'condition': '讨论日常爱好', 'behavior': '先用短句表达偏好，再给一个具体建议',
            'scope': 'private', 'evidence_ids': [selected['id']], 'confidence': 'synthetic_demo'}
    profile = {'id': 'demo', 'display_name': config['name'], 'owner_qq': config['owner_qq'], 'bot_qq': config['bot_qq'],
        'source_identity': report['identity'], 'source_cutoff': datetime.fromtimestamp(report['last_timestamp'], timezone.utc).isoformat(),
        'summary': '这是一个喜欢手冲咖啡与盆栽的虚构角色，仅用于演示证据索引和检索。',
        'rules': [rule], 'unknowns': ['所有内容均为人工构造，不对应真实人物'],
        'style_stats': style_stats(training), 'synthetic_demo': True, 'evidence_audited': False}
    memories = [{'id': 'demo-coffee', 'text': '虚构角色曾明确说喜欢手冲Coffee。', 'kind': 'preference',
        'subject': 'target', 'evidence_ids': [selected['id']], 'visibility': 'owner_private',
        'observed_at': selected['timestamp'], 'source': 'synthetic_demo', 'confidence': 'synthetic_demo'}]
    output = directory / 'output'
    save(output / 'profile.json', profile)
    save(output / 'memories.json', memories)
    save(output / 'examples.json', make_examples(training, 12))
    save(output / 'build-report.json', {'mode': 'synthetic_demo_no_network', 'memory_count': len(memories),
        'text_training_rows': len(training), 'text_holdout_rows': len(holdout), 'api_requests': 0})
    (output / 'persona.md').write_text(render_persona(profile), 'utf-8')
    generate(directory)
    return project


if __name__ == '__main__':
    configure_console()
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, default=ROOT / '.demo')
    args = parser.parse_args()
    path = generate_demo(args.directory)
    print(json.dumps({'demo_project': str(path), 'network_requests': 0, 'real_chat_data': False}, ensure_ascii=False))
