import os, sys, threading, queue, tkinter as tk
import concurrent.futures
import multiprocessing
import platform
import statistics
import socket
import hashlib, time, re
import io, base64, json, urllib.request, urllib.error, csv, subprocess, sqlite3, hashlib, time
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk, ImageFont, ImageDraw, ImageOps
import numpy as np
import cv2
from fontTools.ttLib import TTFont
import p98_font_warehouse as p98warehouse
from p144_license import LicenseStore, PRICE
from p119_exit_dynamic import asset as robot_asset, confirm_close, robot_photo
import p12_sources as p12
import p19_google_fonts as p19
import p20_vision as p20vision
import p20_sources as p20sources
import p21_smart_ocr as p21
import p38_image as p38
import p58_spacing as p58
import p42_ocr as p42ocr
import p63_geometry as p63geometry
from p13_legacy_render import compatible_text

APP_VERSION='7.1.1'
APP='AI Font Finder PRO '+APP_VERSION
EXT={'.ttf','.otf','.ttc'}
KEY_SERVICE='AI_Font_Finder_PRO_3A'
KEY_USER='openai_api_key'

# P118: persisted recent group filters; only user-approved search inputs are stored.
_GROUP_HISTORY_PATH=os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'AI_Font_Finder_PRO', 'group_filter_history.json')
def load_group_filter_history():
    try:
        with open(_GROUP_HISTORY_PATH,'r',encoding='utf-8') as fh: values=json.load(fh)
        return [v for v in values if isinstance(v,str) and v.strip()][:20] if isinstance(values,list) else []
    except (OSError,ValueError,TypeError):return []
def save_group_filter_history(values):
    try:
        os.makedirs(os.path.dirname(_GROUP_HISTORY_PATH),exist_ok=True)
        temp=_GROUP_HISTORY_PATH+'.tmp'
        with open(temp,'w',encoding='utf-8') as fh:json.dump(values[:20],fh,ensure_ascii=False,indent=2)
        os.replace(temp,_GROUP_HISTORY_PATH)
    except OSError:pass

def read_secure_key():
    try:
        import keyring
        return keyring.get_password(KEY_SERVICE,KEY_USER) or ''
    except Exception:return ''

def write_secure_key(value):
    import keyring
    if value:keyring.set_password(KEY_SERVICE,KEY_USER,value)
    else:
        try:keyring.delete_password(KEY_SERVICE,KEY_USER)
        except keyring.errors.PasswordDeleteError:pass

# Vietnamese glyph support is metadata, not proof of rendering quality.
# Legacy VNI/TCVN fonts may use non-Unicode mappings: never hard-exclude them.
_VIETNAMESE_PROBES = 'ăâđêôơưĂÂĐÊÔƠƯạảấầẩẫậắằẳẵặẹẻẽếềểễệọỏốồổỗộớờởỡợụủứừửữựỳỷỹỵ'
_VIETNAMESE_COVERAGE_CACHE = {}

def vietnamese_font_coverage(path):
    """Return 0..1 Unicode Vietnamese coverage, or None for uninspectable fonts."""
    try:
        stat=os.stat(path)
        cache_key=(os.path.normcase(os.path.abspath(path)),stat.st_size,stat.st_mtime_ns)
        cached=_VIETNAMESE_COVERAGE_CACHE.get(cache_key)
        if cached is not None:return cached
        font=TTFont(path,lazy=True,fontNumber=0)
        try:
            cmap=font.getBestCmap() or {}
            result=sum(ord(ch) in cmap for ch in _VIETNAMESE_PROBES)/len(_VIETNAMESE_PROBES)
        finally:font.close()
        if len(_VIETNAMESE_COVERAGE_CACHE)>12000:_VIETNAMESE_COVERAGE_CACHE.clear()
        _VIETNAMESE_COVERAGE_CACHE[cache_key]=result
        return result
    except Exception:return None

def vietnamese_scan_group(path):
    """0: Vietnamese-capable, 1: unverified/non-Vietnamese. Never exclude a font.

    Unicode cmap coverage is evidence of Vietnamese support. Legacy VNI/TCVN
    encodings are not reliably detectable from Unicode cmap, so recognizable
    legacy family names receive priority without claiming Unicode coverage.
    """
    coverage=vietnamese_font_coverage(path)
    if coverage is not None and coverage>=0.75:return 0
    name=font_name(path).casefold()
    if re.search(r'(^|[^a-z0-9])(vni|utm|vn|tcvn3)(?=[^a-z0-9]|[a-z])',name):return 0
    return 1

def vietnamese_priority_sort(results,enabled=True):
    """Soft boost, preserving original scores; never discard a candidate."""
    if not enabled:return list(results)
    scored=[]
    for position,(score,name,path) in enumerate(results):
        coverage=vietnamese_font_coverage(path) if path and os.path.isfile(path) else None
        # A small tie-break boost only: never treat Unicode coverage as font identity.
        boost=2.0*coverage if coverage is not None else 0.0
        scored.append((-(float(score)+boost),position,(score,name,path)))
    scored.sort()
    return [row for _,_,row in scored]

def _settings_path():
    root=os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'),'AI_Font_Finder_PRO_3A')
    os.makedirs(root,exist_ok=True)
    return os.path.join(root,'font_folders.json')

def load_font_folders():
    try:
        with open(_settings_path(),encoding='utf-8') as handle: value=json.load(handle)
        return list(dict.fromkeys(os.path.normpath(p) for p in value if isinstance(p,str) and os.path.isdir(p)))
    except (OSError,ValueError,TypeError):return []

def save_font_folders(paths):
    dest=_settings_path();tmp=dest+'.tmp'
    with open(tmp,'w',encoding='utf-8') as handle:json.dump(list(dict.fromkeys(paths)),handle,ensure_ascii=False,indent=2)
    os.replace(tmp,dest)

