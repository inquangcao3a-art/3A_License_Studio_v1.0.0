"""P65: conservative component-aware foreground cleanup.

Never changes the source image. Large text strokes are preserved, and tiny
components near text are retained as possible Vietnamese diacritics.
"""
import cv2
import numpy as np


def clean_mask(mask):
    src=(np.asarray(mask)>0).astype(np.uint8)
    h,w=src.shape
    if h<16 or w<16 or not src.any():
        return src
    n,labels,stats,centroids=cv2.connectedComponentsWithStats(src,8)
    if n<=2:
        return src.copy()
    components=[]
    for i in range(1,n):
        x,y,cw,ch,area=map(int,stats[i])
        components.append((i,x,y,cw,ch,area))
    # Estimate scale from substantial components, not from tiny wood grain.
    plausible=[c for c in components if c[5]>=max(12,int(h*w*.0008)) and c[4]>=max(5,int(h*.10))]
    if not plausible:
        return src.copy()
    max_area=max(c[5] for c in plausible)
    dominant=[c for c in plausible if c[5]>=max(12,max_area*.065)]
    if not dominant:
        return src.copy()
    typical_height=float(np.median([c[4] for c in dominant]))
    # Very small specks are candidates for removal, but preserve dots/accents
    # above, below and alongside substantial letter bodies.
    tiny_area=max(3,min(90,int(max_area*.008)))
    keep=np.zeros(n,dtype=bool)
    keep[0]=False
    for i,x,y,cw,ch,area in components:
        if area>=tiny_area:
            keep[i]=True
            continue
        cx=x+cw/2.0;cy=y+ch/2.0
        for _,bx,by,bw,bh,ba in dominant:
            dx=max(bx-cx,0,cx-(bx+bw))
            dy=max(by-cy,0,cy-(by+bh))
            # Generous vertical allowance for stacked Vietnamese accents.
            if dx<=max(3,typical_height*.30) and dy<=max(4,typical_height*.65):
                keep[i]=True
                break
    out=keep[labels].astype(np.uint8)
    # Reject aggressive cleaning: preserve original if it removes too much ink.
    if out.sum()<src.sum()*.76:
        return src.copy()
    return out


def clean_variants(variants):
    """Return cleaned masks in the same seven slots, preserving original ranking."""
    return [(score,label,clean_mask(mask)) for score,label,mask in variants]
