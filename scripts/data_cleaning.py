import pandas as pd
import numpy as np
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
REPORTS_DIR = PROJECT_ROOT / "reports"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

# Business rules
EXPENSE_RATIO_MIN = 0.1
EXPENSE_RATIO_MAX = 2.5
VALID_TXN_TYPES = {"SIP", "Lumpsum", "Redemption"}
VALID_KYC = {"Verified", "Pending"}
DAILY_RETURN_ANOMALY = 0.25

log_lines = []


def log(msg=""):
    print(msg)
    log_lines.append(msg)


def section(title):
    log()
    log("=" * 78)
    log(title)
    log("=" * 78)


def read_raw(name):
    return pd.read_csv(RAW_DIR / name)


def save(df, name):
    df.to_csv(PROCESSED_DIR / name, index=False)
    log(f"  -> data/processed/{name}  ({len(df):,} rows x {df.shape[1]} cols)")


def standardise_txn_type(value):
    """Map free-text transaction types onto SIP / Lumpsum / Redemption."""
    v = str(value).strip().lower().replace("-", " ").replace("_", " ")
    v = " ".join(v.split())
    if v in {"sip", "systematic investment plan", "systematic investment"}:
        return "SIP"
    if v in {"lumpsum", "lump sum", "purchase", "one time", "onetime", "additional purchase"}:
        return "Lumpsum"
    if v in {"redemption", "redeem", "redemptions", "swp", "withdrawal", "switch out"}:
        return "Redemption"
    return str(value).strip().title()


log("BLUESTOCK MUTUAL FUND ANALYTICS - DAY 2 CLEANING REPORT")
log(f"generated: {pd.Timestamp.now():%Y-%m-%d %H:%M:%S}")
log(f"pandas {pd.__version__} / numpy {np.__version__}")


# 1. FUND MASTER
section("01_fund_master.csv")
master = read_raw("01_fund_master.csv")
before = len(master)

master["launch_date"] = pd.to_datetime(master["launch_date"], errors="coerce")
log(f"  launch_date unparseable      : {int(master.launch_date.isna().sum())}")

dupes = int(master.duplicated(["amfi_code"]).sum())
master = master.drop_duplicates(["amfi_code"], keep="first")
log(f"  duplicate amfi_code removed  : {dupes}")

for col in ["fund_house", "scheme_name", "category", "sub_category", "plan",
            "benchmark", "fund_manager", "risk_category", "sebi_category_code"]:
    master[col] = master[col].astype(str).str.strip()

er = master["expense_ratio_pct"]
er_bad = (er < EXPENSE_RATIO_MIN) | (er > EXPENSE_RATIO_MAX)
master["expense_ratio_flag"] = np.where(er_bad, "OUT_OF_BAND", "OK")
log(f"  expense_ratio outside {EXPENSE_RATIO_MIN}-{EXPENSE_RATIO_MAX}%   : {int(er_bad.sum())}")
log(f"  rows {before} -> {len(master)}")

master["launch_date"] = master["launch_date"].dt.strftime("%Y-%m-%d")
save(master, "01_fund_master_clean.csv")

valid_codes = master["amfi_code"]


# 2. NAV HISTORY
section("02_nav_history.csv")
nav = read_raw("02_nav_history.csv")
before = len(nav)

nav["date"] = pd.to_datetime(nav["date"], errors="coerce")
bad_dates = int(nav.date.isna().sum())
nav = nav.dropna(subset=["date"])
log(f"  unparseable dates dropped    : {bad_dates}")

dupes = int(nav.duplicated(["amfi_code", "date"]).sum())
nav = nav.drop_duplicates(["amfi_code", "date"], keep="last")
log(f"  duplicate (amfi_code,date)   : {dupes}")

nonpos = int((nav["nav"] <= 0).sum())
nulls = int(nav["nav"].isna().sum())
nav.loc[nav["nav"] <= 0, "nav"] = np.nan
log(f"  NAV <= 0 nulled for fill     : {nonpos}")
log(f"  NAV already null             : {nulls}")

nav = nav.sort_values(["amfi_code", "date"]).reset_index(drop=True)

# Put every scheme on the same business-day calendar, then carry the last NAV
# forward over holidays and gaps. AMFI does not publish NAV on market holidays.
full_bdays = pd.bdate_range(nav["date"].min(), nav["date"].max())
log(f"  business-day calendar        : {len(full_bdays)} days "
    f"({full_bdays.min().date()} -> {full_bdays.max().date()})")

