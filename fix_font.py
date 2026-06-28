import os

font_style = '''<style>
@import url("https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap");
html, body, [class*="css"], [class*="st-"], p, div, h1, h2, h3, h4, h5, h6, span {
    font-family: "Inter", sans-serif !important;
}
</style>'''

for file in ["dashboard.py", "dashboard_v1.py"]:
    if not os.path.exists(file): continue
    with open(file, "r", encoding="utf-8") as f2:
        content = f2.read()
    if "st.set_page_config" in content:
        parts = content.split("st.set_page_config", 1)
        rest = parts[1]
        if ")" in rest:
            sub_parts = rest.split(")", 1)
            new_content = parts[0] + "st.set_page_config" + sub_parts[0] + ")\n\nst.markdown(\"\"\"" + font_style + "\"\"\", unsafe_allow_html=True)\n" + sub_parts[1]
            with open(file, "w", encoding="utf-8") as f3:
                f3.write(new_content)
            print("Fixed font in", file)
