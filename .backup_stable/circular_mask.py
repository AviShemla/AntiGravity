from PIL import Image, ImageDraw
from rembg import remove
import os

def fix_logo():
    input_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oracle_logo_fixed.png')
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'oracle_logo_fixed.png')
    
    print("1. Running AI Background Removal...")
    input_image = Image.open(input_path).convert("RGBA")
    
    extracted = remove(
        input_image, 
        alpha_matting=True, 
        alpha_matting_foreground_threshold=240, 
        alpha_matting_background_threshold=10, 
        alpha_matting_erode_size=10
    )
    
    print("2. Applying perfect circular bounding mask...")
    width, height = extracted.size
    
    # We create a perfect circle mask that spans the entire image (radius = 512)
    # This will preserve the top/bottom/left/right diamonds, but will gently 
    # curve off the corners, turning the hard vertical cuts on the characters 
    # into a smooth rounded badge shape!
    
    mask = Image.new('L', (width, height), 0)
    draw = ImageDraw.Draw(mask)
    
    # Draw a circle slightly smaller than the full width to ensure no flat edges remain
    # Radius = 508. Center = 512, 512.
    # Bounding box: 4, 4, 1020, 1020
    draw.ellipse((4, 4, 1020, 1020), fill=255)
    
    # Apply the circular mask to the extracted image's alpha channel
    r, g, b, a = extracted.split()
    
    final_alpha = Image.new('L', (width, height))
    for x in range(width):
        for y in range(height):
            orig_a = a.getpixel((x, y))
            mask_a = mask.getpixel((x, y))
            final_a = min(orig_a, mask_a)
            final_alpha.putpixel((x, y), final_a)
            
    extracted.putalpha(final_alpha)
    extracted.save(output_path)
    print(f"Successfully cleaned logo and saved to {output_path}")

if __name__ == "__main__":
    fix_logo()