frames = []
gaps_filled = 0
for code, grp in nav.groupby("amfi_code", sort=True):
    g = grp.set_index("date").reindex(full_bdays)
    gaps_filled += int(g["nav"].isna().sum())
    g["nav"] = g["nav"].ffill()
    g["amfi_code"] = code
    g.index.name = "date"
    frames.append(g.reset_index())
nav = pd.concat(frames, ignore_index=True)
log(f"  NAV values forward-filled    : {gaps_filled}")

# A scheme launched after the window start has nothing to carry forward, so those
# leading rows are dropped rather than back-filled with invented history.
leading = int(nav["nav"].isna().sum())
nav = nav.dropna(subset=["nav"])
log(f"  leading rows w/o NAV dropped : {leading}")

nav = nav[nav["amfi_code"].isin(valid_codes)]
nav = nav.sort_values(["amfi_code", "date"]).reset_index(drop=True)

nav["daily_return"] = nav.groupby("amfi_code")["nav"].pct_change()
anomalies = nav["daily_return"].abs() > DAILY_RETURN_ANOMALY
nav["return_anomaly_flag"] = np.where(anomalies, "ANOMALY", "OK")
log(f"  |daily return| > {DAILY_RETURN_ANOMALY:.0%} flagged   : {int(anomalies.sum())}")

assert (nav["nav"] > 0).all(), "NAV <= 0 survived cleaning"
assert not nav.duplicated(["amfi_code", "date"]).any(), "duplicate keys survived"
log(f"  rows {before} -> {len(nav)}  | schemes: {nav.amfi_code.nunique()}")

out = nav.copy()
out["date"] = out["date"].dt.strftime("%Y-%m-%d")
save(out, "02_nav_history_clean.csv")


# 3. AUM BY FUND HOUSE
section("03_aum_by_fund_house.csv")
aum = read_raw("03_aum_by_fund_house.csv")
before = len(aum)

aum["date"] = pd.to_datetime(aum["date"], errors="coerce")
aum["fund_house"] = aum["fund_house"].astype(str).str.strip()
dupes = int(aum.duplicated(["date", "fund_house"]).sum())
aum = aum.drop_duplicates(["date", "fund_house"], keep="last")
log(f"  duplicate (date,fund_house)  : {dupes}")

nonpos = int((aum["aum_crore"] <= 0).sum())
aum = aum[aum["aum_crore"] > 0]
log(f"  non-positive AUM removed     : {nonpos}")

# aum_lakh_crore and aum_crore are the same measure in two units, so check they agree
implied = aum["aum_crore"] / 100000.0
mismatch = int((implied - aum["aum_lakh_crore"]).abs().gt(0.01).sum())
log(f"  unit mismatch lakh-cr vs cr  : {mismatch}")

aum["year"] = aum["date"].dt.year
aum = aum.sort_values(["date", "aum_crore"], ascending=[True, False]).reset_index(drop=True)
log(f"  rows {before} -> {len(aum)}  | houses: {aum.fund_house.nunique()}, dates: {aum.date.nunique()}")

out = aum.copy()
out["date"] = out["date"].dt.strftime("%Y-%m-%d")
save(out, "03_aum_by_fund_house_clean.csv")


# 4. MONTHLY SIP INFLOWS
section("04_monthly_sip_inflows.csv")
sip = read_raw("04_monthly_sip_inflows.csv")
before = len(sip)

sip["month_start"] = pd.to_datetime(sip["month"], format="%Y-%m", errors="coerce")
bad = int(sip.month_start.isna().sum())
sip = sip.dropna(subset=["month_start"]).drop_duplicates(["month"], keep="last")
log(f"  unparseable months           : {bad}")

nonpos = int((sip["sip_inflow_crore"] <= 0).sum())
sip = sip[sip["sip_inflow_crore"] > 0]
log(f"  non-positive inflow removed  : {nonpos}")

sip = sip.sort_values("month_start").reset_index(drop=True)

# Recompute YoY from the series instead of trusting the supplied column. The first
# 12 months stay null because there is no prior-year base to compare against.
recomputed = sip["sip_inflow_crore"].pct_change(12) * 100
supplied = sip["yoy_growth_pct"]
both = supplied.notna() & recomputed.notna()
max_gap = float((supplied[both] - recomputed[both]).abs().max()) if both.any() else 0.0
sip["yoy_growth_pct"] = recomputed.round(2)
log(f"  YoY nulls (first 12 months)  : {int(sip.yoy_growth_pct.isna().sum())}")
log(f"  max drift vs supplied YoY    : {max_gap:.2f} pp")

