"""Resolve a key from the configured environment; DSH reuse is explicit opt-in."""
import os
from pathlib import Path
import yaml


def deepseek_key(config=None):
    config = config or {}
    variable = config.get("api_key_env", "DEEPSEEK_API_KEY")
    if not isinstance(variable, str) or not variable:
        raise RuntimeError("api_key_env must name an environment variable")
    value = os.environ.get(variable, "").strip()
    if value:
        return value
    credentials = Path.home() / ".dsh" / ".credentials.yaml"
    if config.get("use_dsh_credentials") is True and credentials.exists():
        data = yaml.safe_load(credentials.read_text("utf-8")) or {}
        value = (data.get("refs") or {}).get("DEEPSEEK_API_KEY", "")
        if isinstance(value, str) and value.startswith("sk-"):
            return value
    raise RuntimeError(f"请设置 {variable}；或显式启用 use_dsh_credentials 复用已有DSH配置。")
