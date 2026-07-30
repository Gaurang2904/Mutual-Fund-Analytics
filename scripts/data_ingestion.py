import pandas as pd
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

csv_files = [
    "01_fund_master.csv",
    "02_nav_history.csv",
    "03_aum_by_fund_house.csv",
    "04_monthly_sip_inflows.csv",
    "05_category_inflows.csv",
    "06_industry_folio_count.csv",
    "07_scheme_performance.csv",
    "08_investor_transactions.csv",
    "09_portfolio_holdings.csv",
    "10_benchmark_indices.csv"
]

data = {}

print("DAY 1: DATA INGESTION")
for file in csv_files:
    filepath = RAW_DIR / file

    if not filepath.exists():
        print(f"\n--- {file} ---")
        print(f"WARNING: File not found at {filepath}")
        continue

    try:
        df = pd.read_csv(filepath)
        clean_name = file.replace(".csv", "").split("_", 1)[1] if "_" in file else file.replace(".csv", "")
        data[clean_name] = df

        print(f"\n--- {file} ---")
        print(f"Shape (rows, cols): {df.shape}")
        print(f"Columns: {list(df.columns)}")
        print(f"\nData Types:\n{df.dtypes}")
        print(f"\nFirst 5 rows:\n{df.head()}")
        print("-" * 50)

    except Exception as e:
        print(f"ERROR loading {file}: {e}")

print("ANOMALY CHECK")

for name, df in data.items():
    missing = df.isnull().sum().sum()
    dups = df.duplicated().sum()

    issues = []
    if missing > 0:
        issues.append(f"{missing} missing values")
    if dups > 0:
        issues.append(f"{dups} duplicate rows")
    if df.empty:
        issues.append("EMPTY DATAFRAME")

    if issues:
        print(f"{name}: {' | '.join(issues)}")
    else:
        print(f"{name}: OK (no issues)")

print("FUND MASTER EXPLORATION")

if "fund_master" in data:
    fm = data["fund_master"]

    print(f"\nTotal Funds in Master: {len(fm)}")
    print(f"Columns: {list(fm.columns)}")

    print(f"\n--- Unique Fund Houses ({fm['fund_house'].nunique()}) ---")
    print(fm["fund_house"].unique())

    print(f"\n--- Unique Categories ({fm['category'].nunique()}) ---")
    print(fm["category"].unique())

    print(f"\n--- Unique Sub-Categories ({fm['sub_category'].nunique()}) ---")
    print(fm["sub_category"].unique())

    print(f"\n--- Risk Category Distribution ---")
    print(fm["risk_category"].value_counts())

    print(f"\n--- AMFI Code Structure ---")
    print(f"Sample codes: {fm['amfi_code'].head(10).tolist()}")
    print(f"Code lengths: {fm['amfi_code'].astype(str).str.len().value_counts().to_dict()}")

    report_path = REPORTS_DIR / "fund_master_exploration.txt"
    with open(report_path, "w") as f:
        f.write("FUND MASTER EXPLORATION REPORT\n")
        f.write("=" * 40 + "\n\n")
        f.write(f"Total Funds: {len(fm)}\n\n")
        f.write(f"FUND HOUSES ({fm['fund_house'].nunique()}):\n")
        f.write(str(fm["fund_house"].value_counts()) + "\n\n")
        f.write(f"CATEGORIES ({fm['category'].nunique()}):\n")
        f.write(str(fm["category"].value_counts()) + "\n\n")
        f.write(f"SUB-CATEGORIES ({fm['sub_category'].nunique()}):\n")
        f.write(str(fm["sub_category"].value_counts()) + "\n\n")
        f.write(f"RISK CATEGORY DISTRIBUTION:\n")
        f.write(str(fm["risk_category"].value_counts()) + "\n\n")
        f.write(f"SEBI CATEGORY CODES:\n")
        f.write(str(fm["sebi_category_code"].value_counts()) + "\n")

    print(f"\nReport saved to: {report_path}")
else:
    print("fund_master not loaded")

print("DATA QUALITY: AMFI CODE VALIDATION")

if "fund_master" in data and "nav_history" in data:
    fm = data["fund_master"]
    nav = data["nav_history"]

    master_codes = set(fm["amfi_code"].dropna().astype(str).unique())
    nav_codes = set(nav["amfi_code"].dropna().astype(str).unique())

    print(f"\nCodes in fund_master: {len(master_codes)}")
    print(f"Codes in nav_history: {len(nav_codes)}")

    missing_in_nav = master_codes - nav_codes
    extra_in_nav = nav_codes - master_codes
    common = master_codes & nav_codes

    coverage_pct = (len(common) / len(master_codes)) * 100 if master_codes else 0

    print(f"\nCoverage: {len(common)} / {len(master_codes)} ({coverage_pct:.1f}%)")
    print(f"Missing in NAV history: {len(missing_in_nav)}")
    print(f"Extra in NAV history: {len(extra_in_nav)}")

    if missing_in_nav:
        print(f"Missing codes: {sorted(list(missing_in_nav))}")
    if extra_in_nav:
        print(f"Extra codes (first 10): {sorted(list(extra_in_nav))[:10]}")

    report_path = REPORTS_DIR / "data_quality_summary.txt"
    with open(report_path, "w") as f:
        f.write("DATA QUALITY SUMMARY — DAY 1\n")
        f.write("=" * 40 + "\n\n")
        f.write(f"Fund master codes: {len(master_codes)}\n")
        f.write(f"NAV history codes: {len(nav_codes)}\n")
        f.write(f"Coverage: {len(common)} / {len(master_codes)} ({coverage_pct:.1f}%)\n")
        f.write(f"Missing in NAV: {len(missing_in_nav)}\n")
        if missing_in_nav:
            f.write(f"Missing list: {sorted(list(missing_in_nav))}\n")
        f.write(f"Extra in NAV: {len(extra_in_nav)}\n")

    print(f"\nReport saved to: {report_path}")
else:
    print("Could not validate — fund_master or nav_history not loaded")