peak = sip.loc[sip["sip_inflow_crore"].idxmax()]
log(f"  peak inflow                  : {peak['month']} = Rs {peak['sip_inflow_crore']:,.0f} Cr")
log(f"  rows {before} -> {len(sip)}")

out = sip.copy()
out["month_start"] = out["month_start"].dt.strftime("%Y-%m-%d")
save(out, "04_monthly_sip_inflows_clean.csv")


# 5. CATEGORY INFLOWS
section("05_category_inflows.csv")
cat = read_raw("05_category_inflows.csv")
before = len(cat)

cat["month_start"] = pd.to_datetime(cat["month"], format="%Y-%m", errors="coerce")
cat["category"] = cat["category"].astype(str).str.strip()
dupes = int(cat.duplicated(["month", "category"]).sum())
cat = cat.drop_duplicates(["month", "category"], keep="last").dropna(subset=["month_start"])
log(f"  duplicate (month,category)   : {dupes}")

# Negative net inflow means the category saw net redemptions, so keep the sign
outflows = int((cat["net_inflow_crore"] < 0).sum())
cat["flow_direction"] = np.where(cat["net_inflow_crore"] < 0, "Outflow", "Inflow")
log(f"  net-outflow months (kept)    : {outflows}")

cat = cat.sort_values(["month_start", "category"]).reset_index(drop=True)
log(f"  coverage: {cat.month.nunique()} months x {cat.category.nunique()} categories")
log(f"  rows {before} -> {len(cat)}")

out = cat.copy()
out["month_start"] = out["month_start"].dt.strftime("%Y-%m-%d")
save(out, "05_category_inflows_clean.csv")


# 6. INDUSTRY FOLIO COUNT
section("06_industry_folio_count.csv")
folios = read_raw("06_industry_folio_count.csv")
before = len(folios)

folios["month_start"] = pd.to_datetime(folios["month"], format="%Y-%m", errors="coerce")
dupes = int(folios.duplicated(["month"]).sum())
folios = folios.drop_duplicates(["month"], keep="last").dropna(subset=["month_start"])
folios = folios.sort_values("month_start").reset_index(drop=True)
log(f"  duplicate months             : {dupes}")

# The four segment columns should add up to the reported total
parts = folios[["equity_folios_crore", "debt_folios_crore",
                "hybrid_folios_crore", "others_folios_crore"]].sum(axis=1)
drift = (parts - folios["total_folios_crore"]).abs()
log(f"  max segment-vs-total drift   : {drift.max():.3f} Cr")

folios["total_folios_yoy_pct"] = (folios["total_folios_crore"].pct_change(4) * 100).round(2)
log(f"  span: {folios.month.iloc[0]} ({folios.total_folios_crore.iloc[0]} Cr) -> "
    f"{folios.month.iloc[-1]} ({folios.total_folios_crore.iloc[-1]} Cr)")
log(f"  rows {before} -> {len(folios)}")

out = folios.copy()
out["month_start"] = out["month_start"].dt.strftime("%Y-%m-%d")
save(out, "06_industry_folio_count_clean.csv")


# 7. SCHEME PERFORMANCE
section("07_scheme_performance.csv")
perf = read_raw("07_scheme_performance.csv")
before = len(perf)

numeric_cols = ["return_1yr_pct", "return_3yr_pct", "return_5yr_pct", "benchmark_3yr_pct",
                "alpha", "beta", "sharpe_ratio", "sortino_ratio", "std_dev_ann_pct",
                "max_drawdown_pct", "aum_crore", "expense_ratio_pct", "morningstar_rating"]
coerce_failures = 0
for c in numeric_cols:
    pre = perf[c].notna().sum()
    perf[c] = pd.to_numeric(perf[c], errors="coerce")
    coerce_failures += int(pre - perf[c].notna().sum())
log(f"  non-numeric values coerced   : {coerce_failures}")

dupes = int(perf.duplicated(["amfi_code"]).sum())
perf = perf.drop_duplicates(["amfi_code"], keep="last")
log(f"  duplicate amfi_code          : {dupes}")

