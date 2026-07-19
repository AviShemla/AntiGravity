import os
from PIL import Image

in_path = r"C:\Users\AviShemla\.gemini\antigravity\brain\e6da8969-1069-4402-8307-e101b4874b0c\media__1780390852309.jpg"
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'etf_icon.png')

img = Image.open(in_path).convert("RGBA")
datas = img.getdata()
newData = []
for item in datas:
    if item[0] < 25 and item[1] < 25 and item[2] < 25:
        newData.append((0, 0, 0, 0))
    else:
        newData.append(item)
img.putdata(newData)
img.thumbnail((250, 250), Image.Resampling.LANCZOS)
img.save(out_path, "PNG")
print("ETF icon processed!")
