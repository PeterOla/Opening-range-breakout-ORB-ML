from pathlib import Path
import random
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIVE_MIN_DIR = ROOT / "data" / "processed" / "5min"


def main() -> None:
    files = sorted(FIVE_MIN_DIR.glob("*.parquet"))
    print(f"Found {len(files)} 5m files in {FIVE_MIN_DIR}")

    if not files:
        print("No 5m parquet files found.")
        return

    sample_files = random.sample(files, k=min(5, len(files)))
    for path in sample_files:
        symbol = path.stem
        df = pd.read_parquet(path)

        print("\n=== Symbol:", symbol, "===")
        print("Rows:", len(df))
        print("Columns:", list(df.columns))
        print("Head:")
        print(df.head())
        print("Tail:")
        print(df.tail())


if __name__ == "__main__":
    main()
