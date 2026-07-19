from PIL import Image
import os

base_dir = os.path.dirname(os.path.abspath(__file__))

def resize_img(filename, size=(200, 200)):
    path = os.path.join(base_dir, filename)
    if os.path.exists(path):
        img = Image.open(path)
        img.thumbnail(size, Image.Resampling.LANCZOS)
        img.save(path, "PNG")
        print(f"Resized {filename} to {img.size}")
    else:
        print(f"Missing {filename}")

resize_img("autopsy_icon.png", (200, 200))
resize_img("oracle_eye.png", (400, 400))
resize_img("oracle_logo.png", (400, 400))
