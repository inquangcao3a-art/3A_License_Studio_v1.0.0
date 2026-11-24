"""P41 optional offline deep-learning OCR; never overwrites uncertain user text.
RapidOCR + PP-OCRv6 model must be installed and available locally.
"""
import re
import unicodedata
import numpy as np
from PIL import Image, ImageOps

def _clean(text):
    return unicodedata.normalize('NFC',' '.join(str(text or '').split()))

def _suspicious(text):
    t=_clean(text)
    letters=[c for c in t if c.isalpha()]
    return not t or len(letters)<3 or (len(letters)<5 and len(t.split())>1)

def _deep_read(image):
    try:
        from rapidocr import RapidOCR
    except ImportError:
        return None,0.0,'RapidOCR chưa cài'
    try:
        # One engine per worker call; avoid sharing non-thread-safe inference sessions.
        # If models are not present locally, RapidOCR may try to download them.
        engine=RapidOCR(params={
            'Det.ocr_version':'PP-OCRv6', 'Rec.ocr_version':'PP-OCRv6',
            'Det.lang_type':'vi','Rec.lang_type':'vi',
            'Det.model_type':'small','Rec.model_type':'small',
        })
        result=engine(np.asarray(image.convert('RGB')))
        items=getattr(result,'txts',None)
        scores=getattr(result,'scores',None)
        if items is None and isinstance(result,tuple) and result:
            items=[x[1] for x in result[0] if len(x)>1] if result[0] else []
            scores=[x[2] for x in result[0] if len(x)>2] if result[0] else []
        if not items:return None,0.0,'RapidOCR không đọc được'
        text=_clean(' '.join(items))
        confidence=float(sum(scores)/len(scores)) if scores is not None and len(scores) else 0.0
        return text,confidence,'RapidOCR PP-OCRv6'
    except Exception as exc:
        return None,0.0,'RapidOCR: '+str(exc)[:120]

def recognize_with_fallback(image,legacy):
    """Prefer verified deep result; retain old OCR as fallback. No guessed accents."""
    image=ImageOps.exif_transpose(image.convert('RGB'))
    deep,score,engine=_deep_read(image)
    if deep and score>=0.85 and not _suspicious(deep):
        return deep,engine+' %.2f'%score,False
    old,old_engine=legacy(image)
    if deep and old and _clean(deep).casefold()==_clean(old).casefold() and not _suspicious(deep):
        return deep,engine+' + '+old_engine,False
    if deep and not _suspicious(deep):
        return deep,engine+' %.2f'%score,True
    if old:
        return old,old_engine,True
    return None,engine+'; '+str(old_engine),True
