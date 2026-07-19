from PIL import Image
import numpy as np
import os

in_path = r"C:\Users\AviShemla\.gemini\antigravity\brain\e6da8969-1069-4402-8307-e101b4874b0c\media__1780391897996.jpg"
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend/stock_icon.png')

img = Image.open(in_path).convert("RGBA")
w, h = img.size

# Extract bottom right quadrant
quad_box = (w//2, h//2, w, h)
quad = img.crop(quad_box)
quad_data = np.array(quad)

# Find bounding box of non-black pixels in the quadrant
# Threshold for "not black"
mask = (quad_data[:,:,0] > 20) | (quad_data[:,:,1] > 20) | (quad_data[:,:,2] > 20)
coords = np.argwhere(mask)

if len(coords) > 0:
    y0, x0 = coords.min(axis=0)
    y1, x1 = coords.max(axis=0)
    
    # Crop the exact circle
    circle = quad.crop((x0, y0, x1, y1))
    
    # Make black transparent
    circle_data = np.array(circle)
    black_mask = (circle_data[:,:,0] < 20) & (circle_data[:,:,1] < 20) & (circle_data[:,:,2] < 20)
    circle_data[black_mask] = [0, 0, 0, 0]
    
    final_img = Image.fromarray(circle_data)
    final_img.thumbnail((200, 200), Image.Resampling.LANCZOS)
    final_img.save(out_path, "PNG")
    print("Stock icon successfully cropped and saved!")
else:
    print("Could not find circle in bottom right.")
