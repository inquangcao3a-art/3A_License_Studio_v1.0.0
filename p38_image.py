"""P38: conservative, source-preserving text foreground hypotheses.
No generative redrawing. All masks use 1 for glyph foreground.
"""
import cv2
import numpy as np
from PIL import Image, ImageOps


def quality(image):
    a=np.asarray(image.convert('RGB'))
    g=cv2.cvtColor(a,cv2.COLOR_RGB2GRAY)
    return {'brightness':round(float(np.median(g)),1),
            'sharpness':round(float(cv2.Laplacian(g,cv2.CV_64F).var()),1),
            'contrast':round(float(np.percentile(g,95)-np.percentile(g,5)),1)}


def _tight(m):
    yy,xx=np.where(m)
    if len(xx)<12:return None
    return m[yy.min():yy.max()+1,xx.min():xx.max()+1].astype(np.uint8)


def _rank(m):
    """Reject full-width background strips; reward repeated separated ink islands."""
    h,w=m.shape
    if min(h,w)<3:return -1e9
    fill=float(m.mean())
    if fill<.025 or fill>.72:return -1e9
    n,labels,stats,_=cv2.connectedComponentsWithStats(m,8)
    components=[]
    for i in range(1,n):
        x,y,cw,ch,area=map(int,stats[i])
        if area>=max(2,m.size*.00006):components.append((x,y,cw,ch,area))
    if not components:return -1e9
    # A background band usually forms a single huge connected component.
    largest=max(x[4] for x in components)/max(1,int(m.sum()))
    band=max((x[2]/w for x in components if x[3]>=h*.32),default=0)
    row_ink=m.mean(axis=1)
    col_ink=m.mean(axis=0)
    score=1.7*min(len(components),16)/16 + .9*float(np.std(col_ink))
    score+=.5*float(np.std(row_ink))
    score-=1.9*max(0,largest-.50)
    score-=2.0*max(0,band-.85)
    score-=.8*abs(fill-.30)
    # Cropped text is typically wider than tall, but allow one-letter crops.
    if w/h>1.6:score+=.15
    return score


