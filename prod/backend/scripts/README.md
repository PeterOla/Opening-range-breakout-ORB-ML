Quick scripts for local Parquet delta ingestion and EOD merge

1. eod_merge.py

Merge delta parquet files into processed partitioned parquet path:

python eod_merge.py --symbol AAPL --date 2025-12-05 --interval 1min

2. delta_writer.py

Write a CSV or Parquet file as a delta for today:

python delta_writer.py --symbol AAPL --interval 1min --infile /path/to/file.csv
