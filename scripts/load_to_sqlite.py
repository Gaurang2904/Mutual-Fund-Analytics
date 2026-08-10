import pandas as pd
import os
from pathlib import Path
from sqlalchemy import create_engine, event, text

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
DB_PATH = PROJECT_ROOT / "bluestock_mf.db"
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"

FY_START_MONTH = 4  # Indian fiscal year runs April to March


def read_clean(name):
    return pd.read_csv(PROCESSED_DIR / name)


if not PROCESSED_DIR.is_dir() or not os.listdir(PROCESSED_DIR):
    raise SystemExit("ERROR: data/processed is empty - run scripts/data_cleaning.py first.")

if DB_PATH.exists():
    DB_PATH.unlink()
    print(f"removed existing {DB_PATH.name}")

engine = create_engine(f"sqlite:///{DB_PATH}")


# SQLite ignores foreign keys unless the pragma is set on each connection
@event.listens_for(engine, "connect")
def enable_foreign_keys(dbapi_conn, connection_record):
    dbapi_conn.execute("PRAGMA foreign_keys=ON")


print("\n--- creating schema ---")
with open(SCHEMA_PATH, encoding="utf-8") as f:
    ddl = f.read()

# executescript instead of splitting on ';' - the DDL has semicolons inside comments
raw_conn = engine.raw_connection()
try:
    raw_conn.cursor().executescript(ddl)
    raw_conn.commit()
finally:
    raw_conn.close()
print("schema applied from sql/schema.sql")


print("\n--- loading dimensions ---")
fund = read_clean("01_fund_master_clean.csv")
nav = read_clean("02_nav_history_clean.csv")
aum = read_clean("03_aum_by_fund_house_clean.csv")
sip = read_clean("04_monthly_sip_inflows_clean.csv")
cat = read_clean("05_category_inflows_clean.csv")
fol = read_clean("06_industry_folio_count_clean.csv")
perf = read_clean("07_scheme_performance_clean.csv")
txn = read_clean("08_investor_transactions_clean.csv")
hold = read_clean("09_portfolio_holdings_clean.csv")
bench = read_clean("10_benchmark_indices_clean.csv")

dim_fund = fund[[
    "amfi_code", "fund_house", "scheme_name", "category", "sub_category", "plan",
    "launch_date", "benchmark", "expense_ratio_pct", "exit_load_pct",
    "min_sip_amount", "min_lumpsum_amount", "fund_manager", "risk_category",
    "sebi_category_code", "expense_ratio_flag",
]]

# Every date referenced by any fact table, so no fact can point at a missing calendar row
all_dates = set(nav["date"]) | set(txn["transaction_date"]) | set(aum["date"])
all_dates |= set(sip["month_start"]) | set(cat["month_start"]) | set(fol["month_start"])
all_dates |= set(bench["date"]) | set(hold["portfolio_date"])

# Built as a dense daily calendar so month-end and quarter-end rows exist even on
# days when nothing traded
calendar = pd.date_range(min(pd.to_datetime(sorted(all_dates))),
                         max(pd.to_datetime(sorted(all_dates))), freq="D")
dim_date = pd.DataFrame({"date_key": calendar.strftime("%Y-%m-%d")})
dim_date["year"] = calendar.year
dim_date["quarter"] = calendar.quarter
dim_date["month"] = calendar.month
dim_date["month_name"] = calendar.strftime("%B")
dim_date["month_key"] = calendar.strftime("%Y-%m")
dim_date["day"] = calendar.day
dim_date["day_of_week"] = calendar.dayofweek
dim_date["day_name"] = calendar.strftime("%A")
dim_date["is_weekend"] = (calendar.dayofweek >= 5).astype(int)
dim_date["is_month_end"] = calendar.is_month_end.astype(int)
dim_date["is_quarter_end"] = calendar.is_quarter_end.astype(int)
fy_start = calendar.year.where(calendar.month >= FY_START_MONTH, calendar.year - 1)
dim_date["fiscal_year"] = [f"FY{y}-{str(y + 1)[2:]}" for y in fy_start]

dim_date.to_sql("dim_date", engine, if_exists="append", index=False)
print(f"  dim_date  {len(dim_date):,} rows  "
      f"({dim_date.date_key.min()} -> {dim_date.date_key.max()})")

dim_fund.to_sql("dim_fund", engine, if_exists="append", index=False)
print(f"  dim_fund  {len(dim_fund):,} rows")


print("\n--- loading facts ---")

