"""P63 conservative image geometry. Never modifies the source."""
import cv2
import numpy as np
from PIL import Image, ImageOps

def _order(points):
    p=np.asarray(points,dtype=np.float32).reshape(4,2)
    s=p.sum(1); d=np.diff(p,axis=1).ravel()
    return np.array([p[np.argmin(s)],p[np.argmin(d)],p[np.argmax(s)],p[np.argmax(d)]],np.float32)

def rectify_perspective(image):
    """Only rectify a large, clear quadrilateral with plausible proportions.

    Return original when the scene does not provide reliable four corners.
    """
    source=ImageOps.exif_transpose(image).convert('RGB')
    rgb=np.asarray(source); h,w=rgb.shape[:2]
    if min(w,h)<80:return source,False
    factor=min(1.0,1100/max(w,h))
    small=cv2.resize(rgb,(round(w*factor),round(h*factor))) if factor<1 else rgb
    sh,sw=small.shape[:2]
    lab=cv2.cvtColor(small,cv2.COLOR_RGB2LAB)
    gray=cv2.GaussianBlur(lab[:,:,0],(5,5),0)
    edges=cv2.Canny(gray,55,140)
    edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    possible=[]
    for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:35]:
        area=cv2.contourArea(contour)
        if not (0.20*sw*sh<=area<=0.96*sw*sh):continue
        perimeter=cv2.arcLength(contour,True)
        polygon=cv2.approxPolyDP(contour,.025*perimeter,True)
        if len(polygon)!=4 or not cv2.isContourConvex(polygon):continue
        corners=_order(polygon)
        tl,tr,br,bl=corners
        top=np.linalg.norm(tr-tl);bottom=np.linalg.norm(br-bl)
        left=np.linalg.norm(bl-tl);right=np.linalg.norm(br-tr)
        if min(top,bottom,left,right)<25:continue
        if max(top,bottom)/min(top,bottom)>2.0 or max(left,right)/min(left,right)>2.0:continue
        # Require substantial projective distortion; do not warp ordinary upright text.
        disparity=max(abs(top-bottom)/max(top,bottom),abs(left-right)/max(left,right))
        if disparity<.10:continue
        possible.append((area,corners))
    if not possible:return source,False
    corners=possible[0][1]/factor
    tl,tr,br,bl=corners
    out_w=int(round(max(np.linalg.norm(tr-tl),np.linalg.norm(br-bl))))
    out_h=int(round(max(np.linalg.norm(bl-tl),np.linalg.norm(br-tr))))
    if min(out_w,out_h)<50 or max(out_w,out_h)>4000:return source,False
    dst=np.float32([[0,0],[out_w-1,0],[out_w-1,out_h-1],[0,out_h-1]])
    matrix=cv2.getPerspectiveTransform(corners,dst)
    result=cv2.warpPerspective(rgb,matrix,(out_w,out_h),flags=cv2.INTER_CUBIC,borderMode=cv2.BORDER_REPLICATE)
    return Image.fromarray(result),True

def correct(image,skew_estimator):
    source=ImageOps.exif_transpose(image).convert('RGB')
    candidate,rectified=rectify_perspective(source)
    angle,confidence=skew_estimator(candidate)
    rotated=False
    if angle is not None and 1.0<=abs(angle)<=25.0 and confidence>=.88:
        trial=candidate.rotate(float(angle),resample=Image.Resampling.BICUBIC,expand=True,fillcolor=(255,255,255))
        residual,rc=skew_estimator(trial)
        if residual is None or abs(residual)<=max(1.2,abs(angle)*.35) or rc<.45:
            candidate=trial;rotated=True
    return candidate,rectified,rotated
