"""Searchable original utterances, supplementing summaries without inventing facts."""
import json
from collections import defaultdict
from pathlib import Path
from build import save


def generate(root):
    evidence = json.loads((root / 'data/evidence.json').read_text('utf-8'))
    sessions = defaultdict(list)
    for row in evidence.values():
        if row['partition'] == 'training' and row['type'] == 1 and row['sender']:
            sessions[row['session_id']].append(row)
    episodes = []
    for session in sessions.values():
        for i, row in enumerate(session):
            if not row['is_target'] or len(row['text'].strip()) < 6:
                continue
            context = session[max(0, i - 1):i + 2] if row['scope'] == 'private' else [row]
            episodes.append({'id': 'episode-' + row['id'], 'text': row['text'], 'timestamp': row['timestamp'],
                'scope': row['scope'], 'visibility': 'owner_private',
                'context': [{'speaker': 'target' if r['is_target'] else 'owner', 'text': r['text'][:600]} for r in context],
                'evidence_ids': [r['id'] for r in context]})
    save(root / 'output/episodes.json', episodes)
    report_path = root / 'output/build-report.json'
    report = json.loads(report_path.read_text('utf-8'))
    report['searchable_source_episodes'] = len(episodes)
    save(report_path, report)
    print(json.dumps({'source_episodes': len(episodes)}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    generate(args.project.resolve().parent)
