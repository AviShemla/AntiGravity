import json
path = "C:/Users/AviShemla/AntiGravity/financial_data/Pending_Orders.json"
with open(path, "r") as f:
    data = json.load(f)
for k in data:
    data[k]["Date"] = "2026-07-23"
with open(path, "w") as f:
    json.dump(data, f, indent=4)
print("DATES FIXED TO 2026-07-23")
