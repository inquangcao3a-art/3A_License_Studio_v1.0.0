"""P19 opt-in Google Fonts Developer API connector and bounded font cache.

Only downloads files advertised by the official API from fonts.gstatic.com.
No third-party website scraping, no OpenAI calls, no guessed previews.
"""
import json, os, hashlib, urllib.parse, urllib.request
from pathlib import Path

API='https://www.googleapis.com/webfonts/v1/webfonts'
MAX_BYTES=2_500_000

def cache_root(root=None):
    path=Path(root or (Path(os.environ.get('LOCALAPPDATA') or Path.home())/'AI_Font_Finder_PRO_3A'/'p19_google_fonts'))
    path.mkdir(parents=True,exist_ok=True)
    return path

def _get(url, timeout=18, opener=None):
    req=urllib.request.Request(url,headers={'User-Agent':'AI-Font-Finder-3A/5.5.1'})
    if opener is None: opener=urllib.request.urlopen
    with opener(req,timeout=timeout) as res:
        size=res.headers.get('Content-Length') if hasattr(res,'headers') else None
        if size and int(size)>MAX_BYTES:raise ValueError('Tệp font vượt giới hạn')
        raw=res.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('Tệp font vượt giới hạn')
    return raw

def fetch_catalog(api_key,opener=None):
    if not api_key or not api_key.strip():raise ValueError('Cần Google Fonts API key (không phải OpenAI key)')
    url=API+'?'+urllib.parse.urlencode({'key':api_key.strip(),'sort':'popularity'})
    data=json.loads(_get(url,opener=opener).decode('utf-8'))
    if not isinstance(data,dict) or not isinstance(data.get('items'),list):raise ValueError('API không trả danh mục font hợp lệ')
    return data['items']

def candidates(items,limit=80):
    out=[]
    for item in items:
        if not isinstance(item,dict):continue
        family=str(item.get('family') or '').strip()
        files=item.get('files') or {}
        if not isinstance(files,dict):continue
        url=files.get('regular') or next(iter(files.values()),'')
        if not family or not valid_font_url(url):continue
        out.append({'font_name':family,'source_id':'googlefonts','source_url':'https://fonts.google.com/specimen/'+urllib.parse.quote(family), 'font_url':url,'category':str(item.get('category','')),'subsets':item.get('subsets',[])})
        if len(out)>=limit:break
    return out

def valid_font_url(url):
    try:
        p=urllib.parse.urlsplit(url)
        return p.scheme=='https' and p.hostname=='fonts.gstatic.com' and p.path.lower().endswith(('.ttf','.otf')) and not p.username and not p.password
    except (ValueError,TypeError):return False

def cached_font(row,root=None,opener=None):
    url=row.get('font_url','')
    if not valid_font_url(url):raise ValueError('URL font không thuộc máy chủ được phép')
    path=cache_root(root)/(hashlib.sha256(url.encode()).hexdigest()+Path(urllib.parse.urlsplit(url).path).suffix.lower())
    if path.is_file() and path.stat().st_size>100:return str(path)
    raw=_get(url,opener=opener)
    if len(raw)<100 or raw[:4] not in (b'\x00\x01\x00\x00',b'OTTO',b'true',b'ttcf'):
        raise ValueError('Dữ liệu không phải tệp font TTF/OTF')
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_bytes(raw);temp.replace(path)
    return str(path)
