import requests
import pandas as pd
import os
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent

RAW_DIR = PROJECT_ROOT / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

print(f">>> Project root: {PROJECT_ROOT}")
print(f">>> Saving CSVs to: {RAW_DIR}")

def fetch_nav(scheme_code, scheme_name, max_retries=3):
    """
    Fetch NAV from mfapi.in with automatic retry on timeout.
    Retries up to max_retries times before giving up.
    """
    url = f"https://api.mfapi.in/mf/{scheme_code}"

    for attempt in range(1, max_retries + 1):
        try:
            print(f"\n[Attempt {attempt}/{max_retries}] Fetching {scheme_name} (Code: {scheme_code})...")
            response = requests.get(url, timeout=15)
            response.raise_for_status()

            data = response.json()
            nav_list = data.get("data", [])

            if not nav_list:
                print(f"  WARNING: Empty data returned for {scheme_name}")
                return None

            print(f"  SUCCESS! Latest NAV: {nav_list[0]}")

            df = pd.DataFrame(nav_list)
            df["scheme_code"] = scheme_code
            df["scheme_name"] = scheme_name
            df["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            return df

        except requests.exceptions.Timeout:
            print(f"  TIMEOUT on attempt {attempt}")
            if attempt == max_retries:
                print(f"  ERROR: All {max_retries} retries failed for {scheme_name}")
                return None
            print(f"  Retrying...")

        except requests.exceptions.HTTPError as e:
            print(f"  HTTP ERROR: {e}")
            return None

        except Exception as e:
            print(f"  UNEXPECTED ERROR: {e}")
            return None

print("LIVE NAV FETCH — mfapi.in")

schemes = {
    125497: "HDFC Top 100 Direct",
    119551: "SBI Bluechip",
    120503: "ICICI Bluechip",
    118632: "Nippon Large Cap",
    119092: "Axis Bluechip",
    120841: "Kotak Bluechip",
}

all_data = []

for code, name in schemes.items():
    df = fetch_nav(code, name, max_retries=3)
    if df is not None:
        filename = f"nav_{code}_{name.replace(' ', '_').lower()}.csv"
        filepath = RAW_DIR / filename
        df.to_csv(filepath, index=False)
        print(f"  Saved: {filename}")
        all_data.append(df)

if all_data:
    combined = pd.concat(all_data, ignore_index=True)
    combined_path = RAW_DIR / "all_live_nav_combined.csv"
    combined.to_csv(combined_path, index=False)
    print(f"\n>>> Combined file saved: {combined_path}")
    print(f">>> Total rows fetched: {len(combined)}")
    print(f">>> Funds successfully fetched: {len(all_data)} / {len(schemes)}")
else:
    print("\n No data was fetched at all!")
