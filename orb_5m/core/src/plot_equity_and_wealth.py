from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


def plot_equity_curve(daily_path: Path, output_image: Path) -> None:
    df = pd.read_csv(daily_path, parse_dates=["date"])
    if df.empty or "equity" not in df.columns:
        print(f"[WARN] Cannot plot equity curve, missing data in {daily_path}")
        return

    df = df.sort_values("date")

    plt.figure(figsize=(12, 6))
    plt.plot(df["date"], df["equity"], label="Equity", linewidth=1.5)
    plt.xlabel("Date")
    plt.ylabel("Equity")
    plt.title("ORB Portfolio Equity Curve")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    output_image.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_image, dpi=150)
    plt.close()
    print(f"[INFO] Saved equity curve image to {output_image}")


def compute_wealth_from_1000(daily_path: Path, output_csv: Path, yearly_summary_path: Path) -> None:
    df = pd.read_csv(daily_path, parse_dates=["date"])
    if df.empty or "equity" not in df.columns:
        print(f"[WARN] Cannot compute wealth, missing data in {daily_path}")
        return

    df = df.sort_values("date").reset_index(drop=True)
    start_eq = float(df["equity"].iloc[0])
    # wealth_1000 scales equity curve to start at 1000
    df["wealth_1000"] = 1000.0 * df["equity"] / start_eq

    # Save full path
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)
    print(f"[INFO] Saved wealth path (start 1000) to {output_csv}")

    # Per-year snapshot at last trading day of each year
    df["year"] = df["date"].dt.year
    year_ends = df.sort_values("date").groupby("year").tail(1)
    yearly = year_ends[["year", "date", "wealth_1000"]].rename(columns={"wealth_1000": "wealth_end_of_year"})

    # Overall final wealth
    overall_final = float(df["wealth_1000"].iloc[-1])

    # Save yearly summary CSV
    yearly.to_csv(yearly_summary_path, index=False)

    # Also append a human-readable text summary next to it
    summary_txt = yearly_summary_path.with_suffix(".txt")
    lines = ["Wealth path starting from 1000:"]
    for _, r in yearly.iterrows():
        lines.append(f"Year {int(r['year'])} (as of {r['date'].date()}): {r['wealth_end_of_year']:.2f}")
    lines.append("")
    lines.append(f"Final wealth at end of sample: {overall_final:.2f}")
    summary_txt.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[INFO] Saved yearly wealth summary to {yearly_summary_path} and {summary_txt}")


if __name__ == "__main__":
    base = Path("results_combined_top20")
    daily_csv = base / "all_daily_pnl.csv"
    img_path = base / "equity_curve.png"
    wealth_csv = base / "wealth_1000_path.csv"
    yearly_csv = base / "wealth_1000_yearly.csv"

    plot_equity_curve(daily_csv, img_path)
    compute_wealth_from_1000(daily_csv, wealth_csv, yearly_csv)
