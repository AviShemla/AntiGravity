with open('C:\\Users\\AviShemla\\AntiGravity\\frontend\\app.js', 'r', encoding='utf-8') as f:
    c = f.read()
c = c.replace(r"\'no-store\'", "'no-store'")
with open('C:\\Users\\AviShemla\\AntiGravity\\frontend\\app.js', 'w', encoding='utf-8') as f:
    f.write(c)
