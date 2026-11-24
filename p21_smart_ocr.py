"""P21 OCR agreement and explicitly confirmed correction history.
Never silently infer Vietnamese accents or change the user's text.
"""
import hashlib
import os
import sqlite3
import unicodedata
from pathlib import Path

def same_text(a,b):
    return unicodedata.normalize('NFC',' '.join(a.split())) == unicodedata.normalize('NFC',' '.join(b.split()))

def image_key(image):
    im=image.convert('RGB')
    return hashlib.sha256(im.tobytes()+str(im.size).encode('ascii')).hexdigest()

def correction_path():
    root=Path(os.environ.get('LOCALAPPDATA') or Path.home())/'AI_Font_Finder_PRO_3A'
    root.mkdir(parents=True,exist_ok=True)
    return root/'p21_ocr_corrections.sqlite3'

def save_correction(signature,google,offline,confirmed,db_path=None):
    if not signature or not confirmed.strip():raise ValueError('Missing confirmed OCR text')
    with sqlite3.connect(str(db_path or correction_path()),timeout=10) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS corrections (image_hash TEXT PRIMARY KEY, google_text TEXT, offline_text TEXT, confirmed_text TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)')
        conn.execute('INSERT OR REPLACE INTO corrections(image_hash,google_text,offline_text,confirmed_text) VALUES (?,?,?,?)',(signature,google,offline,confirmed.strip()))

def previous_correction(signature,db_path=None):
    path=Path(db_path or correction_path())
    if not path.exists():return None
    with sqlite3.connect(str(path),timeout=10) as conn:
        row=conn.execute('SELECT confirmed_text FROM corrections WHERE image_hash=?',(signature,)).fetchone()
    return row[0] if row else None
