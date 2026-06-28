from PIL import Image, ImageDraw
from rembg import remove
import os

def fix_logo():
    input_path = r'C:\Users\AviShemla\AntiGravity\oracle_logo.jpg'
    output_path = r'C:\Users\AviShemla\AntiGravity\oracle_logo_fixed.png'
    
    print("1. Running AI Background Removal...")
    input_image = Image.open(input_path).convert("RGBA")
    
    # We use rembg to perfectly extract the foreground with sub-pixel matting
    extracted = remove(
        input_image, 
        alpha_matting=True, 
        alpha_matting_foreground_threshold=240, 
        alpha_matting_background_threshold=10, 
        alpha_matting_erode_size=10
    )
    
    print("2. Erasing side characters (Einstein and Cyborg)...")
    # Now we manually erase the left and right characters by setting their alpha to 0
    # The image is 1024x1024.
    # The central ring radius is roughly 400 pixels. Center is 512,512.
    # We will use a precise polygon or bounding box to erase the sides.
    
    width, height = extracted.size
    
    # We will erase everything that is outside a radius of 430 from the center, 
    # EXCEPT for the top, bottom, left, and right diamonds which lie on the axes.
    # Actually, a simpler way: just erase the rectangle containing Einstein (top left)
    # and Cyborg (top right).
    
    # Einstein bounding box (approximate): x from 0 to 250, y from 0 to 512
    # Cyborg bounding box (approximate): x from 774 to 1024, y from 0 to 512
    
    r, g, b, a = extracted.split()
    draw = ImageDraw.Draw(a)
    
    # Erase Top Left (Einstein)
    # We use a polygon to carefully cut around the ring.
    # Let's just erase a big rectangle on the left, but leave the left diamond intact (y near 512).
    # Left diamond is around y=512. So we erase y from 0 to 400 on the left.
    draw.rectangle([0, 0, 230, 430], fill=0) # Top-Left
    draw.rectangle([0, 590, 230, 1024], fill=0) # Bottom-Left (if any debris)
    
    # Erase Top Right (Cyborg)
    draw.rectangle([794, 0, 1024, 430], fill=0) # Top-Right
    draw.rectangle([794, 590, 1024, 1024], fill=0) # Bottom-Right (if any debris)
    
    extracted.putalpha(a)
    extracted.save(output_path)
    print(f"Successfully cleaned logo and saved to {output_path}")

if __name__ == "__main__":
    fix_logo()
