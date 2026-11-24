"""P120 adaptive offline OCR. Original RGB first; bounded fallbacks only on uncertainty.

Does not alter source pixels or infer Vietnamese accents from a dictionary.
"""
import os
import sys
import threading
import unicodedata
from collections import defaultdict
import cv2
import numpy as np
from PIL import Image, ImageOps

_LOCK = threading.Lock()

def clean(value):
    return unicodedata.normalize('NFC', ' '.join(str(value or '').split()))

def _tesseract(image, psm):
    import pytesseract
    if sys.platform == 'win32':
        # Reuse the application's existing locator, which prioritizes bundled OCR.
        from __main__ import locate_tesseract
        exe = locate_tesseract()
        if not exe:
            return None, 0.0, 'Thiếu Tesseract trong bộ cài'
        pytesseract.pytesseract.tesseract_cmd = exe
        tessdata = os.path.join(os.path.dirname(exe), 'tessdata')
        if os.path.isfile(os.path.join(tessdata, 'vie.traineddata')):
            os.environ['TESSDATA_PREFIX'] = tessdata
    langs = pytesseract.get_languages(config='')
    if 'vie' not in langs:
        return None, 0.0, 'Thiếu dữ liệu tiếng Việt vie.traineddata'
    lang = 'vie+eng' if 'eng' in langs else 'vie'
    with _LOCK:
        data = pytesseract.image_to_data(image, lang=lang, config='--oem 1 --psm %d' % psm,
                                         output_type=pytesseract.Output.DICT, timeout=12)
    words, scores = [], []
    for token, score in zip(data['text'], data['conf']):
        try:
            confidence = float(score)
        except (TypeError, ValueError):
            continue
        if token.strip() and confidence >= 0:
            words.append(token.strip())
            scores.append(confidence / 100.0)
    if not words:
        return None, 0.0, 'Tesseract'
    return clean(' '.join(words)), sum(scores) / len(scores), 'Tesseract'

def _views(image):
    image = ImageOps.exif_transpose(image).convert('RGB')
    # Never downsample a sharp original; do not clip detached Vietnamese accents.
    yield 'ẢNH GỐC', image
    gray = np.asarray(image.convert('L'))
    if min(gray.shape) < 15:
        return
    if max(gray.shape) > 3500:
        return  # avoid expensive and potentially destructive full-frame processing
    # Only a small, deterministic set of fallbacks; preserve geometry and full frame.
    contrast = float(np.percentile(gray, 95) - np.percentile(gray, 5))
    if contrast < 105:
        enhanced = cv2.createCLAHE(clipLimit=1.7, tileGridSize=(8, 8)).apply(gray)
        yield 'TƯƠNG PHẢN', Image.fromarray(enhanced).convert('RGB')
    if contrast >= 35:
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        yield 'ĐEN TRẮNG', Image.fromarray(binary).convert('RGB')

def _valid(text):
    # Short signage labels (e.g. A, BỘ, 3A) are legitimate.
    return bool(text and any(c.isalnum() for c in text))

def _rank(entries):
    groups = defaultdict(list)
    for text, score, detail in entries:
        if _valid(text):
            groups[text.casefold()].append((text, score, detail))
    if not groups:
        return None, 'Không đọc được ký tự', True
    def quality(group):
        # Confidence first, agreement second. Do not prefer longer hallucinations.
        return (max(e[1] for e in group), min(3, len(group)))
    best = max(groups.values(), key=quality)
    selected = max(best, key=lambda e: e[1])
    accepted = selected[1] >= 0.88 and len(best) >= 2
    label = selected[2] + (' • CẦN KIỂM TRA' if not accepted else ' • ĐÃ ĐỐI CHIẾU')
    return selected[0], label, not accepted

def recognize(image, legacy=None):
    """Fast original-first OCR; fallback only if initial evidence is weak."""
    entries = []
    views = _views(image)
    try:
        label, original = next(views)
    except StopIteration:
        return None, 'Ảnh rỗng', True
    try:
        for psm in (7, 6):
            text, score, engine = _tesseract(original, psm)
            if _valid(text):
                entries.append((text, score, '%s • %s • PSM%d' % (engine, label, psm)))
        if entries:
            best = _rank(entries)
            if not best[2]:
                return best
        for label, view in views:
            text, score, engine = _tesseract(view, 7)
            if _valid(text):
                entries.append((text, score, '%s • %s' % (engine, label)))
        return _rank(entries)
    except Exception as exc:
        if entries:
            return _rank(entries)
        return None, 'Lỗi OCR Offline: ' + str(exc)[:150], True

def recognize_single(image, legacy=None):
    """Manual edited image: no preprocessing; no original image substitution."""
    image = ImageOps.exif_transpose(image).convert('RGB')
    entries = []
    try:
        for psm in (7, 6):
            text, score, engine = _tesseract(image, psm)
            if _valid(text):
                entries.append((text, score, '%s • ẢNH CHỈNH SỬA • PSM%d' % (engine, psm)))
    except Exception as exc:
        if not entries:
            return None, 'Lỗi OCR: ' + str(exc)[:150], True
    return _rank(entries)
