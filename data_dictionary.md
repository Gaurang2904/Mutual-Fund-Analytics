# Data Dictionary - Bluestock Mutual Fund Analytics

Reference for every dataset, table and column in the project. Covers the raw extracts
(`data/raw/`), the cleaned outputs (`data/processed/`) and the SQLite warehouse
(`bluestock_mf.db`).

| | |
|---|---|
| **Database** | `bluestock_mf.db` (SQLite 3, 11.7 MB) |
| **Schema** | [`sql/schema.sql`](sql/schema.sql) - star schema, 11 tables + 2 views |
| **Queries** | [`sql/queries.sql`](sql/queries.sql) - 10 required + 2 bonus |
| **Cleaning** | [`scripts/data_cleaning.py`](scripts/data_cleaning.py) -> [`reports/cleaning_report.txt`](reports/cleaning_report.txt) |
| **Load** | [`scripts/load_to_sqlite.py`](scripts/load_to_sqlite.py) |
| **Coverage** | NAV & benchmarks 2022-01-03 -> 2026-05-29 | transactions 2024-01-01 -> 2025-05-30 | industry aggregates 2022-01 -> 2025-12 |

---

## Conventions

| Convention | Definition |
|---|---|
| **amfi_code** | AMFI's scheme identifier. Used as the primary key because it is stable, unique and present in every extract, so no surrogate key was needed. |
| **date_key** | ISO-8601 `YYYY-MM-DD` stored as `TEXT`. SQLite has no native `DATE`; this format sorts and compares correctly as text. |
| **month_key** | `YYYY-MM`, the monthly rollup grain. |
| **Crore / Lakh crore** | 1 crore = 10,000,000 (1e7). 1 lakh crore = 1e12. Transaction amounts are in **rupees**; industry aggregates are in **crore**. Divide transaction sums by 1e7 before comparing. |
| **Fiscal year** | Indian FY, April-March. `FY2024-25` = 2024-04-01 -> 2025-03-31. |
| **pp** | Percentage points (difference between two percentages), as opposed to `%`. |
| **Returns** | Stored as percentages (`12.42` = 12.42%), except `daily_return`, which is a decimal fraction (`0.0124` = 1.24%). |

---

## Source lineage

| # | Raw file | Cleaned file | Table | Rows | Grain |
|---|---|---|---|---|---|
| 1 | `01_fund_master.csv` | `01_fund_master_clean.csv` | `dim_fund` | 40 | scheme |
| 2 | `02_nav_history.csv` | `02_nav_history_clean.csv` | `fact_nav` | 46,000 | scheme x business day |
| 3 | `03_aum_by_fund_house.csv` | `03_aum_by_fund_house_clean.csv` | `fact_aum` | 90 | fund house x reporting date |
| 4 | `04_monthly_sip_inflows.csv` | `04_monthly_sip_inflows_clean.csv` | `fact_sip_inflows` | 48 | month (industry-wide) |
| 5 | `05_category_inflows.csv` | `05_category_inflows_clean.csv` | `fact_category_inflows` | 144 | month x category |
| 6 | `06_industry_folio_count.csv` | `06_industry_folio_count_clean.csv` | `fact_folio_count` | 21 | reporting month |
| 7 | `07_scheme_performance.csv` | `07_scheme_performance_clean.csv` | `fact_performance` | 40 | scheme (snapshot) |
| 8 | `08_investor_transactions.csv` | `08_investor_transactions_clean.csv` | `fact_transactions` | 32,778 | transaction |
| 9 | `09_portfolio_holdings.csv` | `09_portfolio_holdings_clean.csv` | `fact_holdings` | 322 | scheme x stock x date |
| 10 | `10_benchmark_indices.csv` | `10_benchmark_indices_clean.csv` | `fact_benchmark` | 8,050 | index x business day |
| - | *generated* | - | `dim_date` | 1,610 | calendar day |

Row counts are identical raw -> cleaned -> SQLite; nothing was dropped. Verified by
`scripts/load_to_sqlite.py`.

---

## Dimensions

### `dim_fund` - scheme master