orphans = int((~perf["amfi_code"].isin(valid_codes)).sum())
perf = perf[perf["amfi_code"].isin(valid_codes)]
log(f"  codes absent from master     : {orphans}")

er = perf["expense_ratio_pct"]
er_bad = (er < EXPENSE_RATIO_MIN) | (er > EXPENSE_RATIO_MAX)
log(f"  expense_ratio outside {EXPENSE_RATIO_MIN}-{EXPENSE_RATIO_MAX}%   : {int(er_bad.sum())}")

# Flag anomalies instead of dropping them - a fund really can post a 60% year,
# and deleting the row would hide it from the analyst.
flags = pd.DataFrame(index=perf.index)
flags["expense_ratio_out_of_band"] = er_bad
flags["drawdown_not_negative"] = perf["max_drawdown_pct"] > 0
flags["beta_implausible"] = (perf["beta"] < 0) | (perf["beta"] > 2.5)
flags["return_1yr_extreme"] = perf["return_1yr_pct"].abs() > 100
flags["sharpe_extreme"] = perf["sharpe_ratio"].abs() > 5
flags["negative_aum"] = perf["aum_crore"] <= 0
for name, series in flags.items():
    log(f"    flag {name:<28}: {int(series.sum())}")

perf["anomaly_flags"] = flags.apply(
    lambda r: ";".join([c for c, v in r.items() if v]) or "NONE", axis=1
)
perf["is_anomalous"] = flags.any(axis=1).astype(int)
perf["excess_return_3yr_pct"] = (perf["return_3yr_pct"] - perf["benchmark_3yr_pct"]).round(2)
log(f"  rows flagged anomalous       : {int(perf.is_anomalous.sum())}")
log(f"  rows {before} -> {len(perf)}")

save(perf, "07_scheme_performance_clean.csv")


# 8. INVESTOR TRANSACTIONS
section("08_investor_transactions.csv")
txn = read_raw("08_investor_transactions.csv")
before = len(txn)

txn["transaction_date"] = pd.to_datetime(txn["transaction_date"], errors="coerce")
bad_dates = int(txn.transaction_date.isna().sum())
txn = txn.dropna(subset=["transaction_date"])
log(f"  unparseable dates dropped    : {bad_dates}")

raw_types = set(txn["transaction_type"].astype(str).str.strip().unique())
original_types = txn["transaction_type"].values.copy()
txn["transaction_type"] = txn["transaction_type"].map(standardise_txn_type)
changed = int((txn["transaction_type"].values != original_types).sum())
log(f"  raw transaction_type values  : {sorted(raw_types)}")
log(f"  values rewritten by mapping  : {changed}")

unknown = set(txn["transaction_type"].unique()) - VALID_TXN_TYPES
log(f"  unmapped transaction types   : {sorted(unknown) if unknown else 'none'}")
txn = txn[txn["transaction_type"].isin(VALID_TXN_TYPES)]

nonpos = int((txn["amount_inr"] <= 0).sum())
txn = txn[txn["amount_inr"] > 0]
log(f"  amount <= 0 removed          : {nonpos}")

txn["kyc_status"] = txn["kyc_status"].astype(str).str.strip().str.title()
bad_kyc = set(txn["kyc_status"].unique()) - VALID_KYC
log(f"  KYC values                   : {sorted(txn.kyc_status.unique())}")
log(f"  invalid KYC values           : {sorted(bad_kyc) if bad_kyc else 'none'}")
txn["kyc_status_valid"] = txn["kyc_status"].isin(VALID_KYC).astype(int)

for c in ["state", "city", "city_tier", "age_group", "gender", "payment_mode"]:
    txn[c] = txn[c].astype(str).str.strip()

dupes = int(txn.duplicated().sum())
txn = txn.drop_duplicates()
log(f"  exact duplicate rows removed : {dupes}")

orphans = int((~txn["amfi_code"].isin(valid_codes)).sum())
txn = txn[txn["amfi_code"].isin(valid_codes)]
log(f"  txns w/ unknown amfi_code    : {orphans}")

txn["month"] = txn["transaction_date"].dt.strftime("%Y-%m")
txn = txn.sort_values(["transaction_date", "investor_id"]).reset_index(drop=True)

log(f"  date range                   : {txn.transaction_date.min().date()} -> "
    f"{txn.transaction_date.max().date()}")
log(f"  mix                          : {txn.transaction_type.value_counts().to_dict()}")
log(f"  rows {before} -> {len(txn)}  | investors: {txn.investor_id.nunique():,}")

