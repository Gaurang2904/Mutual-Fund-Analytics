-- Bluestock Mutual Fund Analytics - analytical queries (Day 2)
-- Run with: python scripts/run_queries.py
-- The runner splits this file on the '-- @QUERY n | title' markers.
--
-- Note: amounts in fact_transactions are in rupees, industry figures are in crore,
-- so transaction sums are divided by 1e7 when shown next to a crore figure.


-- @QUERY 1 | Top 5 funds by AUM
-- AUM here is scheme-level (from fact_performance), not house-level like fact_aum.
SELECT
    f.scheme_name,
    f.fund_house,
    f.category,
    f.plan,
    p.aum_crore,
    ROUND(p.aum_crore / 100000.0, 2)                        AS aum_lakh_crore,
    p.return_3yr_pct,
    p.expense_ratio_pct
FROM fact_performance p
JOIN dim_fund f ON f.amfi_code = p.amfi_code
ORDER BY p.aum_crore DESC
LIMIT 5;


-- @QUERY 2 | Average NAV per month, per scheme (2025)
-- Limited to 2025 and the 10 biggest schemes to keep the output readable.
-- Drop the WHERE clauses for the full 40 x 53-month grid.
SELECT
    f.scheme_name,
    d.month_key,
    ROUND(AVG(n.nav), 4)    AS avg_nav,
    ROUND(MIN(n.nav), 4)    AS min_nav,
    ROUND(MAX(n.nav), 4)    AS max_nav,
    COUNT(*)                AS trading_days
FROM fact_nav n
JOIN dim_date d ON d.date_key  = n.date_key
JOIN dim_fund f ON f.amfi_code = n.amfi_code
WHERE d.year = 2025
  AND n.amfi_code IN (SELECT amfi_code FROM fact_performance ORDER BY aum_crore DESC LIMIT 10)
GROUP BY f.scheme_name, d.month_key
ORDER BY f.scheme_name, d.month_key;


-- @QUERY 3 | SIP inflow year-on-year growth
-- Uses LAG over 12 months instead of the stored yoy_growth_pct column.
-- First 12 months are NULL because there is no prior-year base.
WITH sip AS (
    SELECT
        month,
        month_start,
        sip_inflow_crore,
        LAG(sip_inflow_crore, 12) OVER (ORDER BY month_start) AS inflow_prior_year
    FROM fact_sip_inflows
)
SELECT
    month,
    sip_inflow_crore,
    inflow_prior_year,
    ROUND(sip_inflow_crore - inflow_prior_year, 0)                              AS abs_growth_crore,
    ROUND(100.0 * (sip_inflow_crore - inflow_prior_year) / inflow_prior_year, 2) AS yoy_growth_pct
FROM sip
WHERE inflow_prior_year IS NOT NULL
ORDER BY month;


-- @QUERY 4 | Transactions by state
-- Volume, value and investor count per state, split by city tier.
-- B30 share is included because SEBI incentivises inflows from beyond the top 30 cities.
SELECT
    state,
    COUNT(*)                                                        AS txn_count,
    COUNT(DISTINCT investor_id)                                     AS investors,
    ROUND(SUM(amount_inr) / 10000000.0, 2)                          AS total_crore,
    ROUND(AVG(amount_inr), 0)                                       AS avg_txn_inr,
    SUM(CASE WHEN transaction_type = 'SIP' THEN 1 ELSE 0 END)       AS sip_txns,
    ROUND(100.0 * SUM(CASE WHEN city_tier = 'B30' THEN amount_inr ELSE 0 END)
          / SUM(amount_inr), 1)                                     AS b30_value_share_pct
FROM fact_transactions
GROUP BY state
ORDER BY total_crore DESC;


-- @QUERY 5 | Funds with expense ratio below 1%
-- Direct plans dominate here because they carry no distributor commission,
-- so the plan column is included.
SELECT
    f.scheme_name,
    f.fund_house,
    f.plan,
    f.sub_category,
    f.expense_ratio_pct,
    p.return_3yr_pct,
    p.sharpe_ratio,
    p.aum_crore
FROM dim_fund f
JOIN fact_performance p ON p.amfi_code = f.amfi_code
WHERE f.expense_ratio_pct < 1.0
ORDER BY f.expense_ratio_pct ASC;