| Column | Type | Definition |
|---|---|---|
| `amfi_code` | INTEGER **PK** | AMFI scheme code. |
| `fund_house` | TEXT | Asset management company. 10 distinct. |
| `scheme_name` | TEXT | Full scheme name including plan and option. |
| `category` | TEXT | Top-level asset class: `Equity` or `Debt`. |
| `sub_category` | TEXT | SEBI sub-category - Large Cap, Mid Cap, Small Cap, Flexi Cap, ELSS, Liquid, Gilt, etc. (12 distinct). |
| `plan` | TEXT | `Regular` (distributor commission built into TER) or `Direct` (no commission). |
| `launch_date` | TEXT | Scheme inception date. Predates the NAV window for all 40 schemes. |
| `benchmark` | TEXT | Declared benchmark index, e.g. `NIFTY 100 TRI`. |
| `expense_ratio_pct` | REAL | Total Expense Ratio, % of AUM per year. Observed range 0.55-1.64. |
| `exit_load_pct` | REAL | Charge on early redemption, % of redeemed value. |
| `min_sip_amount` | INTEGER | Minimum SIP instalment, Rs . |
| `min_lumpsum_amount` | INTEGER | Minimum one-time investment, Rs . |
| `fund_manager` | TEXT | Primary fund manager. |
| `risk_category` | TEXT | Riskometer band: Low -> Very High. |
| `sebi_category_code` | TEXT | SEBI scheme classification code, e.g. `EC01`. |
| `expense_ratio_flag` | TEXT | `OK` / `OUT_OF_BAND` - set by cleaning against the 0.1-2.5% band. All 40 are `OK`. |

### `dim_date` - calendar

Dense daily calendar spanning 2022-01-01 -> 2026-05-29, generated rather than sourced.
Built dense so period-end joins always find a row even when no scheme traded that day.

| Column | Type | Definition |
|---|---|---|
| `date_key` | TEXT **PK** | `YYYY-MM-DD`. |
| `year`, `quarter`, `month`, `day` | INTEGER | Calendar parts. |
| `month_name`, `day_name` | TEXT | `January`, `Monday`. |
| `month_key` | TEXT | `YYYY-MM` rollup key. |
| `day_of_week` | INTEGER | 0 = Monday ... 6 = Sunday. |
| `is_weekend` | INTEGER | 1 if Saturday/Sunday. |
| `is_month_end`, `is_quarter_end` | INTEGER | Period-end flags. |
| `fiscal_year` | TEXT | Indian FY label, e.g. `FY2024-25`. |

---

## Fact tables

### `fact_nav` - daily NAV

| Column | Type | Definition |
|---|---|---|
| `nav_id` | INTEGER **PK** | Surrogate, autoincrement. |
| `amfi_code` | INTEGER **FK** -> `dim_fund` | Scheme. |
| `date_key` | TEXT **FK** -> `dim_date` | Business day. |
| `nav` | REAL | Net Asset Value per unit, Rs . Enforced `> 0`. |
| `daily_return` | REAL | `nav_t / nav_{t-1} - 1`, decimal fraction. NULL on each scheme's first day. |
| `return_anomaly_flag` | TEXT | `ANOMALY` if \|daily_return\| > 25%, else `OK`. None triggered. |

**Unique key:** (`amfi_code`, `date_key`).
**Coverage:** 1,150 business days x 40 schemes, no gaps.

### `fact_transactions` - investor transactions

Investor attributes are held on the fact as degenerate dimensions rather than split into
a `dim_investor`: the source carries them per transaction with no history, so a separate
table would be a 1:1 join adding a hop and no information.

| Column | Type | Definition |
|---|---|---|
| `transaction_id` | INTEGER **PK** | Surrogate, autoincrement. |
| `investor_id` | TEXT | Pseudonymous investor ID, e.g. `INV003054`. 5,000 distinct. |
| `amfi_code` | INTEGER **FK** -> `dim_fund` | Scheme transacted. |
| `date_key` | TEXT **FK** -> `dim_date` | Transaction date. |
| `transaction_type` | TEXT | `SIP` \| `Lumpsum` \| `Redemption`. CHECK-constrained. |
| `amount_inr` | REAL | Transaction value in **rupees**. Enforced `> 0`. |
| `state` | TEXT | Indian state. 12 distinct. |
| `city` | TEXT | City. 24 distinct. |
| `city_tier` | TEXT | `T30` (top 30 cities) \| `B30` (beyond top 30). B30 attracts SEBI incentives. |
| `age_group` | TEXT | `18-25`, `26-35`, `36-45`, `46-55`, `56+`. |
| `gender` | TEXT | `Male` \| `Female`. |
| `annual_income_lakh` | REAL | Self-declared annual income, Rs lakh. |
| `payment_mode` | TEXT | `UPI`, `Mandate`, `Net Banking`, `Cheque`. |
| `kyc_status` | TEXT | `Verified` \| `Pending`. |

**Mix:** SIP 19,716 | Lumpsum 8,095 | Redemption 4,967.

### `fact_performance` - vendor performance snapshot

**Point-in-time snapshot, not a time series** - the source has no date column, so nothing
should treat it as one. Independently computed equivalents live in
`reports/fund_scorecard.csv` and `reports/alpha_beta.csv`.

