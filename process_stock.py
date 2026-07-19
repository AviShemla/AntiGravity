import os
from PIL import Image
import numpy as np

img_path = r"C:\Users\AviShemla\.gemini\antigravity\brain\e6da8969-1069-4402-8307-e101b4874b0c\media__1780393317744.png"
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend/stock_icon.png')

img = Image.open(img_path).convert("RGBA")
data = np.array(img)

# The background is practically pure black. Let's make everything where RGB < 15 transparent.
r, g, b, a = data[:,:,0], data[:,:,1], data[:,:,2], data[:,:,3]
mask = (r < 15) & (g < 15) & (b < 15)

data[:,:,3][mask] = 0

img_out = Image.fromarray(data)
# Resize it to a reasonable icon size so it renders crisply and fast
img_out = img_out.resize((80, 80), Image.Resampling.LANCZOS)
img_out.save(out_path)
print("Hexagon Stock Icon processed successfully!")
