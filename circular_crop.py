from PIL import Image, ImageDraw

def circular_crop():
    input_path = r'C:\Users\AviShemla\AntiGravity\oracle_logo.jpg'
    output_path = r'C:\Users\AviShemla\AntiGravity\oracle_logo_fixed.png'
    
    try:
        # Open original image
        img = Image.open(input_path).convert("RGBA")
        width, height = img.size
        
        # The logo is a circle in the center. Let's find the radius.
        # It looks like the height is mostly the circle, maybe slightly less.
        # We will make a circular mask.
        mask = Image.new('L', (width, height), 0)
        draw = ImageDraw.Draw(mask)
        
        # Center of the image
        cx, cy = width // 2, height // 2
        
        # The circle diameter seems to be slightly less than the height.
        # Let's use 95% of the height as the diameter.
        radius = int((height * 0.95) / 2)
        
        # Draw white circle
        left = cx - radius
        top = cy - radius
        right = cx + radius
        bottom = cy + radius
        
        draw.ellipse((left, top, right, bottom), fill=255)
        
        # Apply mask
        output = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        output.paste(img, (0, 0), mask)
        
        # Crop the image to the bounding box of the circle to remove empty space
        output = output.crop((left, top, right, bottom))
        
        output.save(output_path)
        print(f"Successfully cropped to circle: {output_path}")
        
    except Exception as e:
        print(f"Error cropping: {e}")

if __name__ == "__main__":
    circular_crop()
