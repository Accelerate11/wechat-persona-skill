"""Read-only WeChat 4 source acquisition; no keys or full plaintext DBs on disk.

SPDX-License-Identifier: Apache-2.0
Adapted from the WCDB acquisition approach in wechatauto-replica.
Changes: in-memory images, committed/authenticated WAL frames, scoped export,
and no persistent key cache. See NOTICE for upstream attribution.

SQLCipher/WCDB format and Config.Cipher layout reference:
https://github.com/fanyuantaier/wechatauto-replica/blob/main/wechatauto/db.py
The source is never opened for writing. Only selected normalized messages are saved.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import hashlib
import hmac
import json
import re
import sqlite3
import struct
import subprocess
import sys
import time
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
import zstandard

PAGE = 4096
RESERVE = 80
CIPHER_NAME = b"com.Tencent.WCDB.Config.Cipher"
XOR_MASK = bytes.fromhex("d2c7442458020000004889442450488b450048844c2448488944254048584c24")


class Memory:
    """Only PROCESS_QUERY_INFORMATION and PROCESS_VM_READ; never inject or write."""

    class MBI(C.Structure):
        _fields_ = [("base", C.c_void_p), ("allocation", C.c_void_p),
                    ("allocation_protect", W.DWORD), ("padding", W.DWORD),
                    ("size", C.c_size_t), ("state", W.DWORD),
                    ("protect", W.DWORD), ("kind", W.DWORD), ("padding2", W.DWORD)]

    def __init__(self, pid):
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.k.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        self.k.OpenProcess.restype = W.HANDLE
        self.k.CloseHandle.argtypes = [W.HANDLE]
        self.k.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
        self.k.VirtualQueryEx.argtypes = [W.HANDLE, C.c_void_p, C.POINTER(self.MBI), C.c_size_t]
        self.k.VirtualQueryEx.restype = C.c_size_t
        self.handle = self.k.OpenProcess(0x410, False, pid)
        if not self.handle:
            raise OSError("无法只读访问微信进程，请保持当前用户的微信已登录。")

    def read(self, address, length):
        if not 0 < length <= 32 * 1024 * 1024 or not 0x10000 <= address < 0x800000000000:
            return b""
        buffer = C.create_string_buffer(length)
        count = C.c_size_t()
        self.k.ReadProcessMemory(self.handle, C.c_void_p(address), buffer, length, C.byref(count))
        return buffer.raw[:count.value]

    def blocks(self, private_only=False):
        address = 0
        started = time.monotonic()
        while address < 0x800000000000:
            if time.monotonic() - started > 60:
                raise TimeoutError("微信只读内存扫描超时，未继续扫描。")
            info = self.MBI()
            if not self.k.VirtualQueryEx(self.handle, C.c_void_p(address), C.byref(info), C.sizeof(info)):
                break
            base, size = info.base or 0, info.size
            if size <= 0:
                break
            address = base + size
            if info.state != 0x1000 or info.protect & 0x101 or not info.protect & 0xEE:
                continue
            if private_only and info.kind != 0x20000:
                continue
            for offset in range(0, size, 8 * 1024 * 1024):
                blob = self.read(base + offset, min(size - offset, 8 * 1024 * 1024 + 128))
                if blob:
                    yield base + offset, blob

    def close(self):
        self.k.CloseHandle(self.handle)


def weixin_pids():
    if sys.platform != "win32":
        raise RuntimeError("直接读取已登录微信进程仅支持Windows；其他平台请导入JSONL。")
    text = subprocess.check_output(
        ["powershell", "-NoProfile", "-Command", "@(Get-Process Weixin -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id) | ConvertTo-Json -Compress"],
        encoding="utf-8", errors="replace")
    values = json.loads(text) if text.strip() else []
    return [values] if isinstance(values, int) else values


def verify_key(key, page):
    if len(page) != PAGE:
        return False
    salt = bytes(v ^ 0x3A for v in page[:16])
    mac_key = hashlib.pbkdf2_hmac("sha512", key, salt, 2, 32)
    actual = hmac.new(mac_key, page[16:PAGE - 64] + struct.pack("<I", 1), hashlib.sha512).digest()
    return hmac.compare_digest(actual, page[-64:])


def recover_keys(files):
    """Validate candidates against this account's DB headers; never return/log hex."""
    first_pages = {}
    for name, path in files.items():
        with path.open("rb") as handle:
            first_pages[name] = handle.read(PAGE)
    keys = {}
    for pid in weixin_pids():
        memory = Memory(pid)
        try:
            needles = set()
            for base, blob in memory.blocks():
                start = 0
                while (at := blob.find(CIPHER_NAME, start)) >= 0:
                    needles.add(base + at)
                    start = at + 1
            if not needles:
                continue
            pairs = [struct.pack("<QQ", addr, len(CIPHER_NAME)) for addr in needles]
            matcher = re.compile(b"|".join(re.escape(p) for p in pairs))
            tested = set()
            for base, blob in memory.blocks(private_only=True):
                for match in matcher.finditer(blob):
                    node = memory.read(base + match.start() - 16, 80)
                    if len(node) < 64:
                        continue
                    config = struct.unpack_from("<Q", node, 40)[0]
                    obj = memory.read(config + 0x88, 40)
                    if len(obj) < 24:
                        continue
                    ptr, length = struct.unpack_from("<QQ", obj, 8)
                    if not 0 < length <= 1024:
                        continue
                    encrypted = memory.read(ptr, length)
                    decoded = bytes(v ^ XOR_MASK[i % len(XOR_MASK)] for i, v in enumerate(encrypted))
                    for literal in re.finditer(rb"[xX]'([0-9a-fA-F]{64,192})'", decoded):
                        run = literal.group(1)
                        for offset in sorted(set([0, max(0, len(run) - 64), *range(0, len(run) - 63, 32)])):
                            candidate = bytes.fromhex(run[offset:offset + 64].decode())
                            if len(candidate) != 32 or candidate in tested:
                                continue
                            tested.add(candidate)
                            for name, page in first_pages.items():
                                if name not in keys and verify_key(candidate, page):
                                    keys[name] = candidate
                if len(keys) == len(files):
                    return keys
        finally:
            memory.close()
    missing = sorted(set(files) - set(keys))
    if missing:
        raise RuntimeError("未找到通过校验的数据库读取材料：" + ", ".join(missing) + "；请保持微信已登录，或提供可读聊天导出。")
    return keys


