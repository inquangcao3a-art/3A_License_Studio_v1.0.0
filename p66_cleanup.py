"""P66: conservative foreground cleanup for preview and optional OCR candidates."""
import cv2
import numpy as np
last_stats={}

def clean_mask(mask):
    src=(np.asarray(mask)>0).astype(np.uint8)
    h,w=src.shape
    if min(h,w)<16 or not src.any():return src.copy()
    n,labels,stats,_=cv2.connectedComponentsWithStats(src,8)
    if n<=2:return src.copy()
    comps=[]
    for i in range(1,n):
        x,y,cw,ch,area=map(int,stats[i]);comps.append((i,x,y,cw,ch,area))
    # Find substantive foreground without assuming every small island is noise.
    areas=sorted((c[5] for c in comps),reverse=True)
    largest=areas[0]
    substantial=[c for c in comps if c[5]>=max(12,largest*.045) and c[4]>=h*.12]
    if not substantial:return src.copy()
    left=min(c[1] for c in substantial);right=max(c[1]+c[3] for c in substantial)
    top=min(c[2] for c in substantial);bottom=max(c[2]+c[4] for c in substantial)
    height=max(1,bottom-top)
    min_area=max(3,min(100,round(largest*.012)))
    keep=np.zeros(n,dtype=np.uint8)
    for i,x,y,cw,ch,area in comps:
        # Preserve substantial strokes, including isolated letters.
        if area>=min_area and not (cw>max(25,w*.42) and ch<=max(2,h*.018) and area<largest*.22):
            keep[i]=1;continue
        # Preserve small Vietnamese accents close to the letter region.
        cx=x+cw/2;cy=y+ch/2
        if left-height*.12<=cx<=right+height*.12 and top-height*.42<=cy<=bottom+height*.22:
            if cw<=height*.48 and ch<=height*.42:
                keep[i]=1
    out=keep[labels]
    # Fail-safe: do not sacrifice a meaningful part of the letter ink.
    if out.sum()<src.sum()*.78:return src.copy()
    return out.astype(np.uint8)

def clean_variants(variants):
    global last_stats
    result=[];removed=[]
    for score,label,mask in variants:
        original=(np.asarray(mask)>0).astype(np.uint8)
        cleaned=clean_mask(mask)
        removed.append(int(original.sum()-cleaned.sum()))
        result.append((score,label,cleaned))
    last_stats={'removed_pixels':removed}
    return result
