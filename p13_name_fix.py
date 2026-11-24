"""P13: prefer Windows naming records while retaining legacy aliases."""
import os
from fontTools.ttLib import TTFont

def font_aliases(path):
    font = TTFont(path, fontNumber=0, lazy=True)
    try:
        records=[]
        for n in font['name'].names:
            if n.nameID in (1,4,6):
                try:
                    value=n.toUnicode().strip()
                    if value:
                        records.append((n.platformID,n.langID,n.nameID,value))
                except (UnicodeError, ValueError):
                    continue
        records.sort(key=lambda x:(0 if x[0]==3 else 1 if x[0]==0 else 2, 0 if x[1]==1033 else 1, 0 if x[2]==4 else 1 if x[2]==1 else 2))
        return list(dict.fromkeys(row[3] for row in records))
    finally:
        font.close()

def preferred_font_name(path):
    names=font_aliases(path)
    return names[0] if names else os.path.splitext(os.path.basename(path))[0]
