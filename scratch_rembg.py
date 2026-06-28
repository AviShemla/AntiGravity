from rembg import remove
from PIL import Image

def fix_logo():
    input_path = r'C:\Users\AviShemla\AntiGravity\oracle_logo.jpg'
    output_path = r'C:\Users\AviShemla\AntiGravity\oracle_logo_fixed.png'
    
    print(f"Loading {input_path}...")
    try:
        input_image = Image.open(input_path)
        
        # rembg automatically uses U2-Net and pymatting for alpha matting
        # Alpha matting is critical for removing the "halo" or "fringing" effect around complex edges
        print("Running AI background removal (this may download the u2net model on first run)...")
        output_image = remove(
            input_image, 
            alpha_matting=True, 
            alpha_matting_foreground_threshold=240, 
            alpha_matting_background_threshold=10, 
            alpha_matting_erode_size=10
        )
        
        output_image.save(output_path)
        print(f"Success! Clean transparent logo saved to {output_path}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    fix_logo()
