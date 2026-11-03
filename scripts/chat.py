"""Preview the same persona adapter used in Aurabot; no QQ messages are sent."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/wechat-persona/scripts'))
from configuration import load_project
from secret_store import deepseek_key


def retrieve(project, text):
    request = {'bundle': str(project.parent / 'output'), 'query': text}
    proc = subprocess.run(['node', str(ROOT / 'scripts/context.mjs')], input=json.dumps(request),
                          capture_output=True, text=True, encoding='utf-8', check=True)
    return json.loads(proc.stdout)


def reply(project, text, history, offline=False):
    cfg = load_project(project, cloud=not offline)
    context = retrieve(project, text)
    if offline:
        return {'mode': 'retrieval_only_no_network', 'context': context['text'],
                'memory_ids': [m['id'] for m in context['memories']],
                'episode_ids': [m['id'] for m in context['episodes']]}
    payload = {'model': cfg['model'], 'thinking': {'type': 'disabled'}, 'max_tokens': 450,
        'messages': [{'role': 'system', 'content': context['system'] + '\n当前时间：' + datetime.now().astimezone().isoformat(timespec='minutes')}]
                    + history[-20:] + [{'role': 'user', 'content': context['text'] + '\n\n【本轮消息】\n' + text}]}
    request = urllib.request.Request(cfg['api_base'].rstrip('/') + '/chat/completions',
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={'Authorization': 'Bearer ' + deepseek_key(cfg), 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = json.load(response)
    return {'reply': data['choices'][0]['message']['content'],
        'memory_ids': [m['id'] for m in context['memories']],
        'episode_ids': [m['id'] for m in context['episodes']], 'usage': data.get('usage', {})}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', type=Path, default=ROOT / 'project.json')
    parser.add_argument('--message')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    project = args.project.resolve()
    if args.message:
        print(json.dumps(reply(project, args.message, [], args.offline), ensure_ascii=False))
    elif args.offline:
        parser.error('--offline requires --message')
    else:
        config = load_project(project, cloud=True)
        print(config['name'] + ' 本地试聊（使用已配置API，不向QQ发送；/退出结束）')
        history = []
        while True:
            try:
                text = input('你：').strip()
                if text in ('/退出', '/quit', '/exit'):
                    break
                if not text:
                    continue
                result = reply(project, text, history)
                print(config['name'] + '：' + result['reply'].replace('|||', '\n'))
                history += [{'role': 'user', 'content': text}, {'role': 'assistant', 'content': result['reply']}]
            except (EOFError, KeyboardInterrupt):
                break