-- @QUERY 6 | Risk-adjusted leaders: return per unit of risk, net of cost
-- Ranked on Sharpe, but benchmark excess, drawdown and expense ratio are shown too,
-- so a fund that scores well just by taking less risk is easy to spot.
SELECT
    f.scheme_name,
    f.fund_house,
    f.sub_category,
    p.sharpe_ratio,
    p.sortino_ratio,
    p.return_3yr_pct,
    p.benchmark_3yr_pct,
    p.excess_return_3yr_pct,
    p.max_drawdown_pct,
    p.expense_ratio_pct,
    ROUND(p.return_3yr_pct - p.expense_ratio_pct, 2) AS return_net_of_fee_pct,
    p.anomaly_flags
FROM fact_performance p
JOIN dim_fund f ON f.amfi_code = p.amfi_code
WHERE p.is_anomalous = 0            -- exclude the implausible-Sharpe rows flagged in cleaning
ORDER BY p.sharpe_ratio DESC
LIMIT 10;


-- @QUERY 7 | Monthly net investor flow (SIP + Lumpsum - Redemption)
-- The redemption ratio shows how much of each month's gross inflow went back out.
SELECT
    d.month_key,
    ROUND(SUM(CASE WHEN t.transaction_type = 'SIP'        THEN t.amount_inr ELSE 0 END) / 10000000.0, 2) AS sip_crore,
    ROUND(SUM(CASE WHEN t.transaction_type = 'Lumpsum'    THEN t.amount_inr ELSE 0 END) / 10000000.0, 2) AS lumpsum_crore,
    ROUND(SUM(CASE WHEN t.transaction_type = 'Redemption' THEN t.amount_inr ELSE 0 END) / 10000000.0, 2) AS redemption_crore,
    ROUND((SUM(CASE WHEN t.transaction_type IN ('SIP', 'Lumpsum') THEN t.amount_inr ELSE 0 END)
         - SUM(CASE WHEN t.transaction_type = 'Redemption'        THEN t.amount_inr ELSE 0 END)) / 10000000.0, 2) AS net_flow_crore,
    ROUND(100.0 * SUM(CASE WHEN t.transaction_type = 'Redemption' THEN t.amount_inr ELSE 0 END)
          / NULLIF(SUM(CASE WHEN t.transaction_type IN ('SIP', 'Lumpsum') THEN t.amount_inr ELSE 0 END), 0), 1) AS redemption_ratio_pct
FROM fact_transactions t
JOIN dim_date d ON d.date_key = t.date_key
GROUP BY d.month_key
ORDER BY d.month_key;


-- @QUERY 8 | Fund house AUM growth, first to latest reporting date
-- CAGR uses the actual elapsed days between the two snapshots, not a rounded year count.
WITH bounds AS (
    SELECT fund_house, MIN(date_key) AS first_date, MAX(date_key) AS last_date
    FROM fact_aum
    GROUP BY fund_house
)
SELECT
    b.fund_house,
    b.first_date,
    a1.aum_lakh_crore                                       AS aum_start_lakh_cr,
    b.last_date,
    a2.aum_lakh_crore                                       AS aum_end_lakh_cr,
    ROUND(a2.aum_lakh_crore - a1.aum_lakh_crore, 2)         AS growth_lakh_cr,
    ROUND(100.0 * (a2.aum_crore - a1.aum_crore) / a1.aum_crore, 1) AS total_growth_pct,
    ROUND(100.0 * (POWER(a2.aum_crore * 1.0 / a1.aum_crore,
          1.0 / ((JULIANDAY(b.last_date) - JULIANDAY(b.first_date)) / 365.25)) - 1), 2) AS cagr_pct,
    a2.num_schemes
FROM bounds b
JOIN fact_aum a1 ON a1.fund_house = b.fund_house AND a1.date_key = b.first_date
JOIN fact_aum a2 ON a2.fund_house = b.fund_house AND a2.date_key = b.last_date
ORDER BY a2.aum_crore DESC;