out = txn.copy()
out["transaction_date"] = out["transaction_date"].dt.strftime("%Y-%m-%d")
save(out, "08_investor_transactions_clean.csv")


# 9. PORTFOLIO HOLDINGS
section("09_portfolio_holdings.csv")
hold = read_raw("09_portfolio_holdings.csv")
before = len(hold)

hold["portfolio_date"] = pd.to_datetime(hold["portfolio_date"], errors="coerce")
for c in ["stock_symbol", "stock_name", "sector"]:
    hold[c] = hold[c].astype(str).str.strip()

dupes = int(hold.duplicated(["amfi_code", "stock_symbol", "portfolio_date"]).sum())
hold = hold.drop_duplicates(["amfi_code", "stock_symbol", "portfolio_date"], keep="last")
log(f"  duplicate (fund,stock,date)  : {dupes}")

bad_w = int(((hold["weight_pct"] <= 0) | (hold["weight_pct"] > 100)).sum())
hold = hold[(hold["weight_pct"] > 0) & (hold["weight_pct"] <= 100)]
log(f"  weight outside (0,100] rmvd  : {bad_w}")

orphans = int((~hold["amfi_code"].isin(valid_codes)).sum())
hold = hold[hold["amfi_code"].isin(valid_codes)]
log(f"  holdings w/ unknown amfi_code: {orphans}")

# Disclosed holdings are only part of the portfolio, so weights need not sum to 100
wsum = hold.groupby("amfi_code")["weight_pct"].sum()
log(f"  weight sum per fund          : min {wsum.min():.2f}%  max {wsum.max():.2f}%")
log(f"  funds with holdings          : {hold.amfi_code.nunique()} of {len(master)}")
log(f"  rows {before} -> {len(hold)}")

out = hold.copy()
out["portfolio_date"] = out["portfolio_date"].dt.strftime("%Y-%m-%d")
save(out, "09_portfolio_holdings_clean.csv")


# 10. BENCHMARK INDICES
section("10_benchmark_indices.csv")
bench = read_raw("10_benchmark_indices.csv")
before = len(bench)

bench["date"] = pd.to_datetime(bench["date"], errors="coerce")
bench["index_name"] = bench["index_name"].astype(str).str.strip().str.upper()
dupes = int(bench.duplicated(["date", "index_name"]).sum())
bench = bench.drop_duplicates(["date", "index_name"], keep="last").dropna(subset=["date"])
log(f"  duplicate (date,index)       : {dupes}")

nonpos = int((bench["close_value"] <= 0).sum())
bench.loc[bench["close_value"] <= 0, "close_value"] = np.nan
log(f"  close <= 0 nulled            : {nonpos}")

bench = bench.sort_values(["index_name", "date"])
bench["close_value"] = bench.groupby("index_name")["close_value"].ffill()
bench = bench.dropna(subset=["close_value"])
bench["daily_return"] = bench.groupby("index_name")["close_value"].pct_change()
log(f"  indices                      : {sorted(bench.index_name.unique())}")
log(f"  rows {before} -> {len(bench)}")

out = bench.copy().reset_index(drop=True)
out["date"] = out["date"].dt.strftime("%Y-%m-%d")
save(out, "10_benchmark_indices_clean.csv")


# SUMMARY
section("SUMMARY - raw vs cleaned row counts")
pairs = [
    ("01_fund_master", master), ("02_nav_history", nav), ("03_aum_by_fund_house", aum),
    ("04_monthly_sip_inflows", sip), ("05_category_inflows", cat),
    ("06_industry_folio_count", folios), ("07_scheme_performance", perf),
    ("08_investor_transactions", txn), ("09_portfolio_holdings", hold),
    ("10_benchmark_indices", bench),
]
log(f"  {'dataset':<28}{'raw':>10}{'clean':>10}{'delta':>10}")
for name, cleaned in pairs:
    raw_n = len(read_raw(f"{name}.csv"))
    log(f"  {name:<28}{raw_n:>10,}{len(cleaned):>10,}{len(cleaned) - raw_n:>+10,}")

log()
log("NOTE: 02_nav_history gains rows only if the business-day reindex found gaps;")
log("      it is unchanged here because the raw grid is already dense.")

report_path = REPORTS_DIR / "cleaning_report.txt"
with open(report_path, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines) + "\n")
print(f"\nreport written -> reports/cleaning_report.txt")
