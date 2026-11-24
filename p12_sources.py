"""P12 opt-in source catalog and permission-aware local metadata index.
No scraping, font downloading or unauthorized remote automation.
"""
import csv, json, os, re, tempfile, urllib.parse, webbrowser, hashlib
from pathlib import Path
SOURCES = (
 ('vietfont','VietFont','VN','https://vietfont.vn/cua-hang/'),
 ('fontviethoa','FontVietHoa.org','VN','https://fontviethoa.org/'),
 ('fontchuvietcom','FontChuViet.com','VN','https://fontchuviet.com/cua-hang'),
 ('taifontviethoa','TaiFontVietHoa','VN','https://taifontviethoa.com/font/'),
 ('fontchuvietvn','FontChuViet.vn','VN','https://fontchuviet.vn/'),
 ('svnfont','SVNFont','VN','https://www.svnfont.com/the-san-pham/mien-phi/'),
 ('onimine','OniMine','VN','https://www.onimine.com/font'),
 ('sjfont','SJFont','VN','https://sjfont.net/tong-hop-cac-trang-viet-hoa-fonts/'),
 ('adina','Adina','VN','https://adina.com.vn/2000-font-thiet-ke-chuyen-nghiep/'),
 ('phamkhoi','Phạm Khôi','VN','https://www.phamkhoi.com/p/font.html'),
 ('myfonts','WhatTheFont','INT','https://www.myfonts.com/pages/whatthefont'),
 ('fontsquirrel','Matcherator','INT','https://www.fontsquirrel.com/matcherator'),
)
SOURCE_MAP={r[0]:r for r in SOURCES}
DEFAULT_ENABLED=('vietfont','fontviethoa','svnfont')
def settings_path(root=None):
 return index_path(root).with_name('p12_source_settings.json')
def default_sources():
 return [dict(id=sid,name=name,country=country,url=url,enabled=sid in DEFAULT_ENABLED) for sid,name,country,url in SOURCES]
def load_sources(path=None):
 try:
  raw=json.loads(Path(path or settings_path()).read_text(encoding='utf-8'))
  if not isinstance(raw,list):raise ValueError('invalid')
  out=[]; seen=set()
  for row in raw:
   if not isinstance(row,dict):continue
   sid=str(row.get('id',''))
   if not re.fullmatch(r'[a-z0-9_-]{2,80}',sid) or sid in seen:continue
   url=str(row.get('url',''))
   if not valid_url(url):continue
   seen.add(sid)
   out.append(dict(id=sid,name=str(row.get('name',''))[:120] or sid,country=str(row.get('country','OTHER'))[:10],url=url,enabled=bool(row.get('enabled',False))))
  return out
 except (OSError,ValueError,TypeError):return default_sources()
def valid_url(url):
 try:
  u=urllib.parse.urlsplit(url)
  return u.scheme=='https' and bool(u.hostname) and not (u.username or u.password) and '.' in u.hostname
 except ValueError:return False
def save_sources(sources,path=None):
 path=Path(path or settings_path());seen=set();out=[]
 for r in sources:
  sid=str(r['id']);url=str(r['url'])
  if not re.fullmatch(r'[a-z0-9_-]{2,80}',sid) or sid in seen or not valid_url(url):raise ValueError('Nguồn hoặc URL không hợp lệ')
  seen.add(sid);out.append(dict(id=sid,name=str(r['name'])[:120],country=str(r.get('country','OTHER'))[:10],url=url,enabled=bool(r.get('enabled',False))))
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as f:
  tmp=f.name;json.dump(out,f,ensure_ascii=False,indent=2)
 os.replace(tmp,path)
def enabled_rows(rows,sources):
 ids={r['id'] for r in sources if r['enabled']}
 return [r for r in rows if r.get('source_id') in ids]

FIELDS=('source_id','font_name','aliases','style','sample_path','license_note','source_url')
def index_path(root=None):
 root=Path(root or os.environ.get('LOCALAPPDATA') or Path.home())/'AI_Font_Finder_PRO_3A'
 root.mkdir(parents=True,exist_ok=True)
 return root/'p12_font_metadata.json'
def normalize(s):return re.sub(r'[^a-z0-9]+','',str(s).casefold())
def load_index(path=None):
 try:
  data=json.loads(Path(path or index_path()).read_text(encoding='utf-8'))
  return [r for r in data if isinstance(r,dict) and r.get('source_id') in {x['id'] for x in load_sources()} and r.get('font_name')]
 except (OSError,ValueError,TypeError):return []
def import_csv(filename,path=None):
 """Import manually prepared/licensed metadata. No remote fetch. Merge by source+name."""
 path=Path(path or index_path()); existing=load_index(path)
 with open(filename,encoding='utf-8-sig',newline='') as f:
  reader=csv.DictReader(f)
  if not {'source_id','font_name'}.issubset(reader.fieldnames or []):raise ValueError('CSV cần cột source_id,font_name')
  incoming=[]
  for row in reader:
   sid=(row.get('source_id') or '').strip(); name=(row.get('font_name') or '').strip()
   if sid not in {x['id'] for x in load_sources()}:raise ValueError('Nguồn không hợp lệ: '+sid)
   if not name or len(name)>200:raise ValueError('Tên font trống hoặc quá dài')
   record={k:(row.get(k) or '').strip()[:500] for k in FIELDS}
   if record['source_url']:
    url=urllib.parse.urlsplit(record['source_url'])
    host=urllib.parse.urlsplit(next(x['url'] for x in load_sources() if x['id']==sid)).hostname or ''
    if url.scheme!='https' or (url.hostname or '').lower() not in (host, 'www.'+host, host.removeprefix('www.')):
     raise ValueError('URL không thuộc nguồn đã chọn: '+sid)
   # Sample images are not downloaded; only local user-authorized file references.
   incoming.append(record)
 combined={(r['source_id'],normalize(r['font_name'])):r for r in existing}
 for r in incoming:combined[(r['source_id'],normalize(r['font_name']))]=r
 path.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=path.parent,delete=False) as f:
  tmp=f.name;json.dump(list(combined.values()),f,ensure_ascii=False,indent=2)
 os.replace(tmp,path)
 return len(incoming),len(combined)
def search_index(rows,clue='',text='',limit=50):
 clue=normalize(clue)[:32];text=normalize(text)
 scored=[]
 for r in rows:
  names=[r.get('font_name','')]+[v.strip() for v in r.get('aliases','').split('|') if v.strip()]
  match=any(clue in normalize(n) for n in names) if clue else False
  text_hit=bool(text and any(text in normalize(n) for n in names))
  if clue and not match:continue
  score=(10 if match else 0)+(2 if text_hit else 0)
  scored.append((-score,r.get('font_name','').casefold(),r))
 return [r for _,_,r in sorted(scored)[:limit]]
def context_for_ai(rows,clue='',limit=24):
 matches=search_index(rows,clue=clue,limit=limit) if clue else []
 return '\n'.join('%s (%s; %s)'%(r['font_name'],r['source_id'],r.get('style','')) for r in matches)
