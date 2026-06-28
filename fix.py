with open("dashboard.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_block = """            st.metric("EL_VOLTI Max DD", f"{d_v:.2f}%")
            
        r_ch, d_ch = calc_o_metrics(df_merged, 'CHAMPION (Live VIP)')
        with c_o3:
            st.metric("🏆 CHAMPION Return", f"{r_ch:+.2f}%")
            st.metric("🏆 CHAMPION Max DD", f"{d_ch:.2f}%")
            
        disp_merged = format_df_for_display(df_merged.iloc[::-1])
        st.dataframe(disp_merged.style.format(na_rep=''), use_container_width=True)
    else:
        st.info("Olympic Backtest ledgers are currently being generated in the background. Please check the ETA timer in the sidebar to see when the race will begin!")

# --- VIEW 4: TRADE AUTOPSY ---
with tab4:
    try:
        col_img, col_txt = st.columns([1, 6])
        with col_img:
            import os
            st.image(os.path.join(BASE_DIR.replace("financial_data", ""), "autopsy_icon.png"), width=120)
        with col_txt:
            st.markdown("<h2 style='text-align: left; margin-top: 25px;'>Trade Autopsy (Failure Pattern Analytics)</h2>", unsafe_allow_html=True)
    except Exception as e:
        st.markdown("<h2 style='text-align: center;'>Trade Autopsy (Failure Pattern Analytics)</h2>", unsafe_allow_html=True)
        
    st.markdown("<p style='text-align: center;'>Forensic cross-referencing of capitalized losses against historical PyMC predictions.</p>", unsafe_allow_html=True)
    
    c_auto1, c_auto2, c_auto3 = st.columns([1, 2, 1])
    with c_auto2:
        col_p, col_m = st.columns(2)
        with col_p:
            auto_persona_ui = st.selectbox("Select Target Persona", ["Conservative", "Neutral", "BallsForBrains", "Dynamic Sharpe"], index=3, key="auto_persona")
            auto_persona = "Dynamic" if auto_persona_ui == "Dynamic Sharpe" else auto_persona_ui
        with col_m:
            auto_mode = st.selectbox("Select Market Sector", ["Single Stocks", "ETFs"], index=0, key="auto_mode")
            auto_mode_val = "Single" if auto_mode == "Single Stocks" else "ETF"
            
"""

# Find line index for `    st.markdown("---")` around 1319
idx = -1
for i, line in enumerate(lines):
    if line.strip() == 'st.markdown("---")' and i > 1310 and i < 1330:
        idx = i
        break

if idx != -1:
    lines.insert(idx, new_block)
    with open("dashboard.py", "w", encoding="utf-8") as f:
        f.writelines(lines)
    print("Fixed!")
else:
    print("Could not find the target line to replace")
