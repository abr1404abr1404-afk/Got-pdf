"""Conservative preview-only removal of text ink from raster regions."""
import cv2
import numpy as np

def _bbox(value, width, height):
    if isinstance(value, dict): value = value.get("bbox")
    if not isinstance(value, (list, tuple)) or len(value) != 4: raise ValueError("bbox must contain [x0, y0, x1, y1]")
    try: x0, y0, x1, y1 = [int(round(float(v))) for v in value]
    except (TypeError, ValueError, OverflowError) as exc: raise ValueError("bbox coordinates must be finite numbers") from exc
    if x1 <= x0 or y1 <= y0 or x1 <= 0 or y1 <= 0 or x0 >= width or y0 >= height: raise ValueError("bbox is invalid or outside the image")
    x0, x1, y0, y1 = max(0, x0), min(width, x1), max(0, y0), min(height, y1)
    if x1-x0 < 3 or y1-y0 < 3: raise ValueError("bbox is too small")
    return x0, y0, x1, y1

def _make_ink_mask(region):
    h, w = region.shape[:2]; band = max(2, min(8, round(min(h,w)*0.12)))
    border = np.concatenate([region[:band].reshape(-1,3), region[-band:].reshape(-1,3), region[:,:band].reshape(-1,3), region[:,-band:].reshape(-1,3)])
    lab = cv2.cvtColor(region, cv2.COLOR_BGR2LAB).astype(np.float32)
    blab = cv2.cvtColor(border.reshape(-1,1,3).astype(np.uint8), cv2.COLOR_BGR2LAB).reshape(-1,3).astype(np.float32)
    bg = np.median(blab, axis=0); dev = np.linalg.norm(blab-bg, axis=1)
    noise = float(np.median(np.abs(dev-np.median(dev)))*1.4826)
    threshold = float(np.clip(max(18.0, np.median(dev)+4*noise+8),18,55))
    # Local median removes thin table rules from the background estimate while retaining character strokes.
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    k = max( nine := 9, min(31, (min(h, w) // 5) | 1))
    local_bg = cv2.medianBlur(gray, k if k % 2 else k + 1)
    local_ink = (local_bg.astype(np.int16) - gray.astype(np.int16) > 20)
    color_ink = np.linalg.norm(lab-bg,axis=2)>threshold
    raw = (local_ink | color_ink).astype(np.uint8)*255
    count, labels, stats, _ = cv2.connectedComponentsWithStats(raw,8); mask=np.zeros_like(raw)
    for i in range(1,count):
        x,y,cw,ch,area=stats[i]
        if max(2,int(h*w*0.000015)) <= area <= int(h*w*0.22) and cw < w*0.98 and ch < h*0.98: mask[labels==i]=255
    mask=cv2.dilate(mask,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3)),iterations=1)
    return mask,threshold,noise

def preview_text_removal(image, bbox, method="telea"):
    if not isinstance(image,np.ndarray) or image.ndim!=3 or image.shape[2]!=3: raise ValueError("image must be a BGR color image")
    if image.dtype!=np.uint8 or image.size==0: raise ValueError("image must be non-empty uint8")
    h,w=image.shape[:2]; x0,y0,x1,y1=_bbox(bbox,w,h); method=str(method).lower().strip()
    flags={"telea":cv2.INPAINT_TELEA,"ns":cv2.INPAINT_NS}
    if method not in flags: raise ValueError("method must be telea or ns")
    region=image[y0:y1,x0:x1]; mask,threshold,noise=_make_ink_mask(region)
    ink=int(cv2.countNonZero(mask)); ratio=ink/max(1,mask.size)
    if ink==0: raise ValueError("لم يتم العثور على حبر واضح داخل المنطقة.")
    if ratio>0.38: raise ValueError("المنطقة مزدحمة بالتفاصيل؛ قلّص مربع النص.")
    output=image.copy(); output[y0:y1,x0:x1]=cv2.inpaint(region,mask,3,flags[method])
    return output,{"method":method,"bbox":[x0,y0,x1,y1],"mask_pixels":ink,"region_pixels":int(mask.size),"mask_ratio":round(ratio,5),"ink_threshold":round(threshold,2),"estimated_border_noise":round(noise,2),"scope":"selected_region_only","preview_only":True,"limitations":"قد تتأثر الخلفيات المزخرفة أو المتداخلة؛ راجع المعاينة."}