#!/usr/bin/env python3
"""Smoke test: loads local data, normalizes CSV, creates an in-memory SQLite DB,
and runs basic SQL queries to verify the local data path works.
Does NOT call AWS or Bedrock.
"""
import os
import sqlite3
import sys
import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
LIB_JSON = os.path.join(DATA_DIR, 's3_library_data.json')
CARS_CSV = os.path.join(DATA_DIR, 's3_cars_data.csv')
NORMALIZED_CARS_CSV = os.path.join(DATA_DIR, 's3_cars_data_normalized.csv')

# Word-to-integer map shared with scripts/normalize_cars.py
WORD_MAP = {
    'two': 2, 'three': 3, 'four': 4, 'five': 5,
    'six': 6, 'seven': 7, 'eight': 8, 'nine': 9,
    'ten': 10, 'twelve': 12,
}


def load_and_check_library() -> pd.DataFrame:
    print('Loading library data from', LIB_JSON)
    if not os.path.exists(LIB_JSON):
        raise FileNotFoundError(f'Library data file not found: {LIB_JSON}')
    df = pd.read_json(LIB_JSON, lines=True)
    df['pub_date'] = pd.to_datetime(df.get('pub_date'), errors='coerce')
    print(f'  Loaded {len(df)} library records.')
    print('  Sample rows:', df.head(2).to_dict(orient='records'))
    return df


def normalize_cars() -> pd.DataFrame:
    print('Normalizing cars CSV:', CARS_CSV)
    if not os.path.exists(CARS_CSV):
        raise FileNotFoundError(f'Cars CSV not found: {CARS_CSV}')
    df = pd.read_csv(CARS_CSV)

    doors_raw = df['doors'].astype(str).str.lower()
    cylinders_raw = df['cylinders'].astype(str).str.lower()
    df['doors'] = doors_raw.map(WORD_MAP).fillna(doors_raw)
    df['cylinders'] = cylinders_raw.map(WORD_MAP).fillna(cylinders_raw)

    numeric_cols = ['doors', 'curb_weight', 'cylinders', 'horsepower', 'mpg', 'price']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    rows_before = len(df)
    df = df.dropna(subset=['horsepower', 'price'])
    dropped = rows_before - len(df)
    if dropped:
        print(f'  Dropped {dropped} row(s) with missing horsepower or price.')

    df.to_csv(NORMALIZED_CARS_CSV, index=False)
    print(f'  Wrote {len(df)} rows to {NORMALIZED_CARS_CSV}')
    return df


def create_sqlite_and_query(cars_df: pd.DataFrame) -> dict:
    print('Creating in-memory SQLite DB and loading `cars` table...')
    conn = sqlite3.connect(':memory:')
    cars_df.to_sql('cars', conn, index=False, if_exists='replace')
    cur = conn.cursor()

    queries = [
        ('Total cars',                 'SELECT COUNT(*) FROM cars;'),
        ('Average price',              'SELECT ROUND(AVG(price), 2) FROM cars;'),
        ('Make with highest HP',       'SELECT make, MAX(horsepower) FROM cars;'),
    ]
    results = {}
    for name, sql in queries:
        cur.execute(sql)
        row = cur.fetchone()
        results[name] = row
        print(f'  {name}: {row}')

    conn.close()
    return results


def main() -> int:
    print('=' * 60)
    print('Smoke Test — Data Architecture with Generative AI')
    print('=' * 60)

    try:
        load_and_check_library()
    except Exception as exc:
        print(f'FAIL: Library data load — {exc}')
        return 2

    try:
        cars_df = normalize_cars()
    except Exception as exc:
        print(f'FAIL: Cars normalization — {exc}')
        return 3

    try:
        create_sqlite_and_query(cars_df)
    except Exception as exc:
        print(f'FAIL: SQLite smoke queries — {exc}')
        return 4

    print('\nSmoke test completed successfully.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
