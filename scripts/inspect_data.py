"""
Run this FIRST, before training. It just inspects your NIFTY50 file so we
know the real column names, dtypes, and whether it's raw OHLCV or already
has engineered indicators -- before we plug it into the training pipeline.

Usage (from ml_service/ directory, with venv active):
    python scripts/inspect_data.py data/raw/NIFTY50_Preprocessed.csv
"""
import sys
import pandas as pd

if len(sys.argv) < 2:
    print("Usage: python scripts/inspect_data.py <path_to_file>")
    sys.exit(1)

path = sys.argv[1]

if path.endswith(".csv"):
    df = pd.read_csv(path)
elif path.endswith((".xlsx", ".xls")):
    df = pd.read_excel(path)
else:
    raise ValueError("Expected a .csv or .xlsx file")

print("=" * 60)
print("SHAPE:", df.shape)
print("=" * 60)
print("COLUMNS:")
for c in df.columns:
    print(f"  - {c}  (dtype: {df[c].dtype})")
print("=" * 60)
print("FIRST 3 ROWS:")
print(df.head(3).to_string())
print("=" * 60)
print("LAST 3 ROWS:")
print(df.tail(3).to_string())
print("=" * 60)
print("NULL COUNTS (non-zero only):")
nulls = df.isnull().sum()
print(nulls[nulls > 0] if nulls.sum() > 0 else "  none")
print("=" * 60)
print("DUPLICATE COLUMN NAMES CHECK:")
dupes = df.columns[df.columns.duplicated()].tolist()
print(f"  {dupes if dupes else 'none found'}")