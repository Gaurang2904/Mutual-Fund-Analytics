-- Bluestock Mutual Fund Analytics - SQLite star schema (Day 2)
-- Load with: python scripts/load_to_sqlite.py
--
-- Grain of each fact table:
--   fact_nav               one row per (scheme, business day)
--   fact_transactions      one row per investor transaction
--   fact_performance       one row per scheme (snapshot, not a time series)
--   fact_aum               one row per (fund house, reporting date)
--   fact_sip_inflows       one row per month, industry-wide
--   fact_category_inflows  one row per (month, scheme category), industry-wide
--   fact_folio_count       one row per reporting month, industry-wide
--   fact_holdings          one row per (scheme, stock, portfolio date)
--   fact_benchmark         one row per (index, business day)
--
-- dim_fund joins on amfi_code and dim_date joins on date_key. The industry-wide facts
-- (SIP, category, folio) have no scheme, so they only join to dim_date.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS fact_benchmark;
DROP TABLE IF EXISTS fact_holdings;
DROP TABLE IF EXISTS fact_folio_count;
DROP TABLE IF EXISTS fact_category_inflows;
DROP TABLE IF EXISTS fact_sip_inflows;
DROP TABLE IF EXISTS fact_aum;
DROP TABLE IF EXISTS fact_performance;
DROP TABLE IF EXISTS fact_transactions;
DROP TABLE IF EXISTS fact_nav;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_fund;


-- DIMENSIONS

-- amfi_code is AMFI's own scheme identifier and every extract carries it, so it is used
-- as the primary key instead of adding a surrogate key.
CREATE TABLE dim_fund (
    amfi_code           INTEGER PRIMARY KEY,
    fund_house          TEXT    NOT NULL,
    scheme_name         TEXT    NOT NULL,
    category            TEXT    NOT NULL,          -- Equity / Debt
    sub_category        TEXT,                      -- Large Cap, Small Cap, ELSS, ...
    plan                TEXT    NOT NULL CHECK (plan IN ('Regular', 'Direct')),
    launch_date         TEXT,                      -- ISO-8601 'YYYY-MM-DD'
    benchmark           TEXT,
    expense_ratio_pct   REAL    CHECK (expense_ratio_pct >= 0),
    exit_load_pct       REAL,
    min_sip_amount      INTEGER,
    min_lumpsum_amount  INTEGER,
    fund_manager        TEXT,
    risk_category       TEXT,
    sebi_category_code  TEXT,
    expense_ratio_flag  TEXT                       -- OK / OUT_OF_BAND, set by cleaning
);

CREATE INDEX idx_dim_fund_house    ON dim_fund (fund_house);
CREATE INDEX idx_dim_fund_category ON dim_fund (category, sub_category);
CREATE INDEX idx_dim_fund_plan     ON dim_fund (plan);


-- Built in Python over the full span of every fact table, so no fact can reference a
-- date that is missing here. date_key is the ISO date string: SQLite has no DATE type
-- and 'YYYY-MM-DD' sorts and compares correctly as TEXT.
CREATE TABLE dim_date (
    date_key        TEXT    PRIMARY KEY,           -- 'YYYY-MM-DD'
    year            INTEGER NOT NULL,
    quarter         INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month           INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    month_name      TEXT    NOT NULL,
    month_key       TEXT    NOT NULL,              -- 'YYYY-MM', the monthly rollup key
    day             INTEGER NOT NULL,
    day_of_week     INTEGER NOT NULL,              -- 0=Monday .. 6=Sunday
    day_name        TEXT    NOT NULL,
    is_weekend      INTEGER NOT NULL CHECK (is_weekend IN (0, 1)),
    is_month_end    INTEGER NOT NULL CHECK (is_month_end IN (0, 1)),
    is_quarter_end  INTEGER NOT NULL CHECK (is_quarter_end IN (0, 1)),
    fiscal_year     TEXT    NOT NULL               -- Indian FY, Apr-Mar, e.g. 'FY2024-25'
);

CREATE INDEX idx_dim_date_year  ON dim_date (year);
CREATE INDEX idx_dim_date_month ON dim_date (month_key);


-- FACTS

