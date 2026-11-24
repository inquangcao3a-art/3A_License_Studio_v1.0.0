"""Offline verification of a product license and a local 15-day trial."""
import base64
import hashlib
import math
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from license_public_key import PUBLIC_KEY

TRIAL_SECONDS = 15 * 86400
PRODUCT = 'AI-FONT-FINDER-PRO'
PRICE = '249.000 ₫'


def smbios_uuid(raw):
    """Read the System Information UUID from a Windows RawSMBIOSData buffer."""
    if len(raw) < 8:
        return None
    end = 8 + int.from_bytes(raw[4:8], 'little')
    if end > len(raw):
        return None
    offset = 8
    while offset + 4 <= end:
        kind, length = raw[offset:offset + 2]
        next_strings = offset + length
        if length < 4 or next_strings > end or kind == 127:
            return None
        if kind == 1 and length >= 24:
            value = uuid.UUID(bytes_le=raw[offset + 8:offset + 24])
            return str(value) if 0 < value.int < (1 << 128) - 1 else None
        marker = raw.find(b'\x00\x00', next_strings, end)
        if marker < 0:
            return None
        offset = marker + 2
    return None


def windows_hardware_id():
    import ctypes
    from ctypes import wintypes

    read_table = ctypes.WinDLL('kernel32').GetSystemFirmwareTable
    read_table.argtypes = (wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
    read_table.restype = wintypes.UINT
    provider = int.from_bytes(b'RSMB', 'big')
    size = read_table(provider, 0, None, 0)
    if not size or size > 16 * 1024 * 1024:
        return None
    buffer = ctypes.create_string_buffer(size)
    if read_table(provider, 0, buffer, size) != size:
        return None
    return smbios_uuid(buffer.raw)


def machine_code():
    if sys.platform == 'win32':
        hardware_id = windows_hardware_id()
        if hardware_id:
            machine_id = f'smbios:{hardware_id}'
        else:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                               0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                machine_id = winreg.QueryValueEx(key, 'MachineGuid')[0]
    else:
        machine_id = str(uuid.getnode())
    return hashlib.sha256(f'{PRODUCT}:{machine_id}'.encode()).hexdigest()[:32].upper()


def license_message(device):
    return f'{PRODUCT}:P144:{device}'.encode('ascii')


class LicenseStore:
    def __init__(self, path=None, device=None, public_key=PUBLIC_KEY):
        local = Path(os.environ.get('LOCALAPPDATA') or Path.home())
        self.path = Path(path) if path is not None else local / 'AI_Font_Finder_PRO_3A' / 'licensing.sqlite3'
        self.device = device if device is not None else machine_code()
        self.public_key = public_key

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, isolation_level='IMMEDIATE')
        try:
            db.execute('CREATE TABLE IF NOT EXISTS license_state (id INTEGER PRIMARY KEY, started REAL, last_seen REAL, code TEXT)')
        except sqlite3.Error:
            db.close()
            raise
        return db

    def validate(self, code):
        if not self.public_key:
            raise ValueError('Bản này chưa được cấu hình khóa cấp bản quyền.')
        try:
            signature = base64.b64decode(code.strip(), validate=True)
            key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(self.public_key))
            key.verify(signature, license_message(self.device))
        except (ValueError, InvalidSignature):
            raise ValueError('Mã không hợp lệ, sai phiên bản hoặc thuộc máy khác.') from None

    def status(self, now=None):
        now = time.time() if now is None else now
        db = self.connect()
        try:
            with db:
                db.execute('BEGIN IMMEDIATE')
                db.execute('INSERT OR IGNORE INTO license_state VALUES (1, ?, ?, NULL)', (now, now))
                started, last_seen, code = db.execute('SELECT started, last_seen, code FROM license_state WHERE id = 1').fetchone()
                if code:
                    try:
                        self.validate(code)
                        return 'licensed', 0
                    except ValueError:
                        pass
                effective_time = max(now, last_seen)
                db.execute('UPDATE license_state SET last_seen = ? WHERE id = 1', (effective_time,))
                days = max(0, math.ceil((started + TRIAL_SECONDS - effective_time) / 86400))
                return ('trial', days) if days else ('expired', 0)
        finally:
            db.close()

    def activate(self, code):
        self.validate(code)
        now = time.time()
        db = self.connect()
        try:
            with db:
                db.execute('INSERT OR IGNORE INTO license_state VALUES (1, ?, ?, NULL)', (now, now))
                db.execute('UPDATE license_state SET code = ? WHERE id = 1', (code.strip(),))
        finally:
            db.close()