| Column | Type | Definition |
|---|---|---|
| `amfi_code` | INTEGER **PK/FK** | Scheme. |
| `return_1yr_pct`, `return_3yr_pct`, `return_5yr_pct` | REAL | Trailing annualised returns, %. |
| `benchmark_3yr_pct` | REAL | Benchmark's 3-year return, %. |
| `excess_return_3yr_pct` | REAL | *Derived:* `return_3yr_pct - benchmark_3yr_pct`, pp. |
| `alpha` | REAL | Excess return vs benchmark after adjusting for beta. |
| `beta` | REAL | Sensitivity to benchmark. 1.0 = moves with the market. |
| `sharpe_ratio` | REAL | Excess return per unit of **total** volatility. |
| `sortino_ratio` | REAL | Excess return per unit of **downside** volatility. |
| `std_dev_ann_pct` | REAL | Annualised standard deviation of returns, %. |
| `max_drawdown_pct` | REAL | Worst peak-to-trough decline, % (negative). |
| `aum_crore` | REAL | Scheme AUM, Rs crore. |
| `expense_ratio_pct` | REAL | TER, %. Mirrors `dim_fund`. |
| `morningstar_rating` | INTEGER | 1-5 stars. |
| `risk_grade` | TEXT | Risk band. |
| `anomaly_flags` | TEXT | `;`-joined flag names, or `NONE`. |
| `is_anomalous` | INTEGER | 1 if any flag fired. **3 of 40 rows** (Sharpe > 5). |

### `fact_aum` - AUM by fund house

Grain is the **fund house**, not the scheme - the source aggregates above scheme level,
so this table cannot join to `dim_fund`.

| Column | Type | Definition |
|---|---|---|
| `aum_id` | INTEGER **PK** | Surrogate. |
| `date_key` | TEXT **FK** -> `dim_date` | Reporting date. 9 dates, roughly half-yearly. |
| `fund_house` | TEXT | AMC name. |
| `aum_crore` | REAL | Assets under management, Rs crore. |
| `aum_lakh_crore` | REAL | Same measure in Rs lakh crore. Reconciled during cleaning (0 mismatches). |
| `num_schemes` | INTEGER | Schemes operated by the house. |
| `year` | INTEGER | *Derived* from `date_key`. |

### `fact_sip_inflows` - monthly SIP flows (industry-wide)

| Column | Type | Definition |
|---|---|---|
| `month_start` | TEXT **PK/FK** | First day of month. |
| `month` | TEXT | `YYYY-MM`. |
| `sip_inflow_crore` | REAL | Total industry SIP contribution that month, Rs crore. |
| `active_sip_accounts_crore` | REAL | Live SIP accounts, crore. |
| `new_sip_accounts_lakh` | REAL | SIPs registered that month, lakh. |
| `sip_aum_lakh_crore` | REAL | AUM attributable to SIPs, Rs lakh crore. |
| `yoy_growth_pct` | REAL | *Recomputed* as 12-month % change. NULL for the first 12 months - no prior-year base exists, so a value there would be fabricated. |

**Peak:** 2025-12 at Rs 31,002 crore.

### `fact_category_inflows` - net flows by category

| Column | Type | Definition |
|---|---|---|
| `month_start` | TEXT **PK/FK** | Month. |
| `month` | TEXT | `YYYY-MM`. |
| `category` | TEXT **PK** | Scheme category. 12 distinct. |
| `net_inflow_crore` | REAL | **Signed** net flow. Negative = net redemptions, which is information, not an error. |
| `flow_direction` | TEXT | `Inflow` / `Outflow` label for charting. |

**Coverage:** 12 months only (2024-04 -> 2025-03) - narrower than the other industry series.

### `fact_folio_count` - industry folio counts

| Column | Type | Definition |
|---|---|---|
| `month_start` | TEXT **PK/FK** | Reporting month. |
| `month` | TEXT | `YYYY-MM`. |
| `total_folios_crore` | REAL | Total investor accounts, crore. |
| `equity_folios_crore`, `debt_folios_crore`, `hybrid_folios_crore`, `others_folios_crore` | REAL | Segment split. Reconciles to total within 0.001 crore. |
| `total_folios_yoy_pct` | REAL | *Derived* 4-period change. |

**Cadence is irregular** - 21 observations across 2022-01 -> 2025-12, not evenly monthly.
Charts must not assume even spacing.

### `fact_holdings` - disclosed equity holdings

| Column | Type | Definition |
|---|---|---|
| `holding_id` | INTEGER **PK** | Surrogate. |
| `amfi_code` | INTEGER **FK** -> `dim_fund` | Scheme. **34 of 40** schemes disclose holdings. |
| `portfolio_date` | TEXT | Single snapshot: 2025-12-31. |
| `stock_symbol`, `stock_name` | TEXT | Holding identity. 30 distinct stocks. |
| `sector` | TEXT | Sector classification. 14 distinct. |
| `weight_pct` | REAL | Share of the **disclosed** portfolio, %. Sums to 100 +/- 0.02 per fund. |
| `market_value_cr` | REAL | Position value, Rs crore. |
| `current_price_inr` | REAL | Share price at `portfolio_date`, Rs . |