-- @QUERY 9 | Maximum drawdown per scheme, computed from daily NAV
-- Running MAX gives the peak to date, and the lowest NAV/peak - 1 is the worst
-- peak-to-trough loss. Computed from fact_nav so it can be checked against the
-- vendor's max_drawdown_pct column.
WITH running AS (
    SELECT
        amfi_code,
        date_key,
        nav,
        MAX(nav) OVER (PARTITION BY amfi_code ORDER BY date_key
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS peak_nav
    FROM fact_nav
),
dd AS (
    SELECT amfi_code, date_key, nav, peak_nav,
           (nav / peak_nav) - 1.0 AS drawdown
    FROM running
),
worst AS (
    SELECT amfi_code, MIN(drawdown) AS max_drawdown
    FROM dd
    GROUP BY amfi_code
)
SELECT
    f.scheme_name,
    f.fund_house,
    f.sub_category,
    ROUND(100.0 * w.max_drawdown, 2)    AS computed_max_dd_pct,
    p.max_drawdown_pct                  AS vendor_max_dd_pct,
    ROUND(100.0 * w.max_drawdown - p.max_drawdown_pct, 2) AS difference_pp,
    (SELECT MIN(date_key) FROM dd
     WHERE dd.amfi_code = w.amfi_code AND dd.drawdown = w.max_drawdown) AS trough_date
FROM worst w
JOIN dim_fund f        ON f.amfi_code = w.amfi_code
JOIN fact_performance p ON p.amfi_code = w.amfi_code
ORDER BY w.max_drawdown ASC
LIMIT 15;


-- @QUERY 10 | Direct vs Regular plan - what the commission costs the investor
-- The expense gap between the two plans of the same scheme is the distributor
-- commission. Shown next to the 3-year return gap.
WITH by_plan AS (
    SELECT
        f.fund_house,
        f.plan,
        COUNT(*)                        AS schemes,
        ROUND(AVG(f.expense_ratio_pct), 3) AS avg_expense_pct,
        ROUND(AVG(p.return_3yr_pct), 2)    AS avg_return_3yr_pct,
        ROUND(AVG(p.sharpe_ratio), 3)      AS avg_sharpe
    FROM dim_fund f
    JOIN fact_performance p ON p.amfi_code = f.amfi_code
    GROUP BY f.fund_house, f.plan
)
SELECT
    r.fund_house,
    r.schemes                                           AS regular_schemes,
    r.avg_expense_pct                                   AS regular_expense_pct,
    dr.avg_expense_pct                                  AS direct_expense_pct,
    ROUND(r.avg_expense_pct - dr.avg_expense_pct, 3)    AS expense_gap_pp,
    r.avg_return_3yr_pct                                AS regular_return_3yr,
    dr.avg_return_3yr_pct                               AS direct_return_3yr,
    ROUND(dr.avg_return_3yr_pct - r.avg_return_3yr_pct, 2) AS direct_advantage_pp
FROM by_plan r
JOIN by_plan dr ON dr.fund_house = r.fund_house AND dr.plan = 'Direct'
WHERE r.plan = 'Regular'
ORDER BY expense_gap_pp DESC;


-- Bonus queries - not part of the required ten. These back two of the EDA charts.

-- @QUERY 11 | Sector allocation across all equity funds
SELECT
    h.sector,
    COUNT(DISTINCT h.amfi_code)             AS funds_holding,
    COUNT(*)                                AS positions,
    ROUND(AVG(h.weight_pct), 2)             AS avg_weight_pct,
    ROUND(SUM(h.market_value_cr), 2)        AS total_market_value_cr,
    ROUND(100.0 * SUM(h.market_value_cr) / (SELECT SUM(market_value_cr) FROM fact_holdings), 2)
                                            AS share_of_total_pct
FROM fact_holdings h
JOIN dim_fund f ON f.amfi_code = h.amfi_code
WHERE f.category = 'Equity'
GROUP BY h.sector
ORDER BY total_market_value_cr DESC;


-- @QUERY 12 | SIP behaviour by investor age group and city tier
SELECT
    age_group,
    city_tier,
    COUNT(*)                                    AS sip_txns,
    COUNT(DISTINCT investor_id)                 AS investors,
    ROUND(AVG(amount_inr), 0)                   AS avg_sip_inr,
    ROUND(SUM(amount_inr) / 10000000.0, 2)      AS total_crore,
    ROUND(AVG(annual_income_lakh), 1)           AS avg_income_lakh,
    ROUND(100.0 * SUM(CASE WHEN kyc_status = 'Verified' THEN 1 ELSE 0 END) / COUNT(*), 1)
                                                AS kyc_verified_pct
FROM fact_transactions
WHERE transaction_type = 'SIP'
GROUP BY age_group, city_tier
ORDER BY age_group, city_tier;
