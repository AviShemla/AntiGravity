from PIL import Image, ImageDraw, ImageFilter
import os

def smooth_edges():
    input_path = r'C:\Users\AviShemla\AntiGravity\oracle_logo_fixed.png'
    output_path = r'C:\Users\AviShemla\AntiGravity\oracle_logo_fixed.png'
    
    try:
        img = Image.open(input_path).convert("RGBA")
        width, height = img.size
        
        # Create an alpha mask
        mask = Image.new('L', (width, height), color=255)
        draw = ImageDraw.Draw(mask)
        
        # We want to fade the left and right edges (e.g. 10% of the width)
        fade_width = int(width * 0.15)
        
        for x in range(fade_width):
            # Left edge fade (0 at edge, 255 at fade_width)
            alpha = int((x / fade_width) * 255)
            draw.line([(x, 0), (x, height)], fill=alpha)
            
            # Right edge fade (0 at edge, 255 at fade_width from right)
            draw.line([(width - 1 - x, 0), (width - 1 - x, height)], fill=alpha)
            
        # Optional: Fade the top and bottom slightly just in case
        fade_height = int(height * 0.05)
        for y in range(fade_height):
            alpha = int((y / fade_height) * 255)
            # Combine with existing mask using min()
            for x in range(width):
                current = mask.getpixel((x, y))
                mask.putpixel((x, y), min(current, alpha))
                
                bottom_y = height - 1 - y
                current_bottom = mask.getpixel((x, bottom_y))
                mask.putpixel((x, bottom_y), min(current_bottom, alpha))
                
        # Apply a gaussian blur to the mask to make the transition ultra smooth
        mask = mask.filter(ImageFilter.GaussianBlur(radius=10))
        
        # Apply the mask to the image's alpha channel
        r, g, b, a = img.split()
        
        # Multiply the new mask with the existing alpha channel
        final_alpha = Image.new('L', (width, height))
        for x in range(width):
            for y in range(height):
                orig_a = a.getpixel((x, y))
                mask_a = mask.getpixel((x, y))
                # Combine alphas
                final_a = int((orig_a * mask_a) / 255)
                final_alpha.putpixel((x, y), final_a)
                
        img.putalpha(final_alpha)
        img.save(output_path)
        print(f"Successfully smoothed the edges of {output_path}")
        
    except Exception as e:
        print(f"Error smoothing edges: {e}")

if __name__ == "__main__":
    smooth_edges()
