import pandas as pd
import os

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'financial_data')
TARGET_ETFS = ['XLK', 'XLV', 'XLY', 'XLF', 'XLC', 'XLI', 'XLE', 'XLP', 'XLU', 'XLRE', 'XLB']

def merge_scorecards():
    print("--- Compiling All ETF Scorecards into a single workbook ---")
    out_excel = os.path.join(BASE_DIR, 'All_ETFs_Scorecard.xlsx')
    writer = pd.ExcelWriter(out_excel, engine='xlsxwriter')
    workbook = writer.book
    
    meta_format = workbook.add_format({'bold': True, 'fg_color': '#1f497d', 'font_color': 'white', 'border': 1})
    header_format = workbook.add_format({'bold': True, 'fg_color': '#1f497d', 'font_color': 'white', 'border': 1, 'text_wrap': True})
    pct_format = workbook.add_format({'num_format': '0.00%'})
    
    green_format = workbook.add_format({'bg_color': '#e2efda', 'font_color': '#375623'})
    red_format = workbook.add_format({'bg_color': '#fce4d6', 'font_color': '#c00000'})
    neutral_format = workbook.add_format({'bg_color': '#fff2cc', 'font_color': '#806000'})
    hit_format = workbook.add_format({'bg_color': '#33CC33', 'font_color': '#000000', 'bold': True})
    miss_format = workbook.add_format({'bg_color': '#FF0000', 'font_color': '#FFFFFF', 'bold': True})
    
    compiled_any = False
    
    for etf in TARGET_ETFS:
        in_excel = os.path.join(BASE_DIR, f'{etf}_Bayesian_Scorecard.xlsx')
        if not os.path.exists(in_excel):
            continue
            
        try:
            df_raw = pd.read_excel(in_excel, header=None)
            if df_raw.empty:
                continue
                
            title_str = str(df_raw.iloc[0, 0])
            features_str = str(df_raw.iloc[1, 0])
            
            df = pd.read_excel(in_excel, skiprows=2)
            
            df.to_excel(writer, sheet_name=etf, startrow=2, index=False)
            worksheet = writer.sheets[etf]
            
            worksheet.merge_range('A1:I1', title_str, meta_format)
            worksheet.merge_range('A2:I2', features_str, meta_format)
            
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(2, col_num, value, header_format)
                
            worksheet.set_column(0, 0, 15)
            worksheet.set_column(1, 4, 18, pct_format)
            worksheet.set_column(6, 8, 18)
            
            last_row = len(df) + 3
            worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"UP"', 'format': green_format})
            worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Down"', 'format': red_format})
            worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Pending"', 'format': neutral_format})
            worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Hold"', 'format': neutral_format})
            worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Buy"', 'format': green_format})
            worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Sell"', 'format': red_format})
            worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"On target"', 'format': hit_format})
            worksheet.conditional_format(f'A4:Z{last_row}', {'type': 'cell', 'criteria': '==', 'value': '"Miss"', 'format': miss_format})
            
            compiled_any = True
        except Exception as e:
            print(f"Error compiling {etf}: {e}")

    if compiled_any:
        writer.close()
        print(f"Successfully compiled All_ETFs_Scorecard.xlsx")
    else:
        print("No scorecards found to compile.")

if __name__ == '__main__':
    merge_scorecards()