-- Daily NAV per scheme. daily_return is stored rather than recomputed on each read so
-- that the SQL queries and both notebooks use the same definition of a return.
CREATE TABLE fact_nav (
    nav_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    amfi_code       INTEGER NOT NULL,
    date_key        TEXT    NOT NULL,
    nav             REAL    NOT NULL CHECK (nav > 0),
    daily_return    REAL,                          -- null on each scheme's first day
    return_anomaly_flag TEXT,
    UNIQUE (amfi_code, date_key),
    FOREIGN KEY (amfi_code) REFERENCES dim_fund (amfi_code),
    FOREIGN KEY (date_key)  REFERENCES dim_date (date_key)
);

CREATE INDEX idx_fact_nav_fund ON fact_nav (amfi_code, date_key);
CREATE INDEX idx_fact_nav_date ON fact_nav (date_key);


-- Investor transactions. State, age group, gender and income stay on the fact table
-- instead of going into a dim_investor - the extract repeats them on every row with no
-- history, so a separate dimension would just be a 1:1 join.
CREATE TABLE fact_transactions (
    transaction_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    investor_id         TEXT    NOT NULL,
    amfi_code           INTEGER NOT NULL,
    date_key            TEXT    NOT NULL,
    transaction_type    TEXT    NOT NULL
                        CHECK (transaction_type IN ('SIP', 'Lumpsum', 'Redemption')),
    amount_inr          REAL    NOT NULL CHECK (amount_inr > 0),
    state               TEXT,
    city                TEXT,
    city_tier           TEXT    CHECK (city_tier IN ('T30', 'B30')),
    age_group           TEXT,
    gender              TEXT,
    annual_income_lakh  REAL,
    payment_mode        TEXT,
    kyc_status          TEXT    CHECK (kyc_status IN ('Verified', 'Pending')),
    FOREIGN KEY (amfi_code) REFERENCES dim_fund (amfi_code),
    FOREIGN KEY (date_key)  REFERENCES dim_date (date_key)
);

CREATE INDEX idx_fact_txn_fund  ON fact_transactions (amfi_code);
CREATE INDEX idx_fact_txn_date  ON fact_transactions (date_key);
CREATE INDEX idx_fact_txn_type  ON fact_transactions (transaction_type);
CREATE INDEX idx_fact_txn_state ON fact_transactions (state);


-- Vendor performance snapshot, one row per scheme. No date column because the source
-- has none, so this cannot be used as a time series. The versions computed from NAV are
-- in reports/fund_scorecard.csv.
CREATE TABLE fact_performance (
    amfi_code               INTEGER PRIMARY KEY,
    return_1yr_pct          REAL,
    return_3yr_pct          REAL,
    return_5yr_pct          REAL,
    benchmark_3yr_pct       REAL,
    excess_return_3yr_pct   REAL,                  -- fund 3yr minus benchmark 3yr
    alpha                   REAL,
    beta                    REAL,
    sharpe_ratio            REAL,
    sortino_ratio           REAL,
    std_dev_ann_pct         REAL,
    max_drawdown_pct        REAL CHECK (max_drawdown_pct <= 0),
    aum_crore               REAL CHECK (aum_crore >= 0),
    expense_ratio_pct       REAL,
    morningstar_rating      INTEGER CHECK (morningstar_rating BETWEEN 1 AND 5),
    risk_grade              TEXT,
    anomaly_flags           TEXT,                  -- ';'-joined flag names, or 'NONE'
    is_anomalous            INTEGER CHECK (is_anomalous IN (0, 1)),
    FOREIGN KEY (amfi_code) REFERENCES dim_fund (amfi_code)
);


-- AUM per fund house per reporting date. The source aggregates above scheme level,
-- so this cannot join to dim_fund.
CREATE TABLE fact_aum (
    aum_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date_key        TEXT    NOT NULL,
    fund_house      TEXT    NOT NULL,
    aum_crore       REAL    NOT NULL CHECK (aum_crore > 0),
    aum_lakh_crore  REAL    NOT NULL,
    num_schemes     INTEGER CHECK (num_schemes >= 0),
    year            INTEGER NOT NULL,
    UNIQUE (date_key, fund_house),
    FOREIGN KEY (date_key) REFERENCES dim_date (date_key)
);

CREATE INDEX idx_fact_aum_house ON fact_aum (fund_house);
CREATE INDEX idx_fact_aum_year  ON fact_aum (year);


