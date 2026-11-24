"""Optional official Google Cloud Vision OCR; no web UI automation."""
import base64, hashlib, json, urllib.request, urllib.error, os, sqlite3
from pathlib import Path

ENDPOINT='https://vision.googleapis.com/v1/images:annotate'

def cloud_ocr(image, api_key, opener=None):
    if not api_key or not api_key.strip():
        raise ValueError('Cần Google Cloud Vision API key')
    from io import BytesIO
    buf=BytesIO();image.convert('RGB').save(buf,format='PNG')
    raw=buf.getvalue()
    if len(raw)>8_000_000:raise ValueError('Ảnh OCR vượt giới hạn 8 MB')
    signature=hashlib.sha256(raw+b'google-vision-v1').hexdigest()
    db=Path(os.environ.get('LOCALAPPDATA') or Path.home())/'AI_Font_Finder_PRO_3A'/'p20_vision_cache.sqlite3'
    db.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(db,timeout=8) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS ocr (hash TEXT PRIMARY KEY, text TEXT)')
        cached=conn.execute('SELECT text FROM ocr WHERE hash=?',(signature,)).fetchone()
        if cached:return cached[0]
    payload={'requests':[{'image':{'content':base64.b64encode(raw).decode('ascii')},'features':[{'type':'DOCUMENT_TEXT_DETECTION'}],'imageContext':{'languageHints':['vi','en']}}]}
    request=urllib.request.Request(ENDPOINT+'?key='+__import__('urllib.parse',fromlist=['urlencode']).urlencode({'key':api_key.strip()}).split('=',1)[1],data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
    with (opener or urllib.request.urlopen)(request,timeout=25) as response:
        data=json.load(response)
    result=(data.get('responses') or [{}])[0]
    if result.get('error'):raise ValueError(str(result['error'].get('message','Cloud Vision lỗi'))[:200])
    text=(result.get('fullTextAnnotation') or {}).get('text','').strip()
    if not text:
        annotations=result.get('textAnnotations') or []
        text=str(annotations[0].get('description','')).strip() if annotations else ''
    text=' '.join(text.split())
    if text:
        with sqlite3.connect(db,timeout=8) as conn:
            conn.execute('INSERT OR REPLACE INTO ocr(hash,text) VALUES (?,?)',(signature,text))
    return text

def accent_disagreement(a,b):
    import unicodedata
    def stripped(s):return ''.join(c for c in unicodedata.normalize('NFD',s.casefold()) if unicodedata.category(c)!='Mn').replace('đ','d')
    return bool(a and b and a!=b and stripped(a)==stripped(b))
