"""Compile observable contextual behavior; no psychological scores or network calls."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import statistics

from configuration import configure_console, load_project


def distribution(rows):
    lengths = [len(r['text']) for r in rows]
    if not lengths:
        return {'messages': 0}
    return {'messages': len(rows), 'sessions': len({r['session_id'] for r in rows}),
            'median_characters': statistics.median(lengths),
            'length_bands': {label: sum(low <= n <= high for n in lengths) / len(lengths)
                             for label, low, high in [('1_8', 1, 8), ('9_30', 9, 30), ('31_100', 31, 100), ('101_plus', 101, float('inf'))]},
            'question_marker_fraction': sum(bool(re.search(r'[?？]', r['text'])) for r in rows) / len(rows),
            'laughter_marker_fraction': sum(bool(re.search(r'哈哈|hhh|哈哈哈|\b(?:lol|lmao)\b', r['text'], re.I)) for r in rows) / len(rows)}


def compile_model(profile, memories, evidence):
    training = {key: value for key, value in evidence.items() if value.get('partition') == 'training'}
    target = [r for r in training.values() if r.get('is_target') and r.get('type', 1) == 1]
    by_session = defaultdict(list)
    for row in sorted(training.values(), key=lambda r: (r['timestamp'], r['id'])):
        by_session[row['session_id']].append(row)
    strata = defaultdict(list)
    for session in by_session.values():
        previous = None
        for row in session:
            if row.get('is_target'):
                scope = row.get('scope', 'private')
                strata[scope + ':all'].append(row)
                if previous and previous.get('is_owner'):
                    label = 'after_question_marker' if re.search(r'[?？]', previous['text']) else 'after_other_message'
                    strata[scope + ':' + label].append(row)
            previous = row
    rules = []
    for i, rule in enumerate(profile.get('rules', [])):
        ids = rule.get('evidence_ids', [])
        if not ids or any(e not in training for e in ids):
            continue
        own = [e for e in ids if training[e].get('is_target')]
        if not own:
            continue
        sessions = {training[e]['session_id'] for e in own}
        confidence = rule.get('confidence', 'low')
        if len(sessions) < 2:
            confidence = 'low'
        elif len(sessions) < 3 and confidence == 'high':
            confidence = 'medium'
        counter = [e for e in rule.get('counterevidence_ids', []) if e in training and training[e].get('is_target')]
        rules.append({**rule, 'id': 'behavior-' + str(i), 'confidence': confidence,
                      'supporting_target_messages': len(own), 'supporting_sessions': len(sessions),
                      'generality': 'single_session_observation' if len(sessions) < 2 else 'repeated_conditional_pattern',
                      'counterevidence_ids': counter,
                      'counterevidence_reviewed': bool(rule.get('counterevidence_reviewed', False))})
    narrative = []
    for item in memories:
        ids = item.get('evidence_ids', [])
        if item.get('subject') != 'target' or not ids or any(e not in training for e in ids):
            continue
        if not any(training[e].get('is_target') for e in ids):
            continue
        narrative.append({key: item.get(key) for key in ('id', 'text', 'kind', 'observed_at', 'evidence_ids', 'confidence')})
    narrative.sort(key=lambda m: (m.get('observed_at') or 0, m['id']))
    return {'schema_version': 1, 'persona_id': profile['id'],
            'built_at': datetime.now(timezone.utc).isoformat(), 'source': 'audited_training_evidence',
            'training_target_messages': len(target), 'holdout_used': False,
            'interpretation': 'Observable language distributions, not psychometric scores. Unreviewed counterexamples remain unknown.',
            'distributions': {key: distribution(rows) for key, rows in sorted(strata.items())},
            'conditional_rules': rules, 'autobiographical_timeline': narrative,
            'unknowns': profile.get('unknowns', []),
            'references': ['10.1037/0033-295X.102.2.246', '10.1037/0022-3514.80.6.1011',
                           '10.1037/0033-295X.107.2.261', '10.1177/0963721413475622']}


def run(project):
    load_project(project)
    root = project.parent
    profile = json.loads((root / 'output/profile.json').read_text('utf-8'))
    if profile.get('evidence_audited') is not True and not profile.get('synthetic_demo'):
        raise RuntimeError('Compile behavior only after the evidence audit')
    memories = json.loads((root / 'output/memories.json').read_text('utf-8'))
    evidence = json.loads((root / 'data/evidence.json').read_text('utf-8'))
    result = compile_model(profile, memories, evidence)
    # Keep the always-present portrait consistent with the conservative support
    # assessment, rather than only lowering confidence in a retrieval supplement.
    for rule in result['conditional_rules']:
        profile['rules'][int(rule['id'].split('-')[-1])]['confidence'] = rule['confidence']
    from build import render_persona
    (root / 'output/profile.json').write_text(json.dumps(profile, ensure_ascii=False, indent=2), 'utf-8')
    (root / 'output/persona.md').write_text(render_persona(profile), 'utf-8')
    destination = root / 'output/behavior-model.json'
    temporary = destination.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), 'utf-8')
    temporary.replace(destination)
    return {'rules': len(result['conditional_rules']), 'target_messages': result['training_target_messages'],
            'timeline_memories': len(result['autobiographical_timeline']), 'holdout_used': False}


if __name__ == '__main__':
    configure_console()
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.project.resolve()), ensure_ascii=False))