f_nav = nav.rename(columns={"date": "date_key"})[
    ["amfi_code", "date_key", "nav", "daily_return", "return_anomaly_flag"]]

f_txn = txn.rename(columns={"transaction_date": "date_key"})[
    ["investor_id", "amfi_code", "date_key", "transaction_type", "amount_inr",
     "state", "city", "city_tier", "age_group", "gender", "annual_income_lakh",
     "payment_mode", "kyc_status"]]

f_perf = perf[[
    "amfi_code", "return_1yr_pct", "return_3yr_pct", "return_5yr_pct",
    "benchmark_3yr_pct", "excess_return_3yr_pct", "alpha", "beta", "sharpe_ratio",
    "sortino_ratio", "std_dev_ann_pct", "max_drawdown_pct", "aum_crore",
    "expense_ratio_pct", "morningstar_rating", "risk_grade", "anomaly_flags",
    "is_anomalous"]]

f_aum = aum.rename(columns={"date": "date_key"})[
    ["date_key", "fund_house", "aum_crore", "aum_lakh_crore", "num_schemes", "year"]]

f_sip = sip[["month_start", "month", "sip_inflow_crore", "active_sip_accounts_crore",
             "new_sip_accounts_lakh", "sip_aum_lakh_crore", "yoy_growth_pct"]]

f_cat = cat[["month_start", "month", "category", "net_inflow_crore", "flow_direction"]]

f_fol = fol[["month_start", "month", "total_folios_crore", "equity_folios_crore",
             "debt_folios_crore", "hybrid_folios_crore", "others_folios_crore",
             "total_folios_yoy_pct"]]

f_hold = hold[["amfi_code", "portfolio_date", "stock_symbol", "stock_name", "sector",
               "weight_pct", "market_value_cr", "current_price_inr"]]

f_bench = bench.rename(columns={"date": "date_key"})[
    ["date_key", "index_name", "close_value", "daily_return"]]

# append, not replace - if_exists="replace" would drop the table and let pandas
# recreate it from dtypes, throwing away every FK, CHECK and index in schema.sql
facts = [
    ("fact_nav", f_nav), ("fact_transactions", f_txn), ("fact_performance", f_perf),
    ("fact_aum", f_aum), ("fact_sip_inflows", f_sip),
    ("fact_category_inflows", f_cat), ("fact_folio_count", f_fol),
    ("fact_holdings", f_hold), ("fact_benchmark", f_bench),
]
for table, df in facts:
    df.to_sql(table, engine, if_exists="append", index=False, chunksize=5000)
    print(f"  {table:<24}{len(df):>8,} rows")


print("\n--- verification: SQLite row count vs source CSV ---")
expected = {
    "dim_fund": len(fund), "fact_nav": len(nav), "fact_transactions": len(txn),
    "fact_performance": len(perf), "fact_aum": len(aum), "fact_sip_inflows": len(sip),
    "fact_category_inflows": len(cat), "fact_folio_count": len(fol),
    "fact_holdings": len(hold), "fact_benchmark": len(bench),
}
all_match = True
print(f"  {'table':<26}{'csv':>10}{'sqlite':>10}   status")
with engine.connect() as conn:
    for table, exp in expected.items():
        got = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
        all_match &= got == exp
        print(f"  {table:<26}{exp:>10,}{got:>10,}   {'MATCH' if got == exp else 'MISMATCH'}")

    orphan_nav = conn.execute(text(
        "SELECT COUNT(*) FROM fact_nav n "
        "LEFT JOIN dim_fund f ON f.amfi_code = n.amfi_code WHERE f.amfi_code IS NULL"
    )).scalar_one()
    orphan_txn = conn.execute(text(
        "SELECT COUNT(*) FROM fact_transactions t "
        "LEFT JOIN dim_date d ON d.date_key = t.date_key WHERE d.date_key IS NULL"
    )).scalar_one()
    print(f"\n  orphan fact_nav -> dim_fund      : {orphan_nav}")
    print(f"  orphan fact_transactions -> date : {orphan_txn}")
    all_match &= orphan_nav == 0 and orphan_txn == 0

    tables = conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")).scalars().all()
    views = conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")).scalars().all()

size_mb = DB_PATH.stat().st_size / 1024 / 1024
print(f"\n  tables ({len(tables)}): {', '.join(tables)}")
print(f"  views  ({len(views)}): {', '.join(views)}")
print(f"\nbluestock_mf.db written ({size_mb:.1f} MB)")
print("RESULT:", "all row counts match" if all_match else "MISMATCH - investigate above")
