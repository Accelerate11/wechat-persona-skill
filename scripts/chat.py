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
from configuration import load_project, configure_console
from secret_store import deepseek_key


def adapter(project, request):
    request = {'bundle': str(project.parent / 'output'),
               'runtime_dir': str(project.parent / 'data/conversation-memory'), **request}
    proc = subprocess.run(['node', str(ROOT / 'scripts/context.mjs')], input=json.dumps(request),
                          capture_output=True, text=True, encoding='utf-8', check=True)
    return json.loads(proc.stdout)


def retrieve(project, text, history=None):
    return adapter(project, {'query': text, 'history': history or []})


def reply(project, text, history, offline=False):
    cfg = load_project(project, cloud=not offline)
    context = retrieve(project, text, history)
    if offline:
        return {'mode': 'retrieval_only_no_network', 'context': context['text'],
                'memory_ids': [m['id'] for m in context['memories']],
                'episode_ids': [m['id'] for m in context['episodes']],
                'conversation_ids': context.get('conversation_ids', [])}
    payload = {'model': cfg['model'], 'thinking': {'type': 'disabled'}, 'max_tokens': 900,
        'messages': [{'role': 'system', 'content': context['system'] + '\n当前时间：' + datetime.now().astimezone().isoformat(timespec='minutes')}]
                    + context['history'] + [{'role': 'user', 'content': context['text'] + '\n\n【本轮消息】\n' + text}]}
    request = urllib.request.Request(cfg['api_base'].rstrip('/') + '/chat/completions',
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={'Authorization': 'Bearer ' + deepseek_key(cfg), 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = json.load(response)
    message = data['choices'][0]['message']['content']
    adapter(project, {'action': 'record', 'messages': [{'role': 'user', 'text': text}, {'role': 'assistant', 'text': message}]})
    return {'reply': message,
        'memory_ids': [m['id'] for m in context['memories']],
        'episode_ids': [m['id'] for m in context['episodes']],
        'conversation_ids': context.get('conversation_ids', []), 'usage': data.get('usage', {})}


if __name__ == '__main__':
    configure_console()
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