def decrypt_page(key, page, number, mac_key=None):
    offset = 16 if number == 1 else 0
    if len(page) != PAGE:
        raise ValueError("数据库页面不完整")
    if mac_key is not None:
        expected = hmac.new(mac_key, page[offset:PAGE - 64] + struct.pack("<I", number), hashlib.sha512).digest()
        if not hmac.compare_digest(expected, page[-64:]):
            raise ValueError(f"数据库页面 {number} 校验失败；源文件可能正在变化")
    iv = page[PAGE - RESERVE:PAGE - RESERVE + 16]
    decoder = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = decoder.update(page[offset:PAGE - RESERVE]) + decoder.finalize()
    return (b"SQLite format 3\x00" if number == 1 else b"") + plain + bytes(RESERVE)


def wal_checksum(data, endian, first=0, second=0):
    if len(data) % 8:
        raise ValueError("WAL 校验长度错误")
    values = struct.unpack(endian + "I" * (len(data) // 4), data)
    for i in range(0, len(values), 2):
        first = (first + values[i] + second) & 0xffffffff
        second = (second + values[i + 1] + first) & 0xffffffff
    return first, second


def apply_wal(database, wal, key, mac_key):
    """Merge only checked frames of the current generation through the last commit."""
    if len(wal) < 32:
        return database, 0
    magic, _, page_size = struct.unpack_from(">III", wal)
    if magic not in (0x377f0682, 0x377f0683) or page_size != PAGE:
        raise ValueError("WAL 格式不受支持")
    endian = "<" if magic == 0x377f0682 else ">"
    checksum = wal_checksum(wal[:24], endian)
    if checksum != struct.unpack_from(">II", wal, 24):
        raise ValueError("WAL 头校验失败")
    pending, committed = {}, 0
    for pos in range(32, len(wal) - PAGE - 23, PAGE + 24):
        header, page = wal[pos:pos + 24], wal[pos + 24:pos + 24 + PAGE]
        if header[8:16] != wal[16:24]:
            break  # preallocated old-generation tail
        expected = wal_checksum(header[:8] + page, endian, *checksum)
        if expected != struct.unpack_from(">II", header, 16):
            break  # unwritten or incomplete tail
        checksum = expected
        number, size = struct.unpack_from(">II", header)
        if not 0 < number <= 2_000_000:
            raise ValueError("WAL 页号不合法")
        pending[number] = decrypt_page(key, page, number, mac_key)
        if size:
            required = size * PAGE
            if required > len(database):
                database.extend(bytes(required - len(database)))
            for pg, content in pending.items():
                if pg <= size:
                    database[(pg - 1) * PAGE:pg * PAGE] = content
            del database[required:]
            pending.clear()
            committed += 1
    return database, committed


def open_snapshot(path, key):
    """Acquire a stable encrypted image, decrypt in RAM, and open a read-only connection."""
    wal_path = Path(str(path) + "-wal")
    def stamp():
        return [(p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None for p in (path, wal_path)]
    for attempt in range(3):
        before = stamp()
        raw = path.read_bytes()
        wal = wal_path.read_bytes() if wal_path.exists() else b""
        if before == stamp():
            break
        if attempt == 2:
            raise RuntimeError("微信数据库持续变化，未取得稳定快照；请稍后重试。")
        time.sleep(0.15)
    if len(raw) % PAGE:
        raise ValueError("数据库大小不是整页")
    mac_key = hashlib.pbkdf2_hmac("sha512", key, bytes(v ^ 0x3A for v in raw[:16]), 2, 32)
    image = bytearray(len(raw))
    for offset in range(0, len(raw), PAGE):
        image[offset:offset + PAGE] = decrypt_page(key, raw[offset:offset + PAGE], offset // PAGE + 1, mac_key)
    image, commits = apply_wal(image, wal, key, mac_key)
    image[18:20] = b"\x01\x01"  # standalone in-memory image; no external WAL access
    struct.pack_into(">I", image, 28, len(image) // PAGE)
    conn = sqlite3.connect(":memory:")
    conn.deserialize(bytes(image))
    conn.execute("PRAGMA query_only=ON")
    checked = conn.execute("PRAGMA quick_check").fetchone()[0]
    if checked != "ok":
        conn.close()
        raise RuntimeError("读取快照完整性检查失败：" + str(checked)[:160])
    conn.row_factory = sqlite3.Row
    return conn, {"source": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                  "wal_sha256": hashlib.sha256(wal).hexdigest(), "wal_commits": commits,
                  "acquired_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "quick_check": checked}


def decode_content(value):
    if isinstance(value, str):
        return value, "text"
    if value is None:
        return "", "empty"
    raw = bytes(value)
    if raw.startswith(b"\x28\xb5\x2f\xfd"):
        try:
            raw = zstandard.ZstdDecompressor().decompress(raw, max_output_size=2_000_000)
        except zstandard.ZstdError:
            return "", "decode_failed"
    try:
        return raw.decode("utf-8"), "text"
    except UnicodeDecodeError:
        return "", "decode_failed"


def normalize_row(row, mapping, conversation, shard, target, owner):
    data = dict(row)
    sender = mapping.get(data.get("real_sender_id"), "")
    body, status = decode_content(data.get("message_content"))
    if not body and data.get("compress_content"):
        body, status = decode_content(data["compress_content"])
    if conversation.endswith("@chatroom"):
        prefix = re.match(r"^([a-zA-Z0-9_@.-]+):\r?\n", body)
        if prefix:
            if sender and prefix.group(1) != sender:
                raise ValueError("群消息正文发送者与本分片 Name2Id 不一致")
            sender = prefix.group(1)
            body = body[prefix.end():]
    kind = int(data.get("local_type") or 0) & 0xffffffff
    return {"id": f"{shard}:{conversation}:{data.get('local_id')}",
            "server_id": str(data.get("server_id") or ""), "conversation": conversation,
            "scope": "group" if conversation.endswith("@chatroom") else "private",
            "sender": sender, "is_target": sender == target, "is_owner": sender == owner,
            "timestamp": data.get("create_time"), "sort_seq": data.get("sort_seq"),
            "type": kind, "text": body, "decode_status": status,
            "source_shard": shard, "local_id": data.get("local_id")}
