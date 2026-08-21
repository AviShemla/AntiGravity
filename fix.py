import database_manager
import json

true_equity = 11214.44

# Fix DB
database_manager.execute_write("""
    UPDATE prod_vs_shadow_master 
    SET total_equity = ? 
    WHERE date = '2026-08-20' AND model_name = 'Sandbox_V1'
""", [true_equity])

# Fix state json
with open('financial_data/prod_shadow_state.json', 'r') as f:
    state = json.load(f)

state['V1_Classic'] = true_equity
state['last_date'] = '2026-08-20'

with open('financial_data/prod_shadow_state.json', 'w') as f:
    json.dump(state, f)

print("Fix applied to Turso DB and state json.")
