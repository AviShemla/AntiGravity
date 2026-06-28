from PIL import Image
import os

def remove_black(in_path, out_path, tolerance=25):
    img = Image.open(in_path).convert("RGBA")
    datas = img.getdata()
    newData = []
    for item in datas:
        if item[0] < tolerance and item[1] < tolerance and item[2] < tolerance:
            newData.append((0, 0, 0, 0))
        else:
            newData.append(item)
    img.putdata(newData)
    img.save(out_path, "PNG")

logo_src = r"C:\Users\AviShemla\.gemini\antigravity\brain\e6da8969-1069-4402-8307-e101b4874b0c\media__1780389447885.jpg"
autopsy_src = r"C:\Users\AviShemla\.gemini\antigravity\brain\e6da8969-1069-4402-8307-e101b4874b0c\media__1780388742677.jpg"

base_dir = r"C:\Users\AviShemla\AntiGravity"

remove_black(logo_src, os.path.join(base_dir, "oracle_eye.png"))
remove_black(logo_src, os.path.join(base_dir, "oracle_logo.png"))
remove_black(autopsy_src, os.path.join(base_dir, "autopsy_icon.png"))
print("Images processed and saved.")
