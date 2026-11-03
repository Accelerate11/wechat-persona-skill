"""Plan or atomically install the verified Aurabot core patch; never restart apps."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ('src/chat/conversation-context.js', 'src/chat/hub.js', 'src/core/config.js',
         'src/features/memory.js', 'src/modules/memory/index.js')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalized(data):
    return data.replace(b'\r\n', b'\n')


def inside(root, relative):
    if relative not in FILES:
        raise ValueError('Unexpected core file')
    path = root / relative
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or (hasattr(ancestor, 'is_junction') and ancestor.is_junction()):
            raise ValueError('Linked installation paths are not supported')
        if ancestor == root:
            break
    if not path.resolve().is_relative_to(root):
        raise ValueError('Core path escaped installation directory')
    return path


def plan(source, target, manifest):
    source, target = Path(source).absolute(), Path(target).absolute()
    if source.resolve() == target.resolve():
        raise ValueError('Source and target must be different directories')
    for root in (source, target):
        package = json.loads((root / 'package.json').read_text('utf-8-sig'))
        if package.get('name') != 'dsh-aurabot-qq' or package.get('version') != manifest['plugin_version']:
            raise ValueError('Unsupported Aurabot package identity or version')
    if len(manifest['files']) != len(FILES) or {x['path'] for x in manifest['files']} != set(FILES):
        raise ValueError('Incomplete core manifest')
    entries = []
    for entry in manifest['files']:
        relative = entry['path']
        src, dst = inside(source, relative), inside(target, relative)
        new = normalized(src.read_bytes())
        if digest(new) != entry['after_sha256']:
            raise ValueError('Source verification failed: ' + relative)
        before = dst.read_bytes() if dst.exists() else None
        before_normalized = digest(normalized(before)) if before is not None else None
        accepted = [entry['before_sha256'], entry['after_sha256'], *entry.get('previous_sha256', [])]
        if before_normalized not in accepted:
            raise ValueError('Target has independent changes; no files installed: ' + relative)
        entries.append({'path': relative, 'before_sha256': digest(before) if before is not None else None,
                        'after_sha256': digest(new), 'change': before is None or normalized(before) != new})
    return {'source': str(source), 'target': str(target), 'files': entries,
            'restart_required': True, 'applications_restarted': False}


def atomic_replace(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    # A new file in the same directory breaks pnpm hardlinks without changing
    # the shared package store, and keeps the final rename on the same volume.
    fd, temporary = tempfile.mkstemp(prefix='.persona-core-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def apply_upgrade(source, target, manifest, backup):
    result = plan(source, target, manifest)
    source, target, backup = Path(result['source']), Path(result['target']), Path(backup).absolute()
    if backup.exists():
        raise ValueError('Backup directory must be new; existing backups are never overwritten')
    if backup.resolve().is_relative_to(target.resolve()) or backup.resolve().is_relative_to(source.resolve()):
        raise ValueError('Place backups outside both package directories')
    originals, replacements = {}, {}
    # Re-read and verify everything before the first mutation.
    for entry in result['files']:
        relative = entry['path']; dst = inside(target, relative)
        old = dst.read_bytes() if dst.exists() else None
        if (digest(old) if old is not None else None) != entry['before_sha256']:
            raise ValueError('Target changed after planning')
        new = normalized(inside(source, relative).read_bytes())
        if digest(new) != entry['after_sha256']:
            raise ValueError('Source changed after planning')
        originals[relative], replacements[relative] = old, new
    backup.mkdir(parents=True)
    for relative, data in originals.items():
        if data is not None:
            saved = inside(backup, relative); saved.parent.mkdir(parents=True, exist_ok=True); saved.write_bytes(data)
            if digest(saved.read_bytes()) != digest(data):
                raise RuntimeError('Backup verification failed')
    result['backup'] = str(backup)
    result['status'] = 'prepared'
    report = backup / 'core-upgrade.json'
    report.write_text(json.dumps(result, indent=2), 'utf-8')
    changed = []
    try:
        for entry in result['files']:
            if not entry['change']:
                continue
            relative = entry['path']; dst = inside(target, relative)
            current = dst.read_bytes() if dst.exists() else None
            if current != originals[relative]:
                raise ValueError('Target changed during installation')
            atomic_replace(dst, replacements[relative]); changed.append(relative)
            if digest(dst.read_bytes()) != entry['after_sha256']:
                raise RuntimeError('Installed core verification failed')
    except Exception:
        for relative in reversed(changed):
            dst = inside(target, relative)
            if originals[relative] is None:
                if dst.read_bytes() == replacements[relative]:
                    dst.unlink()
            else:
                atomic_replace(dst, originals[relative])
        result['status'] = 'rolled_back_after_failure'
        report.write_text(json.dumps(result, indent=2), 'utf-8')
        raise
    result['status'] = 'installed'
    report.write_text(json.dumps(result, indent=2), 'utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--target', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'integrations/aurabot-core.manifest.json')
    parser.add_argument('--backup', type=Path)
    parser.add_argument('--apply', action='store_true', help='Stop/unload the target host before applying; this script never stops it')
    args = parser.parse_args()
    if args.apply and not args.backup:
        parser.error('--apply requires --backup')
    manifest = json.loads(args.manifest.read_text('utf-8'))
    result = apply_upgrade(args.source, args.target, manifest, args.backup) if args.apply else plan(args.source, args.target, manifest)
    print(json.dumps(result))
