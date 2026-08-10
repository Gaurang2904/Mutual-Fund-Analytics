import pandas as pd
import re
import sys
from pathlib import Path
from sqlalchemy import create_engine

SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
DB_PATH = PROJECT_ROOT / "bluestock_mf.db"
QUERIES_PATH = PROJECT_ROOT / "sql" / "queries.sql"
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)

# Usage: python scripts/run_queries.py        all queries, first 12 rows each
#        python scripts/run_queries.py 3 9    only queries 3 and 9, full output

if not DB_PATH.exists():
    raise SystemExit("ERROR: bluestock_mf.db not found - run scripts/load_to_sqlite.py first.")

wanted = {int(a) for a in sys.argv[1:] if a.isdigit()}
row_limit = None if wanted else 12
engine = create_engine(f"sqlite:///{DB_PATH}")

# Split queries.sql on the '-- @QUERY n | title' markers
with open(QUERIES_PATH, encoding="utf-8") as f:
    content = f.read()
parts = re.split(r"^--\s*@QUERY\s+(\d+)\s*\|\s*(.+)$", content, flags=re.MULTILINE)

queries = []
for i in range(1, len(parts), 3):
    num = int(parts[i])
    title = parts[i + 1].strip()
    block = parts[i + 2]
    if ";" not in block:
        continue
    # cut at the last semicolon so trailing comments don't end up in the statement
    queries.append((num, title, block[:block.rfind(";") + 1].strip()))

lines = []
failures = 0
for num, title, sql in queries:
    if wanted and num not in wanted:
        continue
    header = f"\n{'=' * 90}\nQUERY {num}  |  {title}\n{'=' * 90}"
    print(header)
    lines.append(header)
    try:
        df = pd.read_sql_query(sql, engine)
    except Exception as e:
        failures += 1
        msg = f"  FAILED: {type(e).__name__}: {e}"
        print(msg)
        lines.append(msg)
        continue
    shown = df if row_limit is None else df.head(row_limit)
    body = shown.to_string(index=False)
    if row_limit is not None and len(df) > row_limit:
        body += f"\n  ... {len(df) - row_limit} more rows (total {len(df)})"
    print(body)
    lines.append(body)

with open(REPORTS_DIR / "query_results.txt", "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

ran = len(wanted) if wanted else len(queries)
print(f"\n{'=' * 90}")
print(f"{ran - failures}/{ran} queries succeeded" + (f" - {failures} FAILED" if failures else ""))
print("results written -> reports/query_results.txt")
