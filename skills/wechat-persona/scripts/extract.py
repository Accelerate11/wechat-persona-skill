"""Extract the selected private conversation and target-authored group rows only."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from wechat_source import recover_keys, open_snapshot, normalize_row
from configuration import load_project


def run(project):
    root = project.parent
    cfg = load_project(project, source=True)
    source = Path(cfg["source_root"])
    if not source.is_absolute():
        source = root / source
    files = {"contact": source / "contact" / "contact.db"}
    files.update({p.stem: p for p in sorted((source / "message").glob("message_[0-9]*.db"))})
    if len(files) < 2:
        raise RuntimeError("没有找到消息分片")
    print(json.dumps({"phase": "read_source", "databases": list(files)}, ensure_ascii=False), flush=True)
    keys = recover_keys(files)
    contact, contact_manifest = open_snapshot(files["contact"], keys["contact"])
    target = cfg["target_username"]
    record = contact.execute("SELECT username, remark, nick_name, alias FROM contact WHERE username=?", (target,)).fetchone()
    if not record or record["remark"] != cfg["target_remark"]:
        raise RuntimeError("联系人备注与内部账号未同时匹配，停止提取")
    identity = dict(record)
    contact.close()
    output = root / "data"
    output.mkdir(exist_ok=True)
    rows, manifests, seen = [], [contact_manifest], set()
    private_table = "Msg_" + hashlib.md5(target.encode()).hexdigest()
    for name, path in files.items():
        if name == "contact":
            continue
        conn, manifest = open_snapshot(path, keys[name])
        manifests.append(manifest)
        mapping = {r[0]: r[1] for r in conn.execute("SELECT rowid, user_name FROM Name2Id")}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name LIKE 'Msg_%'")}
        group_map = {"Msg_" + hashlib.md5(u.encode()).hexdigest(): u for u in mapping.values() if u.endswith("@chatroom")}
        selected = [(private_table, target)] if private_table in tables else []
        if cfg.get("include_group_target_messages", False):
            selected += [(t, u) for t, u in group_map.items() if t in tables]
        target_ids = [rid for rid, user in mapping.items() if user == target]
        if not target_ids:
            raise RuntimeError(f"{name} 缺少目标人物的发送者映射")
        for table, conversation in selected:
            if not all(c in "0123456789abcdefMsg_" for c in table):
                raise ValueError("非法消息表标识")
            query = f'SELECT * FROM "{table}"'
            args = ()
            if conversation.endswith("@chatroom"):
                query += " WHERE real_sender_id IN (" + ",".join("?" for _ in target_ids) + ")"
                args = tuple(target_ids)
            for row in conn.execute(query, args):
                item = normalize_row(row, mapping, conversation, name, target, cfg["source_account"])
                item["sender_resolution"] = "mapped" if item["sender"] else "unresolved"
                if item["scope"] == "group" and not item["is_target"]:
                    raise RuntimeError("群聊语料过滤未通过")
                sid = item["server_id"]
                key = (conversation, sid) if sid not in ("", "0") else (name, table, item["local_id"])
                if key not in seen:
                    seen.add(key)
                    rows.append(item)
        conn.close()
        print(json.dumps({"phase": "shard_complete", "shard": name, "selected_rows": len(rows)}, ensure_ascii=False), flush=True)
    rows.sort(key=lambda x: (x["timestamp"] or 0, x["sort_seq"] or 0, x["id"]))
    if not any(r["scope"] == "private" and r["is_target"] for r in rows):
        raise RuntimeError("未取得目标人物私聊发言，不能生成有依据的人格")
    with (output / "messages.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    times = [r["timestamp"] for r in rows if r["timestamp"]]
    report = {"identity": identity, "counts": dict(Counter(("target_" if r["is_target"] else "owner_" if r["is_owner"] else "unknown_") + r["scope"] for r in rows)),
              "message_types": dict(Counter(str(r["type"]) for r in rows)),
              "decode_status": dict(Counter(r["decode_status"] for r in rows)),
              "unresolved_senders": sum(not r["sender"] for r in rows),
              "first_timestamp": min(times), "last_timestamp": max(times),
              "group_conversations": len({r["conversation"] for r in rows if r["scope"] == "group"}),
              "snapshots": manifests, "cross_database_transaction": False,
              "keys_saved": False, "plaintext_database_saved": False,
              "exported_at": datetime.now(timezone.utc).isoformat()}
    (output / "source-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "snapshots"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    run(args.project.resolve())
