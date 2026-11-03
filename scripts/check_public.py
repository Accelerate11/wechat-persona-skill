"""Check the Git index, not ignored local data. Findings never echo secret values."""
import argparse
from pathlib import Path
import re
import subprocess

PATTERNS = {
    'api-key-shaped token': re.compile(r'\bsk-[A-Za-z0-9_-]{16,}'),
    'GitHub token': re.compile(r'\bgh[pousr]_[A-Za-z0-9]{20,}'),
    'private key': re.compile(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----'),
    'non-demo WeChat identity': re.compile(r'\bwxid_(?!demo_)[A-Za-z0-9_]{5,}\b'),
    'hardcoded QQ recipient': re.compile(r'''["']?(?:bot_qq|owner_qq|botQQ|ownerQQ)["']?\s*[:=]\s*["'][1-9][0-9]{4,14}["']'''),
    'personal Windows path': re.compile(r'[A-Za-z]:[\\/](?:Users|CODEX)[\\/][^\s"\'<>]+', re.IGNORECASE),
}
PRIVATE_DIRS = {'data', 'output', '.demo', '.venv', 'venv', 'node_modules', '__pycache__'}
PRIVATE_SUFFIXES = ('.db', '.db-wal', '.db-shm', '.sqlite', '.sqlite3', '.key', '.pem', '.log', '.zip')


def scan_files(root, names, indexed_content=None, indexed_modes=None):
    root = Path(root).resolve()
    findings = []
    for name in names:
        relative = Path(name)
        path = root / relative
        if relative.is_absolute() or '..' in relative.parts or (indexed_modes or {}).get(name) == '120000' or (indexed_content is None and path.is_symlink()):
            findings.append({'file': str(name), 'rule': 'unsafe or linked path', 'line': 0})
            continue
        if any(part in PRIVATE_DIRS for part in relative.parts) or relative.name in {'project.json', 'project.local.json', 'project.demo.json'}:
            findings.append({'file': str(name), 'rule': 'private runtime artifact', 'line': 0})
        if relative.name.startswith('.env') and relative.name != '.env.example':
            findings.append({'file': str(name), 'rule': 'environment credentials file', 'line': 0})
        if relative.name.endswith(PRIVATE_SUFFIXES):
            findings.append({'file': str(name), 'rule': 'private/binary artifact', 'line': 0})
        if relative.suffix == '.jsonl' and not (relative.parts[0] == 'examples' and relative.name.endswith('.example.jsonl')):
            findings.append({'file': str(name), 'rule': 'non-example transcript', 'line': 0})
        if indexed_content is None and not path.is_file():
            findings.append({'file': str(name), 'rule': 'tracked file missing', 'line': 0})
            continue
        try:
            text = indexed_content[name].decode('utf-8') if indexed_content is not None else path.read_text('utf-8')
        except UnicodeDecodeError:
            findings.append({'file': str(name), 'rule': 'unexpected binary file', 'line': 0})
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                if pattern.search(line):
                    findings.append({'file': str(name), 'rule': label, 'line': number})
    return findings


def tracked_files(root):
    output = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--cached', '-z'])
    names = [name.decode('utf-8') for name in output.split(b'\0') if name]
    if not names:
        raise RuntimeError('没有已跟踪/暂存文件；请先明确暂存准备公开的源码。')
    return names


def scan_index(root):
    """Read the exact staged blobs; unstaged edits cannot conceal a staged leak."""
    root = Path(root).resolve()
    raw = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--stage', '-z'])
    modes, contents = {}, {}
    for item in filter(None, raw.split(b'\0')):
        metadata, name = item.split(b'\t', 1)
        mode, sha, stage = metadata.decode('ascii').split()
        if stage != '0':
            raise RuntimeError('索引有未解决冲突，停止发布检查')
        name = name.decode('utf-8')
        modes[name] = mode
        contents[name] = subprocess.check_output(['git', '-C', str(root), 'cat-file', 'blob', sha])
    if not modes:
        raise RuntimeError('没有已跟踪/暂存文件；请先明确暂存准备公开的源码。')
    return list(modes), scan_files(root, list(modes), contents, modes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    names, findings = scan_index(args.root)
    for item in findings:
        print(f"{item['file']}:{item['line']}: {item['rule']}")
    if findings:
        raise SystemExit(1)
    print(f'Public-source checks passed for {len(names)} tracked files.')
