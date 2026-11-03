"""Convenience entry point; the implementation also ships inside the skill."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/wechat-persona/scripts'))
from import_jsonl import main

if __name__ == '__main__':
    main()