def candidates(image,limit=5):
    """Return ranked masks and descriptive labels; no geometry distortion."""
    rgb=np.asarray(ImageOps.exif_transpose(image).convert('RGB'))
    h,w=rgb.shape[:2]
    if min(h,w)<8:return []
    # Bound processing time on very large phone images; preserve aspect ratio.
    if max(h,w)>1300:
        f=1300/max(h,w);rgb=cv2.resize(rgb,(round(w*f),round(h*f)),interpolation=cv2.INTER_AREA)
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB)
    hsv=cv2.cvtColor(rgb,cv2.COLOR_RGB2HSV)
    options=[]
    def add(label,m):options.append((label,np.asarray(m,dtype=np.uint8)))
    blur=cv2.GaussianBlur(gray,(3,3),0)
    _,bw=cv2.threshold(blur,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    add('NGƯỠNG SÁNG',bw>0);add('NGƯỠNG TỐI',bw==0)
    clahe=cv2.createCLAHE(clipLimit=2,tileGridSize=(8,8)).apply(gray)
    _,cb=cv2.threshold(clahe,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    add('TƯƠNG PHẢN SÁNG',cb>0);add('TƯƠNG PHẢN TỐI',cb==0)
    block=min(41,min(gray.shape)//2*2-1)
    if block>=11:
        local=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,block,8)
        add('THIẾU SÁNG - SÁNG',local>0);add('THIẾU SÁNG - TỐI',local==0)
    # The border is an estimate, not a truth: include both polarities.
    edges=np.concatenate((lab[0],lab[-1],lab[:,0],lab[:,-1]),axis=0).astype(np.float32)
    bg=np.median(edges,axis=0)
    distance=np.linalg.norm(lab.astype(np.float32)-bg,axis=2)
    for threshold in (22,36,50):add('TÁCH MÀU '+str(threshold),distance>threshold)
    # White letters on a saturated green band: saturation-only incorrectly selects the band.
    sat=hsv[:,:,1]
    add('CHỮ SÁNG TRÊN NỀN MÀU',(gray>np.percentile(gray,65)) & (sat<np.percentile(sat,55)))
    add('CHỮ TỐI TRÊN NỀN MÀU',(gray<np.percentile(gray,35)) & (sat<np.percentile(sat,65)))
    # Detect a saturated horizontal sign band and isolate neutral/light glyphs
    # *within* that band, not the identical white page outside it.
    row_sat=np.median(sat,axis=1)
    band_rows=row_sat>max(38,float(np.percentile(row_sat,65)))
    if band_rows.sum()>=8:
        band=np.repeat(band_rows[:,None],gray.shape[1],axis=1)
        active_gray=gray[band]
        if active_gray.size:
            cutoff=max(110,float(np.percentile(active_gray,68)))
            add('CHỮ SÁNG TRONG DẢI MÀU',band & (gray>cutoff) & (sat<85))
            add('CHỮ TỐI TRONG DẢI MÀU',band & (gray<float(np.percentile(active_gray,25))) & (sat<110))

    # Lab clusters are complementary to luminance and useful for multicolour sources.
    pixels=lab.reshape(-1,3).astype(np.float32)
    if len(pixels)>80000:
        rng=np.random.default_rng(38);pixels=pixels[rng.choice(len(pixels),80000,replace=False)]
    try:
        cv2.setRNGSeed(38)
        _,_,centers=cv2.kmeans(pixels,3,None,(cv2.TERM_CRITERIA_EPS+cv2.TERM_CRITERIA_MAX_ITER,10,.5),2,cv2.KMEANS_PP_CENTERS)
        dist=((lab.astype(np.float32)[:,:,None,:]-centers[None,None,:,:])**2).sum(axis=3)
        labels=dist.argmin(axis=2)
        for i in range(3):add('TÁCH MÀU LAB '+str(i+1),labels==i)
    except cv2.error:pass
    # P40: additional hypotheses for gradient fills and outlined/shadowed text.
    # Colour membership is evaluated independently of brightness: a gradient
    # can span several LAB clusters while belonging to the same glyph.
    try:
        cv2.setRNGSeed(40)
        for k in (4, 5):
            _, _, ctr = cv2.kmeans(pixels, k, None,
                (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, .5),
                2, cv2.KMEANS_PP_CENTERS)
            dd = ((lab.astype(np.float32)[:,:,None,:] - ctr[None,None,:,:])**2).sum(axis=3)
            cluster = dd.argmin(axis=2)
            # Individual colour layers can represent a fill or an outline.
            for j in range(k):
                add('P40 LÕI MÀU %d.%d' % (k,j+1), cluster == j)
            # Join colour layers only when their union forms a plausible glyph.
            # This recovers gradients crossing two colour clusters.
            for j in range(k):
                for z in range(j+1,k):
                    union = (cluster == j) | (cluster == z)
                    frac=float(union.mean())
                    if .025 < frac < .65:
                        add('P40 GRADIENT %d.%d-%d' % (k,j+1,z+1),union)
    except cv2.error:
        pass
    # A dark drop shadow is usually shifted relative to the bright fill.
    # Keep the unmodified bright fill as a separate candidate, not a
    # morphological erosion of the full shadow+stroke silhouette.
    for q in (55, 70, 82):
        bright = (gray > np.percentile(gray,q))
        if .025 < bright.mean() < .7:
            add('P40 LÕI SÁNG %d' % q, bright)
    # For very dark photographs, do not force a denoised result: retain
    # original candidates so fine serif strokes and accents remain available.
    ranked=[];seen=set()
    for label,m in options:
        if m.mean()<.02 or m.mean()>.78:continue
        tight=_tight(m)
        if tight is None:continue
        key=(cv2.resize(tight,(40,24),interpolation=cv2.INTER_AREA)>.5).tobytes()
        if key in seen:continue
        seen.add(key)
        value=_rank(tight)
        if value>-1e8:ranked.append((value,label,tight))
    ranked.sort(key=lambda x:-x[0])
    return ranked[:limit]



# P52: fixed, independently named processing families. The previous candidates()
# function remains untouched for OCR/font search compatibility.
P52_NAMES = (
    'PA1 — TƯƠNG PHẢN THÍCH ỨNG',
    'PA2 — PHÂN TÁCH MÀU',
    'PA3 — TÁCH LÕI CHỮ / VIỀN BÓNG',
    'PA4 — NGƯỠNG HÓA CỤC BỘ',
    'PA5 — PHỤC HỒI NÉT CHỮ',
)


def five_methods(image):
    """Five stable method slots, each returning a real binary mask.

    Each method tries a small set of its own polarity/threshold hypotheses and
    selects its best by geometric mask quality. This is a heuristic ranking,
    not a ground-truth claim of font similarity.
    """
    rgb=np.asarray(ImageOps.exif_transpose(image).convert('RGB'))
    h,w=rgb.shape[:2]
    if min(h,w)<8:return []
    if max(h,w)>1300:
        factor=1300/max(h,w)
        rgb=cv2.resize(rgb,(max(1,round(w*factor)),max(1,round(h*factor))),interpolation=cv2.INTER_AREA)
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB)
    methods=[[] for _ in range(5)]
    def add(slot,mask):
        m=np.asarray(mask,dtype=np.uint8)
        if m.shape!=gray.shape:return
        t=_tight(m)
        if t is None:return
        score=_rank(t)
        if score>-1e8:methods[slot].append((score,t))
        elif .01<float(m.mean())<.90:methods[slot].append((-1e8,t))
    # PA1: global Otsu with adaptive contrast enhancement.
    clahe=cv2.createCLAHE(clipLimit=2.0,tileGridSize=(8,8)).apply(gray)
    for g in (gray,clahe):
        smooth=cv2.GaussianBlur(g,(3,3),0)
        _,binary=cv2.threshold(smooth,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        add(0,binary>0);add(0,binary==0)
    # PA2: chromatic foreground versus estimated border background.
    border=np.concatenate((lab[0],lab[-1],lab[:,0],lab[:,-1])).astype(np.float32)
    bg=np.median(border,axis=0)
    distance=np.linalg.norm(lab.astype(np.float32)-bg,axis=2)
    for threshold in (18,26,36,48):
        add(1,distance>threshold)
        add(1,distance<=threshold)
    # PA3: isolate likely bright/dark glyph fill, avoiding dilated shadows.
    for q in (55,65,75,85):
        v=np.percentile(gray,q)
        add(2,gray>v)
        add(2,gray<v)
    # PA4: local threshold for uneven illumination.
    for block in (21,41):
        block=min(block,min(gray.shape)//2*2-1)
        if block<11:continue
        for c in (5,10):
            local=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,block,c)
            add(3,local>0);add(3,local==0)
    # PA5: edge-preserving denoising, followed by contrast segmentation.
    smooth=cv2.bilateralFilter(gray,5,40,40)
    smooth=cv2.createCLAHE(clipLimit=1.5,tileGridSize=(8,8)).apply(smooth)
    _,binary=cv2.threshold(smooth,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
    for m in (binary>0,binary==0):
        add(4,m)
        add(4,cv2.morphologyEx(m.astype(np.uint8),cv2.MORPH_OPEN,np.ones((2,2),np.uint8)))
    result=[]
    for slot,choices in enumerate(methods):
        if choices:
            score,mask=max(choices,key=lambda x:x[0])
        else:
            # A method with no valid foreground remains selectable, but cannot
            # win automatic selection; do not substitute a different method.
            mask=np.zeros_like(gray,dtype=np.uint8)
            score=-1e9
        result.append((float(score),P52_NAMES[slot],mask))
    # P121: remove PA6/PA7 as selectable variants; keep internal segmentation.
    return result


def method_image(mask,index):
    """P56: output exactly the selected polarity without changing its mask."""
    if index==6:
        return Image.fromarray(np.where(mask>0,255,0).astype(np.uint8),'L')
    return Image.fromarray(np.where(mask>0,0,255).astype(np.uint8),'L')


def preview(image,index=0):
    ranked=candidates(image)
    if not ranked:return None,'KHÔNG TÁCH ĐƯỢC CHỮ',0
    _,label,mask=ranked[index%len(ranked)]
    # Black glyphs, white background; never invert the whole coloured sign.
    return Image.fromarray(np.where(mask>0,0,255).astype(np.uint8),'L'),label,len(ranked)


def estimate_text_skew(image):
    """Estimate horizontal text-line tilt; returns PIL counterclockwise correction and confidence.

    This is in-plane rotation only, NOT perspective rectification.
    """
    rgb=np.asarray(ImageOps.exif_transpose(image).convert('RGB'))
    h,w=rgb.shape[:2]
    if min(h,w)<24:return None,0.0
    scale=min(1.0,1200.0/max(h,w))
    if scale<1:rgb=cv2.resize(rgb,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_AREA)
    gray=cv2.cvtColor(rgb,cv2.COLOR_RGB2GRAY)
    gray=cv2.GaussianBlur(gray,(3,3),0)
    edges=cv2.Canny(gray,60,160)
    lines=cv2.HoughLinesP(edges,1,np.pi/720,threshold=max(20,int(rgb.shape[1]*.08)),minLineLength=max(18,int(rgb.shape[1]*.12)),maxLineGap=15)
    if lines is None:return None,0.0
    angles=[];weights=[]
    for segment in np.asarray(lines).reshape(-1,4):
        x1,y1,x2,y2=map(int,segment)
        dx=float(x2-x1);dy=float(y2-y1)
        if abs(dx)<1:continue
        a=float(np.degrees(np.arctan2(dy,dx)))
        if abs(a)>35:continue
        length=float(np.hypot(dx,dy))
        angles.append(a);weights.append(length)
    if len(angles)<2:return None,0.0
    order=np.argsort(angles);aa=np.asarray(angles)[order];ww=np.asarray(weights)[order]
    med=float(aa[np.searchsorted(np.cumsum(ww),ww.sum()/2)])
    close=np.abs(aa-med)<4
    confidence=float(ww[close].sum()/ww.sum())
    # PIL positive angle rotates counterclockwise, while pixel-space y grows downward.
    # A line sloping downward to the right needs positive PIL rotation.
    return med,confidence
