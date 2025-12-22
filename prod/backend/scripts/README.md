Quick scripts for local Parquet delta ingestion and EOD merge

1. eod_merge.py

Merge delta parquet files into processed partitioned parquet path:

python eod_merge.py --symbol AAPL --date 2025-12-05 --interval 1min

2. delta_writer.py

Write a CSV or Parquet file as a delta for today:

python delta_writer.py --symbol AAPL --interval 1min --infile /path/to/file.csv

---

## Trading ops (local execution)

These scripts interact with the configured execution broker.

1) close_all_trades_today.py

Emergency/manual flatten now: cancels open orders then closes all open positions.
Writes a detailed JSON audit under repo-root `logs/`.

Preview (no actions):

python scripts/close_all_trades_today.py --broker tradezero

Execute:

python scripts/close_all_trades_today.py --broker tradezero --yes

2) test_two_way_entries.py

Places two opposing stop-entry orders (LONG + SHORT) for a single symbol, each with
its own stop-loss. Intended to test entry placement + stop-loss wiring.

python scripts/test_two_way_entries.py --broker tradezero --symbol GIS --long-entry <p> --long-stop <p> --short-entry <p> --short-stop <p> --shares-long 1 --shares-short 1 --yes

3) test_one_way_entry.py

Places a single stop-entry (LONG or SHORT) for one symbol, with a protective stop-loss.
This is the simplest live test when you only care that the stop-loss wiring works.

python scripts/test_one_way_entry.py --broker tradezero --symbol GIS --side LONG --entry 48.98 --stop 48.92 --shares 1 --yes
