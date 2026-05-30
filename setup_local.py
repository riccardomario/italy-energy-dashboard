"""
One-shot local setup. Run with:  py setup_local.py

Does two things:
  1. Installs the Python dependencies listed in requirements.txt
  2. Copies .streamlit/secrets.toml.example -> .streamlit/secrets.toml
     (only if the real secrets.toml does not already exist, so it never
     overwrites your filled-in credentials)
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
REQ = ROOT / "requirements.txt"
SECRETS_EXAMPLE = ROOT / ".streamlit" / "secrets.toml.example"
SECRETS_REAL = ROOT / ".streamlit" / "secrets.toml"


def install_requirements():
    print("\n[1/2] Installing Python dependencies from requirements.txt ...")
    if not REQ.exists():
        print(f"  ERROR: {REQ} not found.")
        sys.exit(1)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQ)],
    )
    if result.returncode != 0:
        print("  ERROR: pip install failed.")
        sys.exit(result.returncode)
    print("  OK.")


def copy_secrets_template():
    print("\n[2/2] Preparing .streamlit/secrets.toml ...")
    if not SECRETS_EXAMPLE.exists():
        print(f"  ERROR: template not found at {SECRETS_EXAMPLE}")
        sys.exit(1)
    if SECRETS_REAL.exists():
        print(f"  Skipped: {SECRETS_REAL} already exists (not overwriting).")
        return
    shutil.copy(SECRETS_EXAMPLE, SECRETS_REAL)
    print(f"  Created: {SECRETS_REAL}")
    print("  >>> Open it and replace the placeholder values with your real")
    print("      ENTSO-e API token and a dashboard password.")


if __name__ == "__main__":
    install_requirements()
    copy_secrets_template()
    print("\nSetup complete.")
