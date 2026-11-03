"""Import normalized JSONL without opening WeChat or contacting a service."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from configuration import load_project
from build import save


def import_rows(project, input_path):
    project, input_path = Path(project).resolve(), Path(input_path).resolve()
    cfg = load_project(project)
    target, owner = cfg['target_username'], cfg['source_account']
    rows, seen, skipped = [], {}, 0
    with input_path.open(encoding='utf-8-sig') as handle:
        for number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            raw = json.loads(line)
            conversation, sender = raw.get('conversation'), raw.get('sender')
            timestamp, text = raw.get('timestamp'), raw.get('text')
            if not isinstance(conversation, str) or not isinstance(sender, str) or not isinstance(text, str):
                raise ValueError(f'第{number}行缺少conversation、sender或text字符串')
            if not isinstance(timestamp, int) or isinstance(timestamp, bool) or not 0 < timestamp < 4102444800:
                raise ValueError(f'第{number}行timestamp须为有效的Unix秒时间戳')
            kind = int(raw.get('type', 1))
            group = conversation.endswith('@chatroom')
            if group:
                if not cfg.get('include_group_target_messages', False) or sender != target:
                    skipped += 1
                    continue
            elif conversation != target:
                skipped += 1
                continue
            elif sender not in (owner, target) and not (sender == '' and kind == 10000):
                raise ValueError(f'第{number}行的私聊发送者不属于所选双方')
            identity = str(raw.get('id') or f'import:{number}')
            normalized = {'id': identity, 'server_id': str(raw.get('server_id') or ''),
                'conversation': conversation, 'scope': 'group' if group else 'private',
                'sender': sender, 'is_target': sender == target, 'is_owner': sender == owner,
                'timestamp': timestamp, 'sort_seq': int(raw.get('sort_seq') or number),
                'type': kind, 'text': text, 'decode_status': 'text', 'source_shard': 'jsonl',
                'local_id': number, 'sender_resolution': 'mapped' if sender else 'unresolved'}
            signature = (conversation, sender, timestamp, kind, text)
            if identity in seen:
                if seen[identity] != signature:
                    raise ValueError(f'第{number}行重复id对应不同消息')
                skipped += 1
                continue
            seen[identity] = signature
            rows.append(normalized)
    if not any(r['is_target'] and r['scope'] == 'private' and r['type'] == 1 for r in rows):
        raise ValueError('至少需要一条目标人物的私聊文本消息')
    rows.sort(key=lambda r: (r['timestamp'], r['sort_seq'], r['id']))
    data = project.parent / 'data'
    data.mkdir(parents=True, exist_ok=True)
    temporary = data / 'messages.jsonl.tmp'
    with temporary.open('w', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    temporary.replace(data / 'messages.jsonl')
    report = {'identity': {'username': target, 'remark': cfg['target_remark']},
        'counts': dict(Counter(('target_' if r['is_target'] else 'owner_' if r['is_owner'] else 'unknown_') + r['scope'] for r in rows)),
        'message_types': dict(Counter(str(r['type']) for r in rows)), 'decode_status': {'text': len(rows)},
        'unresolved_senders': sum(not r['sender'] for r in rows),
        'first_timestamp': rows[0]['timestamp'], 'last_timestamp': rows[-1]['timestamp'],
        'group_conversations': len({r['conversation'] for r in rows if r['scope'] == 'group'}),
        'snapshots': [], 'source_format': 'normalized_jsonl',
        'source_sha256': hashlib.sha256(input_path.read_bytes()).hexdigest(),
        'skipped_rows': skipped, 'keys_saved': False, 'plaintext_database_saved': False,
        'exported_at': datetime.now(timezone.utc).isoformat()}
    save(data / 'source-report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    result = import_rows(args.project, args.input)
    print(json.dumps({'imported_counts': result['counts'], 'skipped_rows': result['skipped_rows']}, ensure_ascii=False))

if __name__ == '__main__':
    main()
