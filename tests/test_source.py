import hashlib
import hmac
from pathlib import Path
import sqlite3
import struct
import sys
import unittest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/wechat-persona/scripts'))
from wechat_source import decrypt_page, verify_key, apply_wal, wal_checksum, normalize_row, PAGE, RESERVE
from build import prepare, valid_items


KEY = bytes(range(32))
SALT = bytes(range(16))
MAC = hashlib.pbkdf2_hmac('sha512', KEY, bytes(v ^ 0x3a for v in SALT), 2, 32)


def encrypted_page(payload, number=1):
    offset = 16 if number == 1 else 0
    iv = bytes(range(16, 32))
    encoder = Cipher(algorithms.AES(KEY), modes.CBC(iv)).encryptor()
    ciphertext = encoder.update(payload[offset:PAGE - RESERVE]) + encoder.finalize()
    body = (SALT if number == 1 else b'') + ciphertext + iv
    mac = hmac.new(MAC, body[offset:] + struct.pack('<I', number), hashlib.sha512).digest()
    return body + mac


class SourceTests(unittest.TestCase):
    def test_encrypted_page_authentication_and_corruption(self):
        plain = b'SQLite format 3\0' + bytes(range(256)) * 15 + bytes(240)
        self.assertEqual(len(plain), PAGE)
        encrypted = encrypted_page(plain)
        self.assertTrue(verify_key(KEY, encrypted))
        self.assertFalse(verify_key(bytes(reversed(KEY)), encrypted))
        self.assertEqual(decrypt_page(KEY, encrypted, 1, MAC)[:PAGE - RESERVE], plain[:PAGE - RESERVE])
        damaged = bytearray(encrypted)
        damaged[100] ^= 1
        with self.assertRaises(ValueError):
            decrypt_page(KEY, bytes(damaged), 1, MAC)

    def test_wal_ignores_uncommitted_tail(self):
        header = bytearray(struct.pack('>IIIIII', 0x377f0682, 3007000, PAGE, 0, 123, 456))
        checksum = wal_checksum(header, '<')
        header.extend(struct.pack('>II', *checksum))
        wal = bytearray(header)
        for number, commit in [(2, 2), (2, 0)]:
            page = encrypted_page(bytes([13 if commit else 10]) + bytes(PAGE - 1), 2)
            frame = struct.pack('>IIII', number, commit, 123, 456)
            checksum = wal_checksum(frame[:8] + page, '<', *checksum)
            wal.extend(frame + struct.pack('>II', *checksum) + page)
        image, commits = apply_wal(bytearray(PAGE), wal, KEY, MAC)
        self.assertEqual(commits, 1)
        self.assertEqual(len(image), PAGE * 2)
        self.assertEqual(image[PAGE], 13)

    def test_sender_id_is_resolved_in_its_own_shard(self):
        row = {'real_sender_id': 2, 'local_type': 1, 'message_content': '行', 'local_id': 1}
        first = normalize_row(row, {2: 'target'}, 'target', 'message_0', 'target', 'owner')
        second = normalize_row(row, {2: 'owner'}, 'target', 'message_1', 'target', 'owner')
        self.assertTrue(first['is_target'])
        self.assertFalse(second['is_target'])
        with self.assertRaises(ValueError):
            normalize_row({**row, 'message_content': 'someone_else:\n行'}, {2: 'target'}, 'a@chatroom', 'message_0', 'target', 'owner')

    def test_holdout_sessions_cannot_enter_evidence(self):
        rows = [{'id': str(i), 'conversation': 'target', 'timestamp': 100000 + i * 100000,
                 'type': 1, 'sender': 'target', 'is_target': True, 'is_owner': False, 'text': '行'} for i in range(40)]
        evidence, training, holdout = prepare(rows)
        self.assertTrue(holdout)
        bad = {'evidence_ids': [holdout[0]['id']], 'text': 'should reject'}
        good = {'evidence_ids': [training[0]['id']], 'text': 'supported'}
        self.assertEqual(valid_items([bad, good], evidence), [good])

    def test_api_secrets_are_redacted_before_model_input(self):
        rows = [{'id': '1', 'conversation': 'target', 'timestamp': 100000, 'type': 1,
                 'sender': 'target', 'is_target': True, 'is_owner': False, 'text': 'key: sk-' + 'x' * 32}]
        evidence, training, holdout = prepare(rows)
        self.assertNotIn('sk-', evidence['m00001']['text'])


if __name__ == '__main__':
    unittest.main()
