"""DEPRECATED.

This script derived Micro+Small+Unknown by combining pre-built universes.
That approach can drop candidates and break the "Top-50/day within category" semantics.

Use the canonical raw-scan builder instead:

    cd prod/backend
    python ORB/build_universe.py --start 2021-01-01 --end 2025-12-31 --workers 4 --categories micro_small_unknown
"""

def main() -> None:
    raise SystemExit(
        "ORB/build_micro_small_unknown_universe.py is deprecated. "
        "Use ORB/build_universe.py --categories micro_small_unknown instead."
    )


if __name__ == "__main__":
    main()
