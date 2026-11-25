import unittest
import cv2
import numpy as np
from image_cleanup import preview_text_removal

class ImageCleanupTests(unittest.TestCase):
    def test_flat_background_and_source_unchanged(self):
        image=np.full((120,260,3),248,np.uint8); cv2.putText(image,"TEST",(35,82),cv2.FONT_HERSHEY_SIMPLEX,1.5,(15,15,15),3,cv2.LINE_AA); original=image.copy()
        preview,info=preview_text_removal(image,[25,35,180,95]); self.assertTrue(np.array_equal(image,original)); self.assertGreater(info["mask_pixels"],0); self.assertLess(info["mask_ratio"],0.38); self.assertEqual(preview.shape,image.shape)
    def test_other_region_untouched(self):
        image=np.full((140,300,3),245,np.uint8); cv2.putText(image,"FIRST",(20,55),cv2.FONT_HERSHEY_SIMPLEX,1.0,(0,0,0),2,cv2.LINE_AA); cv2.putText(image,"SECOND",(20,115),cv2.FONT_HERSHEY_SIMPLEX,1.0,(0,0,0),2,cv2.LINE_AA)
        preview,_=preview_text_removal(image,[10,20,160,70]); self.assertTrue(np.array_equal(preview[80:],image[80:]))
    def test_texture_mask_not_whole_rectangle(self):
        image=np.full((130,280,3),242,np.uint8)
        for y in range(0,130,5): image[y:y+1]=215
        cv2.putText(image,"TEXT",(35,88),cv2.FONT_HERSHEY_SIMPLEX,1.4,(5,5,5),3,cv2.LINE_AA)
        preview,info=preview_text_removal(image,[25,35,190,100]); self.assertLess(info["mask_ratio"],0.38)
        changed=np.count_nonzero(np.any(preview[35:100,25:190]!=image[35:100,25:190],axis=2)); self.assertLess(changed,65*165*0.55)
    def test_bbox_clipping_and_outside_rejection(self):
        image=np.full((50,80,3),255,np.uint8); cv2.putText(image,"A",(2,35),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,0,0),2,cv2.LINE_AA)
        _,info=preview_text_removal(image,[-5,5,45,45]); self.assertEqual(info["bbox"][0],0)
        with self.assertRaises(ValueError): preview_text_removal(image,[100,100,120,120])
    def test_invalid_method_and_bbox(self):
        image=np.full((60,100,3),255,np.uint8); cv2.putText(image,"A",(10,42),cv2.FONT_HERSHEY_SIMPLEX,1.0,(0,0,0),2,cv2.LINE_AA)
        with self.assertRaises(ValueError): preview_text_removal(image,[1,1,80,50],"unknown")
        with self.assertRaises(ValueError): preview_text_removal(image,[1,2,3])

if __name__=="__main__": unittest.main()