"""Conservative VNI encoder for legacy fonts, with Unicode cmap verification.
Only VNI family; preserve Unicode font behavior. No downloaded font assets.
"""
import os, unicodedata
from functools import lru_cache
from fontTools.ttLib import TTFont

TONES={'\u0301':'ù','\u0300':'ø','\u0309':'û','\u0303':'õ','\u0323':'ï'}
BASE={'ă':'aê','â':'aâ','ê':'eâ','ô':'oâ','ơ':'ô','ư':'ö','đ':'ñ',
      'Ă':'AÊ','Â':'AÂ','Ê':'EÂ','Ô':'OÂ','Ơ':'Ô','Ư':'Ö','Đ':'Ñ'}

def encode_vni(text):
    out=[]
    for ch in text:
        decomposed=unicodedata.normalize('NFD',ch)
        base=decomposed[0]
        mods=decomposed[1:]
        if '\u031b' in mods: base={'o':'ơ','u':'ư','O':'Ơ','U':'Ư'}.get(base,base)
        elif '\u0302' in mods: base={'a':'â','e':'ê','o':'ô','A':'Â','E':'Ê','O':'Ô'}.get(base,base)
        elif '\u0306' in mods: base={'a':'ă','A':'Ă'}.get(base,base)
        encoded=BASE.get(base,base)
        tone=next((TONES[x] for x in mods if x in TONES), '')
        if tone: encoded+=tone
        out.append(encoded)
    return ''.join(out)

@lru_cache(maxsize=4096)
def font_mapping(path,size,mtime_ns):
    try:
        font=TTFont(path,lazy=True)
        try:
            cmap=font.getBestCmap() or {}
            from p13_name_fix import font_aliases
            names=font_aliases(path)
            legacy=any(x.casefold().startswith('vni-') for x in names) or os.path.basename(path).casefold().startswith('vni-')
            return legacy,frozenset(cmap)
        finally:font.close()
    except Exception:return False,frozenset()

def compatible_text(text,path):
    try:
        st=os.stat(path)
        legacy,cmap=font_mapping(path,st.st_size,st.st_mtime_ns)
        if not legacy or all(ord(c) in cmap for c in text):return text
        converted=encode_vni(text)
        if all(ord(c) in cmap for c in converted):return converted
    except (OSError,ValueError):pass
    return text
