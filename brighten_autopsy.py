from PIL import Image, ImageEnhance
import os

path = r"C:\Users\AviShemla\AntiGravity\frontend\autopsy_icon.png"
if os.path.exists(path):
    img = Image.open(path)
    enhancer = ImageEnhance.Brightness(img)
    # Brighten by 1.8x
    bright_img = enhancer.enhance(1.8)
    
    # Also increase contrast a bit
    contrast_enhancer = ImageEnhance.Contrast(bright_img)
    final_img = contrast_enhancer.enhance(1.2)
    
    final_img.save(path)
    print("Autopsy icon brightened successfully!")
else:
    print("File not found.")