### `fact_benchmark` - daily index closes

| Column | Type | Definition |
|---|---|---|
| `benchmark_id` | INTEGER **PK** | Surrogate. |
| `date_key` | TEXT **FK** -> `dim_date` | Business day. |
| `index_name` | TEXT | `NIFTY50`, `NIFTY100`, `NIFTY500`, `NIFTY_MIDCAP150`, `BSE_SMALLCAP`, `CRISIL_GILT`, `CRISIL_LIQUID`. |
| `close_value` | REAL | Index close. |
| `daily_return` | REAL | Decimal fraction. NULL on first day per index. |

---

## Views

| View | Purpose |
|---|---|
| `v_nav_enriched` | `fact_nav` + scheme attributes + calendar parts. Removes the two joins repeated in nearly every NAV query. |
| `v_transactions_enriched` | `fact_transactions` + scheme attributes + calendar parts. |

---

## Cleaning rules applied

| Rule | Applied to | Result |
|---|---|---|
| Parse dates to datetime | all dated tables | 0 unparseable |
| Sort by `amfi_code` + `date` | NAV | applied |
| Reindex to business-day calendar, forward-fill NAV | NAV | 0 gaps found (grid already dense) |
| Drop leading rows with no prior NAV | NAV | 0 - no scheme starts mid-window |
| Remove duplicates on business key | all tables | 0 found |
| Validate `nav > 0` | NAV | 0 violations |
| Validate `amount_inr > 0` | transactions | 0 violations |
| Standardise `transaction_type` | transactions | 0 rewritten - already canonical |
| Validate KYC enum | transactions | 0 invalid |
| Coerce performance columns to numeric | performance | 0 coercion failures |
| Expense ratio within 0.1-2.5% | fund master, performance | 0 out of band |
| Referential integrity to `dim_fund` | NAV, transactions, holdings, performance | 0 orphans |

The raw extracts turned out to be already clean, so every counter above reads zero. The
checks are still kept, because the pipeline gets re-run whenever the upstream extract is
refreshed and a check that is deleted once it passes will not catch the next problem.

---

## Known data caveats

These come from the source data, not from the cleaning step. Each one limits what can be
concluded from the analysis.

1. **NAV history spans 4.4 years** (2022-01-03 -> 2026-05-29), so a true **5-year CAGR is
   not computable**. `Performance_Analytics.ipynb` computes 1-year and 3-year CAGR from
   NAV and reports the 5-year figure only from the vendor's `return_5yr_pct`, labelled as
   such. Any 5-year number derived from this NAV series would be an extrapolation.

2. **Vendor `max_drawdown_pct` disagrees with the NAV series.** Recomputing drawdown from
   `fact_nav` (query 9) gives materially different results - SBI Small Cap Direct is
   -52.6% computed vs -24.8% supplied; Axis Small Cap -51.7% vs -14.5%. The computed
   values are reproducible from the NAV data; the vendor column's basis is undocumented.
   Prefer the computed column and treat the vendor's as unverified.

3. **Three schemes carry implausible Sharpe ratios** (> 5, max 7.68). Flagged as
   `is_anomalous = 1`, retained rather than deleted, and excluded from query 6's ranking.

4. **Transactions cover 17 months** (2024-01 -> 2025-05), not the full 2022-2025 window.
   SIP time-series analysis should use `fact_sip_inflows` (48 months); transaction data
   supports demographic and geographic cuts, not long-run trend.

5. **Category inflows cover 12 months** (2024-04 -> 2025-03) - the heatmap is 12 x 12, not
   a four-year view.

6. **Folio counts are irregularly spaced** (21 observations over 48 months).

7. **Holdings cover 34 of 40 schemes** at a single date (2025-12-31), so sector allocation
   is a snapshot, not a trend, and excludes 6 schemes.

8. **`fact_aum` is house-level**, so scheme-level AUM (`fact_performance.aum_crore`) and
   house-level AUM are different measures and must not be summed together.

---

## Reproducing

```bash
python scripts/data_cleaning.py     # data/raw -> data/processed + cleaning_report.txt
python scripts/load_to_sqlite.py    # data/processed -> bluestock_mf.db (verifies counts)
python scripts/run_queries.py       # runs all 12 queries -> reports/query_results.txt
```

Then run `notebooks/EDA_Analysis.ipynb` and `notebooks/Performance_Analytics.ipynb`.
