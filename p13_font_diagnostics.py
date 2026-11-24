"""P13: Non-destructive diagnosis of Unicode/legacy font rendering problems."""
import os, json, argparse, unicodedata
from fontTools.ttLib import TTFont
from PIL import ImageFont

def inspect_font(path, sample='Cửa Hàng'):
    if not os.path.isfile(path):
        return {'path':path,'error':'Font file not found'}
    try:
        font=TTFont(path,fontNumber=0,lazy=True)
    except (OSError, ValueError) as exc:
        return {'path':path,'error':str(exc)}
    try:
        cmap=font.getBestCmap() or {}
        names={}
        for record in font['name'].names:
            if record.nameID in (1,2,4,6):
                try:names.setdefault(str(record.nameID),record.toUnicode())
                except (UnicodeError,ValueError):pass
        needed=sorted(set(sample)-set(' \n\t'))
        missing=[{'char':c,'codepoint':f'U+{ord(c):04X}','name':unicodedata.name(c,'UNKNOWN')} for c in needed if ord(c) not in cmap]
        result={'path':path,'names':names,'sample':sample,'missing_glyphs':missing,'all_sample_codepoints_mapped':not missing,'unicode_cmap_size':len(cmap),'legacy_name_hint':any('VNI' in x.upper() or 'TCVN' in x.upper() for x in list(names.values())+[os.path.basename(path)])}
        try:
            pillow=ImageFont.truetype(path,64)
            result['pillow_bbox']=pillow.getbbox(sample)
        except Exception as exc:result['pillow_error']=str(exc)
        result['assessment']='Missing Unicode mappings: direct Unicode preview may display tofu or incorrect glyphs' if missing else 'Unicode mappings present; visual correctness still requires image comparison'
        return result
    finally:font.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('font');p.add_argument('--text',default='Cửa Hàng');args=p.parse_args()
    print(json.dumps(inspect_font(args.font,args.text),ensure_ascii=False,indent=2))
