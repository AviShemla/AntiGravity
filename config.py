import os
import json

# Try to find settings.json dynamically (supports being run from subfolders)
_current_dir = os.path.dirname(os.path.abspath(__file__))
_settings_path = os.path.join(_current_dir, 'settings.json')

if not os.path.exists(_settings_path):
    raise FileNotFoundError(f"CRITICAL ERROR: {settings_path} not found. AI Context Amnesia protection failed.")

with open(_settings_path, 'r') as f:
    _settings = json.load(f)

# Global Export Variables
WORKSPACE_DIR = _settings.get("WORKSPACE_DIR", _current_dir)
DATA_DIR = os.path.join(WORKSPACE_DIR, _settings.get("DATA_DIR_NAME", "financial_data"))

# Engine Directives
BAYESIAN_ENGINE = _settings.get("BAYESIAN_ENGINE", "PyMC_NUTS")
USE_NUTPIE = _settings.get("USE_NUTPIE", False)

# Email Directives
ADMIN_EMAIL = _settings.get("EMAILS", {}).get("ADMIN_EMAIL", "")

# Ensure data directory exists
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# System Versioning
CURRENT_MODEL_VERSION = "V2.0 - Rust Deep Learning SV Engine"