-- Industry-wide monthly SIP flows. month_start is a real date so it joins to dim_date.
CREATE TABLE fact_sip_inflows (
    month_start                 TEXT    PRIMARY KEY,
    month                       TEXT    NOT NULL,      -- 'YYYY-MM'
    sip_inflow_crore            REAL    NOT NULL CHECK (sip_inflow_crore > 0),
    active_sip_accounts_crore   REAL,
    new_sip_accounts_lakh       REAL,
    sip_aum_lakh_crore          REAL,
    yoy_growth_pct              REAL,                  -- null for the first 12 months
    FOREIGN KEY (month_start) REFERENCES dim_date (date_key)
);


-- Industry-wide net flows by scheme category. net_inflow_crore is signed - negative
-- means the category had net redemptions that month.
CREATE TABLE fact_category_inflows (
    month_start         TEXT    NOT NULL,
    month               TEXT    NOT NULL,
    category            TEXT    NOT NULL,
    net_inflow_crore    REAL    NOT NULL,
    flow_direction      TEXT    CHECK (flow_direction IN ('Inflow', 'Outflow')),
    PRIMARY KEY (month_start, category),
    FOREIGN KEY (month_start) REFERENCES dim_date (date_key)
);


-- Industry folio counts. Only 21 observations across 2022-2025, at irregular intervals,
-- so charts over this must not assume even monthly spacing.
CREATE TABLE fact_folio_count (
    month_start             TEXT    PRIMARY KEY,
    month                   TEXT    NOT NULL,
    total_folios_crore      REAL    NOT NULL CHECK (total_folios_crore > 0),
    equity_folios_crore     REAL,
    debt_folios_crore       REAL,
    hybrid_folios_crore     REAL,
    others_folios_crore     REAL,
    total_folios_yoy_pct    REAL,
    FOREIGN KEY (month_start) REFERENCES dim_date (date_key)
);


-- Disclosed equity holdings per scheme at one portfolio date. weight_pct is a share of
-- the disclosed portfolio only, so it does not sum to exactly 100 per fund.
CREATE TABLE fact_holdings (
    holding_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    amfi_code           INTEGER NOT NULL,
    portfolio_date      TEXT    NOT NULL,
    stock_symbol        TEXT    NOT NULL,
    stock_name          TEXT,
    sector              TEXT,
    weight_pct          REAL    NOT NULL CHECK (weight_pct > 0 AND weight_pct <= 100),
    market_value_cr     REAL,
    current_price_inr   REAL,
    UNIQUE (amfi_code, stock_symbol, portfolio_date),
    FOREIGN KEY (amfi_code) REFERENCES dim_fund (amfi_code)
);

CREATE INDEX idx_fact_holdings_sector ON fact_holdings (sector);
CREATE INDEX idx_fact_holdings_fund   ON fact_holdings (amfi_code);


-- Daily benchmark index closes. Used as the market series for the alpha/beta regression
-- and for tracking error against the fund NAV series.
CREATE TABLE fact_benchmark (
    benchmark_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    date_key        TEXT    NOT NULL,
    index_name      TEXT    NOT NULL,
    close_value     REAL    NOT NULL CHECK (close_value > 0),
    daily_return    REAL,
    UNIQUE (date_key, index_name),
    FOREIGN KEY (date_key) REFERENCES dim_date (date_key)
);

CREATE INDEX idx_fact_benchmark_index ON fact_benchmark (index_name, date_key);


-- VIEWS
-- These just save repeating the same two joins in nearly every query.

DROP VIEW IF EXISTS v_nav_enriched;
CREATE VIEW v_nav_enriched AS
SELECT  n.amfi_code, n.date_key, n.nav, n.daily_return,
        d.year, d.month_key, d.quarter, d.fiscal_year,
        f.fund_house, f.scheme_name, f.category, f.sub_category, f.plan
FROM    fact_nav n
JOIN    dim_date d ON d.date_key  = n.date_key
JOIN    dim_fund f ON f.amfi_code = n.amfi_code;

DROP VIEW IF EXISTS v_transactions_enriched;
CREATE VIEW v_transactions_enriched AS
SELECT  t.*, d.year, d.month_key, d.quarter, d.fiscal_year,
        f.fund_house, f.scheme_name, f.category, f.sub_category, f.plan
FROM    fact_transactions t
JOIN    dim_date d ON d.date_key  = t.date_key
JOIN    dim_fund f ON f.amfi_code = t.amfi_code;
