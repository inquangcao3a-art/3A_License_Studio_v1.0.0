"""P58 optional, non-destructive horizontal gap compaction for binary text masks."""
import re
import numpy as np

def remove_word_spaces(text):
    return re.sub(r'\s+', '', text or '')

def compact_mask(mask, mode='words', ratio=0.18):
    """Reduce blank vertical columns without touching ink pixels.
    mode=words: shrink only unusually wide blank runs;
    mode=letters: shrink all internal runs. Keeps diacritics with their glyphs
    by operating on full-height column projections rather than connected components.
    """
    if mask is None:return None
    a=np.asarray(mask,dtype=np.uint8)
    if a.ndim!=2 or a.shape[1]<3:return a.copy()
    ink=np.any(a>0,axis=0)
    occupied=np.flatnonzero(ink)
    if len(occupied)<2:return a.copy()
    a=a[:,occupied[0]:occupied[-1]+1]
    ink=np.any(a>0,axis=0)
    runs=[];i=0
    while i<len(ink):
        if ink[i]:i+=1;continue
        j=i
        while j<len(ink) and not ink[j]:j+=1
        runs.append((i,j))
        i=j
    if not runs:return a.copy()
    widths=np.array([j-i for i,j in runs]); typical=float(np.median(widths))
    word_threshold=max(3,int(round(typical*2.4)))
    chunks=[];last=0
    for i,j in runs:
        chunks.append(a[:,last:i]);width=j-i
        if mode=='letters' or width>=word_threshold:
            keep=max(1,int(round(width*max(0,min(1,ratio)))))
        else:keep=width
        chunks.append(a[:,i:i+keep]);last=j
    chunks.append(a[:,last:])
    return np.concatenate(chunks,axis=1)

def prepare_candidates(candidates,words=False,letters=False):
    if not (words or letters):return candidates
    output=[]
    for m in candidates:
        if m is None:continue
        # Word gaps are collapsed first; optional letter compaction then applies.
        z=compact_mask(m,'words') if words else np.asarray(m).copy()
        if letters:z=compact_mask(z,'letters',ratio=0.35)
        output.append(z)
    return output