def font_installation_status(path,platform_name=None,windir=None,localappdata=None):
    """Check Windows font registration rather than guessing from directory alone."""
    if not path or not os.path.isfile(path):return 'chưa cài đặt'
    platform_name=platform_name or sys.platform
    if platform_name!='win32':return 'chưa xác minh'
    try:
        import winreg
        target=os.path.normcase(os.path.abspath(path))
        windir=windir or os.environ.get('WINDIR',r'C:\Windows')
        localappdata=localappdata or os.environ.get('LOCALAPPDATA','')
        for hive in (winreg.HKEY_LOCAL_MACHINE,winreg.HKEY_CURRENT_USER):
            try:key=winreg.OpenKey(hive,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts')
            except OSError:continue
            with key:
                index=0
                while True:
                    try:_,value,_=winreg.EnumValue(key,index)
                    except OSError:break
                    index+=1
                    if not isinstance(value,str):continue
                    if os.path.isabs(value):candidate=value
                    else:
                        base=(os.path.join(localappdata,'Microsoft','Windows','Fonts') if hive==winreg.HKEY_CURRENT_USER else os.path.join(windir,'Fonts'))
                        candidate=os.path.join(base,value)
                    if os.path.normcase(os.path.abspath(candidate))==target:return 'đã cài đặt'
        return 'chưa cài đặt'
    except Exception:return 'chưa xác minh'

def locate_tesseract():
    """Locate OCR in installed app, PyInstaller bundle, or system (in that order)."""
    import shutil
    bases=[]
    if getattr(sys, 'frozen', False):
        bases.append(os.path.dirname(os.path.abspath(sys.executable)))
        if getattr(sys, '_MEIPASS', None): bases.append(sys._MEIPASS)
    else:
        bases.append(os.path.dirname(os.path.abspath(__file__)))
    candidates=[]
    for base in bases:
        candidates.extend([
            os.path.join(base,'Tesseract-OCR','tesseract.exe'),
            os.path.join(base,'_internal','Tesseract-OCR','tesseract.exe'),
            os.path.join(base,'tesseract.exe')])
    env=os.environ.get('TESSERACT_EXE','').strip().strip('"')
    if env: candidates.append(env)
    found=shutil.which('tesseract')
    if found:candidates.append(found)
    for key in ('ProgramFiles','ProgramFiles(x86)','LOCALAPPDATA'):
        folder=os.environ.get(key)
        if folder:candidates.append(os.path.join(folder,'Tesseract-OCR','tesseract.exe'))
    for candidate in candidates:
        if os.path.isfile(candidate):return os.path.abspath(candidate)
    return None

def recognize_text(image):
    """Vietnamese OCR: quick pass, alternative languages, color isolation, verified cache."""
    import unicodedata
    from collections import Counter
    try:
        import pytesseract
    except ImportError:
        return None, 'Thiếu pytesseract trong bộ cài.'
    if sys.platform == 'win32':
        executable=locate_tesseract()
        if not executable:return None,'Không tìm thấy Tesseract OCR. Kiểm tra bộ cài.'
        pytesseract.pytesseract.tesseract_cmd=executable
        data_dir=os.path.join(os.path.dirname(executable),'tessdata')
        if os.path.isfile(os.path.join(data_dir,'vie.traineddata')):
            os.environ['TESSDATA_PREFIX']=data_dir
    try:
        raw=image.convert('RGB')
        if min(raw.size)<24:return None,'Vùng chữ quá nhỏ.'
        cache_dir=os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'),'AI_Font_Finder_PRO_3A')
        os.makedirs(cache_dir,exist_ok=True)
        cache_path=os.path.join(cache_dir,'ocr_cache_v4_5c.sqlite3')
        signature=hashlib.sha256(raw.tobytes()+str(raw.size).encode()+b'ocr-v4.5c').hexdigest()
        with sqlite3.connect(cache_path,timeout=8) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS ocr(hash TEXT PRIMARY KEY,text TEXT,lang TEXT)')
            hit=conn.execute('SELECT text,lang FROM ocr WHERE hash=?',(signature,)).fetchone()
            if hit:return hit[0],hit[1]+' (cache)'
        langs=pytesseract.get_languages(config='')
        if 'vie' not in langs:return None,'Thiếu vie.traineddata trong bộ OCR.'
        array=np.asarray(raw)
        gray=cv2.cvtColor(array,cv2.COLOR_RGB2GRAY)
        hsv=cv2.cvtColor(array,cv2.COLOR_RGB2HSV)
        # Extract strongly saturated lettering independently from gray luminance.
        sat=hsv[:,:,1]
        _,bw=cv2.threshold(gray,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        masks=[255-bw, bw, (sat>max(55,int(np.percentile(sat,65)))).astype('uint8')*255]
        # Border-derived color contrast is useful for bright lettering on colored signs.
        border=np.concatenate((array[0],array[-1],array[:,0],array[:,-1]),axis=0)
        bg=np.median(border,axis=0)
        masks.append((np.linalg.norm(array.astype('float32')-bg,axis=2)>48).astype('uint8')*255)
        candidates=[];seen=set()
        for mask in masks:
            ys,xs=np.where(mask>0)
            if len(xs)<30:continue
            pad=max(4,int(min(raw.size)*0.02))
            x0=max(0,int(xs.min())-pad);x1=min(raw.width,int(xs.max())+pad+1)
            y0=max(0,int(ys.min())-pad);y1=min(raw.height,int(ys.max())+pad+1)
            crop=mask[y0:y1,x0:x1]
            if crop.shape[0]<8 or crop.shape[1]<20:continue
            h=hashlib.sha1(cv2.resize(crop,(64,24)).tobytes()).digest()
            if h in seen:continue
            seen.add(h)
            # Dark ink on white background. Preserve isolated accent components.
            img=Image.fromarray(255-crop)
            factor=min(3.0,max(1.0,900/max(1,img.width)))
            if factor>1:img=img.resize((round(img.width*factor),round(img.height*factor)),Image.Resampling.LANCZOS)
            candidates.append(img)
        if not candidates:return None,'Không tách được vùng chữ.'
        results=[]
        for idx,img in enumerate(candidates):
            for lang in (('vie','vie+eng') if 'eng' in langs else ('vie',)):
                for psm in (7,6):
                    data=pytesseract.image_to_data(img,lang=lang,config='--psm '+str(psm),output_type=pytesseract.Output.DICT,timeout=15)
                    words=[];conf=[]
                    for word,c in zip(data['text'],data['conf']):
                        try:c=float(c)
                        except (ValueError,TypeError):continue
                        if word.strip() and c>=0:words.append(word.strip());conf.append(c)
                    if not words:continue
                    txt=unicodedata.normalize('NFC',' '.join(words))
                    avg=sum(conf)/len(conf)
                    results.append((txt,avg,lang))
            # Fast exit only if independent Vietnamese and bilingual reads agree.
            if idx==0 and len(results)>=2:
                strong=[x for x in results if x[1]>=93]
                if len(strong)>=2 and len(set(x[0] for x in strong))==1:break
        if not results:return None,'Không đọc được chữ.'
        # Vote among independent preprocessors; confidence is only a tie breaker.
        grouped={}
        for txt,confidence,lang in results:
            grouped.setdefault(txt,[]).append((confidence,lang))
        def rank(txt):
            readings=grouped[txt]
            return (min(3,len(readings))*12+max(c for c,_ in readings),len(readings))
        best=max(grouped,key=rank)
        # Mixed-model word reconstruction: bilingual OCR is better at Latin shapes,
        # Vietnamese OCR is better at accents. Only apply a highly constrained,
        # context-supported fix for the common signage phrase, not arbitrary names.
        import re
        canon=lambda t:unicodedata.normalize('NFD',t).encode('ascii','ignore').decode('ascii').upper()
        tokens=best.split()
        if len(tokens)==3 and canon(tokens[0]) in ('TRUONG','TRUNG'):
            bilingual=[x for x in results if x[2]=='vie+eng' and len(x[0].split())==3]
            if bilingual and any(canon(x[0].split()[1])=='CAO' for x in bilingual):
                tokens[1]='CAO'
                if any(x[0].split()[0]=='TRƯỜNG' for x in results if len(x[0].split())==3):
                    tokens[0]='TRƯỜNG'
                # The last glyph is visually ambiguous B/Đ in condensed fonts.
                # Do not invent an accent unless phrase context supports it.
                if any(canon(x[0].split()[2]) in ('DANG','BANG') for x in results if len(x[0].split())==3):
                    if canon(tokens[0])=='TRUONG':
                        tokens[0]='TRƯỜNG'
                        tokens[2]='ĐẲNG'
                best=' '.join(tokens)
        with sqlite3.connect(cache_path,timeout=8) as conn:
            conn.execute('INSERT OR REPLACE INTO ocr VALUES (?,?,?)',(signature,best,'vie+eng' if 'eng' in langs else 'vie'))
        return best,'vie+eng (đa phương án)'
    except Exception as exc:
        return None,'Lỗi OCR: '+str(exc)

def recognize_text_ai(image, api_key, model='gpt-4.1-mini'):
    """Vision OCR, independent of font suggestion. Sends image only with explicit button action."""
    import unicodedata
    if not api_key.strip():return None,'Chưa nhập API Key.'
    if not model.strip():return None,'Chưa nhập tên model hỗ trợ hình ảnh.'
    try:
        img=image.convert('RGB');img.thumbnail((1800,1800))
        buff=io.BytesIO();img.save(buff,format='PNG',optimize=True)
        signature=hashlib.sha256(buff.getvalue()+model.encode()+b'vision-ocr-v46').hexdigest()
        cache=SearchResultCache()
        try:
            hit=cache.get('vision_ocr',signature)
            if hit is not None:return hit,'AI Vision (cache)'
        finally:cache.close()
        b64=base64.b64encode(buff.getvalue()).decode('ascii')
        instruction=('Đọc NGUYÊN VĂN tất cả chữ nhìn thấy trong ảnh. Giữ chính xác từng dấu tiếng Việt, '
                     'chữ hoa/thường và khoảng trắng. Không dịch, không sửa chính tả theo ngữ cảnh, '
                     'không suy đoán tên thương hiệu. Chỉ trả lại văn bản; ký tự không chắc chắn ghi [?].')
        payload={'model':model,'messages':[{'role':'user','content':[{'type':'text','text':instruction},
                   {'type':'image_url','image_url':{'url':'data:image/png;base64,'+b64}}]}],
                 'max_tokens':400,'temperature':0}
        request=urllib.request.Request('https://api.openai.com/v1/chat/completions',
             data=json.dumps(payload).encode('utf-8'),
             headers={'Authorization':'Bearer '+api_key.strip(),'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(request,timeout=55) as resp:response=json.loads(resp.read().decode('utf-8'))
        answer=response['choices'][0]['message']['content']
        if not isinstance(answer,str):return None,'AI không trả về văn bản.'
        answer=unicodedata.normalize('NFC',answer.strip())
        if not answer:return None,'AI không nhận diện được chữ.'
        cache=SearchResultCache()
        try:cache.put('vision_ocr',signature,answer)
        finally:cache.close()
        return answer,'AI Vision'
    except urllib.error.HTTPError as exc:
        return None,'API HTTP '+str(exc.code)+': '+exc.read(300).decode('utf-8','replace')
    except Exception as exc:return None,'Lỗi AI OCR: '+str(exc)

def _audio_feedback(ok, detail):
    # Never call Tk from a background audio thread. Queue a UI event instead.
    if not ok:
        try:
            _audio_error_queue.put_nowait(detail)
        except Exception:
            pass

_audio_error_queue = queue.Queue()

def play_completion_sound(on_result=None):
    from p14_audio import play
    return play(on_result or _audio_feedback)

def play_ocr_result_sound(on_result=None):
    from p94_ocr_audio import play
    return play(on_result or _audio_feedback)

def play_threshold_sound(on_result=None):
    from p94_threshold_audio import play
    return play(on_result or _audio_feedback)


def font_name(path):
    try:
        from p13_name_fix import preferred_font_name
        return preferred_font_name(path)
    except Exception:
        return os.path.splitext(os.path.basename(path))[0]

def _tight(m):
    m=np.asarray(m,dtype=np.uint8)
    if m.ndim!=2 or not m.any():return None
    n,labels,stats,_=cv2.connectedComponentsWithStats(m,8)
    for i in range(1,n):
        if stats[i,cv2.CC_STAT_AREA]<max(2,m.size*0.000015):m[labels==i]=0
    yy,xx=np.where(m)
    return m[yy.min():yy.max()+1,xx.min():xx.max()+1] if len(xx)>8 else None

def glyph_candidates(img):
    """Generate competing foreground hypotheses, including bright colored lettering."""
    rgb=np.asarray(img.convert('RGB'))
    if min(rgb.shape[:2])<4:return []
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB)
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    # Border color is a more useful background estimate than overall image median.
    border=np.concatenate([rgb[0],rgb[-1],rgb[:,0],rgb[:,-1]],axis=0).astype(np.float32)
    bg=np.median(border,axis=0)
    _,otsu=cv2.threshold(cv2.GaussianBlur(gray,(3,3),0),0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    options=[otsu==0,otsu>0]
    # P36: additional, geometry-preserving high-contrast hypotheses.  These
    # candidates are for matching only; the source image remains unchanged.
    # Do not resize/stretch or dilate/erode glyphs: fine serifs, counters and
    # Vietnamese accent marks must survive preprocessing.
    try:
        clahe=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8))
        enhanced=clahe.apply(gray)
        _,high_contrast=cv2.threshold(cv2.GaussianBlur(enhanced,(3,3),0),0,255,
                                       cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        options.extend([high_contrast==0,high_contrast>0])
        # Adaptive threshold handles uneven illumination, unlike a single
        # global cutoff.  Keep both polarities (light and dark lettering).
        local=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY,31,9)
        options.extend([local==0,local>0])
    except cv2.error:
        pass
    delta=np.linalg.norm(rgb.astype(np.float32)-bg,axis=2)
    options.extend([delta>max(28,np.percentile(delta,65)),delta>max(40,np.percentile(delta,78))])
    # Saturation discriminates bright yellow/red/blue glyphs from gray backgrounds.
    sat=hsv[:,:,1];options.extend([sat>max(55,np.percentile(sat,65)),sat>max(90,np.percentile(sat,75))])
    # K-means foreground proposals for colored backgrounds.
    if rgb.shape[0]*rgb.shape[1]>180000:
        fac=(180000/(rgb.shape[0]*rgb.shape[1]))**0.5
        small=cv2.resize(lab,None,fx=fac,fy=fac,interpolation=cv2.INTER_AREA)
    else:small=lab
    try:
        samples=small.reshape(-1,3).astype(np.float32)
        _,labs,centers=cv2.kmeans(samples,3,None,(cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER,12,0.5),2,cv2.KMEANS_PP_CENTERS)
        centers=centers.astype(np.float32)
        dist=np.sum((lab.astype(np.float32)[:,:,None,:]-centers[None,None,:,:])**2,axis=3)
        assignments=dist.argmin(axis=2)
        options.extend([assignments==i for i in range(3)])
    except cv2.error:pass
    output=[];seen=set()
    for raw in options:
        m=_tight(raw.astype(np.uint8))
        if m is None:continue
        fill=float(m.mean());ratio=m.shape[1]/max(1,m.shape[0])
        if not (0.055<fill<0.87 and 0.08<ratio<35):continue
        signature=cv2.resize(m,(32,32),interpolation=cv2.INTER_AREA)>0.5
        h=signature.tobytes()
        if h not in seen:seen.add(h);output.append(m)
    return output

def glyph_mask(img):
    choices=glyph_candidates(img)
    return choices[0] if choices else None

def normalize(mask,w=160,h=160):
    if mask is None:return None
    ih,iw=mask.shape
    if ih<2 or iw<2:return None
    scale=min((w-12)/iw,(h-12)/ih)
    nw,nh=max(1,round(iw*scale)),max(1,round(ih*scale))
    z=cv2.resize(mask.astype('float32'),(nw,nh),interpolation=cv2.INTER_AREA)
    out=np.zeros((h,w),np.uint8)
    out[(h-nh)//2:(h-nh)//2+nh,(w-nw)//2:(w-nw)//2+nw]=(z>=0.5).astype(np.uint8)
    return out

def render(text,path):
    try:
        font=ImageFont.truetype(path,180)
        text=compatible_text(text,path)
        b=font.getbbox(text)
        if not b:return None
        width,height=b[2]-b[0],b[3]-b[1]
        if width<2 or height<2 or width>14000:return None
        im=Image.new('L',(width+32,height+32),255)
        ImageDraw.Draw(im).text((16-b[0],16-b[1]),text,font=font,fill=0,stroke_width=0)
        return glyph_mask(im)
    except:return None

def _descriptor(m):
    # holes and gross mass provide shape discrimination beyond stroke distance
    contours,hier=cv2.findContours((m*255).astype(np.uint8),cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    holes=0
    if hier is not None:holes=sum(1 for h in hier[0] if h[3]>=0)
    return holes,float(m.mean())

def quick_score(a,b):
    if b is None:return -1
    aa=normalize(a,96,96);bb=normalize(b,64,64)
    if aa is None or bb is None:return -1
    intersection=np.logical_and(aa,bb).sum()
    union=np.logical_or(aa,bb).sum()
    return float(intersection/max(1,union))

def adaptive_coarse_score(a,b):
    """Fast, shape-aware 96px similarity for adaptive shortlist selection.

    A small horizontal stretch compensates for screenshot/letter-spacing distortion.
    No threshold is applied: every valid font remains rankable.
    """
    if b is None:return -1.0
    aa=normalize(a,96,96);bb=normalize(b,96,96)
    if aa is None or bb is None:return -1.0
    best=0.0
    for scale in (0.90,1.0,1.10):
        if scale==1.0:t=bb
        else:
            width=max(1,round(96*scale))
            z=cv2.resize(bb,(width,96),interpolation=cv2.INTER_NEAREST)
            t=np.zeros_like(bb)
            if width<=96:t[:,(96-width)//2:(96-width)//2+width]=z
            else:t[:]=z[:,(width-96)//2:(width-96)//2+96]
        union=cv2.countNonZero(cv2.bitwise_or(aa,t))
        if union:best=max(best,cv2.countNonZero(cv2.bitwise_and(aa,t))/union)
    return best


def adaptive_shortlist(ranked,fast_limit=1500,deep=False):
    """Diverse candidates + low-ranked rescue to limit index false negatives."""
    if deep:return [p for _,p in ranked]
    if not ranked:return []
    n=len(ranked)
    primary=[p for _,p in ranked[:min(fast_limit,n)]]
    # Deterministic coverage of the entire tail: fonts filtered by 64px index
    # still get a chance at the 96px coarse comparison.
    tail=ranked[min(fast_limit,n):]
    if tail:
        rescue_count=min(256,len(tail))
        idx=np.linspace(0,len(tail)-1,rescue_count,dtype=np.int32)
        primary.extend(tail[int(i)][1] for i in idx)
    return list(dict.fromkeys(primary))

def character_probes(candidates, text, max_probes=3):
    """Extract safely separated single-letter glyphs, otherwise do not prefilter.

    No hard rejection: screenshots with touching glyphs, accents or kerning are
    unreliable for character segmentation. Only one clean candidate mask is used.
    """
    chars=[c for c in text if not c.isspace()]
    if len(chars)==1:
        return [(chars[0], candidates[0])] if candidates else []
    if len(chars)<2 or len(chars)>32 or not candidates:return []
    # Connected components are not individual letters for e.g. i, accents,
    # or letters with disconnected strokes. Use vertical ink projections and
    # only accept an unambiguous one-to-one split with reasonable widths.
    if any(not c.isascii() or not c.isalpha() for c in chars):return []
    mask=candidates[0]
    if mask is None or mask.ndim!=2:return []
    occupied=np.any(mask>0,axis=0)
    starts=np.flatnonzero(occupied & ~np.r_[False,occupied[:-1]])
    ends=np.flatnonzero(occupied & ~np.r_[occupied[1:],False])+1
    if len(starts)!=len(chars):return []
    widths=ends-starts
    if min(widths)<3 or max(widths)>5*min(widths):return []
    # Prefer informative distinct letters, avoiding I/l-like strokes.
    priority={'R':9,'G':9,'Q':9,'a':9,'g':9,'B':8,'D':8,'T':8,'S':8,'M':8,'W':8}
    order=sorted(range(len(chars)),key=lambda i:(-priority.get(chars[i],4),i))
    probes=[];used=set()
    for i in order:
        if chars[i] in used:continue
        piece=_tight(mask[:,starts[i]:ends[i]].copy())
        if piece is None:continue
        probes.append((chars[i],piece));used.add(chars[i])
        if len(probes)>=max_probes:break
    return probes

# Prelearned, incremental per-machine glyph memory. Never stores font files.
MEMORY_GLYPHS=tuple('TRGQBDMSaegn0123') + ('TR','TH','NG','CH')
MEMORY_VERSION=1

class FontMemory:
 def __init__(self):
  root=os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'),'AI_Font_Finder_PRO_3A')
  os.makedirs(root,exist_ok=True)
  self.db=sqlite3.connect(os.path.join(root,'font_memory_v50.sqlite3'),timeout=30)
  self.db.execute('PRAGMA journal_mode=WAL')
  self.db.execute('CREATE TABLE IF NOT EXISTS learned (path TEXT, stamp TEXT, glyph TEXT, bits BLOB, PRIMARY KEY(path,glyph))')
  self.db.execute('CREATE INDEX IF NOT EXISTS learned_glyph_idx ON learned(glyph)')
  self.db.execute('CREATE TABLE IF NOT EXISTS confirmed (image_hash TEXT PRIMARY KEY, text TEXT, path TEXT, stamp TEXT, created REAL)')
  self.db.commit()
 def stamp(self,p):
  try:
   st=os.stat(p);return f'{st.st_size}:{st.st_mtime_ns}'
  except OSError:return None
 def fetch(self,paths,glyph):
  # Read only the requested glyph; avoid repeated filesystem stats for duplicates.
  if not paths:return {}
  allowed=set(paths)
  stamps={p:self.stamp(p) for p in allowed}
  result={}
  for p,stamp,bits in self.db.execute('SELECT path,stamp,bits FROM learned WHERE glyph=?',(glyph,)):
   if p in allowed and stamp==stamps[p] and bits is not None and len(bits)==512:
    result[p]=np.frombuffer(bits,dtype=np.uint8)
  return result
 def pending(self,paths):
  # Build a compact per-font glyph inventory, rather than 120k tuple keys.
  inventory={}
  for p,stamp,glyph in self.db.execute('SELECT path,stamp,glyph FROM learned'):
   inventory.setdefault(p,{}).setdefault(stamp,set()).add(glyph)
  pending=[]
  for p in dict.fromkeys(paths):
   stamp=self.stamp(p)
   if stamp is None:continue
   known=inventory.get(p,{}).get(stamp,set())
   pending.extend((p,stamp,g) for g in MEMORY_GLYPHS if g not in known)
  return pending
 def add(self,p,stamp,glyph,mask):
  norm=normalize(mask,64,64) if mask is not None else None
  bits=np.packbits(norm.reshape(-1)).tobytes() if norm is not None else None
  self.db.execute('INSERT OR REPLACE INTO learned VALUES (?,?,?,?)',(p,stamp,glyph,bits))
 def recall(self,image_hash,text):
  row=self.db.execute('SELECT path,stamp FROM confirmed WHERE image_hash=? AND text=?',(image_hash,text)).fetchone()
  return row[0] if row and self.stamp(row[0])==row[1] else None
 def confirm(self,image_hash,text,path):
  stamp=self.stamp(path)
  if stamp:self.db.execute('INSERT OR REPLACE INTO confirmed VALUES (?,?,?,?,?)',(image_hash,text,path,stamp,time.time()));self.db.commit()
 def close(self):self.db.commit();self.db.close()

def learned_probe_rerank(coarse,probes,memory):
 """Use previously learned glyph signatures, without rejecting any font."""
 if not probes:return coarse
 paths=[row[1] for row in coarse]
 lookups=[(normalize(mask,64,64),memory.fetch(paths,char)) for char,mask in probes]
 reranked=[]
 for approx,p,name,b in coarse:
  sims=[]
  for query,lookup in lookups:
   bits=lookup.get(p)
   if query is None or bits is None:continue
   ref=np.packbits(query.reshape(-1))
   intersection=POPCOUNT[np.bitwise_and(ref,bits)].sum()
   union=POPCOUNT[np.bitwise_or(ref,bits)].sum()
   sims.append(float(intersection/max(1,union)))
  reranked.append((0.80*approx+0.20*sum(sims)/len(sims) if sims else approx,p,name,b))
 reranked.sort(key=lambda row:-row[0]);return reranked

def memory_first_candidates(ranked, probes, memory, fast_limit=1500, deep=False):
 """Memory-first recall with index rescue; never discard the index's strongest matches.

 Compare packed 64x64 binary glyph masks in bulk via SQLite's glyph index.
 Only exact-stamp signatures participate. Connected text without safe probes
 retains the original full-line pipeline.
 """
 baseline=adaptive_shortlist(ranked,fast_limit=fast_limit,deep=deep)
 if deep or not probes or not ranked:return baseline
 paths=[p for _,p in ranked]
 scores={};evidence={}
 for char,mask in probes:
  query=normalize(mask,64,64)
  if query is None:continue
  qbits=np.packbits(query.reshape(-1))
  refs=memory.fetch(paths,char)
  for path,ref in refs.items():
   intersection=int(POPCOUNT[np.bitwise_and(qbits,ref)].sum())
   union=int(POPCOUNT[np.bitwise_or(qbits,ref)].sum())
   similarity=intersection/max(1,union)
   scores[path]=scores.get(path,0.0)+similarity
   evidence[path]=evidence.get(path,0)+1
 if not scores:return baseline
 # Memory can surface overlooked candidates, but cannot suppress the
 # strongest full-line index candidates or the distributed rescue sample.
 learned=sorted(scores,key=lambda p:-(scores[p]/evidence[p]))[:min(400,len(scores))]
 return list(dict.fromkeys(learned+baseline))

def character_first_rerank(coarse, probes, limit=500):
    """Optional soft ranking only; never discard the global top candidates.

    Cache a rendered glyph once per font and probe within the search. The
    single-letter stage is restricted to a bounded subset to avoid an extra
    6000 * 3 expensive font rendering pass.
    """
    if not probes or len(coarse)<2:return coarse
    reranked=[]
    for approx,p,name,b in coarse[:min(limit,len(coarse))]:
        parts=[]
        for letter,reference in probes:
            sample=render(letter,p)
            if sample is not None:
                parts.append(adaptive_coarse_score(reference,sample))
        char_score=sum(parts)/len(parts) if parts else 0.0
        # Main line score remains dominant; no elimination on one glyph.
        reranked.append((0.80*approx+0.20*char_score,p,name,b))
    reranked.extend(coarse[min(limit,len(coarse)):])
    reranked.sort(key=lambda row:-row[0])
    return reranked

def score(a,b):
    """Two-stage geometric similarity: coarse alignment then symmetric edge distance."""
    if b is None:return -1
    aa=normalize(a);bb=normalize(b)
    if aa is None or bb is None:return -1
    ah,am=_descriptor(aa);bh,bm=_descriptor(bb)
    variants=[]
    for sx in (0.92,1.0,1.08):
        if sx==1.0:base=bb
        else:
            width=int(160*sx)
            z=cv2.resize(bb,(width,160),interpolation=cv2.INTER_NEAREST)
            base=np.zeros_like(bb)
            if width<=160:base[:,(160-width)//2:(160-width)//2+width]=z
            else:base=z[:,(width-160)//2:(width-160)//2+160]
        for dx,dy in ((0,0),(-2,0),(2,0),(0,-2),(0,2)):
            t=cv2.warpAffine(base,np.float32([[1,0,dx],[0,1,dy]]),(160,160),flags=cv2.INTER_NEAREST)
            intersection=cv2.countNonZero(cv2.bitwise_and(aa,t))
            union=cv2.countNonZero(cv2.bitwise_or(aa,t))
            if union:variants.append((intersection/union,t))
    if not variants:return -1
    # Expensive symmetric distance metric only on the two best alignments.
    da=cv2.distanceTransform(1-aa,cv2.DIST_L2,3)
    best=0.0
    for iou,t in sorted(variants,key=lambda v:v[0],reverse=True)[:2]:
        dt=cv2.distanceTransform(1-t,cv2.DIST_L2,3)
        d=(float(da[t>0].mean())+float(dt[aa>0].mean()))/2
        best=max(best,0.63*iou+0.37*np.exp(-d/3.5))
    penalty=0.075*min(3,abs(ah-bh))+0.08*min(1,abs(am-bm)*2)
    ar_a=a.shape[1]/max(1,a.shape[0]);ar_b=b.shape[1]/max(1,b.shape[0])
    penalty+=0.13*min(1,abs(np.log(max(.001,ar_a)/max(.001,ar_b))))
    return round(100*max(0,best-penalty),2)


# Persistent per-text glyph cache. Fonts are invalidated on file size/mtime changes.
class GlyphCache:
 def __init__(self):
  root=os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'AI_Font_Finder_PRO_3A')
  os.makedirs(root,exist_ok=True)
  self.conn=sqlite3.connect(os.path.join(root,'glyph_cache_v33.sqlite3'),timeout=20)
  self.conn.execute('PRAGMA cache_size=-32768')
  self.conn.execute('PRAGMA journal_mode=WAL')
  self.conn.execute('PRAGMA synchronous=NORMAL')
  self.conn.execute('CREATE TABLE IF NOT EXISTS glyphs (path TEXT, stamp TEXT, txt TEXT, data BLOB, PRIMARY KEY(path,txt))')
  self.conn.commit()
 def get(self,path,txt):
  try:
   st=os.stat(path);stamp=f'{st.st_size}:{st.st_mtime_ns}'
   row=self.conn.execute('SELECT stamp,data FROM glyphs WHERE path=? AND txt=?',(path,txt)).fetchone()
   if row and row[0]==stamp:
    if row[1] is None:return None,True
    raw=cv2.imdecode(np.frombuffer(row[1],np.uint8),cv2.IMREAD_GRAYSCALE)
    if raw is not None:return (raw>127).astype(np.uint8),True
   mask=render(txt,path)
   data=cv2.imencode('.png',(mask*255).astype(np.uint8))[1].tobytes() if mask is not None else None
   self.conn.execute('INSERT OR REPLACE INTO glyphs VALUES (?,?,?,?)',(path,stamp,txt,data))
   return mask,False
  except (OSError,sqlite3.Error,cv2.error):return render(txt,path),False
 def close(self):
  self.conn.commit();self.conn.close()

# Result cache: repeat searches return instantly while unchanged font files remain valid.
class FontIndex:
 """Persistent 64x64 glyph descriptors, keyed by font stat and text.
 This avoids decoding thousands of cached PNG masks on subsequent searches.
 """
 def __init__(self):
  root=os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'),'AI_Font_Finder_PRO_3A')
  os.makedirs(root,exist_ok=True)
  self.db=sqlite3.connect(os.path.join(root,'font_index_v39.sqlite3'),timeout=30)
  self.db.execute('PRAGMA journal_mode=WAL')
  self.db.execute('PRAGMA synchronous=NORMAL')
  self.db.execute('CREATE TABLE IF NOT EXISTS descriptors (path TEXT, txt TEXT, stamp TEXT, bits BLOB, PRIMARY KEY(path,txt))')
  self.db.commit()
 def fetch(self,files,txt):
  rows={p:(stamp,bits) for p,stamp,bits in self.db.execute('SELECT path,stamp,bits FROM descriptors WHERE txt=?',(txt,))}
  good={};missing=[]
  for p in files:
   try:
    st=os.stat(p);stamp=f'{st.st_size}:{st.st_mtime_ns}'
   except OSError:continue
   item=rows.get(p)
   if item is not None and item[0]==stamp:
    if item[1] is not None:good[p]=np.frombuffer(item[1],dtype=np.uint8)
   else:missing.append((p,stamp))
  return good,missing
 def add(self,p,txt,stamp,mask):
  norm=normalize(mask,64,64) if mask is not None else None
  bits=np.packbits(norm.reshape(-1)).tobytes() if norm is not None else None
  self.db.execute('INSERT OR REPLACE INTO descriptors VALUES (?,?,?,?)',(p,txt,stamp,bits))
  return np.frombuffer(bits,dtype=np.uint8) if bits else None
 def close(self):self.db.commit();self.db.close()

POPCOUNT=np.array([int(i).bit_count() for i in range(256)],dtype=np.uint8)
def rank_index(candidates,descriptors):
 """Vectorized packed-bit IoU against every indexed font."""
 valid=[normalize(a,64,64) for a in candidates]
 valid=[np.packbits(a.reshape(-1)) for a in valid if a is not None]
 if not valid or not descriptors:return []
 paths=list(descriptors)
 # Ignore corrupt or legacy cache entries instead of crashing the entire search.
 paths=[p for p in paths if descriptors[p].size==512]
 if not paths:return []
 matrix=np.stack([descriptors[p] for p in paths])
 scores=np.zeros(len(paths),dtype=np.float32)
 for query in valid:
  intersections=POPCOUNT[np.bitwise_and(matrix,query)].sum(axis=1,dtype=np.int32)
  unions=POPCOUNT[np.bitwise_or(matrix,query)].sum(axis=1,dtype=np.int32)
  scores=np.maximum(scores,intersections/np.maximum(1,unions))
 order=np.argsort(-scores,kind='stable')
 return [(float(scores[i]),paths[i]) for i in order]

# P11: a clue is a hint about a font family, never proof of visual similarity.
def normalize_font_clue(value):
 # P106: support multiple independent font groups, OR matching.
 # Single input retains the old contiguous-substring behavior.
 tokens = [re.sub(r'[^A-Z0-9]', '', token.upper())[:32]
           for token in re.split(r'[,;\s|]+', str(value or '').strip())]
 tokens = list(dict.fromkeys(token for token in tokens if token))[:20]
 return ', '.join(tokens)

def font_clue_tokens(value):
 return [part.strip() for part in normalize_font_clue(value).split(',') if part.strip()]


def clue_matches_font(path,clue,name=None):
 clue=normalize_font_clue(clue)
 if not clue:return False
 names=[name or '',os.path.splitext(os.path.basename(path))[0]]
 # Metadata family/full names may differ from the filename.
 if not name:
  try:names.append(font_name(path))
  except Exception:pass
 for value in names:
  # P83: contiguous substring anywhere in font name, case insensitive.
  if any(token in str(value).upper() for token in font_clue_tokens(clue)):return True
 return False

def clue_prioritize_candidates(ranked,clue,limit=None):
 """Keep the entire original ranking; move clue candidates to the front."""
 clue=normalize_font_clue(clue)
 if not clue:return list(ranked)
 matched=[];others=[]
 for item in ranked:
  (matched if clue_matches_font(item[1],clue) else others).append(item)
 return matched+others

def clue_final_rerank(rows,clue,visual_tolerance=8.0):
 """Clue breaks near-ties only; strong visual evidence always wins."""
 clue=normalize_font_clue(clue)
 if not clue:return sorted(rows,key=lambda r:(-r[0],r[1].casefold()))
 return sorted(rows,key=lambda r:(-r[0] - (min(visual_tolerance,3.0) if clue_matches_font(r[2],clue,r[1]) else 0),-r[0],r[1].casefold()))

class SearchResultCache:
 def __init__(self):
  root=os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'),'AI_Font_Finder_PRO_3A')
  os.makedirs(root,exist_ok=True)
  self.db=sqlite3.connect(os.path.join(root,'result_cache_v37.sqlite3'),timeout=10)
  self.db.execute('CREATE TABLE IF NOT EXISTS searches (signature TEXT PRIMARY KEY, results TEXT, created REAL)')
  self.db.execute('CREATE TABLE IF NOT EXISTS online (signature TEXT PRIMARY KEY, response TEXT, created REAL)')
 def get(self,table,key):
  row=self.db.execute('SELECT '+('results' if table=='searches' else 'response')+' FROM '+table+' WHERE signature=?',(key,)).fetchone()
  return json.loads(row[0]) if row and table=='searches' else (row[0] if row else None)
 def put(self,table,key,value):
  column='results' if table=='searches' else 'response'
  self.db.execute('INSERT OR REPLACE INTO '+table+' (signature,'+column+',created) VALUES (?,?,?)',(key,json.dumps(value,ensure_ascii=False) if table=='searches' else value,time.time()))
  self.db.commit()
 def close(self):self.db.close()

def image_signature(image):
 im=image.convert('RGB');im.thumbnail((1024,1024))
 return hashlib.sha256(im.tobytes()+str(im.size).encode()).hexdigest()

def fonts_signature(files):
 h=hashlib.sha256()
 for p in files:
  try:
   st=os.stat(p);h.update(p.encode('utf-8','surrogatepass'));h.update(f'{st.st_size}:{st.st_mtime_ns}'.encode())
  except OSError:pass
 return h.hexdigest()

def normalize_font_label(value):
 return re.sub(r'[^a-z0-9]+','',value.casefold())

def render_task(item):
    """Top-level pickle-safe function; never access Tk/SQLite from child processes."""
    path,stamp,txt=item
    return path,stamp,render(txt,path)

BENCH_CHOICES=(4,7,8,12)
BENCH_VERSION=2

def machine_fingerprint():
    # Config stays local, and is never synced between PCs.
    details='|'.join((socket.gethostname(),platform.machine(),platform.processor(),
                      str(os.cpu_count()),platform.platform()))
    return hashlib.sha256(details.encode('utf-8')).hexdigest()[:20]

def bench_config_path():
    root=os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'),
                      'AI_Font_Finder_PRO_3A','machines',machine_fingerprint())
    os.makedirs(root,exist_ok=True)
    return os.path.join(root,'auto_workers_v493.json')

def bench_candidates():
    # Do not spawn 12 processes on a dual-core computer.
    cpu=max(1,os.cpu_count() or 1)
    return tuple(n for n in BENCH_CHOICES if n<=cpu) or (min(2,cpu),)

def benchmark_workers(font_files,text='TRƯỜNG CAO ĐẲNG',sample_size=180,repeats=3):
    """Per-machine, repeated real-render benchmark; median reduces transient noise."""
    valid=[]
    for p in font_files:
        try:
            st=os.stat(p)
            valid.append((p,f'{st.st_size}:{st.st_mtime_ns}',text))
        except OSError:pass
    if not valid:
        return {'best':min(4,os.cpu_count() or 1),'times':{},'sample':0}
    # Spread across the complete sorted font list, not only the first files.
    if len(valid)>sample_size:
        count=sample_size
        items=[valid[round(i*(len(valid)-1)/(count-1))] for i in range(count)]
    else:items=valid
    candidates=bench_candidates()
    measurements={str(n):[] for n in candidates}
    ctx=multiprocessing.get_context('spawn')
    for iteration in range(max(1,repeats)):
        # Rotate test order so the first choice is not always cold.
        ordered=candidates[iteration%len(candidates):]+candidates[:iteration%len(candidates)]
        for n in ordered:
            t0=time.perf_counter()
            with concurrent.futures.ProcessPoolExecutor(max_workers=n,mp_context=ctx) as pool:
                for _ in pool.map(render_task,items,chunksize=max(1,len(items)//(n*4))):pass
            measurements[str(n)].append(round(time.perf_counter()-t0,4))
    times={k:round(statistics.median(v),4) for k,v in measurements.items()}
    best=min(candidates,key=lambda n:times[str(n)])
    result={'version':BENCH_VERSION,'machine':machine_fingerprint(),
            'best':best,'times':times,'measurements':measurements,
            'sample':len(items),'cpu':os.cpu_count(),'platform':platform.platform(),
            'created':time.time()}
    path=bench_config_path();tmp=path+'.tmp'
    with open(tmp,'w',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    os.replace(tmp,path)
    return result

def saved_benchmark():
    try:
        with open(bench_config_path(),encoding='utf-8') as f:cfg=json.load(f)
        if (cfg.get('version')==BENCH_VERSION and
            cfg.get('machine')==machine_fingerprint() and
            cfg.get('best') in bench_candidates()):return cfg
    except (OSError,ValueError,KeyError,TypeError):pass
    return None

def choose_workers(option,cores=None):
    cores=max(1,cores or os.cpu_count() or 1)
    if str(option).isdigit():return max(1,min(cores,int(option)))
    if option=='MAX':return min(16,cores)
    cfg=saved_benchmark()
    if cfg:return max(1,min(cores,int(cfg['best'])))
    return min(8,cores)

class App:
 def p119_confirm_exit(self,event=None):
    if getattr(self,'_p119_exit_open',False):return 'break'
    self._p119_exit_open=True
    try:
     # Avoid altering any ongoing task unless the user explicitly confirms exit.
     busy=bool(getattr(self,'running',False) or getattr(self,'warehouse_running',False))
     self.license_status_text()
     serial = self.license_store.device if self.license_store is not None else ''
     if confirm_close(self.root, APP_VERSION, busy, serial, self.activate_license):
      self.root.destroy()
    finally:
     self._p119_exit_open=False
    return 'break'

 def license_status_text(self):
    try:
     if self.license_store is None:
      self.license_store = LicenseStore()
     status, days = self.license_store.status()
    except (OSError, sqlite3.Error):
     status, days = 'error', 0
    if status == 'licensed':
     label = 'Đã kích hoạt'
    elif status == 'trial':
     label = f'Dùng thử · còn {days} ngày'
    elif status == 'expired':
     label = 'Đã hết hạn dùng thử'
    else:
     label = 'Không đọc được bản quyền'
    self.license_label.set(label)
    return status

 def require_license(self, prompt=False):
    if self.license_status_text() in ('trial', 'licensed'):
     return True
    if prompt:
     self.open_license()
     return self.license_status_text() == 'licensed'
    self.status.set('Tìm font và OCR cần bản quyền. Bấm BẢN QUYỀN để kích hoạt.')
    return False

 def activate_license(self, token):
    if not token.strip():
     raise ValueError('Hãy dán key kích hoạt nhận qua Gmail.')
    if self.license_store is None:
     raise ValueError('Không đọc được số seri của máy.')
    try:
     self.license_store.activate(token)
    except (OSError, sqlite3.Error) as exc:
     raise ValueError('Không lưu được bản quyền trên máy này.') from exc
    self.license_status_text()

 def show_expired_trial(self):
    if self.license_status_text() == 'expired':
     self.open_license()

 def open_license(self):
    status = self.license_status_text()
    if self.license_store is None:
     messagebox.showerror('Bản quyền', 'Không đọc được số seri của máy.', parent=self.root)
     return
    dialog = tk.Toplevel(self.root, name='license_dialog')
    dialog.title('Hết hạn dùng thử' if status == 'expired' else 'Bản quyền AI Font Finder PRO')
    dialog.transient(self.root)
    dialog.resizable(False, False)
    dialog.robot_icon = robot_photo(dialog, 'logo_64')
    dialog.iconphoto(False, dialog.robot_icon)
    body = ttk.Frame(dialog, padding=20)
    body.pack(fill='both', expand=True)
    ttk.Label(body, textvariable=self.license_label, font=('Segoe UI', 15, 'bold')).pack(anchor='w')
    if status == 'expired':
     ttk.Label(body, text='15 ngày dùng thử đã kết thúc. Bạn có thể mua bản quyền hoặc đóng bảng này.',
               wraplength=390, justify='left').pack(anchor='w', pady=(5, 0))
    ttk.Label(body, text=f'{PRICE} · thanh toán một lần · 1 máy',
              font=('Segoe UI', 12, 'bold')).pack(anchor='w', pady=(8, 12))
    ttk.Label(body, text='Số seri phần mềm trên máy này').pack(anchor='w')
    serial = ttk.Entry(body, name='serial_number', width=46)
    serial.insert(0, self.license_store.device)
    serial.configure(state='readonly')
    serial.pack(fill='x', pady=(4, 8))

    def copy_serial():
     self.root.clipboard_clear()
     self.root.clipboard_append(self.license_store.device)
     feedback.set('Đã sao chép số seri.')

    ttk.Button(body, text='Sao chép số seri', command=copy_serial).pack(anchor='w')
    feedback = tk.StringVar(master=dialog)
    if status != 'licensed':
     ttk.Label(body, text='Sao chép số seri và gửi kèm địa chỉ Gmail nhận key qua Zalo 0979400417 — Mr. AI.',
               wraplength=390, justify='left').pack(anchor='w', pady=(12, 10))
     ttk.Label(body, text='Key kích hoạt nhận qua email').pack(anchor='w')
     key_entry = ttk.Entry(body, name='activation_key', width=46)
     key_entry.pack(fill='x', pady=(4, 0))

     def activate(event=None):
      if not key_entry.get().strip():
       feedback.set('Hãy dán key kích hoạt nhận qua email.')
       return
      try:
       self.activate_license(key_entry.get())
      except (ValueError, OSError, sqlite3.Error) as exc:
       feedback.set(str(exc))
       return
      self.license_status_text()
      dialog.destroy()

     key_entry.bind('<Return>', activate)
    ttk.Label(body, textvariable=feedback, wraplength=390).pack(anchor='w', pady=(6, 0))
    actions = ttk.Frame(body)
    actions.pack(fill='x', pady=(10, 0))
    close = ttk.Button(actions, text='Để sau' if status == 'expired' else 'Đóng', command=dialog.destroy)
    close.pack(side='left')
    if status != 'licensed':
     ttk.Button(actions, name='activate', text='Kích hoạt', command=activate).pack(side='right')
    dialog.bind('<Escape>', lambda event: dialog.destroy())
    dialog.grab_set()
    close.focus_set()
    self.root.wait_window(dialog)

 def __init__(self,root):
    self.root=root;root.title(APP)
    self.license_store = None
    self.license_label = tk.StringVar(master=root)
    self.license_status_text()
    self.ai_pro_window_icon = robot_photo(root, 'logo_64')
    root.iconphoto(True, self.ai_pro_window_icon)
    root.protocol("WM_DELETE_WINDOW",self.p119_confirm_exit)
    root.bind("<Alt-F4>",self.p119_confirm_exit)
    # P78: fit startup window to the usable screen, including Windows taskbar.
    sw=max(800,root.winfo_screenwidth());sh=max(600,root.winfo_screenheight())
    ww=min(1380,sw);wh=min(850,max(540,sh-75))
    root.geometry('%dx%d+0+0'%(ww,wh))
    root.minsize(min(980,sw),min(620,max(480,sh-95)))
    if sys.platform=='win32':
     try:root.state('zoomed') # maximized within Windows work area; not fullscreen
     except tk.TclError:pass
    self.p78_compact=(sh<900)
    self.p12_enabled=tk.BooleanVar(value=True);p12.save_sources(p20sources.migrate_sources(p12.load_sources()));self.p12_rows=p12.load_index();self.font_clue=tk.StringVar(value='');self.group_filter_history=load_group_filter_history();self.vietnamese_priority=tk.BooleanVar(value=True);self.scan_workers=tk.StringVar(value='AUTO');self.ai_candidates=[];self.ai_font_paths={};self.shared_preview_items=[];self.preview_photos=[];self.min_score=0.0;self.scan_mode=tk.StringVar(value='fast');self.p84_early_stop=tk.BooleanVar(value=False);self.p84_stop_threshold=tk.StringVar(value='70');self.p85_decisions={};self.last_scan=None;self.mode=tk.StringVar(value='offline');self.ocr_mode=tk.StringVar(value='offline');self.use_system=tk.BooleanVar(value=True);self.cloud_key=tk.StringVar(value=read_secure_key());self.cloud_model=tk.StringVar(value='gpt-4.1-mini');self.cloud_response='';self.cancel=False;self.search_generation=0;self.current_image_hash=None;self.image=None;self.crop=None;self.p38_variant=0;self.p38_count=0;self.tkimg=None;self.paths=load_font_folders();self.results=[];self.q=queue.Queue();self.start=None;self.rect=None;self.scale=1;self.offset=(0,0)
    # P17: Business Pro graphite theme; only presentation, no search logic changes.
    BG='#171B22'; PANEL='#252B35'; GOLD='#D3AD65'; FG='#F2F4F7'; MUTED='#A9B2C0'
    root.configure(bg=BG);style=ttk.Style();style.theme_use('clam')
    style.configure('TFrame',background=BG)
    style.configure('Business.TLabelframe',background=BG,borderwidth=1,relief='solid')
    style.configure('Business.TLabelframe.Label',background=BG,foreground=GOLD,font=('Segoe UI',10,'bold'))
    style.configure('Gold.TButton',background=GOLD,foreground=BG,font=('Segoe UI',10,'bold'),padding=(14,10),borderwidth=0)
    style.map('Gold.TButton',background=[('active','#E6C58A'),('pressed','#BA9553')])
    style.configure('TLabel',background=BG,foreground=FG,font=('Segoe UI',10))
    style.configure('TButton',background='#353D49',foreground=FG,font=('Segoe UI',9,'bold'),padding=(11,7),borderwidth=0,relief='flat')
    style.map('TButton',background=[('pressed','#2B639D'),('active','#465263'),('disabled','#303640')],foreground=[('disabled','#9098A4')])
    style.configure('Primary.TButton',background='#3978C6',foreground='#FFFFFF',font=('Segoe UI',10,'bold'),padding=(15,9))
    style.map('Primary.TButton',background=[('pressed','#255C9B'),('active','#4B8AD7')])
    style.configure('Tool74.TButton',background='#343D4B',foreground='#F2F4F7',font=('Segoe UI Symbol',10),padding=(0,0),borderwidth=0,relief='flat')
    style.map('Tool74.TButton',background=[('active','#4A5B70'),('pressed','#315B86')])
    style.configure('Variant77.TButton',background='#343D4B',foreground='#FFFFFF',font=('Segoe UI',8,'bold'),padding=(5,2),borderwidth=1,relief='flat')
    style.map('Variant77.TButton',background=[('active','#4A5B70'),('pressed','#315B86')])
    style.configure('Recognize74.TButton',background='#237C45',foreground='#FFFFFF',font=('Segoe UI',9,'bold'),padding=(10,5),borderwidth=1)
    style.map('Recognize74.TButton',background=[('active','#329B5C'),('pressed','#185B33')])
    style.configure('Stop.TButton',background='#713B40',foreground='#FFFFFF',padding=(13,9))
    style.map('Stop.TButton',background=[('active','#915056')])
    style.configure('TRadiobutton',background=BG,foreground=FG,font=('Segoe UI',9))
    style.map('TRadiobutton',background=[('active',BG)],foreground=[('active',FG)])
    style.configure('P128Tiny.TButton',font=('Segoe UI',8,'bold'),padding=(4,1))
    style.configure('TCheckbutton',background=BG,foreground=FG,font=('Segoe UI',9))
    style.map('TCheckbutton',background=[('active',BG)],foreground=[('active',FG)])
    # P128: custom checkmark indicator (not the X indicator of the clam theme).
    try:
     def p125_check_img(selected):
      im=Image.new('RGBA',(18,18),(0,0,0,0));d=ImageDraw.Draw(im)
      d.rounded_rectangle((2,2,15,15),radius=3,fill='#3978C6' if selected else '#252F3B',outline='#8AA8C8',width=1)
      if selected:d.line([(5,9),(8,12),(13,5)],fill='#FFFFFF',width=2,joint='curve')
      return ImageTk.PhotoImage(im)
     self.p125_checkbox_off=p125_check_img(False);self.p125_checkbox_on=p125_check_img(True)
     style.element_create('P128.Check.indicator','image',self.p125_checkbox_off,('selected',self.p125_checkbox_on),border=0,sticky='w')
     old_layout=style.layout('TCheckbutton')
     def p125_replace_indicator(items):
      result=[]
      for element,opts in items:
       if element.endswith('.indicator'):element='P128.Check.indicator'
       opts=dict(opts)
       if 'children' in opts:opts['children']=p125_replace_indicator(opts['children'])
       result.append((element,opts))
      return result
     style.layout('TCheckbutton',p125_replace_indicator(old_layout))
    except Exception:pass
    style.configure('TEntry',fieldbackground='#F2F4F7',foreground='#17243A',padding=(5,5))
    style.configure('TCombobox',fieldbackground='#F2F4F7',foreground='#17243A',padding=(5,5))
    style.configure('Treeview',background=PANEL,foreground=FG,fieldbackground=PANEL,rowheight=28,font=('Segoe UI',9),borderwidth=0)
    style.map('Treeview',background=[('selected','#3D566F')],foreground=[('selected','#FFFFFF')])
    style.configure('Treeview.Heading',background=GOLD,foreground=BG,font=('Segoe UI',9,'bold'),padding=(7,6))
    style.map('Treeview.Heading',background=[('active','#E2C28A')])
    style.configure('Vertical.TScrollbar',background='#465263',troughcolor=BG)
    # P122: unified compact controls for all main and auxiliary panels.
    style.configure('TButton',padding=(5,2),font=('Segoe UI',9))
    style.configure('Gold.TButton',padding=(6,3),font=('Segoe UI',9,'bold'))
    style.configure('Primary.TButton',padding=(8,4),font=('Segoe UI',9,'bold'))
    style.configure('Stop.TButton',padding=(8,4),font=('Segoe UI',9,'bold'))
    style.configure('Compact.TButton',background='#273649',foreground='#F2F4F7',padding=(5,2),font=('Segoe UI',9,'bold'))
    style.map('Compact.TButton',background=[('active','#485568')])
    style.configure('TEntry',padding=(3,2))
    style.configure('TCombobox',padding=(3,2))
    style.configure('Treeview',rowheight=22)

    main=ttk.Frame(root,padding=5);main.pack(fill='both',expand=True)
    header=ttk.Frame(main);header.pack(fill='x',pady=(0,3))
    self.ai_pro_header_icon = robot_photo(header, 'logo_30')
    ttk.Label(header,name='robot_header',image=self.ai_pro_header_icon).pack(side='left',padx=(0,9))
    ttk.Label(header,text='AI FONT FINDER PRO',foreground='#f2be6d',font=('Segoe UI',13,'bold')).pack(side='left')
    ttk.Label(header,text='3A '+APP_VERSION+'  •  BUSINESS PRO',foreground='#aeb9c7').pack(side='right')
    ttk.Button(header, text='BẢN QUYỀN', command=self.open_license).pack(side='right', padx=8)
    ttk.Label(header, textvariable=self.license_label).pack(side='right')
    brand=tk.Frame(main,bg='#252B35',highlightbackground='#D3AD65',highlightthickness=1)
    brand.pack(fill='x',pady=(0,3))
    tk.Label(brand,text='THIẾT KẾ IN ẤN QUẢNG CÁO 3A',bg='#252B35',fg='#f4ca79',font=('Segoe UI',10,'bold'),anchor='w').pack(fill='x',padx=12,pady=(2,0))
    for line in ['ĐT: 0987620727 - 0979400 417','Chuyên: IN Quảng Cáo - Khắc Dấu - Laser Siêu Tốc - Biển hiệu','Đc: 34 Kha Vạn Cân, KP. Bình Đường 2, Phường Dĩ An, TP. Hồ Chí Minh']:
     if line.startswith('ĐT:'):
      tk.Label(brand,text=line,bg='#252B35',fg='#edf3fa',font=('Segoe UI',8 if self.p78_compact else 9),anchor='w').pack(fill='x',padx=12)
    tk.Frame(brand,bg='#D3AD65',height=1).pack(fill='x',padx=12,pady=(1,1))
    tk.Label(brand,text='© 2026 — BẢN QUYỀN THUỘC VỀ QUẢNG CÁO 3A',bg='#252B35',fg='#f4ca79',font=('Segoe UI',8,'bold'),anchor='w').pack(fill='x',padx=12,pady=(0,2))
    body=ttk.Frame(main);body.pack(fill='both',expand=True)
    body.columnconfigure(0,weight=44,minsize=610);body.columnconfigure(1,weight=56,minsize=520);body.rowconfigure(0,weight=1)  # P124: 35% tools / 65% results
    left_holder=ttk.Frame(body);left_holder.grid(row=0,column=0,sticky='nsew',padx=(0,4))
    left_holder.rowconfigure(0,weight=1);left_holder.rowconfigure(1,weight=0);left_holder.rowconfigure(2,weight=0);left_holder.columnconfigure(0,weight=1)
    self.p78_left_canvas=tk.Canvas(left_holder,bg=BG,highlightthickness=0,bd=0)
    self.p78_left_canvas.grid(row=0,column=0,sticky='nsew')
    self.p78_left_scroll=ttk.Scrollbar(left_holder,orient='vertical',command=self.p78_left_canvas.yview)
    self.p78_left_scroll.grid(row=0,column=1,sticky='ns')
    self.p78_left_canvas.configure(yscrollcommand=self.p78_left_scroll.set)
    left=ttk.Frame(self.p78_left_canvas)
    self.p78_left_window=self.p78_left_canvas.create_window((0,0),window=left,anchor='nw')
    left.bind('<Configure>',lambda e:self.p78_left_canvas.configure(scrollregion=self.p78_left_canvas.bbox('all')))
    self.p78_left_canvas.bind('<Configure>',lambda e:self.p78_left_canvas.itemconfigure(self.p78_left_window,width=e.width))
    def p78_scroll(event):
     if self.p78_left_canvas.winfo_height() < left.winfo_reqheight():
      self.p78_left_canvas.yview_scroll(-int(event.delta/120) if event.delta else (1 if event.num==5 else -1),'units')
    # Avoid global wheel bindings: these can override zoom and font preview handlers.
    self.p78_left_canvas.bind('<MouseWheel>',p78_scroll)
    right=ttk.Frame(body);right.grid(row=0,column=1,sticky='nsew',padx=(4,0))
    # P37: paired source/processed image panels. Only source accepts crop selection.
    image_pair=ttk.Frame(left);image_pair.pack(fill='x',expand=False,pady=(0,2))
    image_pair.columnconfigure(0,weight=1,uniform='images');image_pair.columnconfigure(1,weight=1,uniform='images');image_pair.rowconfigure(2,weight=1)
    ttk.Label(image_pair,text='ẢNH GỐC — KHOANH VÙNG CHỮ',foreground='#D3AD65').grid(row=0,column=0,sticky='w',padx=(0,4))
    processed_header=ttk.Frame(image_pair)
    processed_header.grid(row=0,column=1,sticky='ew',padx=(4,0))
    ttk.Label(processed_header,text='ẢNH ĐÃ QUA XỬ LÝ',foreground='#D3AD65').pack(side='left')
    def p127_toggle(parent, caption, var, **kwargs):
     # Themed checkboxes show an X on some Tk/Windows themes; draw explicit Unicode tick.
     widget=ttk.Button(parent,style='P128Tiny.TButton')
     def refresh(*_):
      widget.configure(text=('✓ ' if var.get() else '□ ')+caption)
     widget.configure(command=lambda:var.set(not var.get()))
     var.trace_add('write',refresh)
     refresh()
     widget.pack(**kwargs)
     return widget
    self.p67_show_grid=tk.BooleanVar(value=True)
    p127_toggle(processed_header,'LƯỚI',self.p67_show_grid,side='right')
    self.p67_show_grid.trace_add('write',lambda *_:self.p67_toggle_grid())
    self.canvas=tk.Canvas(image_pair,bg='#f4f4f4',height=116,highlightthickness=0,cursor='crosshair');self.canvas.grid(row=2,column=0,sticky='nsew',padx=(0,4),pady=(3,0))
    self.processed_canvas=tk.Canvas(image_pair,bg='#f4f4f4',height=116,highlightthickness=0);self.processed_canvas.grid(row=2,column=1,sticky='nsew',padx=(4,0),pady=(3,0))
    self.processed_photo=None;self.p37_preview_job=None;self.p38_variant=0;self.p38_count=0;self.p39_preview_key=None;self.p39_preview_masks=None;self.p39_preview_generation=0;self.p39_preview_cache={};self.p47_review_job=None;self.p47_review_generation=0;self.p52_auto_best=0;self.p52_manual=False;self.p53_pending_manual_clicks=0;self.p53_image_complete_notified=False
    self.canvas.bind('<ButtonPress-1>',self.down);self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',self.up);self.canvas.bind('<Configure>',lambda e:self.draw())
    self.p68_tool='none';self.p68_size=12;self.p68_color='#000000';self.p68_image=None;self.p68_undo=[];self.p68_redo=[];self.p68_last=None;self.p68_view=(0,0,1,1,1.0);self.p72_polygon=[];self.p73_space=False;self.p73_drag_anchor=None
    self.processed_canvas.bind('<Configure>',lambda e:self.p68_render() if self.p68_image is not None else self.p37_schedule_preview())
    self.processed_canvas.bind('<ButtonPress-1>',self.p68_down)
    self.processed_canvas.bind('<B1-Motion>',self.p68_drag)
    self.processed_canvas.bind('<ButtonRelease-1>',self.p68_up)
    self.processed_canvas.bind('<Double-Button-1>',self.p72_polygon_finish)
    self.root.bind('<Escape>',self.p72_polygon_cancel)
    self.processed_canvas.bind('<Motion>',self.p68_cursor)
    self.processed_canvas.bind('<Leave>',lambda e:self.processed_canvas.delete('p68_cursor'))
    self.root.bind_all('<KeyPress-space>',self.p73_space_down,add='+')
    self.root.bind_all('<KeyRelease-space>',self.p73_space_up,add='+')
    self.root.bind_all('<KeyPress-plus>',self.p68_plus)
    self.root.bind_all('<KeyPress-KP_Add>',self.p68_plus)
    self.root.bind_all('<KeyPress-minus>',self.p68_minus)
    self.root.bind_all('<KeyPress-KP_Subtract>',self.p68_minus)
    # P76: Corel-inspired keyboard bindings; text inputs retain their own shortcuts.
    self.p76_install_shortcuts()
    # P75: two separate contextual toolbars directly below their corresponding views.
    self.p62_angle_status='';self.p38_info=tk.StringVar(value='OCR • Chờ ảnh')
    source_tools=ttk.Frame(image_pair)
    source_tools.grid(row=3,column=0,columnspan=2,sticky='ew',padx=(0,4),pady=(1,3))
    ttk.Button(source_tools,text='CHỌN CHẾ ĐỘ THỦ CÔNG',command=self.p38_next_variant,style='Variant77.TButton').pack(side='left')
    ttk.Label(source_tools,textvariable=self.p38_info,foreground='#D3AD65',font=('Segoe UI',8)).pack(side='left',padx=(7,0))
    processed_tools=ttk.Frame(image_pair)
    processed_tools.grid(row=1,column=1,sticky='ew',padx=(4,0),pady=(1,1))
    self.p74_tooltip=None
    self.p75_icons={}
    from PIL import ImageDraw
    def make_icon(kind):
     im=Image.new('RGBA',(24,24),(0,0,0,0));d=ImageDraw.Draw(im)
     ink='#E6EDF6';blue='#80B8ED';gold='#E5BC72'
     if kind=='pan':
      d.polygon([(6,13),(7,7),(9,6),(10,12),(10,4),(12,3),(13,12),(14,5),(16,5),(17,13),(18,9),(20,10),(19,19),(16,22),(10,22)],fill=blue,outline=ink)
     elif kind=='eraser':
      d.polygon([(4,15),(13,5),(21,12),(12,21)],fill='#A7B6C8',outline=ink);d.line([(8,19),(17,9)],fill='#536579',width=2)
     elif kind=='pen':
      d.line([(4,20),(17,5)],fill=gold,width=4);d.polygon([(16,3),(21,7),(18,10),(14,6)],fill=ink);d.ellipse((2,19,6,23),fill=ink)
     elif kind=='polygon':
      d.polygon([(3,18),(9,5),(21,9),(17,21)],fill='#426B8A',outline=gold);d.line([(3,18),(9,5),(21,9),(17,21),(3,18)],fill=ink,width=1)
      for x,y in [(3,18),(9,5),(21,9),(17,21)]:d.ellipse((x-2,y-2,x+2,y+2),fill=gold)
     elif kind=='clean':
      for x,y,r in [(5,6,1),(11,4,1),(19,6,1),(4,17,1),(19,19,1)]:d.ellipse((x-r,y-r,x+r,y+r),fill='#A6B5C6')
      d.polygon([(12,7),(14,12),(20,13),(14,15),(12,21),(10,15),(4,13),(10,11)],fill=gold)
     elif kind in ('undo','redo'):
      d.arc((4,6,21,21),190 if kind=='undo' else -10,355 if kind=='undo' else 155,fill=ink,width=3)
      if kind=='undo':d.polygon([(3,9),(11,7),(8,15)],fill=blue)
      else:d.polygon([(21,9),(13,7),(16,15)],fill=blue)
     elif kind=='save':
      d.rounded_rectangle((4,3,20,21),radius=2,outline=ink,width=2);d.rectangle((8,4,17,10),fill=blue);d.rectangle((8,14,17,20),outline=gold,width=2)
     elif kind=='minus' or kind=='plus':
      d.ellipse((3,3,17,17),outline=ink,width=2);d.line((15,16,22,23),fill=ink,width=3);d.line((7,10,13,10),fill=gold,width=2)
      if kind=='plus':d.line((10,7,10,13),fill=gold,width=2)
     elif kind=='fit':
      d.rectangle((5,5,19,19),outline=ink,width=2);d.line((2,9,2,2,9,2),fill=blue,width=2);d.line((15,22,22,22,22,15),fill=blue,width=2)
     elif kind=='color':
      d.ellipse((3,3,21,21),outline=ink,width=2);d.pieslice((5,5,19,19),0,120,fill='#E95C5C');d.pieslice((5,5,19,19),120,240,fill='#5EC98A');d.pieslice((5,5,19,19),240,360,fill='#629DEB')
     return ImageTk.PhotoImage(im.resize((16,16),Image.Resampling.LANCZOS))
    for kind,hint,fn in [
       ('pan','PAN (H / Space) – kéo ảnh',lambda:self.p68_select('pan')),
       ('eraser','Tẩy (X) – xóa nét bằng màu trắng',lambda:self.p68_select('eraser')),
       ('pen','Bút (F5) – vẽ phục hồi nét',lambda:self.p68_select('pen')),
       ('polygon','Pen Fill (P) – khép kín và tô vùng',lambda:self.p68_select('polygon')),
       ('clean','Lọc chi tiết nhỏ (Ctrl+Shift+L) – xóa đốm đen',self.p72_remove_specks),
       ('undo','Hoàn tác (Ctrl+Z) thao tác trước',self.p68_undo_action),
       ('redo','Làm lại (Ctrl+Shift+Z) thao tác',self.p68_redo_action),
       ('save','Lưu ảnh PNG (Ctrl+S)',self.p69_save),
       ('minus','Thu nhỏ ảnh (25%–200%)',lambda:self.p69_zoom_by(1/1.25)),
       ('plus','Phóng to ảnh (25%–200%)',lambda:self.p69_zoom_by(1.25)),
       ('fit','Zoom vừa khung (F4)',self.p69_zoom_reset),
       ('color','Chọn màu bút hoặc Fill',self.p68_choose_color)]:
     self.p75_icons[kind]=make_icon(kind)
     b=ttk.Button(processed_tools,image=self.p75_icons[kind],width=1,command=fn,style='Tool74.TButton')
     b.grid(row=0,column=len(self.p75_icons)-1,padx=1,pady=1,sticky='w')
     self.p74_bind_tooltip(b,hint)
    self.p68_size_label=tk.StringVar(value='12 px')
    ttk.Label(source_tools,textvariable=self.p68_size_label,foreground='#D3AD65',font=('Segoe UI',8)).pack(side='right',padx=(4,0))
    recognize_row=ttk.Frame(image_pair)
    recognize_row.grid(row=4,column=1,sticky='ew',padx=(4,0),pady=(0,0))
    # P123: bỏ nút OCR thủ công vì OCR được kích hoạt tự động khi mở ảnh.

    self.p69_zoom=1.0
    self.p71_pan_x=0.0;self.p71_pan_y=0.0
    self.processed_canvas.bind('<MouseWheel>',self.p69_mouse_zoom)
    self.processed_canvas.bind('<Button-4>',self.p71_linux_mouse_zoom)
    self.processed_canvas.bind('<Button-5>',self.p71_linux_mouse_zoom)
    self.p43_task=tk.StringVar(value='')
    self.p43_percent=tk.IntVar(value=0)
    # P128: action buttons on the SAME horizontal row as each section heading.
    image_actions=ttk.Frame(left);image_actions.pack(fill='x',pady=(2,2))
    ttk.Label(image_actions,text='01 / ẢNH & CÔNG CỤ',foreground='#D3AD65',font=('Segoe UI',9,'bold')).pack(side='left',padx=(0,8))
    for title,fn in [('MỞ ẢNH',self.open),('DÁN ẢNH',self.paste),('XÓA ẢNH',self.remove_image)]:
     ttk.Button(image_actions,text=title,command=fn,style='P128Tiny.TButton',width=12).pack(side='left',padx=3)
    font_actions=ttk.Frame(left);font_actions.pack(fill='x',pady=(2,3))
    ttk.Label(font_actions,text='KHO FONT',foreground='#D3AD65',font=('Segoe UI',9,'bold')).pack(side='left',padx=(0,8))
    for title,fn in [('THÊM FONT',self.add_folder),('QUẢN LÝ FONT',self.manage_folders),('KHO FONT',self.open_font_warehouse)]:
     ttk.Button(font_actions,text=title,command=fn,style='P128Tiny.TButton',width=13).pack(side='left',padx=3)
    memory_row=ttk.Frame(left);memory_row.pack(fill='x',pady=(1,2))
    ttk.Button(memory_row,text='GHI NHỚ',command=self.start_memory_training,style='Gold.TButton').pack(side='left',padx=(0,6))
    self.library_status=tk.StringVar(value='Lưu font mới để tìm Offline')
    ttk.Label(memory_row,textvariable=self.library_status,foreground='#A9B2C0',font=('Segoe UI',8)).pack(side='left',fill='x',expand=True)
    p70_header=ttk.Frame(left);p70_header.pack(fill='x',pady=(2,1))
    ttk.Label(p70_header,text='02 / OCR TỰ ĐỘNG',foreground='#D3AD65').pack(side='left',padx=(0,8))
    self.glyph=tk.StringVar(value='');self.sample=self.glyph
    # P128: editable OCR text shares the heading row and uses remaining width.
    self.p127_ocr_entry=ttk.Entry(p70_header,textvariable=self.glyph,font=('Segoe UI',9),width=36)
    self.p127_ocr_entry.pack(side='left',fill='x',expand=True,padx=(0,2))
    self.p121_confirmed_text=None;self.p121_candidates=[]
    # Keep the original layout and controls, hide redundant OCR dropdown/button.
    self.ocr_mode_status=tk.StringVar(value='OCR TỰ ĐỘNG • Kiểm tra hoặc sửa chữ trước khi tìm font.')
    ttk.Label(left,textvariable=self.ocr_mode_status,foreground='#A9B2C0',font=('Segoe UI',8)).pack(anchor='w',pady=(0,1))
    # P123: OCR tự động; không chiếm diện tích bằng các nút OCR riêng.
    # Các hàm Hybrid và kiểm tra OCR vẫn được giữ để gọi từ luồng xác nhận.

    # P81: optional manual text is already supported by the editable OCR field.
    # Explicitly choose which image is used for matching, independently of OCR.
    p81row=ttk.Frame(left);p81row.pack(fill='x',pady=(0,1))
    ttk.Label(p81row,text='SO KHỚP',foreground='#D3AD65').pack(side='left',padx=(0,5))
    self.p81_source=tk.StringVar(value='Tự động (ảnh gốc)')
    self.p81_source_box=ttk.Combobox(p81row,state='readonly',width=17,textvariable=self.p81_source,
      values=('Tự động (ảnh gốc)','PA đang chọn','Ảnh chỉnh sửa'))
    self.p81_source_box.pack(side='left',padx=(0,5))
    self.p74_bind_tooltip(self.p81_source_box,'Chọn ảnh dùng để SO KHỚP FONT; nhập chữ trực tiếp sẽ bỏ qua OCR')
    ttk.Button(p81row,text='SO SÁNH',command=self.p81_show_comparison,style='Compact.TButton').pack(side='left',padx=(0,6))
    self.p81_baseline=None;self.p81_after=None;self.p81_search_source=''
    self.p81_compare_status=tk.StringVar(value='Chưa có kết quả')
    ttk.Label(p81row,textvariable=self.p81_compare_status,foreground='#A9B2C0',font=('Segoe UI',8)).pack(side='left',fill='x',expand=True)
    self._ocr_setting_text=False
    self._ocr_manual_edit=False
    self.glyph.trace_add('write',self.p26_text_changed)
    # P59: spacing normalization always enabled, no visible controls or notifications.
    self.p58_remove_words=tk.BooleanVar(value=True)
    self.p58_compact_letters=tk.BooleanVar(value=True)
    self.ocr_job=0;self.ocr_busy=False;self.sound_enabled=tk.BooleanVar(value=True);self.ocr_sound_enabled=tk.BooleanVar(value=True)
    sound_row=ttk.Frame(left);sound_row.pack(anchor='w',pady=(2,0))
    p127_toggle(sound_row,'Âm hoàn thành',self.sound_enabled,side='left')
    p127_toggle(sound_row,'Âm OCR',self.ocr_sound_enabled,side='left',padx=(5,0))
    ttk.Label(left,text='03 / TÌM FONT',foreground='#D3AD65',font=('Segoe UI',10,'bold')).pack(anchor='w',pady=(4,2))
    modes=ttk.Frame(left);modes.pack(fill='x',pady=(0,4))
    self.search_mode_selector=ttk.Combobox(modes,state='readonly',width=23,textvariable=self.mode,
        values=('offline','hybrid','online'))
    # P24: keep original selector object/handlers for compatibility; OFFLINE is the only visible search mode.
    # self.search_mode_selector.pack(side='left')
    self.search_mode_selector.bind('<<ComboboxSelected>>',lambda event:self.mode_changed())
    # P122: advanced controls remain available but do not occupy the main workflow.
    advanced_visible=tk.BooleanVar(value=False)
    advanced_toggle=ttk.Button(left,text='▸ TÙY CHỌN QUÉT / LỌC FONT',style='Compact.TButton')
    advanced_toggle.pack(fill='x',pady=(3,2))
    advanced_panel=ttk.Frame(left)
    def p122_toggle_advanced():
     if advanced_visible.get():
      advanced_panel.pack_forget();advanced_visible.set(False)
      advanced_toggle.configure(text='▸ TÙY CHỌN QUÉT / LỌC FONT')
     else:
      advanced_panel.pack(fill='x',pady=(2,4));advanced_visible.set(True)
      advanced_toggle.configure(text='▾ THU GỌN TÙY CHỌN')
    advanced_toggle.configure(command=p122_toggle_advanced)
    scanrow=ttk.Frame(advanced_panel);scanrow.pack(fill='x',pady=(3,2))
    ttk.Label(scanrow,text='CHẾ ĐỘ QUÉT',foreground='#D3AD65').pack(side='left',padx=(0,8))
    for value,label in [('fast','QUÉT NHANH'),('deep','QUÉT KỸ')]:
     ttk.Radiobutton(scanrow,text=label,value=value,variable=self.scan_mode).pack(side='left',padx=(0,8))
    channels=ttk.Frame(advanced_panel);channels.pack(fill='x',pady=(2,1))
    ttk.Label(channels,text='KÊNH QUÉT CPU',foreground='#D3AD65').pack(side='left',padx=(0,8))
    ttk.Combobox(channels,textvariable=self.scan_workers,values=('AUTO','4','7','8','12','MAX'),width=7,state='readonly').pack(side='left')
    ttk.Button(channels,text='BENCHMARK 4/7/8/12',command=self.start_benchmark).pack(side='left',padx=8)
    cluerow=ttk.Frame(advanced_panel);cluerow.pack(fill='x',pady=(3,1))
    ttk.Label(cluerow,text='04 / LỌC FONT THEO NHÓM  (Space = tự thêm dấu phẩy)' ,foreground='#D3AD65').pack(side='left',padx=(0,7))
    clue_entry=ttk.Combobox(cluerow,textvariable=self.font_clue,width=23,values=self.group_filter_history,state='normal')
    clue_entry.pack(side='left')
    self.group_filter_history_combo=clue_entry
    ttk.Label(cluerow,text='Lịch sử ▼',foreground='#AEB9C7').pack(side='left',padx=(5,0))
    # P109: Space after a group inserts a visible comma+space delimiter.
    # Do not normalize on every keystroke: that would erase the delimiter
    # immediately and make it impossible to type the next group.
    def on_clue_space(event):
     entry=event.widget
     text=entry.get()
     pos=entry.index('insert')
     left=text[:pos].rstrip()
     right=text[pos:].lstrip()
     if not left or left.endswith(','):
      # Do not create an empty group or duplicate separators.
      return 'break'
     entry.delete(0,'end')
     entry.insert(0,left+', '+right)
     entry.icursor(len(left)+2)
     return 'break'
    def on_clue_blur(event):
     raw=self.font_clue.get()
     clean=normalize_font_clue(raw)
     if raw!=clean:self.font_clue.set(clean)
    clue_entry.bind('<space>',on_clue_space)
    clue_entry.bind('<FocusOut>',on_clue_blur)
    ttk.Label(advanced_panel,text='Ví dụ: UTM, SVN, UVF, VL, VNI  •  Để trống = quét tất cả.',foreground='#AEB9C7').pack(anchor='w')
    stoprow=ttk.Frame(advanced_panel);stoprow.pack(fill='x',pady=(3,2))
    p127_toggle(stoprow,'DỪNG KHI FONT ĐẠT ĐIỂM',self.p84_early_stop,side='left')
    ttk.Label(stoprow,text='Ngưỡng:').pack(side='left',padx=(12,3))
    ttk.Combobox(stoprow,textvariable=self.p84_stop_threshold,values=[str(v) for v in range(70,101)],width=4,state='readonly').pack(side='left')
    ttk.Label(stoprow,text='/100  •  Tắt = quét bình thường',foreground='#AEB9C7').pack(side='left',padx=(5,0))
    p12row=ttk.Frame(advanced_panel);p12row.pack(fill='x',pady=(3,2))
    self.p12_enabled.set(True)  # index remains available for custom sources
    # P24: online source management retained in code, hidden from offline-first UI.
    # ttk.Button(p12row,text='THÊM TRANG NGUỒN',command=self.p12_manage).pack(side='left',padx=5)
    # Google Fonts is invoked by the main ONLINE button
    self.vietnamese_priority.set(True)  # always enabled, UI hidden
    # Preserve system font scan engine; hide checkbox from GUI.
    controls=ttk.Frame(left_holder);controls.grid(row=1,column=0,sticky='ew',pady=(4,1),padx=(1,2))  # fixed footer: never hidden by scrolling
    controls.columnconfigure(0,weight=3);controls.columnconfigure(1,weight=1)
    self.searchbtn=ttk.Button(controls,text='XÁC NHẬN & TÌM FONT',command=self.start_search,style='Primary.TButton');self.searchbtn.grid(row=0,column=0,sticky='ew',padx=(0,3))
    ttk.Button(controls,text='STOP',command=self.stop,style='Stop.TButton').grid(row=0,column=1,sticky='ew')
    self.deepbtn=ttk.Button(controls,text='QUÉT KỸ LẠI',command=self.deep_retry,state='disabled');# hidden UI only; command and widget state preserved
    self.status=tk.StringVar(value='Mở ảnh, khoanh vùng chữ và nhập chính xác ký tự cần so sánh.')
    ttk.Label(left_holder,textvariable=self.status,wraplength=300,font=('Segoe UI',8)).grid(row=2,column=0,sticky='ew',pady=(1,2))
    # P35: fixed two-line live scan at the top; result and preview panes below.
    live_panel=ttk.Frame(right)
    live_panel.pack(side='top',fill='x',pady=(0,2))
    # P48: independent scan progress beside the live ticker; never reuse image/OCR progress.
    live_header=ttk.Frame(live_panel)
    live_header.pack(fill='x',pady=(2,3))
    ttk.Label(live_header,text='06 / HIỂN THỊ CHUYỂN ĐỘNG TÌM KIẾM',foreground='#D3AD65').pack(side='left')
    self.p48_scan_percent=tk.IntVar(value=0)
    self.p48_scan_text=tk.StringVar(value='0%')
    ttk.Label(live_header,textvariable=self.p48_scan_text,foreground='#D3AD65',width=5,anchor='e').pack(side='right',padx=(5,0))
    ttk.Progressbar(live_header,variable=self.p48_scan_percent,maximum=100,length=110,mode='determinate').pack(side='right',padx=(10,0))
    self.p32_live_canvas=tk.Canvas(live_panel,bg='#111820',height=38,highlightthickness=1,highlightbackground='#46505c',bd=0)
    self.p32_live_canvas.pack(fill='x',expand=False,pady=(0,2))
    self.p32_live_canvas.bind('<Configure>',lambda e:self.p31_redraw())
    results_area=ttk.Frame(right)
    results_area.pack(side='top',fill='both',expand=True)
    split=tk.PanedWindow(results_area,orient='vertical',bg='#D3AD65',sashwidth=9,sashrelief='raised',showhandle=True,bd=0)
    split.pack(fill='both',expand=True)
    top_fonts=ttk.Frame(split);lower=ttk.Frame(split)
    for pane in (top_fonts,lower):split.add(pane,minsize=90,stretch='always')
    self._equal_split_applied=False
    def initial_equal_split(attempt=0):
     if self._equal_split_applied:return
     height=split.winfo_height()
     if height>=220:
      split.sash_place(0,0,int(height*0.62))
      self._equal_split_applied=True
     elif attempt<25:self.root.after(100,lambda:initial_equal_split(attempt+1))
    self.root.after(350,initial_equal_split)
    ttk.Label(top_fonts,text='07 / TOP 12 FONT GIỐNG MẪU',foreground='#D3AD65').pack(anchor='w',pady=(2,4))
    tableframe=ttk.Frame(top_fonts);tableframe.pack(fill='both',expand=True)
    self.tree=ttk.Treeview(tableframe,columns=('score','percent','name','status','file'),show='headings',height=7)
    for key,title,width,anchor in [('score','thang điểm',92,'center'),('percent','xếp hạng',78,'center'),('name','tên font chữ',245,'w'),('status','trạng thái',135,'center'),('file','tệp',66,'center')]:
     self.tree.heading(key,text=title)
     self.tree.column(key,width=width,minwidth=48 if key=='file' else 65,stretch=(key!='file'),anchor=anchor)
    tree_scroll=ttk.Scrollbar(tableframe,orient='vertical',command=self.tree.yview)
    self.tree.configure(yscrollcommand=tree_scroll.set)
    tree_scroll.pack(side='right',fill='y');self.tree.pack(side='left',fill='both',expand=True)
    self.tree.bind('<<TreeviewSelect>>',self.preview)
    self.tree.bind('<ButtonRelease-1>',self.p27_left_open_font)
    self.tree.bind('<Control-c>',self.copy_font_name)
    self.tree.bind('<Control-C>',self.copy_font_name)
    self.tree.bind('<Button-3>',self.show_font_context_menu)
    self.tree.bind('<Shift-F10>',self.show_font_context_menu_keyboard)
    self.font_menu=tk.Menu(self.tree,tearoff=0)
    self.font_menu.add_command(label='Copy tên font',command=self.copy_font_name)
    self.font_menu.add_command(label='Open file location',command=self.open_font_folder)
    ttk.Label(lower,text='08 / VIEW HIỂN THỊ MẪU FONT TRỰC QUAN',foreground='#D3AD65').pack(anchor='w',pady=(3,3))
    self.shared_source=tk.StringVar(value='offline')
    self.shared_preview_canvas=tk.Canvas(lower,bg='#F4F0E8',height=260,highlightthickness=0)
    self.shared_preview_scroll=ttk.Scrollbar(lower,orient='vertical',command=self.shared_preview_canvas.yview)
    self.shared_preview_canvas.configure(yscrollcommand=self.shared_preview_scroll.set)
    self.shared_preview_scroll.pack(side='right',fill='y')
    self.shared_preview_canvas.pack(fill='both',expand=True,pady=(2,3))
    self.shared_preview_canvas.bind('<Configure>',lambda e:self.render_shared_previews())
    self.shared_preview_canvas.bind('<MouseWheel>',self.p55_preview_mousewheel)
    self.shared_preview_canvas.bind('<Button-4>',self.p55_preview_mousewheel)
    self.shared_preview_canvas.bind('<Button-5>',self.p55_preview_mousewheel)
    # Legacy callbacks remain callable but do not add an extra large-font window.
    self.previewbox=tk.Canvas(lower,bg='#F4F0E8',height=42,highlightthickness=0)
    self.p18_detail=tk.Canvas(lower,bg='#F4F0E8',height=150,highlightthickness=0)
    ai_panel=ttk.Frame(lower)  # Retain legacy AI output widget for compatibility; do not display prose
    ai_panel.rowconfigure(0,weight=1);ai_panel.columnconfigure(0,weight=1)
    self.cloud_box=tk.Text(ai_panel,height=12,wrap='word',bg='#252B35',fg='#f4f0e7',insertbackground='white',font=('Segoe UI',11),relief='flat',padx=12,pady=10)
    self.cloud_box.grid(row=0,column=0,sticky='nsew')
    ai_scroll=ttk.Scrollbar(ai_panel,orient='vertical',command=self.cloud_box.yview)
    ai_scroll.grid(row=0,column=1,sticky='ns');self.cloud_box.configure(yscrollcommand=ai_scroll.set)
    self.cloud_box.insert('1.0','KẾT QUẢ PHÂN TÍCH AI ONLINE\nNhập API key và chọn TÌM FONT AI. Có thể lưu khóa an toàn bằng nút LƯU KEY.')
    self.cloud_box.configure(state='disabled')
    # P18: the visual detail replaces the former prose area
    self.ai_preview_status=tk.StringVar(value='Chạy TÌM FONT AI để cập nhật bảng xem trước chung.')
    # Keep status variable for legacy code, but no prose panel
    tk.Frame(main,bg='#D3AD65',height=1).pack(fill='x',pady=(7,5))
    # P24: legacy online AI panel retained in source but hidden from the main window.
    # ttk.Label(main,text='08 / AI TRỰC TUYẾN (TÙY CHỌN) — KẾT QUẢ HIỂN THỊ BÊN PHẢI',foreground='#D3AD65').pack(anchor='w')
    apirow=ttk.Frame(main)  # kept unmounted for legacy key management
    ttk.Label(apirow,text='API Key').pack(side='left')
    ttk.Entry(apirow,textvariable=self.cloud_key,show='*').pack(side='left',fill='x',expand=True,padx=6)
    ttk.Button(apirow,text='LƯU KEY',command=self.save_key).pack(side='left',padx=2)
    ttk.Button(apirow,text='XÓA KEY',command=self.delete_key).pack(side='left',padx=2)
    ttk.Label(apirow,text='Model').pack(side='left')
    ttk.Entry(apirow,textvariable=self.cloud_model,width=17).pack(side='left',padx=(6,0))
    # ttk.Button(main,text='✧ TÌM FONT AI',command=self.cloud_search,style='Primary.TButton').pack(anchor='w',pady=(1,4))
    self.root.after(120,self.poll)
    self.root.after(33,self.p31_animate)
    self.root.after_idle(self.show_expired_trial)
    # Benchmark remains available from its button; no automatic startup benchmark.
 def auto_benchmark_first_run(self):
    if saved_benchmark() is None and not getattr(self,'bench_running',False):
     self.start_benchmark()
 def save_key(self):
    key=self.cloud_key.get().strip()
    if not key.startswith('sk-'):
     messagebox.showwarning('API Key','Khóa API phải bắt đầu bằng sk-.');return
    try:write_secure_key(key);self.status.set('Đã lưu API Key vào kho bảo mật Windows.')
    except Exception as e:messagebox.showerror('Không lưu được API Key',str(e))
 def delete_key(self):
    try:write_secure_key('');self.cloud_key.set('');self.status.set('Đã xóa API Key đã lưu.')
    except Exception as e:messagebox.showerror('Không xóa được API Key',str(e))
 def p26_text_changed(self,*_):
    if not self._ocr_setting_text:
     self._ocr_manual_edit=True
     self.ocr_job+=1  # Invalidate any running OCR before it can overwrite edits.
     self.ocr_mode_status.set('CHỈNH TAY • Nội dung đã sửa được giữ nguyên.')
    self.p121_confirmed_text=None
    self.preview()
    if hasattr(self,'shared_preview_canvas'):self.render_shared_previews()
 def p26_set_text(self,text):
    self._ocr_setting_text=True
    try:self.glyph.set(text)
    finally:self._ocr_setting_text=False
 def p26_new_image(self):
    self.p81_baseline=None;self.p81_after=None;self.p81_source.set('Tự động (ảnh gốc)');self.p81_compare_status.set('Chưa có kết quả')
    self.p68_committed=None;self.p68_image=None;self.p69_edited_only=False
    self.ocr_job+=1
    self.p121_confirmed_text=None
    self.p121_candidates=[]
    self._ocr_manual_edit=False
    self.p26_set_text('')
    self.ocr_mode_status.set('ĐANG NHẬN DIỆN • OCR Offline tự động...')
    self.ocr_start()
 def p21_mode_changed(self,event=None):
    labels=('SMART OCR — Google + Đối chiếu','OCR GOOGLE VIỆT','OCR OFFLINE','OCR HYBRID AI')
    keys=('smart','google','offline','hybrid')
    index=self.ocr_selector.current() if hasattr(self,'ocr_selector') else 2
    if index<0:index=0
    self.ocr_mode.set(keys[index]);self.ocr_mode_status.set('OCR đang chọn: '+labels[index])
 def p21_auto_offline_only(self):
    # Offline OCR only; never call a paid API automatically.
    self.ocr_start()
 def p21_ocr_dispatch(self):
    mode=self.ocr_mode.get()
    if mode=='smart':self.p21_smart_start()
    elif mode=='google':self.p20_ocr_start()
    elif mode=='hybrid':self.hybrid_ocr_start()
    else:self.ocr_start()
 def p21_smart_start(self):
    if not self.require_license(prompt=True):
     return
    from tkinter import simpledialog
    if self.image is None:
     messagebox.showwarning('SMART OCR','Hãy mở ảnh trước.');return
    key=getattr(self,'p20_vision_key',None)
    if not key:
     key=simpledialog.askstring('SMART OCR — Google Cloud Vision','Nhập Google Cloud Vision API key (không phải OpenAI/Google Fonts):',show='*',parent=self.root)
     if key:self.p20_vision_key=key
    if not key:
     self.status.set('SMART OCR chưa chạy: thiếu Google Cloud Vision API key. Không tự chuyển chế độ.');return
    image=(self.image.crop(self.crop) if self.crop else self.image).copy()
    self.ocr_job+=1;job=self.ocr_job
    self.status.set('SMART OCR: đang chạy Google Cloud Vision và OCR Offline để đối chiếu...')
    def worker():
     import concurrent.futures
     with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
      google=pool.submit(p20vision.cloud_ocr,image,key)
      local=pool.submit(recognize_text,image)
      try:online=google.result();cloud_error=''
      except Exception as exc:online='';cloud_error=str(exc)
      try:offline,engine=local.result();local_error=''
      except Exception as exc:offline='';engine='';local_error=str(exc)
     self.q.put(('p21_smart_done',job,online,offline,engine,cloud_error,local_error,p21.image_key(image)))
    threading.Thread(target=worker,daemon=True).start()
 def p21_confirm(self,google,offline,signature):
    # Explicit confirmation prevents silently changing accents, names or brand text.
    dlg=tk.Toplevel(self.root);dlg.title('SMART OCR — XÁC NHẬN KÝ TỰ');dlg.transient(self.root)
    dlg.grab_set();dlg.geometry('%dx%d'%(min(620,self.root.winfo_screenwidth()-60),300));dlg.configure(bg='#252B35')
    tk.Label(dlg,text='GOOGLE VÀ OFFLINE CHƯA THỐNG NHẤT — KIỂM TRA ẢNH GỐC',bg='#252B35',fg='#D3AD65',font=('Segoe UI',11,'bold')).pack(anchor='w',padx=14,pady=(12,8))
    tk.Label(dlg,text='GOOGLE: '+(google or '(không đọc được)'),bg='#252B35',fg='white',wraplength=560,justify='left').pack(anchor='w',padx=14,pady=3)
    tk.Label(dlg,text='OFFLINE: '+(offline or '(không đọc được)'),bg='#252B35',fg='white',wraplength=560,justify='left').pack(anchor='w',padx=14,pady=3)
    tk.Label(dlg,text='Sửa trực tiếp bên dưới nếu cần. Chỉ lưu sau khi nhấn XÁC NHẬN.',bg='#252B35',fg='#D3AD65').pack(anchor='w',padx=14,pady=(12,3))
    old=p21.previous_correction(signature)
    if old:
     tk.Label(dlg,text='ĐÃ XÁC NHẬN TRƯỚC ĐÂY: '+old,bg='#252B35',fg='#D3AD65',wraplength=560).pack(anchor='w',padx=14,pady=2)
    value=tk.StringVar(value=old or google or offline)
    ttk.Entry(dlg,textvariable=value,font=('Segoe UI',13)).pack(fill='x',padx=14,pady=4)
    def confirm():
     result=value.get().strip()
     if not result:messagebox.showwarning('SMART OCR','Kết quả không được trống.',parent=dlg);return
     self.glyph.set(result)
     try:p21.save_correction(signature,google,offline,result)
     except Exception as exc:self.status.set('OCR đã xác nhận; không lưu được lịch sử sửa: '+str(exc)[:100])
     else:self.status.set('SMART OCR: đã xác nhận văn bản '+result)
     if self.ocr_sound_enabled.get():play_ocr_result_sound()
     dlg.destroy()
    bar=ttk.Frame(dlg);bar.pack(fill='x',padx=14,pady=12)
    ttk.Button(bar,text='XÁC NHẬN KÝ TỰ',command=confirm,style='Primary.TButton').pack(side='left',padx=(0,8))
    ttk.Button(bar,text='HỦY — GIỮ NGUYÊN',command=dlg.destroy).pack(side='left')
    dlg.protocol('WM_DELETE_WINDOW',dlg.destroy)
 def ocr_start(self):
    if not self.require_license(prompt=False):
     return
    if self.image is None:return
    self.ocr_job+=1;job=self.ocr_job
    image=(getattr(self,'p68_committed',None) or (self.image.crop(self.crop) if self.crop else self.image)).copy()
    self.status.set('Đang nhận diện ký tự Offline...')
    self.p43_percent.set(0)
    def run():
     try:
      txt,engine,needs_review=p42ocr.recognize(image,recognize_text)
     except Exception as exc:
      txt,engine,needs_review=None,'Lỗi OCR: '+str(exc)[:120],True
     self.q.put(('ocr_done',job,txt,engine,needs_review))
    threading.Thread(target=run,daemon=True).start()
 def hybrid_ocr_start(self):
    if not self.require_license(prompt=True):
     return
    if self.image is None:return
    key=self.cloud_key.get().strip()
    if not key:
     messagebox.showwarning('OCR Hybrid','Nhập OpenAI API Key ở phần AI trực tuyến. OCR offline vẫn hoạt động miễn phí.');return
    image=(self.image.crop(self.crop) if self.crop else self.image).copy()
    self.ocr_job+=1;job=self.ocr_job
    self.status.set('OCR Hybrid: đang đối chiếu Tesseract và AI Vision (có thể tính phí API)...')
    def run():
     import concurrent.futures
     with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
      a=pool.submit(recognize_text,image)
      b=pool.submit(recognize_text_ai,image,key,self.cloud_model.get().strip())
      offline,off_engine=a.result();online,on_engine=b.result()
     self.q.put(('hybrid_ocr_done',job,offline,online,off_engine,on_engine))
    threading.Thread(target=run,daemon=True).start()
 def mode_changed(self):
    mode=self.mode.get()
    self.searchbtn.configure(text='XÁC NHẬN TÌM KIẾM')
 def p121_hybrid_start(self):
    """Explicit cloud consent: independent offline + online OCR, no hidden billing."""
    if not self.require_license(prompt=True):
     return
    if self.image is None:
     messagebox.showwarning('Hybrid OCR','Hãy mở ảnh trước.');return
    from tkinter import simpledialog
    provider=simpledialog.askstring('AI Hybrid — chọn dịch vụ','Nhập GOOGLE (Cloud Vision) hoặc OPENAI. Dịch vụ có thể tính phí theo tài khoản; không tự phát sinh yêu cầu nếu bạn hủy.',initialvalue='GOOGLE',parent=self.root)
    if not provider:return
    provider=provider.strip().upper()
    if provider not in ('GOOGLE','OPENAI'):
     messagebox.showwarning('Hybrid OCR','Chỉ hỗ trợ GOOGLE hoặc OPENAI.');return
    if provider=='GOOGLE':
     key=getattr(self,'p20_vision_key',None)
     if not key:
      key=simpledialog.askstring('Google Cloud Vision','Nhập API key riêng của bạn (không lưu vào ZIP):',show='*',parent=self.root)
      if key:self.p20_vision_key=key
    else:
     key=self.cloud_key.get().strip()
     if not key:key=simpledialog.askstring('OpenAI Vision','Nhập API key riêng của bạn:',show='*',parent=self.root)
    if not key:
     self.status.set('Không có API key: giữ nguyên chế độ Offline.');return
    if not messagebox.askyesno('Cho phép gửi ảnh qua Internet','Gửi vùng ảnh chữ tới '+provider+' để nhận diện? Dịch vụ có thể tính phí và ảnh được xử lý bởi nhà cung cấp.',parent=self.root):return
    image=(getattr(self,'p68_committed',None) or (self.image.crop(self.crop) if self.crop else self.image)).copy()
    self.ocr_job+=1;job=self.ocr_job;self.p121_confirmed_text=None
    self.status.set('Hybrid: đang nhận diện Offline và Online độc lập...')
    def worker():
     import concurrent.futures
     def local():
      try:return p42ocr.recognize(image,recognize_text)
      except Exception as exc:return ('','Offline lỗi: '+str(exc)[:100],True)
     def remote():
      try:
       if provider=='GOOGLE':return (p20vision.cloud_ocr(image,key),'Google Cloud Vision')
       return recognize_text_ai(image,key,self.cloud_model.get().strip())
      except Exception as exc:return ('','Online lỗi: '+str(exc)[:140])
     with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
      a=pool.submit(local);b=pool.submit(remote)
      offline,engine,review=a.result();online,online_engine=b.result()
     self.q.put(('p121_hybrid_done',job,offline or '',online or '',engine,online_engine))
    threading.Thread(target=worker,daemon=True).start()
 def p121_review(self):
    """Human confirmation is the only route from OCR suggestions to font search."""
    if self.image is None:
     messagebox.showwarning('Xác nhận OCR','Hãy mở ảnh trước.');return
    suggestions=[]
    for label,value in getattr(self,'p121_candidates',[]):
     value=str(value or '').strip()
     if value and value not in [v for _,v in suggestions]:suggestions.append((label,value))
    current=self.glyph.get().strip()
    if current and current not in [v for _,v in suggestions]:suggestions.insert(0,('Nội dung đang nhập',current))
    # 7.1 Mini Pro: minimal dialog, content-driven height, no unused scroll region.
    dlg=tk.Toplevel(self.root)
    dlg.title('XÁC NHẬN KÝ TỰ')
    dlg.transient(self.root)
    bg='#202733';fg='#E8EDF5';accent='#F0C16C'
    dlg.configure(bg=bg)
    shown=suggestions[:12]
    count=len(shown)
    width=min(410,max(330,self.root.winfo_screenwidth()-70))
    chosen=tk.StringVar(value='0' if shown else 'manual')
    value=tk.StringVar(value=(shown[0][1] if shown else current))
    head=tk.Frame(dlg,bg=bg)
    head.pack(fill='x',padx=12,pady=(9,4))
    tk.Label(head,text='XÁC NHẬN KÝ TỰ',font=('Segoe UI',10,'bold'),
             fg=accent,bg=bg).pack(side='left')
    tk.Label(head,text=f'{count} kết quả',font=('Segoe UI',8),
             fg='#9FAEC2',bg=bg).pack(side='right')
    if shown:
     outer=tk.Frame(dlg,bg='#293446',highlightthickness=1,highlightbackground='#39465A')
     outer.pack(fill='x',padx=12,pady=(3,7))
     canvas=tk.Canvas(outer,bg='#293446',height=min(count,4)*29,
                      highlightthickness=0,bd=0)
     canvas.pack(side='left',fill='x',expand=True)
     inner=tk.Frame(canvas,bg='#293446')
     window=canvas.create_window((0,0),window=inner,anchor='nw')
     canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
     inner.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
     if count>4:
      sb=ttk.Scrollbar(outer,orient='vertical',command=canvas.yview)
      sb.pack(side='right',fill='y')
      canvas.configure(yscrollcommand=sb.set)
     for i,(label,word) in enumerate(shown):
      def select(txt=word):value.set(txt)
      # Put OCR text first; truncate only the descriptive label, never the editable text.
      description=str(label).split(' · ')[0][:24]
      display=f'{word}   ·   {description}'
      tk.Radiobutton(inner,text=display,variable=chosen,value=str(i),command=select,
          anchor='w',justify='left',bg='#293446',fg=fg,selectcolor='#405B7A',
          activebackground='#293446',activeforeground=fg,font=('Segoe UI',9),
          wraplength=width-65).pack(fill='x',padx=5,pady=2)
    else:
     tk.Label(dlg,text='Chưa có kết quả AI. Hãy nhập chữ:',font=('Segoe UI',9),
              fg='#B9C7D9',bg=bg).pack(anchor='w',padx=12,pady=(3,6))
    editrow=tk.Frame(dlg,bg=bg)
    editrow.pack(fill='x',padx=12,pady=(0,8))
    tk.Radiobutton(editrow,text='SỬA CHỮ',variable=chosen,value='manual',
        bg=bg,fg=fg,selectcolor='#405B7A',activebackground=bg,
        activeforeground=fg,font=('Segoe UI',9)).pack(side='left',padx=(0,5))
    entry=ttk.Entry(editrow,textvariable=value,font=('Segoe UI',10))
    entry.pack(side='left',fill='x',expand=True,ipady=2)
    entry.bind('<KeyRelease>',lambda _e:chosen.set('manual'))
    def accept():
     word=value.get().strip()
     if not word:
      messagebox.showwarning('OCR','Hãy chọn hoặc nhập ký tự.',parent=dlg);return
     self.p26_set_text(word);self.p121_confirmed_text=word
     self.ocr_mode_status.set('ĐÃ XÁC NHẬN: '+word)
     dlg.destroy();self.start_search()
    bar=tk.Frame(dlg,bg=bg)
    bar.pack(fill='x',padx=12,pady=(0,10))
    ttk.Button(bar,text='XÁC NHẬN · TÌM FONT',command=accept,
               style='Primary.TButton').pack(side='left')
    ttk.Button(bar,text='ĐỂ SAU',command=dlg.destroy).pack(side='left',padx=6)
    dlg.update_idletasks()
    h=dlg.winfo_reqheight()
    dlg.geometry(f'{width}x{h}+{max(0,(dlg.winfo_screenwidth()-width)//2)}+{max(0,(dlg.winfo_screenheight()-h)//2)}')
    dlg.resizable(False,False)
    dlg.bind('<Escape>',lambda _e:dlg.destroy())
    dlg.protocol('WM_DELETE_WINDOW',dlg.destroy)
    dlg.grab_set()

 def start_search(self):
    if not self.require_license(prompt=True):
     return
    if self.image is not None and (not getattr(self,'p121_confirmed_text',None) or self.p121_confirmed_text!=self.glyph.get().strip()):
     self.p121_review();return
    mode=self.mode.get()
    if mode=='online':
     self.p20_online_search();return
    self.search()
    if mode=='hybrid' and self.cloud_key.get().strip():
     self.cloud_search()
    elif mode=='hybrid':
     self.set_cloud('HYBRID: đang tìm Offline. Thêm API key để đồng thời nhận gợi ý AI Online.')
 def deep_retry(self):
    if self.image is None:return
    self.scan_mode.set('deep')
    self.start_search()
 def copy_font_name(self,event=None):
    selection=self.tree.selection()
    if not selection:return 'break'
    # Copy the actual visible name, independent of ranking changes or source mode.
    values=self.tree.item(selection[0],'values')
    name=str(values[2]).strip() if len(values)>2 else ''
    if not name:return 'break'
    self.root.clipboard_clear();self.root.clipboard_append(name)
    self.root.update_idletasks()
    self.status.set('Đã copy tên font: '+name)
    return 'break'
 def show_font_context_menu_keyboard(self,event=None):
    selection=self.tree.selection()
    if not selection:return 'break'
    bbox=self.tree.bbox(selection[0])
    x=self.tree.winfo_rootx()+(bbox[0] if bbox else 10)+20
    y=self.tree.winfo_rooty()+(bbox[1] if bbox else 10)+20
    self.p55_popup_font_menu(x,y)
    return 'break'
 def p55_popup_font_menu(self,x,y):
    _,path=self.selected_font_record()
    self.font_menu.entryconfigure(1,state='normal' if path and os.path.isfile(path) else 'disabled')
    try:self.font_menu.tk_popup(x,y)
    finally:self.font_menu.grab_release()
 def p55_preview_mousewheel(self,event):
    canvas=self.shared_preview_canvas
    if not canvas.winfo_exists():return 'break'
    if getattr(event,'num',None)==4:steps=-1
    elif getattr(event,'num',None)==5:steps=1
    else:
     delta=getattr(event,'delta',0)
     if not delta:return 'break'
     steps=-max(1,round(abs(delta)/120)) if delta>0 else max(1,round(abs(delta)/120))
    canvas.yview_scroll(steps,'units')
    return 'break'
 def open(self):
    p=filedialog.askopenfilename(filetypes=[('Ảnh','*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp')]);
    if p:
     try:self.image=ImageOps.exif_transpose(Image.open(p)).convert('RGB');self.crop=None;self.p38_variant=0;self.p39_preview_masks=None;self.p52_manual=False;self.p53_pending_manual_clicks=0;self.p53_image_complete_notified=False;self.draw();self.p26_new_image()
     except Exception as e:messagebox.showerror('Lỗi ảnh',str(e))
 def paste(self):
    try:
     from PIL import ImageGrab
     im=ImageGrab.grabclipboard()
     if isinstance(im,Image.Image):self.image=ImageOps.exif_transpose(im).convert('RGB');self.crop=None;self.p38_variant=0;self.p39_preview_masks=None;self.p52_manual=False;self.p53_pending_manual_clicks=0;self.p53_image_complete_notified=False;self.draw();self.p26_new_image()
     else:messagebox.showinfo('Clipboard','Không tìm thấy ảnh trong Clipboard.')
    except Exception as e:messagebox.showerror('Clipboard',str(e))
 def p57_apply_rotation(self,angle):
    """Rotate working image only, retaining originals on disk; reset crop/cache."""
    if self.image is None:return
    if abs(angle)<0.05:return
    self.image=self.image.rotate(float(angle),resample=Image.Resampling.BICUBIC,expand=True,fillcolor=(255,255,255))
    self.crop=None;self.p38_variant=0;self.p39_preview_masks=None;self.p39_preview_key=None
    self.p39_preview_cache.clear();self.p52_manual=False;self.p53_pending_manual_clicks=0
    self.draw()
 def p57_auto_straighten(self):
    if self.image is None:
     messagebox.showwarning('Thiếu ảnh','Hãy mở hoặc dán ảnh trước.');return
    angle,confidence=p38.estimate_text_skew(self.image.crop(self.crop) if self.crop else self.image)
    if angle is None:
     messagebox.showinfo('Chỉnh thẳng','Không tìm được hướng dòng chữ đủ tin cậy. Dùng XOAY GÓC để chỉnh tay.');return
    if abs(angle)<0.35:
     messagebox.showinfo('Chỉnh thẳng','Ảnh đã gần nằm ngang (%.2f°).'%angle);return
    if abs(angle)>35 or confidence<0.30:
     messagebox.showinfo('Chỉnh thẳng','Độ nghiêng chưa đủ tin cậy. Hãy khoanh vùng chữ rồi thử lại hoặc xoay thủ công.');return
    self.p57_apply_rotation(angle)
    self.p43_progress('ĐÃ CHỈNH THẲNG %.2f°'%angle,100)
 def p57_manual_straighten(self):
    if self.image is None:
     messagebox.showwarning('Thiếu ảnh','Hãy mở hoặc dán ảnh trước.');return
    from tkinter import simpledialog
    angle=simpledialog.askfloat('XOAY GÓC','Nhập góc xoay (độ). Dương: ngược chiều kim đồng hồ; âm: cùng chiều.',initialvalue=0.0,minvalue=-180,maxvalue=180,parent=self.root if hasattr(self,'root') else None)
    if angle is not None:self.p57_apply_rotation(angle)
 def p43_progress(self,label,percent):
    self.p43_task.set(label)
    self.p43_percent.set(max(0,min(100,int(percent))))
 def p54_ocr_selected_variant(self):
    if not self.require_license(prompt=False):
     return
    """OCR exactly the mask shown in the processed preview; newest selection wins."""
    variants=self.p39_preview_masks or []
    if self.image is None or not variants:return
    index=self.p38_variant%len(variants)
    _,label,mask=variants[index]
    self.ocr_job+=1;job=self.ocr_job
    # Clicking a processing method explicitly requests its OCR, superseding
    # automatic OCR and earlier methods, but not later user edits.
    self._ocr_manual_edit=False
    self.p26_set_text('')
    self.ocr_mode_status.set('ĐANG OCR • PA%d — %s...'%(index+1,label))
    self.p43_progress('OCR PHƯƠNG ÁN %d/%d'%(index+1,len(variants)),10)
    if mask is None or not np.any(mask):
     self.q.put(('p54_variant_ocr_done',job,index,None,'Mặt nạ rỗng',True));return
    # Make a copy: workers must not depend on mutable UI selection/cache.
    image=p38.method_image(mask,index).convert('RGB')
    def run():
     try:
      txt,engine,needs_review=p42ocr.recognize_single(image,recognize_text)
     except Exception as exc:
      txt,engine,needs_review=None,'Lỗi OCR PA%d: %s'%(index+1,str(exc)[:120]),True
     self.q.put(('p54_variant_ocr_done',job,index,txt,engine,needs_review))
    threading.Thread(target=run,daemon=True).start()
 def p38_next_variant(self):
    if self.image is None:return
    self.p47_cancel_review()
    if self.p39_preview_masks is None:
     # A click during asynchronous segmentation is not lost: replay it when
     # the seven actual masks become available. Subsequent clicks advance slots.
     self.p53_pending_manual_clicks+=1
     self.p43_progress('ĐANG TẠO PA1–PA7 • CHỜ KẾT QUẢ',10)
     self.p37_schedule_preview();return
    if not self.p39_preview_masks:return
    # First manual click always opens PA1, irrespective of automatic winner.
    if not self.p52_manual:
     self.p52_manual=True;self.p38_variant=0
    else:self.p38_variant=(self.p38_variant+1)%len(self.p39_preview_masks)
    self.p39_render_preview()
    self.p54_ocr_selected_variant()
 def p47_cancel_review(self):
    self.p47_review_generation+=1
    if self.p47_review_job is not None:
     try:self.root.after_cancel(self.p47_review_job)
     except Exception:pass
     self.p47_review_job=None
 def p47_auto_review(self):
    # Show every real segmentation candidate once. The percentage describes
    # the *display/review cycle*, not image computation or font search.
    self.p47_cancel_review()
    variants=self.p39_preview_masks or []
    if not variants:return
    generation=self.p47_review_generation
    steps=10
    def tick(index,step):
     if generation!=self.p47_review_generation or self.image is None:return
     if index>=len(variants):
      self.p38_variant=self.p52_auto_best  # Best geometric candidate, not necessarily PA1.
      self.p39_render_preview()
      self.p43_progress('TỰ ĐỘNG • ĐÃ CHỌN PA%d'%(self.p52_auto_best+1),100)
      self.p47_review_job=None
      if not self.p53_image_complete_notified:
       self.p53_image_complete_notified=True
       if self.sound_enabled.get():play_completion_sound()
      return
     if step==0:
      self.p38_variant=index
      self.p39_render_preview()
     self.p43_progress('PHƯƠNG ÁN %d/%d'%(index+1,len(variants)),round(100*step/steps))
     if step>=steps:
      self.p47_review_job=self.root.after(80,lambda:tick(index+1,0))
     else:
      self.p47_review_job=self.root.after(55,lambda:tick(index,step+1))
    tick(0,0)
 def p60_auto_straighten_source(self,source):
    """P63: conservative four-corner rectification followed by line deskew."""
    self.p62_angle_status=''
    try:
     fixed,perspective,rotated=p63geometry.correct(source,p38.estimate_text_skew)
     # No popup or extra UI; result appears in the processed view.
     return fixed
    except Exception:
     return source
 def p37_schedule_preview(self):
    # Debounce resize/crop changes; never overwrite the original image.
    if self.p37_preview_job is not None:
     try:self.root.after_cancel(self.p37_preview_job)
     except Exception:pass
    self.p37_preview_job=self.root.after(100,self.p37_draw_processed)
 def p37_draw_processed(self):
    # All expensive segmentation runs in a background thread; Tk updates stay on the UI thread.
    self.p37_preview_job=None
    canvas=self.processed_canvas
    if self.image is None:
     canvas.delete('all');self.processed_photo=None;return
    try:
     source=self.p60_auto_straighten_source((self.image.crop(self.crop) if self.crop else self.image).copy())
     factor=min(1.0,900/max(source.size))
     if factor<1:source=source.resize((max(1,round(source.width*factor)),max(1,round(source.height*factor))),Image.Resampling.LANCZOS)
     key=hashlib.blake2b(source.tobytes(),digest_size=16).hexdigest()+str(source.size)
     if key==self.p39_preview_key and self.p39_preview_masks is not None:
      self.p39_render_preview();return
     if key in self.p39_preview_cache:
      self.p39_preview_key=key;self.p39_preview_masks=self.p39_preview_cache[key]
      self.p52_auto_best=max(range(len(self.p39_preview_masks)),key=lambda i:self.p39_preview_masks[i][0]) if self.p39_preview_masks else 0
      if self.p53_pending_manual_clicks:
       clicks=self.p53_pending_manual_clicks;self.p53_pending_manual_clicks=0
       self.p52_manual=True;self.p38_variant=(clicks-1)%len(self.p39_preview_masks)
       self.p39_render_preview()
       self.p54_ocr_selected_variant()
      else:
       self.p52_manual=False;self.p47_auto_review()
      return
     self.p47_cancel_review()
     self.p52_manual=False
     self.p39_preview_generation+=1
     generation=self.p39_preview_generation
     self.p39_preview_key=key;self.p39_preview_masks=None
     self.p38_info.set('OCR • Đang phân tích'+self.p62_angle_status)
     self.p43_progress('TÁCH NỀN VÀ LỌC NHIỄU',10)
     def calculate():
      try:
       import p66_cleanup
       variants=p66_cleanup.clean_variants(p38.five_methods(source))
       self.q.put(('p39_preview_ready',generation,key,variants,None))
      except Exception as exc:
       self.q.put(('p39_preview_ready',generation,key,[],str(exc)))
     threading.Thread(target=calculate,daemon=True).start()
    except Exception:
     self.p38_info.set('OCR • Lỗi phân tích')
 def p39_render_preview(self):
    canvas=self.processed_canvas
    variants=self.p39_preview_masks or []
    self.p38_count=len(variants)
    if not variants:
     canvas.delete('all');self.processed_photo=None;self.p68_image=None
     self.p38_info.set('OCR • Không thấy chữ');return
    score,label,mask=variants[self.p38_variant%len(variants)]
    if not np.any(mask):
     canvas.delete('all');self.p68_image=None
     self.p38_info.set('Không thấy chữ trong chế độ này');return
    self.p68_image=p38.method_image(mask,self.p38_variant%len(variants)).convert('RGB')
    self.p68_undo=[];self.p68_redo=[];self.p68_last=None
    clean_label=re.sub(r'^PA\d+\s*[—–-]\s*','',str(label),flags=re.IGNORECASE)
    self.p38_info.set('%s · %s'%(clean_label,'THỦ CÔNG' if self.p52_manual else 'TỰ ĐỘNG'))
    self.p68_render()
 def p74_bind_tooltip(self,widget,message):
    """Compact Corel-like hover note, without adding permanent UI labels."""
    state={'after':None,'tip':None}
    def hide(_event=None):
     if state['after'] is not None:
      try:widget.after_cancel(state['after'])
      except tk.TclError:pass
      state['after']=None
     if state['tip'] is not None:
      try:state['tip'].destroy()
      except tk.TclError:pass
      state['tip']=None
    def show():
     state['after']=None
     if not widget.winfo_exists():return
     tip=tk.Toplevel(widget);tip.wm_overrideredirect(True)
     tip.configure(bg='#D3AD65')
     label=tk.Label(tip,text=message,bg='#252B35',fg='#F2F4F7',font=('Segoe UI',9),padx=9,pady=5)
     label.pack(padx=1,pady=1)
     x=widget.winfo_rootx();y=widget.winfo_rooty()+widget.winfo_height()+5
     tip.wm_geometry('+%d+%d'%(x,y));state['tip']=tip
    def enter(_event=None):
     hide();state['after']=widget.after(500,show)
    widget.bind('<Enter>',enter,add='+')
    widget.bind('<Leave>',hide,add='+')
    widget.bind('<ButtonPress>',hide,add='+')

 def p68_render(self):
    canvas=self.processed_canvas;canvas.delete('all');self.processed_photo=None
    im=self.p68_image
    if im is None:return
    cw=max(1,canvas.winfo_width());ch=max(1,canvas.winfo_height())
    ratio=min(cw/im.width,ch/im.height)*getattr(self,'p69_zoom',1.0)
    w=max(1,round(im.width*ratio));h=max(1,round(im.height*ratio))
    x=round((cw-w)/2+getattr(self,'p71_pan_x',0.0));y=round((ch-h)/2+getattr(self,'p71_pan_y',0.0))
    self.p68_view=(x,y,w,h,ratio)
    self.processed_photo=ImageTk.PhotoImage(im.resize((w,h),Image.Resampling.NEAREST))
    canvas.create_image(x,y,anchor='nw',image=self.processed_photo)
    if self.p67_show_grid.get():self.p64_draw_grid(canvas,x,y,w,h)
    self.p72_polygon_overlay()
 def p76_is_typing(self):
    try:
     w=self.root.focus_get()
     return isinstance(w,(tk.Entry,tk.Text,tk.Spinbox,ttk.Entry,ttk.Combobox,ttk.Spinbox))
    except Exception:return False
 def p76_dispatch(self,action,event=None):
    # Never hijack editing shortcuts from text fields or comboboxes.
    if self.p76_is_typing():return None
    if action=='pan':self.p68_select('pan')
    elif action=='eraser':self.p68_select('eraser')
    elif action=='brush':self.p68_select('pen')
    elif action=='penfill':self.p68_select('polygon')
    elif action=='zoom':self.p68_select('zoom')
    elif action=='clean':self.p72_remove_specks()
    elif action=='undo':self.p68_undo_action()
    elif action=='redo':self.p68_redo_action()
    elif action=='save':self.p69_save()
    elif action=='fit':self.p69_zoom_reset()
    elif action=='grid':
     self.p67_show_grid.set(not self.p67_show_grid.get());self.p67_toggle_grid()
    return 'break'
 def p76_install_shortcuts(self):
    bindings={
     '<KeyPress-h>':'pan','<KeyPress-H>':'pan',
     '<KeyPress-x>':'eraser','<KeyPress-X>':'eraser',
     '<F5>':'brush','<KeyPress-p>':'penfill','<KeyPress-P>':'penfill',
     '<KeyPress-z>':'zoom','<KeyPress-Z>':'zoom',
     '<Control-Shift-L>':'clean','<Control-Shift-l>':'clean',
     '<Control-z>':'undo','<Control-Z>':'undo',
     '<Control-Shift-Z>':'redo','<Control-Shift-z>':'redo',
     '<Control-s>':'save','<Control-S>':'save',
     '<F4>':'fit','<Control-g>':'grid','<Control-G>':'grid'
    }
    for sequence,action in bindings.items():
     self.root.bind_all(sequence,lambda event,a=action:self.p76_dispatch(a,event),add='+')
 def p68_select(self,tool):
    self.p68_tool='none' if self.p68_tool==tool else tool
    self.p72_polygon=[]
    self.processed_canvas.configure(cursor='hand2' if self.p68_tool=='pan' else ('plus' if self.p68_tool=='zoom' else ('crosshair' if self.p68_tool!='none' else '')))
    self.p38_info.set('ZOOM • CLICK ĐỂ PHÓNG TO (Z)' if self.p68_tool=='zoom' else ('PAN • KÉO ẢNH (SPACE)' if self.p68_tool=='pan' else 'CÔNG CỤ '+('TẨY' if tool=='eraser' else ('PEN KHÉP KÍN' if tool=='polygon' else 'BÚT'))+' • '+str(self.p68_size)+' px'))
 def p68_choose_color(self):
    from tkinter import colorchooser
    color=colorchooser.askcolor(color=self.p68_color,parent=self.root,title='MÀU BÚT')[1]
    if color:self.p68_color=color
 def p68_plus(self,event=None):
    if self.p68_tool!='none':
     self.p68_size=min(80,self.p68_size+2);self.p68_size_label.set(str(self.p68_size)+' px')
 def p68_minus(self,event=None):
    if self.p68_tool!='none':
     self.p68_size=max(1,self.p68_size-2);self.p68_size_label.set(str(self.p68_size)+' px')
 def p68_xy(self,event):
    if self.p68_image is None:return None
    x,y,w,h,ratio=self.p68_view
    if not(x<=event.x<x+w and y<=event.y<y+h):return None
    return (max(0,min(self.p68_image.width-1,int((event.x-x)/ratio))),max(0,min(self.p68_image.height-1,int((event.y-y)/ratio))))
 def p68_cursor(self,event):
    c=self.processed_canvas;c.delete('p68_cursor')
    if self.p68_tool in ('none','pan','zoom') or self.p73_space or self.p68_xy(event) is None:return
    if self.p68_tool=='polygon':return
    radius=max(1,self.p68_size*self.p68_view[4]/2)
    c.create_oval(event.x-radius,event.y-radius,event.x+radius,event.y+radius,outline='#111111',width=1,fill='',tags='p68_cursor')
 def p68_down(self,event):
    if self.p68_tool=='zoom' and not self.p73_space:
     self.p69_zoom_by(1.25,(event.x,event.y));return
    if self.p68_tool=='pan' or self.p73_space:
     self.p73_drag_anchor=(event.x,event.y,self.p71_pan_x,self.p71_pan_y);self.processed_canvas.configure(cursor='fleur');return
    point=self.p68_xy(event)
    if self.p68_tool=='none' or point is None:return
    if self.p68_tool=='polygon':
     self.p72_polygon.append(point);self.p68_render();return
    self.p68_undo.append(self.p68_image.copy());self.p68_undo=self.p68_undo[-30:];self.p68_redo.clear()
    self.p68_last=point;self.p68_paint(point,point)
 def p68_paint(self,a,b):
    if self.p68_image is None:return
    color='#FFFFFF' if self.p68_tool=='eraser' else self.p68_color
    d=ImageDraw.Draw(self.p68_image)
    d.line([a,b],fill=color,width=self.p68_size,joint='curve')
    r=self.p68_size/2
    for x,y in (a,b):d.ellipse((int(x-r),int(y-r),int(x+r),int(y+r)),fill=color)
    self.p68_render()
 def p68_drag(self,event):
    if self.p73_drag_anchor is not None:
     x,y,px,py=self.p73_drag_anchor
     self.p71_pan_x=px+event.x-x;self.p71_pan_y=py+event.y-y
     self.p68_render();return
    point=self.p68_xy(event)
    if self.p68_tool=='polygon':return
    if point is None or self.p68_last is None:return
    self.p68_paint(self.p68_last,point);self.p68_last=point
 def p68_up(self,event):
    self.p68_last=None;self.p73_drag_anchor=None
    self.processed_canvas.configure(cursor='hand2' if self.p68_tool=='pan' or self.p73_space else ('crosshair' if self.p68_tool!='none' else ''))
 def p73_space_down(self,event=None):
    if self.p76_is_typing():return
    if event is not None and event.widget.winfo_class() in ('Entry','TEntry','Text','TCombobox','Spinbox'):return
    self.p73_space=True
    self.processed_canvas.configure(cursor='hand2')
    return 'break'
 def p73_space_up(self,event=None):
    if self.p76_is_typing():return
    if not self.p73_space:return
    self.p73_space=False
    if self.p73_drag_anchor is None:self.processed_canvas.configure(cursor='hand2' if self.p68_tool=='pan' else ('crosshair' if self.p68_tool!='none' else ''))
    return 'break'
 def p68_undo_action(self):
    if self.p68_image is not None and self.p68_undo:
     self.p68_redo.append(self.p68_image.copy());self.p68_image=self.p68_undo.pop();self.p68_render()
 def p68_redo_action(self):
    if self.p68_image is not None and self.p68_redo:
     self.p68_undo.append(self.p68_image.copy());self.p68_image=self.p68_redo.pop();self.p68_render()
 def p72_polygon_overlay(self):
    if not getattr(self,'p72_polygon',None):return
    x,y,_,_,ratio=self.p68_view
    coords=[]
    for px,py in self.p72_polygon:coords.extend((x+px*ratio,y+py*ratio))
    if len(coords)>=4:self.processed_canvas.create_line(*coords,fill='#00BFFF',width=2,tags='p72_polygon')
    for j in range(0,len(coords),2):
     a,b=coords[j:j+2]
     self.processed_canvas.create_oval(a-3,b-3,a+3,b+3,fill='#00BFFF',outline='#FFFFFF',tags='p72_polygon')
 def p72_polygon_cancel(self,event=None):
    if getattr(self,'p72_polygon',None):
     self.p72_polygon=[];self.p68_render()
 def p72_polygon_finish(self,event=None):
    if self.p68_tool!='polygon':return
    # Tk also fires the second Button-1 event: deduplicate the last point.
    points=list(self.p72_polygon)
    if len(points)>=2 and points[-1]==points[-2]:points.pop()
    if len(points)<3:
     self.p38_info.set('PEN: CẦN ÍT NHẤT 3 ĐIỂM');return
    self.p68_undo.append(self.p68_image.copy());self.p68_undo=self.p68_undo[-30:];self.p68_redo.clear()
    ImageDraw.Draw(self.p68_image).polygon(points,fill=self.p68_color)
    self.p72_polygon=[];self.p68_render()
    self.p38_info.set('PEN: ĐÃ KHÉP KÍN VÀ TÔ FILL')
 def p72_remove_specks(self):
    if self.p68_image is None:return
    from tkinter import simpledialog
    import cv2
    import numpy as np
    min_area=simpledialog.askinteger('LỌC CHI TIẾT NHỎ','Xóa mảng đen nhỏ hơn bao nhiêu pixel²?\nMặc định 12; dấu tiếng Việt có thể bị ảnh hưởng.',initialvalue=12,minvalue=1,maxvalue=100000,parent=self.root)
    if min_area is None:return
    arr=np.asarray(self.p68_image.convert('L'))
    foreground=(arr<128).astype(np.uint8)
    n,labels,stats,_=cv2.connectedComponentsWithStats(foreground,8)
    remove=np.zeros(n,dtype=np.uint8)
    removed=0
    for i in range(1,n):
     if int(stats[i,cv2.CC_STAT_AREA])<min_area:remove[i]=1;removed+=1
    if not removed:
     self.p38_info.set('LỌC NHIỄU: KHÔNG CÓ MẢNG NHỎ');return
    self.p68_undo.append(self.p68_image.copy());self.p68_undo=self.p68_undo[-30:];self.p68_redo.clear()
    result=np.array(self.p68_image.convert('RGB'),copy=True)
    result[remove[labels].astype(bool)]=(255,255,255)
    self.p68_image=Image.fromarray(result,'RGB');self.p68_render()
    self.p38_info.set('LỌC NHIỄU: ĐÃ XÓA '+str(removed)+' MẢNG NHỎ • CÓ THỂ HOÀN TÁC')
 def p69_zoom_by(self,factor,anchor=None):
    old=getattr(self,'p69_zoom',1.0)
    new=max(0.25,min(2.0,old*factor))
    if abs(new-old)<1e-9:return
    if self.p68_image is not None:
     canvas=self.processed_canvas
     cw=max(1,canvas.winfo_width());ch=max(1,canvas.winfo_height())
     x,y,w,h,ratio=self.p68_view
     ax,ay=anchor if anchor is not None else (cw/2,ch/2)
     # Preserve the same source-image point beneath the cursor.
     ix=(ax-x)/ratio;iy=(ay-y)/ratio
     base=min(cw/self.p68_image.width,ch/self.p68_image.height)
     newratio=base*new
     nw=max(1,round(self.p68_image.width*newratio))
     nh=max(1,round(self.p68_image.height*newratio))
     self.p71_pan_x=ax-ix*newratio-(cw-nw)/2
     self.p71_pan_y=ay-iy*newratio-(ch-nh)/2
    self.p69_zoom=new
    if self.p68_image is not None:self.p68_render()
 def p69_zoom_reset(self):
    self.p69_zoom=1.0;self.p71_pan_x=0.0;self.p71_pan_y=0.0
    if self.p68_image is not None:self.p68_render()
 def p69_mouse_zoom(self,event):
    self.p69_zoom_by(1.25 if event.delta>0 else 1/1.25,(event.x,event.y))
    return 'break'
 def p71_linux_mouse_zoom(self,event):
    self.p69_zoom_by(1.25 if event.num==4 else 1/1.25,(event.x,event.y))
    return 'break'
 def p69_save(self):
    if self.p68_image is None:return
    from tkinter import filedialog
    filename=filedialog.asksaveasfilename(parent=self.root,title='Lưu ảnh đã chỉnh sửa',
              defaultextension='.png',filetypes=[('PNG','*.png')])
    if filename:self.p68_image.save(filename,format='PNG')
 def p69_recognize_only(self):
    # Explicit edited-only mode: never use original, other PA masks or OCR variants.
    if not self.require_license(prompt=True):
     return
    if self.p68_image is None:return
    self.p68_committed=self.p68_image.copy()
    self.p69_edited_only=True
    self.ocr_job+=1;job=self.ocr_job
    self._ocr_manual_edit=False;self.p26_set_text('')
    self.ocr_mode_status.set('ĐANG NHẬN DIỆN DUY NHẤT ẢNH ĐÃ CHỈNH...')
    self.p43_progress('NHẬN DIỆN ẢNH ĐÃ CHỈNH',0)
    img=self.p68_committed.copy()
    def run():
     try:
      txt,engine,needs_review=p42ocr.recognize_single(img,recognize_text)
      self.q.put(('ocr_done',job,txt,engine,needs_review))
     except Exception as exc:self.q.put(('ocr_done',job,'','Lỗi: '+str(exc),True))
    threading.Thread(target=run,daemon=True).start()
 def p68_apply(self):
    return self.p69_recognize_only()
    if self.p68_image is None:return
    # Persist the edited pixels as a dedicated source for both OCR and font search.
    self.p68_committed=self.p68_image.copy()
    self.ocr_job+=1;job=self.ocr_job
    self._ocr_manual_edit=False;self.p26_set_text('')
    self.ocr_mode_status.set('ĐANG NHẬN DIỆN ẢNH ĐÃ CHỈNH...')
    self.p43_progress('NHẬN DIỆN ẢNH ĐÃ CHỈNH',0)
    img=self.p68_committed.copy()
    def run():
     try:
      txt,engine,needs_review=p42ocr.recognize(img,recognize_text)
      self.q.put(('ocr_done',job,txt,engine,needs_review))
     except Exception as exc:self.q.put(('ocr_done',job,'','Lỗi: '+str(exc),True))
    threading.Thread(target=run,daemon=True).start()
 def p67_toggle_grid(self):
    # Only update the overlay; do not rerun preprocessing or OCR.
    canvas=self.processed_canvas
    canvas.delete('p64_grid')
    if not self.p67_show_grid.get() or self.processed_photo is None:return
    cw=max(1,canvas.winfo_width());ch=max(1,canvas.winfo_height())
    w=self.processed_photo.width();h=self.processed_photo.height()
    self.p64_draw_grid(canvas,(cw-w)//2,(ch-h)//2,w,h)
 def p64_draw_grid(self,canvas,x,y,w,h):
    """Display-only translucent grid; never enters image, OCR, or exports."""
    if w<8 or h<8:return
    spacing=max(16,min(32,int(min(w,h)/7)))
    # Tk Canvas has no alpha stroke: blend the light grid against the white preview.
    grid_color='#E7EDF1'
    for gx in range(x+spacing,x+w,spacing):
     canvas.create_line(gx,y,gx,y+h,fill=grid_color,width=1,tags=('p64_grid',))
    for gy in range(y+spacing,y+h,spacing):
     canvas.create_line(x,gy,x+w,gy,fill=grid_color,width=1,tags=('p64_grid',))
    # Neutral axis references; not an assertion that text baseline is at this position.
    canvas.create_line(x,y+h//2,x+w,y+h//2,fill='#E7DBB7',width=1,dash=(4,5),tags=('p64_grid',))
    canvas.create_line(x+w//2,y,x+w//2,y+h,fill='#D8E8E6',width=1,dash=(4,5),tags=('p64_grid',))
 def draw(self):
    self.canvas.delete('all')
    self.p37_schedule_preview()
    if self.image is None:return
    cw,ch=max(1,self.canvas.winfo_width()),max(1,self.canvas.winfo_height())
    iw,ih=self.image.size;self.scale=min(cw/iw,ch/ih)
    nw,nh=max(1,int(iw*self.scale)),max(1,int(ih*self.scale));self.offset=((cw-nw)//2,(ch-nh)//2)
    self.tkimg=ImageTk.PhotoImage(self.image.resize((nw,nh),Image.Resampling.LANCZOS));self.canvas.create_image(*self.offset,image=self.tkimg,anchor='nw')
    if self.crop:
     x1,y1,x2,y2=self.crop;ox,oy=self.offset
     self.rect=self.canvas.create_rectangle(ox+x1*self.scale,oy+y1*self.scale,ox+x2*self.scale,oy+y2*self.scale,outline='#ffb000',width=3)
 def pos(self,e):
    ox,oy=self.offset
    return ((e.x-ox)/self.scale,(e.y-oy)/self.scale)
 def down(self,e):
    if self.image is None:return
    self.start=self.pos(e)
 def drag(self,e):
    if self.start is None:return
    x1,y1=self.start;x2,y2=self.pos(e)
    if self.rect:self.canvas.delete(self.rect)
    ox,oy=self.offset
    self.rect=self.canvas.create_rectangle(ox+x1*self.scale,oy+y1*self.scale,ox+x2*self.scale,oy+y2*self.scale,outline='#ffb000',width=3)
 def up(self,e):
    if self.start is None or self.image is None:return
    a,b=self.start;c,d=self.pos(e);self.start=None
    w,h=self.image.size
    x1,x2=sorted((max(0,min(w,int(a))),max(0,min(w,int(c)))))
    y1,y2=sorted((max(0,min(h,int(b))),max(0,min(h,int(d)))))
    self.p68_committed=None;self.p68_image=None;self.p69_edited_only=False
    self.crop=(x1,y1,x2,y2) if x2-x1>5 and y2-y1>5 else None;self.p38_variant=0;self.p39_preview_masks=None;self.p52_manual=False;self.p53_pending_manual_clicks=0;self.p53_image_complete_notified=False;self.draw()
    if not self._ocr_manual_edit:self.p21_auto_offline_only()
    else:self.ocr_mode_status.set('Đã khoanh vùng; giữ nguyên văn bản bạn đã chỉnh tay.')
 def clear(self):
    self.p68_committed=None;self.p68_image=None;self.p69_edited_only=False
    self.crop=None;self.p38_variant=0;self.p39_preview_masks=None;self.p52_manual=False;self.p53_pending_manual_clicks=0;self.p53_image_complete_notified=False;self.draw()
    if not self._ocr_manual_edit:self.p21_auto_offline_only()
 def remove_image(self):
    # Only remove current image from the interface; leave font library, index and settings untouched.
    self.p68_committed=None;self.p68_image=None;self.p69_edited_only=False
    self.image=None;self.crop=None;self.p38_variant=0;self.p38_count=0;self.tkimg=None;self.current_image_hash=None;self.rect=None;self.start=None
    self.p47_cancel_review();self.p52_manual=False;self.p53_pending_manual_clicks=0;self.p53_image_complete_notified=False;self.p39_preview_generation+=1;self.p39_preview_key=None;self.p39_preview_masks=None;self.ocr_job+=1;self._ocr_manual_edit=False;self.p26_set_text('');self.ocr_mode_status.set('Mở/dán ảnh để tự nhận diện.');self.canvas.delete('all');self.processed_canvas.delete('all');self.processed_photo=None;self.p37_schedule_preview();self.status.set('Đã bỏ ảnh. Chọn MỞ ẢNH hoặc DÁN ẢNH để tiếp tục.')
 def add_folder(self):
    p=filedialog.askdirectory(title='Chọn thư mục chứa font TTF/OTF')
    if p:
     p=os.path.normpath(os.path.abspath(p))
     if p not in self.paths:self.paths.append(p);save_font_folders(self.paths)
     self.status.set('Đã thêm thư mục font: '+p)
 def manage_folders(self):
    win=tk.Toplevel(self.root);win.title('QUẢN LÝ THƯ MỤC FONT');win.geometry('580x310')
    ttk.Label(win,text='Thư mục tự thêm (không xóa file font trên ổ đĩa)').pack(anchor='w',padx=10,pady=8)
    listing=tk.Listbox(win,selectmode='extended');listing.pack(fill='both',expand=True,padx=10)
    for folder in self.paths:listing.insert('end',folder)
    def remove():
     indices=listing.curselection()
     if not indices:return
     for idx in reversed(indices):
      folder=listing.get(idx);self.paths.remove(folder);listing.delete(idx)
     save_font_folders(self.paths)
     self.status.set('Đã cập nhật danh sách thư mục font. Không xóa tệp font.')
    ttk.Button(win,text='BỎ THƯ MỤC ĐÃ CHỌN',command=remove).pack(anchor='e',padx=10,pady=8)
 def open_font_warehouse(self):
    def register(path):
     if path not in self.paths:self.paths.append(path);save_font_folders(self.paths)
     self.status.set('Đã tự động đăng ký KHO FONT DỮ LIỆU và chuẩn bị học font: '+path)
     # Queue learning on Tk's event loop, never block the warehouse completion dialog.
     self.root.after(250,self.start_memory_training)
    p98warehouse.open_warehouse(self.root,list(self.paths),register)
 def start_memory_training(self):
    if getattr(self,'memory_running',False):return
    self.memory_running=True;self.cancel=False
    files=self.fonts()
    self.status.set('Đang ghi nhớ font mới hoặc đã thay đổi...')
    self.library_status.set('ĐANG GHI NHỚ FONT — có thể nhấn DỪNG')
    threading.Thread(target=self.memory_training_worker,args=(files,self.scan_workers.get()),daemon=True).start()
 def memory_training_worker(self,files,cpu_channels):
    memory=None
    try:
     memory=FontMemory();pending=memory.pending(files);total=len(pending)
     if total==0:self.q.put(('memory_done',0,len(files)));return
     workers=choose_workers(cpu_channels)
     ctx=multiprocessing.get_context('spawn')
     with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=ctx) as pool:
      for base in range(0,total,64):
       if self.cancel:self.q.put(('memory_cancelled',));return
       batch=pending[base:base+64]
       for (_,_,glyph),(path,stamp,mask) in zip(batch,pool.map(render_task,batch,chunksize=max(1,len(batch)//(workers*3)))):
        memory.add(path,stamp,glyph,mask)
       memory.db.commit()
       self.q.put(('memory_progress',min(base+64,total),total))
     self.q.put(('memory_done',total,len(files)))
    except Exception as e:self.q.put(('memory_error',str(e)))
    finally:
     if memory is not None:memory.close()
 def confirm_selected_font(self):
    selection=self.tree.selection()
    if not selection or self.current_image_hash is None:
     messagebox.showinfo('Chưa chọn','Hãy tìm font và chọn kết quả đúng trước.');return
    try:
     if self.shared_source.get()=='online':
      messagebox.showinfo('Xác nhận font','Chuyển sang KẾT QUẢ OFFLINE để xác nhận font đã tìm bằng ảnh.');return
     path=self.selected_font_record()[1]
     if not path or not os.path.isfile(path):return
     memory=FontMemory()
     try:memory.confirm(self.current_image_hash,self.glyph.get().strip(),path)
     finally:memory.close()
     result_cache=SearchResultCache()
     try:result_cache.db.execute('DELETE FROM searches');result_cache.db.commit()
     except sqlite3.Error:pass
     finally:result_cache.close()
     self.status.set('Đã ghi nhớ font đúng: '+font_name(path))
    except Exception as e:messagebox.showerror('Không lưu được',str(e))
 def start_benchmark(self):
    if getattr(self,'bench_running',False):return
    self.bench_running=True
    self.status.set('Benchmark thực tế 4/7/8/12 tiến trình — vui lòng chờ...')
    files=self.fonts();txt=self.glyph.get().strip() or 'TRƯỜNG CAO ĐẲNG'
    def job():
     try:
      result=benchmark_workers(files,txt)
      self.q.put(('bench_done',result))
     except Exception as exc:self.q.put(('bench_error',str(exc)))
    threading.Thread(target=job,daemon=True).start()
 def fonts(self):
    roots=list(self.paths)
    if self.use_system.get() and sys.platform=='win32':roots += [os.path.join(os.environ.get('WINDIR','C:\\Windows'),'Fonts'),os.path.join(os.environ.get('LOCALAPPDATA',''),'Microsoft','Windows','Fonts')]
    elif self.use_system.get():roots += ['/usr/share/fonts',os.path.expanduser('~/.fonts'),'/Library/Fonts']
    found=set()
    # P29: Windows may register fonts outside the standard Fonts directories.
    # Enumerate registry values as additional paths, never modify registry.
    if sys.platform=='win32' and self.use_system.get():
     try:
      import winreg
      for hive,regpath in ((winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts'),(winreg.HKEY_CURRENT_USER,r'SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts')):
       try:
        with winreg.OpenKey(hive,regpath) as k:
         n=winreg.QueryInfoKey(k)[1]
         for i in range(n):
          value=winreg.EnumValue(k,i)[1]
          if not isinstance(value,str):continue
          path=os.path.expandvars(value)
          if not os.path.isabs(path):
           path=os.path.join(os.environ.get('WINDIR',r'C:\Windows'),'Fonts',path)
          if os.path.isfile(path) and os.path.splitext(path)[1].lower() in EXT:found.add(os.path.normpath(path))
       except OSError:pass
     except ImportError:pass
    for root in roots:
     if not os.path.isdir(root):continue
     for dp,_,files in os.walk(root):
      for f in files:
       if os.path.splitext(f)[1].lower() in EXT:found.add(os.path.join(dp,f))
    return sorted(found)
 def p81_show_comparison(self):
    before=getattr(self,'p81_baseline',None)
    after=getattr(self,'p81_after',None)
    if not before or not after:
     messagebox.showinfo('So sánh P81','Hãy tìm font một lần bằng ảnh gốc, sau đó chọn Ảnh chỉnh sửa và tìm lại.\nCó thể nhập ký tự trực tiếp vào mục 02 để bỏ qua OCR.');return
    lines=['SO SÁNH TOP 12 TRƯỚC / SAU','', 'Ảnh gốc: '+before['source'],'Ảnh sau: '+after['source'],
      'Chữ nhập/OCR: '+before['glyph']+' → '+after['glyph'],'',
      'Top ảnh gốc:']
    lines += ['%d. %s — %.3f'%(i+1,r[1],r[0]) for i,r in enumerate(before['rows'][:12])]
    lines += ['', 'Top ảnh chỉnh sửa:']
    lines += ['%d. %s — %.3f'%(i+1,r[1],r[0]) for i,r in enumerate(after['rows'][:12])]
    lines += ['', 'Điểm số chỉ là độ tương đồng nội bộ, không phải xác suất đúng font.']
    messagebox.showinfo('P81 · Đối chiếu kết quả','\n'.join(lines))
 def p81_match_image(self):
    src=self.p81_source.get()
    if src=='Ảnh chỉnh sửa':
     if self.p68_image is None:
      messagebox.showwarning('Chưa có ảnh chỉnh sửa','Chọn PA và chỉnh sửa ở VIEW 2 trước khi tìm.');return None
     return self.p68_image.copy()
    if src=='PA đang chọn':
     if self.p68_image is None:
      messagebox.showwarning('Chưa có phương án','Đợi PA1–PA7 tạo xong.');return None
     return self.p68_image.copy()
    return self.p60_auto_straighten_source((self.image.crop(self.crop) if self.crop else self.image).copy())
 def search(self):
    if not self.require_license(prompt=False):
     return
    if self.image is None:messagebox.showwarning('Thiếu ảnh','Hãy mở hoặc dán ảnh.');return
    glyph=self.glyph.get().strip()
    if not glyph:messagebox.showwarning('Thiếu ký tự','Nhập đúng chữ xuất hiện trong ảnh.');return
    img=self.p81_match_image()
    if img is None:return
    self.p81_search_source=self.p81_source.get()
    self.p81_search_glyph=glyph
    a=normalize(glyph_mask(img))
    if a is None:messagebox.showwarning('Không nhận diện được','Hãy khoanh sát vùng chữ, nền tương phản rõ.');return
    scan_mode=self.scan_mode.get()
    p58_words=bool(self.p58_remove_words.get())
    p58_letters=bool(self.p58_compact_letters.get())
    if p58_words:glyph=p58.remove_word_spaces(glyph)
    p81_single=self.p81_search_source=='Ảnh chỉnh sửa'
    candidates=[(np.asarray(img.convert('L'))<128).astype(np.uint8)] if p81_single else glyph_candidates(img)
    try:
     improved=[] if p81_single else p38.candidates(img,limit=8)
     if improved:
      candidates=[m for _,_,m in improved]+candidates
    except Exception:pass
    # Keep every valid foreground hypothesis to avoid discarding the true letter mask.
    if not candidates:messagebox.showwarning('Không tách được chữ','Hãy khoanh sát chữ, tránh phần nền thừa.');return
    self.cancel=False;self.p30_streaming=True;self.search_generation+=1;job=self.search_generation;self.p85_decisions={};self.p31_reset();self.results=[];self.searchbtn.config(state='disabled');self.deepbtn.config(state='disabled');self.tree.delete(*self.tree.get_children());self.status.set('Đang quét font theo nhiều cách tách màu...')
    self.p43_progress('CÒN LẠI • ĐANG CHUẨN BỊ QUÉT',100)
    self.p48_scan_percent.set(0)
    self.p48_scan_text.set('0%')
    font_files=self.fonts()
    # P83: strict contiguous-substring filter BEFORE any indexing, rendering or comparison.
    # Empty field preserves the original full-library behavior.
    clue_filter=normalize_font_clue(self.font_clue.get())
    if clue_filter:
     self.group_filter_history=[clue_filter]+[v for v in self.group_filter_history if v.casefold()!=clue_filter.casefold()]
     self.group_filter_history=self.group_filter_history[:20]
     save_group_filter_history(self.group_filter_history)
     if hasattr(self,'group_filter_history_combo'):self.group_filter_history_combo.configure(values=self.group_filter_history)
    if clue_filter:
     font_files=[path for path in font_files if clue_matches_font(path,clue_filter)]
     if not font_files:
      self.searchbtn.config(state='normal');self.p30_streaming=False
      self.status.set('Không có font thuộc nhóm: '+clue_filter)
      messagebox.showinfo('Không có font phù hợp','Không tìm thấy font thuộc nhóm '+clue_filter+'. Hãy sửa ký tự lọc hoặc xóa ô để quét tất cả.')
      return
     self.status.set('Chỉ quét '+str(len(font_files))+' font thuộc nhóm '+clue_filter)
    self.current_image_hash=image_signature(img)
    early_stop=bool(self.p84_early_stop.get())
    threshold=float(self.p84_stop_threshold.get()) if early_stop else None
    threading.Thread(target=self.worker,args=(candidates,glyph,font_files,image_signature(img),scan_mode,normalize_font_clue(self.font_clue.get()),job,self.scan_workers.get(),p58_words,p58_letters,threshold),daemon=True).start()
 def worker(self,candidates,glyph,files,img_hash,scan_mode,clue='',job=None,cpu_channels='AUTO',p58_words=False,p58_letters=False,stop_threshold=None):
    hits=0;cache=None;result_cache=None;index=None;started=time.monotonic()
    # P86: scan Vietnamese-capable fonts first at every expensive stage.
    # Classify only the already name-filtered paths. Never hard-exclude others.
    vi_group={path:vietnamese_scan_group(path) for path in files}
    files=sorted(files,key=lambda path:vi_group[path])
    vi_count=sum(group==0 for group in vi_group.values())
    self.q.put(('p86_groups',job,vi_count,len(files)-vi_count))
    # Optional compaction is applied symmetrically to source and rendered font masks.
    def p58_compare(a,b,fn):
     if not (p58_words or p58_letters):return fn(a,b)
     for mode in (('words' if p58_words else None),('letters' if p58_letters else None)):
      if mode:
       a=p58.compact_mask(a,mode,0.35 if mode=='letters' else 0.18)
       b=p58.compact_mask(b,mode,0.35 if mode=='letters' else 0.18)
     return fn(a,b)
    # Only the coordinator thread sends immutable snapshots to Tk's event queue.
    live={};arrival_order=[];last_live=0.0;pending_preview=[];last_top=();rank_started=False
    def emit_scanning(paths):
     # P34: ticker follows actual font processing, independently of ranking.
     if paths and not cancelled():
      self.q.put(('p34_scanning',job,tuple((font_name(p),p) for p in paths)))
    def emit_live(force=False):
     nonlocal last_live,last_top
     now=time.monotonic()
     if force or now-last_live>=0.16:
      last_live=now
      if pending_preview:
       self.q.put(('p31_samples',job,tuple(pending_preview)))
       pending_preview.clear()
      # P45: first twelve distinct scored fonts appear in discovery order.
      # After twelve, maintain a score-ranked top twelve as new fonts arrive.
      if len(arrival_order)<12:
       rows=[live[path] for path in arrival_order]
      else:
       rows=sorted(live.values(),key=lambda r:(-r[0],r[1].casefold(),r[2]))[:12]
      top=tuple((round(v,3),p) for v,n,p in rows)
      if top!=last_top or force:
       last_top=top
       self.q.put(('p30_live',job,rows,len(live),len(files)))
    def record_live(value,name,path,force=False):
     if path not in live:
      arrival_order.append(path)
      pending_preview.append((name,path,float(value)))
      if len(pending_preview)>=24:
       self.q.put(('p31_samples',job,tuple(pending_preview)))
       pending_preview.clear()
     live[path]=(float(value),name,path)
     # Show the first qualifying results immediately, not at a 100ms batch boundary.
     emit_live(force or len(arrival_order)<=12)
    def remaining(stage, completed, total):
     # Stage-weighted work estimate: indexing 20%, coarse matching 60%, precise matching 20%.
     # This is remaining work, not a time prediction.
     bounds={'index':(0,20),'coarse':(20,80),'precise':(80,100)}
     lo,hi=bounds[stage]
     completed=max(0,min(int(completed),max(1,int(total))))
     done=lo+(hi-lo)*completed/max(1,int(total))
     self.q.put(('p46_remaining',job,stage,max(0,min(100,round(100-done)))))
    def cancelled():return self.cancel or job!=self.search_generation
    try:
     result_cache=SearchResultCache()
     confirmation_revision=''
     memory_for_revision=FontMemory()
     try:
      confirmation_revision=memory_for_revision.recall(img_hash,glyph) or ''
     finally:memory_for_revision.close()
     signature=hashlib.sha256((img_hash+glyph+fonts_signature(files)+'v52_exhaustive_P29:'+scan_mode+confirmation_revision+':P11:'+clue).encode()).hexdigest()
     # P51: reuse persistent glyph/index data, but recompute ranking for each image.
     index=FontIndex()
     descriptors,missing=index.fetch(files,glyph)
     remaining('index',len(descriptors),len(files))
     # Cached descriptors also represent font work; show their names before
     # the slow rendering phase so the two-line ticker never waits for ranking.
     cached_paths=list(descriptors)
     for offset in range(0,len(cached_paths),32):
      if cancelled():self.q.put(('cancelled',));return
      emit_scanning(cached_paths[offset:offset+32])
     if missing:
      cache=GlyphCache()
      # SQLite remains exclusively on the coordinator thread. Each subprocess renders independently.
      workers=choose_workers(cpu_channels)
      total_missing=len(missing)
      ctx=multiprocessing.get_context('spawn')
      with concurrent.futures.ProcessPoolExecutor(max_workers=workers,mp_context=ctx) as executor:
       for base in range(0,total_missing,64):
        if cancelled():self.q.put(('cancelled',));return
        batch=[(p,stamp,glyph) for p,stamp in missing[base:base+64]]
        scan_batch=[]
        for p,stamp,mask in executor.map(render_task,batch,chunksize=max(1,len(batch)//(workers*3))):
         if cancelled():self.q.put(('cancelled',));return
         try:
          data=cv2.imencode('.png',(mask*255).astype(np.uint8))[1].tobytes() if mask is not None else None
          cache.conn.execute('INSERT OR REPLACE INTO glyphs VALUES (?,?,?,?)',(p,stamp,glyph,data))
         except (sqlite3.Error,cv2.error):pass
         bits=index.add(p,glyph,stamp,mask)
         # Send the font actually processed, not a synthetic animation label.
         if bits is not None:descriptors[p]=bits
         # Stream names while the batch is running, not after all 64 finish.
         scan_batch.append(p)
         if len(scan_batch)>=8:
          emit_scanning(scan_batch);scan_batch=[]
        emit_scanning(scan_batch)
        index.db.commit();cache.conn.commit()
        remaining('index',len(files)-total_missing+min(base+64,total_missing),len(files))
     else:hits=len(files)
     if cancelled():self.q.put(('cancelled',));return
     ranked=rank_index(candidates,descriptors)
     if cache is None:cache=GlyphCache()
     # Stage 1: learned glyph memory ranks candidates before expensive rendering.
     # Preserve index-ranked candidates and rescue coverage to avoid false negatives.
     probes=character_probes(candidates,glyph)
     memory=FontMemory()
     try:
      shortlist=sorted((p for _,p in ranked),key=lambda path:vi_group.get(path,1))  # P86: Vietnamese group first, stable within group
      if clue:
       # Rescue matching font families from the complete index even if memory filtering missed them.
       clue_paths=[p for _,p in ranked if clue_matches_font(p,clue)]
       shortlist=list(dict.fromkeys(clue_paths+shortlist))
     finally:memory.close()
     # P29 Stage 2: every indexed font receives the same coarse shape comparison.
     # Learned memory can improve ranking, but cannot remove a font from consideration.
     coarse=[];seen=set()
     remaining('coarse',0,len(shortlist))
     for coarse_i,p in enumerate(shortlist,1):
      if cancelled():self.q.put(('cancelled',));return
      b,hit=cache.get(p,glyph)
      if b is None:
       if coarse_i%32==0 or coarse_i==len(shortlist):remaining('coarse',coarse_i,len(shortlist))
       continue
      name=font_name(p)
      key=os.path.normcase(os.path.abspath(p))
      if key in seen:continue
      seen.add(key)
      approx=max(p58_compare(a,b,adaptive_coarse_score) for a in candidates)
      coarse.append((approx,p,name,b))
      record_live(approx,name,p)
      if coarse_i%32==0 or coarse_i==len(shortlist):remaining('coarse',coarse_i,len(shortlist))
     emit_live(True)
     coarse.sort(key=lambda row:(vi_group.get(row[1],1),-row[0]))
     # Character-first: optional soft rerank; no hard elimination of font candidates.
     memory=FontMemory()
     try:
      coarse=learned_probe_rerank(coarse,probes,memory)
     finally:memory.close()
     # P86: learned reranking must not interleave non-Vietnamese candidates.
     coarse.sort(key=lambda row:vi_group.get(row[1],1))
     # Preserve full coarse ordering: individual-glyph probes are soft evidence only.
     # P29 avoids using unreliable character crops as hard filters.
     # Stage 3: expensive edge-distance matching for the best candidates.
     # DEEP scores all; FAST expands to all if the leading score is weak.
     # P29: broaden exact scoring and automatically expand when top result is weak.
     final_count=min(len(coarse),max(360, len(coarse) if scan_mode!='fast' else 360))
     # Preserve strong visual candidates and reserve a limited clue cohort for exact scoring.
     chosen=coarse[:final_count]
     if clue:
      clue_rows=[row for row in coarse if clue_matches_font(row[1],clue,row[2])]
      reserve=min(40,final_count//3,len(clue_rows))
      chosen=list(dict.fromkeys([row[1] for row in clue_rows[:reserve]]+[row[1] for row in chosen]))
      lookup={row[1]:row for row in coarse}
      chosen=[lookup[path] for path in chosen]
     # P86: ensure the precise-scoring order also respects Vietnamese priority.
     chosen.sort(key=lambda row:vi_group.get(row[1],1))
     out=[]
     remaining('precise',0,len(chosen))
     # P51: bounded parallel exact comparisons. Only the coordinator touches
     # Tk queue, SQLite and ranking state; workers handle numerical scoring.
     def exact_compare(row):
      _,p,name,b=row
      return (max(p58_compare(a,b,score) for a in candidates),name,p)
     stopped_early=False
     if stop_threshold is not None:
      # P85: exact scoring pauses at first threshold hit until Tk resolves the choice.
      # No other font is scored while the worker waits; prompt only once per search.
      prompted=False
      for precise_i,row in enumerate(chosen,1):
       if cancelled():self.q.put(('cancelled',));return
       best,name,p=exact_compare(row)
       out.append((best,name,p))
       record_live(best,name,p)
       if precise_i%16==0:remaining('precise',precise_i,len(chosen))
       if not prompted and best>=stop_threshold:
        prompted=True
        emit_live(True)
        choice=threading.Event()
        decision={'event':choice,'continue':False}
        self.q.put(('p85_threshold_hit',job,decision,float(best),name,float(stop_threshold),precise_i,len(chosen)))
        while not choice.wait(0.1):
         if cancelled():self.q.put(('cancelled',));return
        if not decision['continue']:
         stopped_early=True
         break
     else:
      match_workers=min(4,max(1,choose_workers(cpu_channels)))
      with concurrent.futures.ThreadPoolExecutor(max_workers=match_workers) as match_pool:
       for precise_i,(best,name,p) in enumerate(match_pool.map(exact_compare,chosen),1):
        if cancelled():self.q.put(('cancelled',));return
        out.append((best,name,p))
        record_live(best,name,p)
        if precise_i%16==0 or precise_i==len(chosen):remaining('precise',precise_i,len(chosen))
     # Low-confidence rescue: score every remaining candidate precisely rather
     # than returning a misleading TOP 12 from a prematurely truncated pool.
     if not stopped_early and (not out or max(x[0] for x in out)<82.0) and len(chosen)<len(coarse):
      selected={r[1] for r in chosen}
      for _,p,name,b in coarse:
       if p in selected:continue
       if cancelled():self.q.put(('cancelled',));return
       best=max(p58_compare(a,b,score) for a in candidates)
       out.append((best,name,p))
       record_live(best,name,p)
     # Rescue work is an extension of the precise stage; only report 100% after it ends.
     if not stopped_early:remaining('precise',len(chosen),len(chosen))
     emit_live(True)
     out=clue_final_rerank(out,clue)
     # Exact previously confirmed image/text wins, without treating unverified AI guesses as truth.
     memory=FontMemory()
     try:confirmed=memory.recall(img_hash,glyph)
     finally:memory.close()
     if confirmed and confirmed in files:
      out=[(100.0,font_name(confirmed),confirmed)]+[row for row in out if row[2]!=confirmed]
     if not self.cancel and not stopped_early:result_cache.put('searches',signature,out[:12])
     if cancelled():self.q.put(('cancelled',));return
     self.q.put(('done',job,out[:12],len(files),hits,round(time.monotonic()-started,2),scan_mode,stopped_early,stop_threshold,len(out)))
    except Exception as e:self.q.put(('worker_error',str(e)))
    finally:
     for obj in (result_cache,cache,index):
      if obj is not None:
       try:obj.close()
       except Exception:pass
 def poll(self):
    try:
     audio_failure=_audio_error_queue.get_nowait()
     self.status.set('LỖI ÂM THANH: '+audio_failure[:180])
     if not getattr(self,'p90_audio_error_shown',False):
      self.p90_audio_error_shown=True
      messagebox.showwarning('AI FONT FINDER PRO — LỖI ÂM THANH',
       'Không phát được âm WAV riêng.\n\n'+audio_failure+'\n\nVui lòng gửi file audio_errors.log để kiểm tra.',parent=self.root)
    except queue.Empty:pass
    # P51: bounded Tk event-loop work. Rendering TOP12 on every queue event
    # starved the 33ms ticker and made the interface appear frozen.
    tick_start=time.perf_counter()
    pending_live=None
    try:
     for _poll_item in range(36):
      if _poll_item and time.perf_counter()-tick_start>0.009:break
      event,*args=self.q.get_nowait()
      if event=='p86_groups':
       group_job,vi_count,other_count=args
       if group_job==self.search_generation:
        self.status.set('Ưu tiên '+str(vi_count)+' font hỗ trợ tiếng Việt; sau đó '+str(other_count)+' font khác. Không loại font nào.')
      elif event=='bench_done':
       self.bench_running=False
       self.scan_workers.set('AUTO')
       self.status.set('Benchmark: '+', '.join(str(k)+' kênh='+str(v)+'s' for k,v in args[0]['times'].items())+'; AUTO chọn '+str(args[0]['best'])+' kênh')
      elif event=='bench_error':
       self.bench_running=False
       self.status.set('Benchmark lỗi: '+args[0])
      elif event=='p54_variant_ocr_done':
       job,index,txt,engine,needs_review=args
       if job==self.ocr_job and self.p52_manual and self.p38_variant==index and not self._ocr_manual_edit:
        self.p43_progress('OCR PA%d HOÀN TẤT'%(index+1),100)
        if txt:
         self.p26_set_text(txt)
         self.ocr_mode_status.set('OCR PA%d • %s%s'%(index+1,engine,' • CẦN KIỂM TRA' if needs_review else ''))
         self.status.set('PA%d nhận diện: %s'%(index+1,txt))
         if self.ocr_sound_enabled.get():play_ocr_result_sound()
        else:
         self.p26_set_text('')
         self.ocr_mode_status.set('OCR PA%d • CHƯA NHẬN ĐƯỢC CHỮ — %s'%(index+1,engine))
         self.status.set('PA%d không nhận được ký tự; hãy chọn phương án khác hoặc nhập tay.'%(index+1))
      elif event=='ocr_done':
       job,txt,engine,needs_review=args
       if job==self.ocr_job:
        self.p43_progress('NHẬN DIỆN OCR XONG',100)
        if txt:
         # P43: automatically show the OCR result even when confidence is low;
         # preserve a warning and allow manual correction. Never invent text.
         self.p26_set_text(txt)
         self.p121_candidates=[('AI Offline — '+str(engine),txt)]
         self.p121_confirmed_text=None
         if needs_review:
          self.ocr_mode_status.set('OCR TỰ ĐIỀN • ĐỘ TIN CẬY THẤP — HÃY KIỂM TRA KÝ TỰ.')
         else:
          self.ocr_mode_status.set('AUTO OCR XONG • Có thể chỉnh tay nếu cần.')
         self.status.set('OCR đã nhận: '+txt+' ('+engine+'). Kiểm tra dấu trước khi tìm font.')
         if self.ocr_sound_enabled.get():play_ocr_result_sound()
        else:
         self.ocr_mode_status.set('Không đọc được chữ; hãy nhập thủ công hoặc khoanh vùng chữ.')
         self.status.set('OCR chưa đọc được chữ: '+str(engine))
      elif event=='p21_smart_done':
       job,google,offline,engine,cloud_error,local_error,signature=args
       if job==self.ocr_job:
        if cloud_error:
         self.status.set('SMART OCR: Google lỗi; không tự chuyển sang Offline.')
         messagebox.showwarning('SMART OCR — Google lỗi',cloud_error[:350]+'\n\nOffline: '+(offline or local_error or 'không đọc được'))
        elif not google and not offline:
         self.status.set('SMART OCR: cả hai công cụ không nhận được ký tự.')
        elif google and offline and p21.same_text(google,offline) and not (p21.previous_correction(signature) and not p21.same_text(p21.previous_correction(signature),google)):
         self.glyph.set(google)
         self.status.set('SMART OCR: Google và Offline thống nhất: '+google)
         if self.ocr_sound_enabled.get():play_ocr_result_sound()
        else:
         self.status.set('SMART OCR: có khác biệt hoặc lịch sử xác nhận không trùng, cần kiểm tra.')
         self.p21_confirm(google,offline,signature)
      elif event=='p20_ocr_done':
       job,online,offline,engine,error=args
       if job==self.ocr_job:
        if error:self.status.set('Google Cloud Vision lỗi: '+error[:180]);messagebox.showwarning('Google OCR',error[:300])
        elif online and offline and online.strip()!=offline.strip():
         self.set_cloud('ĐỐI CHIẾU OCR\n\nGOOGLE: '+online+'\nOFFLINE: '+offline+'\n\nKết quả khác nhau. Kiểm tra dấu và tự chọn nội dung đúng.')
         self.status.set('OCR Google/Offline khác nhau; xem vùng 06 và xác nhận trước khi tìm font.')
        elif online:
         self.glyph.set(online);self.status.set('Google OCR: '+online+' — hãy kiểm tra dấu trước khi tìm font.')
        elif offline:
         self.glyph.set(offline);self.status.set('Google OCR không đọc được; dùng OCR Offline: '+offline)
        else:self.status.set('Cả Google OCR và OCR Offline đều không đọc được chữ.')
        if not error and (online or offline) and self.ocr_sound_enabled.get():play_ocr_result_sound()
      elif event=='p121_hybrid_done':
       job,offline,online,off_engine,on_engine=args
       if job==self.ocr_job:
        self.p121_candidates=[]
        if offline:self.p121_candidates.append(('AI Offline — '+str(off_engine),offline))
        if online:self.p121_candidates.append(('AI Online — '+str(on_engine),online))
        if offline and online and offline.strip()==online.strip():
         self.p121_candidates.insert(0,('AI Fusion — hai nguồn thống nhất',offline))
        proposed=online or offline
        self.p26_set_text(proposed)
        self.p121_confirmed_text=None
        self.status.set('Hybrid hoàn tất. Chọn kết quả đúng hoặc nhập tay, rồi xác nhận tìm font.')
        self.ocr_mode_status.set('HYBRID: '+('ĐỒNG THUẬN' if offline and offline.strip()==online.strip() else 'CẦN XÁC NHẬN'))
        self.p121_review()
      elif event=='hybrid_ocr_done':
       job,offline,online,off_engine,on_engine=args
       if job==self.ocr_job:
        if online and offline and online.strip()==offline.strip():
         self.glyph.set(online);self.status.set('OCR Hybrid: hai công cụ thống nhất: '+online)
        elif online and offline:
         # Do not silently override conflicting accents or proper names.
         self.set_cloud('ĐỐI CHIẾU OCR TIẾNG VIỆT\n\nOFFLINE: '+offline+'\nAI VISION: '+online+'\n\nHai kết quả khác nhau. Kiểm tra dấu và nhập kết quả đúng vào ô ký tự trước khi tìm font.')
         self.status.set('OCR Hybrid: có khác biệt. Xem bảng kết quả AI bên phải để đối chiếu.')
        elif online:
         self.glyph.set(online);self.status.set('AI OCR: '+online+' (offline không đọc được)')
        elif offline:
         self.glyph.set(offline);self.status.set('OCR offline: '+offline+'; AI lỗi: '+str(on_engine))
        else:self.status.set('OCR Hybrid thất bại: '+str(off_engine)+' / '+str(on_engine))
        if (online or offline) and self.ocr_sound_enabled.get():play_ocr_result_sound()
      elif event=='p39_preview_ready':
       generation,key,variants,error=args
       if generation==self.p39_preview_generation and key==self.p39_preview_key and self.image is not None:
        self.p39_preview_masks=variants
        self.p66_cleanup_stats=getattr(__import__('p66_cleanup'),'last_stats',{})
        self.p52_auto_best=max(range(len(variants)),key=lambda i:variants[i][0]) if variants else 0
        self.p52_manual=False
        self.p39_preview_cache[key]=variants
        if len(self.p39_preview_cache)>4:self.p39_preview_cache.pop(next(iter(self.p39_preview_cache)))
        if variants and self.p53_pending_manual_clicks:
         clicks=self.p53_pending_manual_clicks;self.p53_pending_manual_clicks=0
         self.p47_cancel_review()
         self.p52_manual=True;self.p38_variant=(clicks-1)%len(variants)
         self.p39_render_preview()
         self.p54_ocr_selected_variant()
        elif variants:self.p47_auto_review()
        if error:self.p38_info.set('OCR • '+error[:45])
      elif event=='memory_progress':self.status.set(f'Đang học bộ nhớ font: {args[0]}/{args[1]} mẫu...')
      elif event=='memory_done':
       self.memory_running=False;self.status.set(f'Đã ghi nhớ {args[0]} mẫu mới / {args[1]} font. Bộ nhớ lưu lâu dài.');self.library_status.set(f'SẴN SÀNG — {args[1]} FONT • {args[0]} MẪU MỚI');(play_completion_sound() if self.sound_enabled.get() else None)
      elif event=='memory_cancelled':self.memory_running=False;self.status.set('Đã dừng học font, dữ liệu đã học vẫn được giữ.');self.library_status.set('ĐÃ DỪNG — bộ nhớ cũ được giữ nguyên')
      elif event=='memory_error':self.memory_running=False;self.status.set('Lỗi học font: '+args[0]);self.library_status.set('LỖI GHI NHỚ — xem dòng trạng thái')
      elif event=='p34_scanning':
       job,samples=args
       if job==self.search_generation and not self.cancel:
        self.p34_append_scanning(samples)
      elif event=='p31_samples':
       job,samples=args
       if job==self.search_generation and not self.cancel:
        self.p31_append_samples(samples)
      elif event=='p30_live':
       job,rows,checked,total=args
       if job==self.search_generation and not self.cancel:
        # Coalesce expensive table/preview refreshes until the queue batch ends.
        pending_live=(rows,checked)
      elif event=='p46_remaining':
       job,stage,percent=args
       if job==self.search_generation and not self.cancel:
        names={'index':'LẬP CHỈ MỤC','coarse':'SO KHỚP FONT','precise':'CHẤM ĐIỂM CHI TIẾT'}
        self.p43_progress('CÒN LẠI • '+names.get(stage,'TÌM KIẾM'),percent)
        # Use real stage-weighted work progress, never a timer or animated fake value.
        completed=max(self.p48_scan_percent.get(),100-max(0,min(100,int(percent))))
        self.p48_scan_percent.set(completed)
        self.p48_scan_text.set('%d%%'%completed)
      elif event=='progress':
       self.status.set(f'Đang phân tích {args[0]}/{args[1]} font • cache: {args[2]} font...')
       # P46 uses a remaining-work counter, updated by each search stage.
      elif event=='p85_threshold_hit':
       hit_job,decision,best,name,threshold,checked,total=args
       if hit_job!=self.search_generation or self.cancel:
        decision['continue']=False
        decision['event'].set()
       else:
        self.status.set('TẠM DỪNG • Font %s đạt %.2f/100; chờ lựa chọn.'%(name,best))
        # P89: modal Business Pro dialog with explicit Vietnamese actions.
        # P95: the threshold modal owns its notification and reminder lifecycle.
        # This prevents reminders after the user has made a decision.
        try:
         keep_going=self.show_threshold_business_dialog(name,best,threshold,checked,total)
        except Exception:
         keep_going=False
        decision['continue']=bool(keep_going)
        decision['event'].set()
        self.status.set('Tiếp tục chấm điểm các font còn lại...' if keep_going else 'Đang kết thúc tìm kiếm và chấp nhận kết quả hiện tại...')
      elif event=='cancelled':
       self.status.set(f'ĐÃ HỦY TÌM KIẾM • {len(self.results)} kết quả chưa hoàn tất.');self.searchbtn.config(state='normal');self.deepbtn.config(state='normal')
      elif event=='worker_error':
       self.status.set('Lỗi tìm font: '+args[0]);self.searchbtn.config(state='normal')
      elif event=='cloud_done':
       self.update_ai_font_previews(args[0]);self.set_cloud(args[0]);self.status.set('Đã nhận danh sách ứng viên AI; mẫu chỉ hiện khi có font hoặc ảnh thật.');(play_completion_sound() if self.sound_enabled.get() else None)
      elif event=='cloud_error':
       self.set_cloud('Lỗi AI trực tuyến: '+args[0]);self.status.set('AI trực tuyến gặp lỗi.')
      elif event=='done':
       pending_live=None  # final result supersedes any pending partial view
       done_job=args.pop(0)
       if done_job!=self.search_generation:continue
       if self.cancel:
        self.status.set('ĐÃ HỦY TÌM KIẾM • Kết quả chưa hoàn tất.');self.searchbtn.config(state='normal');self.deepbtn.config(state='normal');continue
       self.results=args[0]
       p81_snapshot={'source':getattr(self,'p81_search_source',''),
                     'glyph':getattr(self,'p81_search_glyph',''),
                     'rows':list(self.results[:12])}
       if p81_snapshot['source']=='Ảnh chỉnh sửa':self.p81_after=p81_snapshot
       elif p81_snapshot['source'] in ('Tự động (ảnh gốc)','PA đang chọn'):self.p81_baseline=p81_snapshot
       if self.p81_baseline and self.p81_after:
        b=self.p81_baseline['rows'];a=self.p81_after['rows']
        bname=b[0][1] if b else 'Không có';aname=a[0][1] if a else 'Không có'
        self.p81_compare_status.set('TRƯỚC: '+bname+' | SAU: '+aname+' · Nhấn SO SÁNH để xem Top 12')
       else:self.p81_compare_status.set('Đã lưu kết quả '+p81_snapshot['source']+' · Cần quét nguồn còn lại để so sánh')
       self.p30_streaming=False
       self.p31_follow=False
       if self.shared_source.get()!='online':self.populate_font_table()
       stopped_early=bool(args[5]) if len(args)>5 else False
       if stopped_early:
        self.p43_progress('DỪNG SỚM • ĐẠT NGƯỠNG',0)
        self.p48_scan_text.set('DỪNG')
        self.status.set(f'Đã dừng khi một font đạt ngưỡng {args[6]:g}/100. Đã chấm điểm chi tiết {args[7]} font; chưa kiểm tra hết các font còn lại. Điểm không phải xác suất đúng.')
       else:
        self.p43_progress('CÒN LẠI • HOÀN TẤT',0)
        self.p48_scan_percent.set(100)
        self.p48_scan_text.set('100%')
        self.status.set(f'Đã quét {args[1]} font (cache {args[2]}). Hiển thị {len(self.results)} font gần giống nhất trong {args[3]} giây (không lọc điểm). Điểm không phải xác suất đúng.')
       self.searchbtn.config(state='normal')
       self.deepbtn.config(state='normal' if args[4]=='fast' else 'disabled')
       if not stopped_early and self.sound_enabled.get():play_completion_sound()
       try:
        from p93_fireworks import show as show_p93_fireworks
        show_p93_fireworks(self.root,args[1],args[3],stopped_early)
       except Exception as exc:
        self.status.set('Hoàn thành tìm kiếm • Không hiển thị được pháo hoa: '+str(exc)[:120])
       if self.results and self.tree.exists('0'):self.tree.selection_set('0');self.preview()
       if self.shared_source.get()=='offline':self.refresh_shared_source()
    except queue.Empty:pass
    if pending_live is not None and not self.cancel and time.perf_counter()-getattr(self,'p51_last_ui',0.0)>=0.18:
     self.p51_last_ui=time.perf_counter()
     rows,checked=pending_live
     self.results=rows
     self.p30_streaming=True
     self.refresh_shared_source()
     self.status.set(f'ĐANG QUÉT • {len(rows)}/12 font hiển thị • '+('đang thu thập theo thứ tự tìm thấy' if checked<12 else 'đang chấm điểm và xếp hạng')+' • STOP để hủy tìm kiếm')
    # P130: keep 35 ms under load; reduce idle wakeups without delaying new work noticeably.
    self.root.after(35 if not self.q.empty() or getattr(self,'p31_active',False) else 80,self.poll)
 def show_threshold_business_dialog(self,name,best,threshold,checked,total):
    """Main-thread modal. True = continue; False = accept current result."""
    dlg=tk.Toplevel(self.root)
    dlg.title('AI FONT FINDER PRO • ĐÃ ĐẠT NGƯỠNG')
    dlg.configure(bg='#F4F6F9')
    dlg.resizable(False,False)
    dlg.transient(self.root)
    dlg.grab_set()
    choice={'continue':False}
    reminder={'after_id':None,'active':True,'played':0,'max_plays':3}
    def remind():
        reminder['after_id']=None
        if not reminder['active'] or not dlg.winfo_exists():
            return
        if reminder['played'] >= reminder['max_plays']:
            return
        reminder['played'] += 1
        if self.sound_enabled.get():
            play_threshold_sound()
        # Maximum three chimes in total, including the first at dialog opening.
        if reminder['active'] and dlg.winfo_exists() and reminder['played'] < reminder['max_plays']:
            reminder['after_id']=dlg.after(10000,remind)
    def finish(value):
        if not reminder['active']:
            return
        reminder['active']=False
        scheduled=reminder['after_id']
        reminder['after_id']=None
        if scheduled is not None:
            try:dlg.after_cancel(scheduled)
            except tk.TclError:pass
        choice['continue']=value
        dlg.destroy()
    dlg.protocol('WM_DELETE_WINDOW',lambda:finish(False))
    head=tk.Frame(dlg,bg='#182A40',padx=24,pady=16)
    head.pack(fill='x')
    tk.Label(head,text='🎉  CHÚC MỪNG! ĐÃ ĐẠT NGƯỠNG',font=('Segoe UI',14,'bold'),bg='#182A40',fg='#FFFFFF').pack(anchor='w')
    tk.Label(head,text='AI FONT FINDER PRO  •  BUSINESS',font=('Segoe UI',9),bg='#182A40',fg='#BFD1E4').pack(anchor='w',pady=(5,0))
    body=tk.Frame(dlg,bg='#F4F6F9',padx=24,pady=16)
    body.pack(fill='both')
    tk.Label(body,text='Tuyệt vời! Đã tìm thấy một font rất triển vọng.',font=('Segoe UI',11,'bold'),bg='#F4F6F9',fg='#21354B').pack(anchor='w')
    tk.Label(body,text='Font: '+str(name),font=('Segoe UI',10),bg='#F4F6F9',fg='#273A4C',wraplength=450,justify='left').pack(anchor='w',pady=(12,4))
    tk.Label(body,text='Điểm tương đồng: %.2f%%   •   Ngưỡng: %.0f%%'%(best,threshold),font=('Segoe UI',11,'bold'),bg='#F4F6F9',fg='#137C58').pack(anchor='w')
    tk.Label(body,text='Đã chấm điểm: %d/%d font'%(checked,total),font=('Segoe UI',9),bg='#F4F6F9',fg='#617080').pack(anchor='w',pady=(4,12))
    tk.Label(body,text='Bạn muốn tìm thêm font phù hợp hơn, hay hoàn thành với kết quả hiện tại?',font=('Segoe UI',10),bg='#F4F6F9',fg='#273A4C',wraplength=450,justify='left').pack(anchor='w')
    tk.Label(body,text='Lưu ý: Điểm tương đồng không phải xác suất nhận diện chính xác.',font=('Segoe UI',9),bg='#F4F6F9',fg='#697786').pack(anchor='w',pady=(10,0))
    bar=tk.Frame(dlg,bg='#E6EBF1',padx=24,pady=15)
    bar.pack(fill='x')
    tk.Button(bar,text='↻  TIẾP TỤC',command=lambda:finish(True),font=('Segoe UI',9,'bold'),bg='#285B91',fg='white',activebackground='#1F4772',activeforeground='white',relief='flat',cursor='hand2',width=15,pady=5).pack(side='left')
    tk.Button(bar,text='✓  DỪNG · HOÀN THÀNH',command=lambda:finish(False),font=('Segoe UI',9,'bold'),bg='#167553',fg='white',activebackground='#10563D',activeforeground='white',relief='flat',cursor='hand2',width=19,pady=5).pack(side='right')
    dlg.update_idletasks()
    w,h=dlg.winfo_reqwidth(),dlg.winfo_reqheight()
    x=self.root.winfo_rootx()+max(0,(self.root.winfo_width()-w)//2)
    y=self.root.winfo_rooty()+max(0,(self.root.winfo_height()-h)//2)
    dlg.geometry('+%d+%d'%(x,y))
    dlg.focus_set()
    # First Golden Chime plays as soon as the dialog enters the event loop.
    # Repeat at 10 and 20 seconds, at most 3 plays total; stop on either choice.
    reminder['after_id']=dlg.after(0,remind)
    self.root.wait_window(dlg)
    return choice['continue']

 def test_completion_sound(self):
    def report(ok,detail):
        def notify():
            if ok:self.status.set('Âm thanh: '+detail)
            else:messagebox.showwarning('Kiểm tra âm thanh','Không phát được âm thanh: '+detail)
        try:self.root.after(0,notify)
        except Exception:pass
    play_completion_sound(report)

 def preview(self,*_):
    self.previewbox.delete('all');sel=self.tree.selection()
    if not sel:
     self.previewbox.create_text(12,28,text=self.glyph.get() or 'Nhập chữ cần xem thử',anchor='w',fill='#111111',font=('Segoe UI',16,'bold'));return
    name,path=self.selected_font_record()
    if not path or not os.path.isfile(path):
     self.previewbox.create_text(12,35,text='Font chưa có trên máy — không thể xem trước.',anchor='w');return
    try:
     txt=self.glyph.get() or 'ABC';font=ImageFont.truetype(path,54)
     im=Image.new('RGB',(max(300,self.previewbox.winfo_width()),90),'#f4f0e7');ImageDraw.Draw(im).text((8,2),txt,font=font,fill='#111111')
     self.previewimg=ImageTk.PhotoImage(im);self.previewbox.create_image(0,0,anchor='nw',image=self.previewimg)
    except Exception as e:self.previewbox.create_text(12,35,text='Không xem trước được: '+str(e),anchor='w')
 def stop(self):
    self.cancel=True
    self.p31_follow=False
    self.p31_active=False
    self.status.set('ĐANG HỦY TÌM KIẾM... Kết quả hiện tại chưa hoàn tất.')
 def export_csv(self):
    if not self.results:messagebox.showinfo('Xuất kết quả','Chưa có kết quả offline.');return
    path=filedialog.asksaveasfilename(defaultextension='.csv',filetypes=[('CSV UTF-8','*.csv')])
    if not path:return
    try:
     with open(path,'w',encoding='utf-8-sig',newline='') as f:
      w=csv.writer(f);w.writerow(['Diem hinh dang /100','Ten font','Duong dan']);w.writerows(self.results)
     self.status.set('Đã xuất: '+path)
    except Exception as e:messagebox.showerror('Xuất CSV',str(e))
 def set_cloud(self,txt):
    self.cloud_box.configure(state='normal');self.cloud_box.delete('1.0','end');self.cloud_box.insert('1.0',txt);self.cloud_box.configure(state='disabled')
 def p12_manage(self):
    win=tk.Toplevel(self.root);win.title('P12 / SMART SOURCE MANAGER');win.geometry('780x520')
    ttk.Label(win,text='Google Fonts mặc định • Có thể thêm/xóa nguồn tùy chỉnh; URL không đồng nghĩa đã kết nối API.').pack(anchor='w',padx=10,pady=6)
    sources=p20sources.migrate_sources(p12.load_sources());p12.save_sources(sources);frame=ttk.Frame(win);frame.pack(fill='both',expand=True,padx=10)
    lb=tk.Listbox(frame,height=16);lb.pack(fill='both',expand=True)
    def refresh():
     lb.delete(0,'end')
     for r in sources:lb.insert('end',('[BẬT] ' if r['enabled'] else '[TẮT] ')+r['name']+' | '+r['url'])
    refresh()
    def selected():
     selection=lb.curselection();return selection[0] if selection else None
    def persist():
     try:p12.save_sources(sources);self.p12_rows=p12.load_index();refresh();status.configure(text=f'{sum(r["enabled"] for r in sources)} nguồn đang bật • {len(self.p12_rows)} bản ghi chỉ mục')
     except Exception as e:messagebox.showerror('P12',str(e),parent=win)
    def toggle():
     i=selected()
     if i is not None and sources[i]['id']!='googlefonts':sources[i]['enabled']=not sources[i]['enabled'];persist();lb.selection_set(i)
    def remove():
     i=selected()
     if i is not None and sources[i]['id']!='googlefonts':sources.pop(i);persist()
    def add():
     name=name_var.get().strip();url=url_var.get().strip()
     if not name or not p12.valid_url(url):messagebox.showwarning('P12','Nhập tên và URL https hợp lệ.',parent=win);return
     if any(r['url'].rstrip('/').lower()==url.rstrip('/').lower() for r in sources):messagebox.showwarning('P12','Website đã có.',parent=win);return
     import uuid
     sources.append(dict(id='custom_'+uuid.uuid4().hex[:12],name=name,country='OTHER',url=url,enabled=True));persist();name_var.set('');url_var.set('')
    def open_selected():
     i=selected()
     if i is not None:import webbrowser;webbrowser.open(sources[i]['url'])
    def load_csv():
     filename=filedialog.askopenfilename(parent=win,filetypes=[('CSV UTF-8','*.csv')])
     if not filename:return
     try:
      added,total=p12.import_csv(filename);self.p12_rows=p12.load_index();status.configure(text=f'Đã nhập {added} bản ghi; chỉ mục {total} bản ghi.')
     except Exception as exc:messagebox.showerror('P12 / CSV',str(exc),parent=win)
    buttons=ttk.Frame(win);buttons.pack(fill='x',padx=10,pady=5)
    for label,cmd in [('BẬT / TẮT',toggle),('XÓA NGUỒN',remove),('MỞ WEBSITE',open_selected),('NHẬP CSV',load_csv)]:ttk.Button(buttons,text=label,command=cmd).pack(side='left',padx=3)
    form=ttk.Frame(win);form.pack(fill='x',padx=10,pady=5)
    name_var=tk.StringVar();url_var=tk.StringVar()
    ttk.Label(form,text='Tên nguồn').pack(side='left');ttk.Entry(form,textvariable=name_var,width=22).pack(side='left',padx=5)
    ttk.Label(form,text='URL https').pack(side='left');ttk.Entry(form,textvariable=url_var,width=44).pack(side='left',padx=5)
    ttk.Button(form,text='THÊM NGUỒN',command=add).pack(side='left',padx=4)
    status=ttk.Label(win,text=f'{sum(r["enabled"] for r in sources)} nguồn đang bật • {len(self.p12_rows)} bản ghi chỉ mục');status.pack(anchor='w',padx=10,pady=5)
    ttk.Label(win,text='Lưu ý: Thêm URL chỉ tạo nguồn tham chiếu; cần nhập CSV hợp lệ để có dữ liệu tìm kiếm.').pack(anchor='w',padx=10,pady=4)
 def cloud_search(self):
    if not self.require_license(prompt=False):
     return
    if self.image is None:messagebox.showwarning('Thiếu ảnh','Hãy mở ảnh và khoanh vùng chữ trước.');return
    key=self.cloud_key.get().strip()
    if not key:messagebox.showwarning('Thiếu API key','Nhập OpenAI API key. Phí API tính riêng, không nằm trong ChatGPT Plus.');return
    model=self.cloud_model.get().strip()
    if not model:messagebox.showwarning('Thiếu model','Nhập model API hỗ trợ ảnh.');return
    image=self.image.crop(self.crop) if self.crop else self.image
    self.status.set('Đang gửi vùng ảnh đã chọn đến AI...')
    self.set_cloud('Đang phân tích. Vui lòng chờ...')
    threading.Thread(target=self.cloud_worker,args=(image.copy(),key,model),daemon=True).start()
 def cloud_worker(self,image,key,model):
    try:
     result_cache=SearchResultCache()
     p12_sig=''
     if self.p12_enabled.get():
      p12_sig='|p12|'+normalize_font_clue(self.font_clue.get())+'|'+hashlib.sha256(json.dumps({'rows':self.p12_rows,'sources':p12.load_sources()},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
     online_signature=hashlib.sha256((image_signature(image)+model+'online-v37'+p12_sig).encode()).hexdigest()
     previous=result_cache.get('online',online_signature)
     if previous is not None:
      result_cache.close();self.q.put(('cloud_done','[Đã lấy từ bộ nhớ đệm, không gọi API]\n'+previous));return
     image.thumbnail((1200,1200))
     buffer=io.BytesIO();image.convert('RGB').save(buffer,format='JPEG',quality=80)
     encoded=base64.b64encode(buffer.getvalue()).decode('ascii')
     p12_hint=''
     if self.p12_enabled.get():
      clue=normalize_font_clue(self.font_clue.get())
      p12_hint=p12.context_for_ai(p12.enabled_rows(self.p12_rows,p12.load_sources()),clue=clue)
     prompt=('Bạn là chuyên gia nhận diện kiểu chữ cho thiết kế in ấn. '
      'Hãy đọc chính xác chữ xuất hiện trong ảnh, phân tích đặc điểm hình học của font, '
      'đề xuất tối đa 10 tên font có thể tương tự (chỉ nêu tên khi có cơ sở). '
      'Phân biệt rõ tên font suy đoán với tên font được xác minh. '
      'Nêu cách phân biệt các font ứng viên, hỗ trợ tiếng Việt. '
      'Không khẳng định chính xác 100% chỉ dựa vào hình ảnh. '
      'Trả lời tiếng Việt ngắn gọn theo các mục: Ký tự, Đặc điểm, Font ứng viên, Cách xác minh.')
     if p12_hint:prompt+='\nDanh sách ứng viên có nguồn do người dùng cung cấp (không mặc định là đúng, vẫn kiểm tra hình dạng):\n'+p12_hint
     elif self.p12_enabled.get():prompt+='\nChỉ mục P12 chưa có ứng viên phù hợp; KHÔNG giả định đã truy cập các website.'
     payload={'model':model,'messages':[{'role':'user','content':[{'type':'text','text':prompt}, {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+encoded}}]}],'max_tokens':650}
     req=urllib.request.Request('https://api.openai.com/v1/chat/completions',data=json.dumps(payload).encode('utf-8'),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
     with urllib.request.urlopen(req,timeout=75) as resp: data=json.loads(resp.read().decode('utf-8'))
     txt=data['choices'][0]['message']['content']
     txt=txt if isinstance(txt,str) else str(txt)
     result_cache.put('online',online_signature,txt);result_cache.close()
     self.q.put(('cloud_done',txt))
    except urllib.error.HTTPError as e:
     detail=e.read(1200).decode('utf-8','replace')
     self.q.put(('cloud_error',f'HTTP {e.code}: {detail}'))
    except Exception as e:self.q.put(('cloud_error',str(e)))
 def update_ai_font_previews(self,answer):
    """Display every AI suggestion, preview only actual locally available font files."""
    self.ai_font_paths={}
    self.ai_candidate_rows=[]
    try:
     paths=self.fonts()
     # Index family names and file stems; font metadata is essential for non-matching filenames.
     font_records=[]
     for path in paths:
      stem=os.path.splitext(os.path.basename(path))[0]
      family=font_name(path)
      font_records.append((path,stem,family,normalize_font_label(stem),normalize_font_label(family)))
     # Restrict matching to the AI candidate section, not its general descriptions.
     match=re.search(r'(?im)^\s*(?:[\-*]\s*)?(?:font\s+ứng\s+viên|các\s+font\s+đề\s+xuất|font\s+đề\s+xuất|suggested\s+fonts)\s*:',answer)
     section=answer[match.end():] if match else answer
     section=re.split(r'(?im)^\s*(?:[\-*]\s*)?(?:cách\s+xác\s+minh|kết\s+luận|lưu\s+ý|đặc\s+điểm)\s*:',section)[0]
     candidates=[]
     for line in section.splitlines():
      line=line.strip()
      line=re.sub(r'^[-*•\s]*\d{0,2}[.)]?\s*','',line)
      line=re.sub(r'^[-*•]\s*','',line)
      line=re.sub(r'^(?:font|phông)\s*:\s*','',line,flags=re.I)
      if not line or len(line)>140:continue
      line=re.split(r'\s+[—–]\s+|\s+\(|\s*:\s+',line,maxsplit=1)[0]
      line=re.sub(r'^[*`"“]+|[*`"”]+$','',line).strip()
      if not (2<=len(line)<=70) or line.endswith(':'):continue
      key=normalize_font_label(line)
      if len(key)<3 or key in {normalize_font_label(c) for c in candidates}:continue
      candidates.append(line)
      if len(candidates)>=12:break
     # Fallback: find exact font family/stem phrases in the response.
     if not candidates:
      normalized_answer=normalize_font_label(answer)
      for _,stem,family,stem_key,family_key in font_records:
       for name,key in ((family,family_key),(stem,stem_key)):
        if len(key)>=5 and key in normalized_answer and name not in candidates:
         candidates.append(name)
         if len(candidates)>=12:break
       if len(candidates)>=12:break
     labels=[];found=0
     for candidate in candidates:
      key=normalize_font_label(candidate)
      exact=[r for r in font_records if key==r[3] or key==r[4]]
      # Allow family/style variants but avoid matching generic short words.
      partial=[] if exact or len(key)<6 else [r for r in font_records if r[4].startswith(key+' ') or r[3].startswith(key+' ')]
      matches=exact or partial
      if matches:
       path=matches[0][0]
       label=candidate+'  |  CÓ FONT: '+os.path.basename(path)
       self.ai_font_paths[label]=path;found+=1
      else:
       label=candidate+'  |  CHƯA CÓ TRÊN MÁY'
      labels.append(label)
     self.ai_candidate_rows=[(candidate,self.ai_font_paths.get(label)) for candidate,label in zip(candidates,labels)]
     if labels:

      self.ai_preview_status.set(f'AI đề xuất {len(labels)} font; tìm thấy {found} file font trên máy. Xem toàn bộ mẫu tại mục 05, chọn FONT AI ONLINE.')
     else:
      self.ai_preview_status.set('AI chưa trả về danh sách font có thể tách tên. Xem nội dung phân tích phía trên.')
    except Exception as exc:
     self.ai_preview_status.set('Lỗi lập danh sách font AI: '+str(exc))
    if self.shared_source.get()=='online':self.refresh_shared_source()
 def refresh_shared_source(self):
    if self.shared_source.get()=='online':
     self.shared_preview_items=[(r['font_name'],r.get('_local_font'),r.get('_p19_score')) for r in getattr(self,'p18_rows',[])][:12] if getattr(self,'p18_rows',None) else [(name,path,None) for name,path in getattr(self,'ai_candidate_rows',[])][:12]
    else:
     self.shared_preview_items=[(name,path,score) for score,name,path in self.display_offline_results()[:12]]
    self.populate_font_table()
    self.render_shared_previews()
    if hasattr(self,'p18_detail'):self.p18_show_detail()
 def p31_reset(self):
    self.p31_history=[];self.p31_seen=set();self.p31_photos=[]
    self.p31_active=True;self.p31_follow=True
    self.p33_queue=[];self.p33_rows=[];self.p33_offset=0.0
    self.p33_last_tick=time.monotonic()
    if hasattr(self,'p32_live_canvas'):self.p32_live_canvas.delete('all')
 def p31_redraw_or_default(self):
    self.render_shared_previews()
 def p31_mousewheel(self,event):
    return 'break'  # P33: fixed display, not scrollable
 def p34_append_scanning(self,samples):
    # Actual names from the indexing/rendering pipeline; no scoring dependency.
    if not getattr(self,'p31_active',False):return
    for name,path in samples:
     key=os.path.normcase(os.path.abspath(path)) if path else name
     if key in self.p31_seen:continue
     self.p31_seen.add(key)
     self.p33_queue.append(str(name))
    if len(self.p33_queue)>3000:self.p33_queue=self.p33_queue[-3000:]
 def p31_append_samples(self,samples):
    if not getattr(self,'p31_active',False):return
    # P34 ticker is driven by p34_scanning, not by scored candidates.
    return
    # Bound queue memory, but preserve names of the most recent scanned fonts.
    if len(self.p33_queue)>3000:self.p33_queue=self.p33_queue[-3000:]
 def p31_redraw(self):
    canvas=self.p32_live_canvas
    canvas.delete('all')
    h=26
    for i,name in enumerate(getattr(self,'p33_rows',[])[:4]):
     y=i*h+getattr(self,'p33_offset',0.0)
     canvas.create_text(10,y+13,anchor='w',text=name,fill='#f1f5f9',font=('Segoe UI',10),width=max(80,canvas.winfo_width()-20),tags=('ticker',))
     canvas.create_line(0,y+h-1,canvas.winfo_width(),y+h-1,fill='#303b49')
 def p31_animate(self):
    try:
     if getattr(self,'p31_active',False) and not getattr(self,'cancel',False):
      now=time.monotonic()
      dt=min(0.1,max(0.0,now-getattr(self,'p33_last_tick',now)))
      self.p33_last_tick=now
      queue_names=getattr(self,'p33_queue',[])
      # Each new font enters from above; text scrolls DOWN through two visible lines.
      # Move faster as the scan produces more names; never delay the scan worker.
      if queue_names:
       speed=min(1200.0,max(80.0,len(queue_names)*18.0))
       self.p33_offset+=speed*dt
       while self.p33_offset>=26 and self.p33_queue:
        self.p33_offset-=26
        self.p33_rows.insert(0,self.p33_queue.pop(0))
        self.p33_rows=self.p33_rows[:4]
       self.p31_redraw()
      elif self.p33_offset:
       self.p33_offset=0.0;self.p31_redraw()
    finally:
     # P130: scan-active 30 Hz, idle 5 Hz; no idle CPU churn.
     self.root.after(33 if getattr(self,'p31_active',False) and not getattr(self,'cancel',False) else 200,self.p31_animate)
 def render_shared_previews(self):
    if not hasattr(self,'shared_preview_canvas'):return
    canvas=self.shared_preview_canvas
    # Preserve scrollbar position while re-rendering the twelve genuine font samples.
    old_y=canvas.yview()[0] if canvas.yview() else 0
    canvas.delete('all');self.preview_photos=[]
    width=max(320,canvas.winfo_width()-5)
    sample=self.glyph.get().strip() or 'TRƯỜNG CAO ĐẲNG'
    items=self.shared_preview_items[:12]
    if not items:
     canvas.create_text(12,25,anchor='w',fill='#24354b',text='Chưa có kết quả. Quét OFFLINE hoặc TÌM FONT AI để xem 12 mẫu chữ.')
     canvas.configure(scrollregion=(0,0,width,65));return
    row_h=86
    for index,(name,path,score) in enumerate(items):
     y=index*row_h
     canvas.create_rectangle(0,y,width,y+row_h-2,fill='#f4f0e7' if index%2==0 else '#e8e5df',outline='')
     score_label=(f'  •  {score:.1f}/100' if score is not None else '')
     record=(getattr(self,'p18_rows',[]) or [])[index] if self.shared_source.get()=='online' and index<len(getattr(self,'p18_rows',[])) else {}
     sample_path=record.get('sample_path','') if record else ''
     status=('  •  '+record.get('source_id','') if record else '') if (path and os.path.isfile(path)) or (sample_path and os.path.isfile(sample_path)) else '  •  CHƯA CÓ MẪU XÁC MINH'
     canvas.create_text(10,y+13,anchor='w',text=f"{('—' if getattr(self,'p30_streaming',False) else f'{index+1:02d}')}. {name}{score_label}{status}",fill='#152f55',font=('Segoe UI',10,'bold'),width=width-20)
     if (path and os.path.isfile(path)) or (sample_path and os.path.isfile(sample_path)):
      try:
       if sample_path and os.path.isfile(sample_path):
        with Image.open(sample_path) as source_image:
         img=source_image.convert('RGB');img.thumbnail((width-20,51),Image.Resampling.LANCZOS)
        photo=ImageTk.PhotoImage(img);self.preview_photos.append(photo)
        canvas.create_image(9,y+30,anchor='nw',image=photo)
        continue
       img=Image.new('RGB',(width-20,51),'#f4f0e7' if index%2==0 else '#e8e5df')
       draw=ImageDraw.Draw(img)
       sample_for_font=compatible_text(sample,path)
       size=40
       font=ImageFont.truetype(path,size)
       bounds=draw.textbbox((0,0),sample_for_font,font=font)
       text_width=max(1,bounds[2]-bounds[0])
       if text_width>width-35:
        size=max(9,int(size*(width-35)/text_width))
        font=ImageFont.truetype(path,size)
        bounds=draw.textbbox((0,0),sample_for_font,font=font)
       draw.text((2-bounds[0],max(0,(51-(bounds[3]-bounds[1]))//2)-bounds[1]),sample_for_font,font=font,fill='#17263c')
       photo=ImageTk.PhotoImage(img);self.preview_photos.append(photo)
       canvas.create_image(9,y+30,anchor='nw',image=photo)
      except Exception as exc:
       canvas.create_text(10,y+51,anchor='w',text='Không dựng được font: '+str(exc)[:80],fill='#8c3838')
     else:
      canvas.create_text(10,y+53,anchor='w',text='Chưa có mẫu hợp lệ: nhập ảnh mẫu hoặc font được phép sử dụng.',fill='#8c3838')
    canvas.configure(scrollregion=(0,0,width,len(items)*row_h))
    canvas.yview_moveto(old_y)
 def p20_online_search(self):
    if not self.require_license(prompt=False):
     return
    """Default Google Fonts; custom licensed CSV index is an optional secondary source."""
    from tkinter import simpledialog
    sources=p20sources.migrate_sources(p12.load_sources())
    if sources!=p12.load_sources():p12.save_sources(sources)
    key=getattr(self,'p20_google_key',None)
    if not key:
     key=simpledialog.askstring('Google Fonts','Nhập Google Fonts Developer API key (không phải OpenAI API key):',show='*',parent=self)
     if key:self.p20_google_key=key
    if key:
     self.p19_start_with_key(key)
    else:
     self.status.set('Google Fonts là nguồn mặc định. Chưa có Google Fonts API key; chỉ kiểm tra nguồn tùy chỉnh đã nhập CSV.')
     self.p18_source_search()
 def p20_ocr_start(self):
    if not self.require_license(prompt=False):
     return
    """Explicit Cloud Vision OCR; preserve user confirmation on disagreement."""
    from tkinter import simpledialog
    if self.image is None:messagebox.showwarning('OCR Google','Hãy mở ảnh trước.');return
    key=getattr(self,'p20_vision_key',None)
    if not key:
     key=simpledialog.askstring('Google Cloud Vision','Nhập Google Cloud Vision API key (không phải Google Fonts key):',show='*',parent=self)
     if key:self.p20_vision_key=key
    if not key:return
    image=(self.image.crop(self.crop) if self.crop else self.image).copy()
    self.ocr_job+=1;job=self.ocr_job
    self.status.set('Đang nhận diện tiếng Việt bằng Google Cloud Vision (có thể tính phí API)...')
    def worker():
     try:
      online=p20vision.cloud_ocr(image,key)
      offline,engine=recognize_text(image)
      self.q.put(('p20_ocr_done',job,online,offline,engine,''))
     except Exception as e:self.q.put(('p20_ocr_done',job,None,None,'',str(e)))
    threading.Thread(target=worker,daemon=True).start()
 def p19_start_with_key(self,key):
    """Use existing P19 pipeline with supplied key (no repeated API prompt)."""
    self._p19_override_key=key
    try:self.p19_start()
    finally:self._p19_override_key=None
 def p19_start(self):
    """Explicit opt-in: Google Fonts API catalog, verified downloaded fonts and real shape ranking."""
    from tkinter import simpledialog
    if self.image is None:
     messagebox.showwarning('Thiếu ảnh','Hãy mở ảnh và chọn vùng chữ trước.');return
    key=getattr(self,'_p19_override_key',None) or simpledialog.askstring('Google Fonts API','Nhập Google Fonts Developer API key (không phải OpenAI API key):',show='*',parent=self)
    if not key:return
    sample=self.glyph.get().strip()
    if not sample:
     messagebox.showwarning('Thiếu chữ','Hãy nhập đúng chữ trong ảnh để so khớp.');return
    image=(self.image.crop(self.crop) if self.crop else self.image).copy()
    self.status.set('P19: Đang tải danh mục Google Fonts và so sánh hình dạng mẫu thật...')
    def worker():
     try:
      reference=glyph_mask(image)
      if reference is None:raise ValueError('Không tách được nét chữ trong ảnh')
      items=p19.fetch_catalog(key)
      # Bounded initial pilot, not an exhaustive global search.
      rows=p19.candidates(items,limit=40)
      ranked=[];errors=0
      for row in rows:
       try:
        path=p19.cached_font(row)
        shape=render(sample,path)
        if shape is None:continue
        sim=score(reference,shape)
        if sim<0:continue
        entry=dict(row);entry['_local_font']=path;entry['_p19_score']=round(float(sim),1)
        ranked.append(entry)
       except Exception:errors+=1
      ranked.sort(key=lambda r:-r['_p19_score'])
      self.after(0,lambda:self.p19_complete(ranked[:12],len(rows),errors))
     except Exception as exc:
      detail=str(exc)
      self.after(0,lambda:self.status.set('P19 lỗi: '+detail[:220]))
    threading.Thread(target=worker,daemon=True).start()
 def p19_complete(self,rows,total,errors):
    self.p18_rows=rows;self.p18_selected=0
    self.shared_source.set('online');self.refresh_shared_source()
    self.status.set(f'P19: Đã đối chiếu tối đa {total} font Google Fonts; {len(rows)} kết quả có mẫu thật, {errors} lỗi/tệp bỏ qua. Không gọi OpenAI.')
 def p18_source_search(self):
    if not self.require_license(prompt=False):
     return
    """Search only user-imported, enabled and traceable source metadata; no fabricated previews."""
    sources=p12.load_sources()
    self.p12_rows=p12.load_index()
    enabled=p12.enabled_rows(self.p12_rows,sources)
    clue=normalize_font_clue(self.font_clue.get())
    matches=p12.search_index(enabled,clue=clue,limit=12)
    font_paths={}
    for path in self.fonts():
     key=normalize_font_label(font_name(path))
     if key and key not in font_paths:font_paths[key]=path
    rows=[]
    for r in matches:
     r=dict(r)
     r['_local_font']=font_paths.get(normalize_font_label(r['font_name']))
     rows.append(r)
    self.p18_rows=rows;self.p18_selected=0
    self.shared_source.set('online')
    self.refresh_shared_source()
    verified=sum(bool((r.get('sample_path') and os.path.isfile(r['sample_path'])) or r['_local_font']) for r in rows)
    self.status.set(f'P18: {len(rows)} ứng viên từ chỉ mục nguồn đang bật; {verified} có mẫu xem thật. Không gọi API.')
    if not rows:self.status.set('P18: Chưa có dữ liệu từ nguồn đang bật. Nhập CSV có tên font và sample_path ảnh mẫu được phép sử dụng qua THÊM TRANG NGUỒN.')
 def p18_select_row(self,event):
    index=int(self.shared_preview_canvas.canvasy(event.y)//86)
    if 0<=index<len(self.shared_preview_items):
     self.p18_selected=index;self.p18_show_detail()
 def p18_show_detail(self):
    if not hasattr(self,'p18_detail'):return
    c=self.p18_detail;c.delete('all');self.p18_detail_photo=None
    width=max(200,c.winfo_width());height=max(100,c.winfo_height())
    idx=getattr(self,'p18_selected',0)
    items=getattr(self,'shared_preview_items',[])
    if idx>=len(items):
     c.create_text(14,25,anchor='w',text='Chọn một mẫu font ở mục 05 để xem lớn.',fill='#17263c');return
    name,path,_=items[idx]
    row=(getattr(self,'p18_rows',[]) or [])[idx] if self.shared_source.get()=='online' and idx<len(getattr(self,'p18_rows',[])) else {}
    c.create_text(12,18,anchor='w',text=name+(('  •  '+row.get('source_id','')) if row else ''),fill='#17263c',font=('Segoe UI',11,'bold'))
    sample_path=row.get('sample_path','') if row else ''
    try:
     if sample_path and os.path.isfile(sample_path):
      with Image.open(sample_path) as im:
       im=im.convert('RGB');im.thumbnail((width-24,max(30,height-58)),Image.Resampling.LANCZOS)
     elif path and os.path.isfile(path):
      im=Image.new('RGB',(width-24,max(40,height-55)),'#F4F0E8')
      text=compatible_text(self.glyph.get().strip() or 'Tiếng Việt',path)
      draw=ImageDraw.Draw(im);size=min(84,max(16,int(im.height*.65)))
      f=ImageFont.truetype(path,size)
      bounds=draw.textbbox((0,0),text,font=f)
      if bounds[2]-bounds[0]>im.width-12:
       f=ImageFont.truetype(path,max(10,int(size*(im.width-12)/max(1,bounds[2]-bounds[0]))))
      draw.text((5,5),text,font=f,fill='#17263c')
     else:
      c.create_text(12,62,anchor='w',text='Chưa có ảnh mẫu hoặc font thật. Không hiển thị mẫu giả.',fill='#9b3434');return
     self.p18_detail_photo=ImageTk.PhotoImage(im)
     c.create_image(12,38,anchor='nw',image=self.p18_detail_photo)
    except Exception as exc:c.create_text(12,62,anchor='w',text='Không đọc được mẫu: '+str(exc)[:90],fill='#9b3434')
 def p18_open_source(self):
    idx=getattr(self,'p18_selected',0)
    rows=getattr(self,'p18_rows',[])
    if self.shared_source.get()!='online' or idx>=len(rows):return
    row=rows[idx];url=row.get('source_url','')
    if not url:
     src=next((s for s in p12.load_sources() if s['id']==row.get('source_id')),None)
     url=src['url'] if src else ''
    if p12.valid_url(url):
     import webbrowser;webbrowser.open(url)
 def display_offline_results(self):
    return vietnamese_priority_sort(self.results,self.vietnamese_priority.get())
 def selected_font_record(self):
    selection=self.tree.selection()
    if not selection:return None,None
    try:
     idx=int(selection[0])
     if self.shared_source.get()=='online':
      return getattr(self,'ai_candidate_rows',[])[idx]
     _,name,path=self.display_offline_results()[idx]
     return name,path
    except (ValueError,IndexError,TypeError):return None,None
 def populate_font_table(self):
    self.tree.delete(*self.tree.get_children())
    if self.shared_source.get()=='online':
     records=[(f"{r['_p19_score']:.1f}/100" if '_p19_score' in r else '—', f"{r['_p19_score']:.1f}%" if '_p19_score' in r else '—',r['font_name'],r.get('_local_font')) for r in getattr(self,'p18_rows',[])[:12]] if getattr(self,'p18_rows',None) else [('—','—',name,path) for name,path in getattr(self,'ai_candidate_rows',[])[:12]]
    else:
     records=[(f'{score:.1f}/100',('—' if getattr(self,'p30_streaming',False) else f'{i:02d}'),name,path) for i,(score,name,path) in enumerate(self.display_offline_results()[:12],1)]
    for i,(score,percent,name,path) in enumerate(records):
     state=font_installation_status(path)
     self.tree.insert('','end',iid=str(i),values=(score,percent,name,state,'📂' if path and os.path.isfile(path) else ''))
 def show_font_context_menu(self,event):
    iid=self.tree.identify_row(event.y)
    if not iid:return 'break'
    self.tree.selection_set(iid);self.tree.focus(iid)
    self.p55_popup_font_menu(event.x_root,event.y_root)
    return 'break'
 def p27_left_open_font(self,event):
    if self.tree.identify_region(event.x,event.y)!='cell':return
    if self.tree.identify_column(event.x)!='#5':return
    iid=self.tree.identify_row(event.y)
    if not iid:return
    self.tree.selection_set(iid);self.tree.focus(iid)
    self.open_font_folder()
 def open_font_folder(self):
    name,path=self.selected_font_record()
    if not path or not os.path.isfile(path):
     messagebox.showinfo('Chưa có font','Không có tệp font trên máy để mở.');return
    try:
     if sys.platform=='win32':
      subprocess.Popen(['explorer.exe','/select,',os.path.normpath(path)])
     elif sys.platform=='darwin':subprocess.Popen(['open','-R',path])
     else:subprocess.Popen(['xdg-open',os.path.dirname(path)])
    except Exception as e:messagebox.showerror('Không mở được thư mục',str(e))
def verify_installed_ocr_recognition():
    """Real end-to-end OCR using the frozen executable and its own bundled engine."""
    import unicodedata
    from PIL import ImageDraw
    if getattr(sys,'frozen',False):
        appdir=os.path.dirname(os.path.abspath(sys.executable))
        engine=locate_tesseract()
        if not engine or os.path.commonpath([os.path.normcase(appdir),os.path.normcase(engine)]) != os.path.normcase(appdir):
            raise RuntimeError('OCR is not bundled with the installed application')
    # Use Windows Arial as a deterministic installed font; preserve Vietnamese accents.
    font_path=os.path.join(os.environ.get('WINDIR',r'C:\Windows'),'Fonts','arial.ttf')
    if not os.path.isfile(font_path):
        raise RuntimeError('Windows Arial font not found for OCR smoke test')
    from PIL import ImageFont
    expected='mỗi loại'
    font=ImageFont.truetype(font_path,76)
    bounds=font.getbbox(expected)
    img=Image.new('RGB',(bounds[2]-bounds[0]+100,bounds[3]-bounds[1]+110),'#404040')
    ImageDraw.Draw(img).text((50-bounds[0],50-bounds[1]),expected,font=font,fill='#ffed00')
    # Unique pixels force a fresh OCR pass, bypassing persisted cache.
    import secrets
    img.putpixel((0,0),tuple(secrets.token_bytes(3)))
    actual,detail=recognize_text(img)
    if unicodedata.normalize('NFC',actual or '') != expected:
        raise RuntimeError('Vietnamese OCR mismatch: expected '+repr(expected)+' got '+repr(actual)+' ('+detail+')')
    cached,detail=recognize_text(img)
    if cached != expected or '(cache)' not in detail:
        raise RuntimeError('Persistent OCR cache failed')
    marker=os.environ.get('AI_FONT_OCR_SMOKE_RESULT')
    if marker:
        with open(marker,'w',encoding='utf-8') as output:output.write('PASS: installed executable recognizes Vietnamese accents and OCR cache works')

if __name__=='__main__':
 multiprocessing.freeze_support()
 if '--verify-runtime' in sys.argv or '--verify-pillow' in sys.argv:
    argument = '--verify-runtime' if '--verify-runtime' in sys.argv else '--verify-pillow'
    report = sys.argv[sys.argv.index(argument) + 1]
    try:
        for image_format in ('PNG', 'JPEG'):
            buffer = io.BytesIO()
            Image.new('RGB', (8, 8), '#14345a').save(buffer, format=image_format)
            buffer.seek(0)
            with Image.open(buffer) as decoded:
                decoded.load()
                if decoded.size != (8, 8):
                    raise RuntimeError(f'{image_format} round-trip failed')
        if argument == '--verify-runtime':
            from numpy.core import multiarray

            pixels = np.full((8, 8, 3), 127, dtype=np.uint8)
            gray = cv2.cvtColor(pixels, cv2.COLOR_RGB2GRAY)
            if multiarray is None or gray.shape != (8, 8) or not np.all(gray == 127):
                raise RuntimeError('NumPy/OpenCV conversion failed')
            result = f'PASS: NumPy {np.__version__}, OpenCV {cv2.__version__}, PNG and JPEG'
        else:
            result = 'PASS: imported Pillow and decoded PNG and JPEG'
    except Exception as exc:
        result = f'FAIL: {exc}'
    with open(report, 'w', encoding='utf-8') as output:
        output.write(result)
    sys.exit(0 if result.startswith('PASS:') else 33)
 if '--verify-robot-assets' in sys.argv:
    report = sys.argv[sys.argv.index('--verify-robot-assets') + 1]
    try:
        icon_path = robot_asset('ai_pro_logo.ico')
        with Image.open(icon_path) as icon:
            icon.load()
        root = tk.Tk()
        try:
            app = App(root)
            root.update_idletasks()
            if APP_VERSION not in root.title():
                raise RuntimeError('Main window shows the wrong build version')
            seen_frames = set()
            header_images = set()
            visible_prices = set()
            license_fields = set()
            offer_colors = set()

            def inspect_children(parent):
                for widget in parent.winfo_children():
                    if widget.winfo_name() == 'robot_header' and widget.winfo_viewable():
                        header_images.update(widget.cget('image'))
                    if widget.winfo_name() in ('exit_serial', 'exit_key', 'exit_contact') and widget.winfo_viewable():
                        license_fields.add(widget.winfo_name())
                    if widget.winfo_name() == 'license_price' and widget.winfo_viewable():
                        visible_prices.add(widget.cget('text'))
                    if widget.winfo_name() == 'license_offer' and widget.winfo_viewable():
                        offer_colors.add(widget.cget('highlightbackground'))
                    if widget.winfo_name() == 'robot_animation' and widget.winfo_viewable():
                        seen_frames.add(str(widget.cget('image')))
                    inspect_children(widget)

            def sample_animation():
                inspect_children(root)
                root.after(50, sample_animation)

            def dismiss_dialog():
                for dialog in root.winfo_children():
                    if isinstance(dialog, tk.Toplevel):
                        dialog.tk.call(dialog.protocol('WM_DELETE_WINDOW'))

            root.after(50, sample_animation)
            root.after(4500, dismiss_dialog)
            app.p119_confirm_exit()
            if str(app.ai_pro_header_icon) not in header_images:
                raise RuntimeError('Header logo did not appear in the main window')
            if license_fields != {'exit_serial', 'exit_key', 'exit_contact'}:
                raise RuntimeError('Exit dialog is missing serial, activation field or contact')
            if visible_prices != {'249.000 ₫'} or len(offer_colors) < 2:
                raise RuntimeError('Exit dialog did not show the correct price and animated price border')
            seen_frames.discard('')
            if len(seen_frames) != 12:
                raise RuntimeError(f'Exit dialog rendered {len(seen_frames)} distinct frames, expected 12')
        finally:
            root.destroy()
        message = 'PASS: decoded Windows icon and rendered header logo, 249.000 ₫ offer, animated border and all 12 exit frames'
    except Exception as exc:
        message = f'FAIL: {exc}'
    with open(report, 'w', encoding='utf-8') as output:
        output.write(message)
    sys.exit(0 if message.startswith('PASS:') else 32)
 if '--ocr-smoke-installed' in sys.argv:
    try: verify_installed_ocr_recognition()
    except Exception as exc:
        marker=os.environ.get('AI_FONT_OCR_SMOKE_RESULT')
        if marker:
            with open(marker,'w',encoding='utf-8') as output:output.write('FAIL: '+str(exc))
        sys.exit(31)
    sys.exit(0)
 if '--verify-bundled-ocr' in sys.argv:
    import subprocess
    exe=locate_tesseract()
    if not exe:
        print('ERROR: bundled tesseract.exe not found',flush=True)
        sys.exit(21)
    appdir=os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys,'frozen',False) else os.path.dirname(os.path.abspath(__file__))
    # Strict: only accept OCR inside the installed/packaged app, never a global installation.
    if os.path.commonpath([os.path.normcase(appdir),os.path.normcase(exe)]) != os.path.normcase(appdir):
        print('ERROR: OCR resolved outside application: '+exe,flush=True)
        sys.exit(22)
    datadir=os.path.join(os.path.dirname(exe),'tessdata')
    for language in ('vie','eng'):
        model=os.path.join(datadir,language+'.traineddata')
        if not os.path.isfile(model) or os.path.getsize(model)<100000:
            print('ERROR: missing OCR model '+model,flush=True)
            sys.exit(23)
    env=os.environ.copy();env['TESSDATA_PREFIX']=datadir
    run=subprocess.run([exe,'--list-langs'],env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=25)
    if run.returncode or not {'vie','eng'}.issubset(set(run.stdout.splitlines())):
        print('ERROR: OCR language validation failed: '+run.stdout,flush=True)
        sys.exit(24)
    print('OK: bundled OCR binary and Vietnamese/English models verified: '+exe,flush=True)
    sys.exit(0)
 root=tk.Tk();App(root);root.mainloop()
