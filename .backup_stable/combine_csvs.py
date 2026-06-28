import os
import csv

nasdaq_dir = r'C:\Users\AviShemla\AntiGravity'
output_file = os.path.join(nasdaq_dir, 'Nasdaq_Data_All_Sectors_Combined.csv')

csv_files = [f for f in os.listdir(nasdaq_dir) if f.startswith('Nasdaq_Data_Combined_') and f.endswith('.csv')]

print(f"Found {len(csv_files)} files to combine.")

with open(output_file, 'w', newline='', encoding='utf-8') as outfile:
    writer = None
    
    for i, filename in enumerate(csv_files):
        file_path = os.path.join(nasdaq_dir, filename)
        # Extract sector name: remove "Nasdaq_Data_Combined_" and ".csv"
        sector_name = filename.replace('Nasdaq_Data_Combined_', '').replace('.csv', '')
        print(f"Processing {filename} (Sector: {sector_name})...")
        
        with open(file_path, 'r', newline='', encoding='utf-8') as infile:
            reader = csv.reader(infile)
            header = next(reader)
            
            if i == 0:
                # Add 'Sector' to the header
                new_header = header + ['Sector']
                writer = csv.writer(outfile)
                writer.writerow(new_header)
            
            for row in reader:
                # Append sector name to each row
                writer.writerow(row + [sector_name])

print(f"Successfully combined data into {output_file}")
