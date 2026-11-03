"""Local project validation; authorization is an explicit user-owned setting."""
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


def configure_console():
    """CLI output is UTF-8 even under non-Unicode Windows runner locales."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')


def load_project(path, cloud=False, source=False):
    config = json.loads(Path(path).expanduser().resolve().read_text('utf-8'))
    if not isinstance(config, dict):
        raise ValueError('项目配置必须是JSON对象')
    for key in ('name', 'target_remark', 'target_username', 'source_account'):
        value = config.get(key)
        if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
            raise ValueError(f'请填写有效的 {key}')
    if config['target_username'] == config['source_account']:
        raise ValueError('target_username不能与source_account相同')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,31}', config.get('persona_id', 'persona')):
        raise ValueError('persona_id须为1至32个小写字母、数字、连字符或下划线')
    if not isinstance(config.get('include_group_target_messages', False), bool):
        raise ValueError('include_group_target_messages必须是布尔值')
    if source and not config.get('source_root'):
        raise ValueError('请填写source_root，或使用JSONL导入入口')
    if cloud:
        if config.get('external_analysis_authorized') is not True:
            raise RuntimeError('未授权模型服务；请了解发送范围后自行开启external_analysis_authorized。')
        url = urlsplit(config.get('api_base', ''))
        loopback = url.hostname in ('localhost', '127.0.0.1', '::1')
        if (url.scheme != 'https' and not (url.scheme == 'http' and loopback)) or not url.hostname:
            raise ValueError('api_base必须使用HTTPS，或本机回环HTTP服务')
        if url.username or url.password or url.query or url.fragment:
            raise ValueError('api_base不得包含凭证、查询参数或片段')
        if not isinstance(config.get('model'), str) or not config['model'].strip():
            raise ValueError('请指定model')
    return config
