"""Convert BTS On-Time Performance ZIP files (data/raw) into typed Parquet files (data/parquet)."""
import tempfile
import zipfile
from pathlib import Path

import duckdb

# Project root = the folder that contains src/ (this file lives in src/)
ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
PARQUET_DIR = ROOT / "data" / "parquet"


def num(column: str, dtype: str = "SMALLINT") -> str:
    """BTS writes numbers as text like '-7.00', so go text -> DOUBLE -> target type."""
    return f"CAST(CAST({column} AS DOUBLE) AS {dtype})"


SELECT_SQL = f"""
SELECT
    CAST(strptime(FL_DATE, '%m/%d/%Y %I:%M:%S %p') AS DATE) AS flight_date,
    OP_UNIQUE_CARRIER                    AS carrier,
    TAIL_NUM                             AS tail_number,
    {num('OP_CARRIER_FL_NUM', 'INTEGER')} AS flight_number,
    ORIGIN                               AS origin,
    DEST                                 AS dest,
    CRS_DEP_TIME                         AS crs_dep_hhmm,
    DEP_TIME                             AS dep_hhmm,
    {num('DEP_DELAY')}                   AS dep_delay,
    {num('TAXI_OUT')}                    AS taxi_out,
    WHEELS_OFF                           AS wheels_off_hhmm,
    WHEELS_ON                            AS wheels_on_hhmm,
    {num('TAXI_IN')}                     AS taxi_in,
    CRS_ARR_TIME                         AS crs_arr_hhmm,
    ARR_TIME                             AS arr_hhmm,
    {num('ARR_DELAY')}                   AS arr_delay,
    {num('CANCELLED', 'BOOLEAN')}        AS cancelled,
    CANCELLATION_CODE                    AS cancellation_code,
    {num('DIVERTED', 'BOOLEAN')}         AS diverted,
    {num('CRS_ELAPSED_TIME')}            AS crs_elapsed,
    {num('ACTUAL_ELAPSED_TIME')}         AS actual_elapsed,
    {num('AIR_TIME')}                    AS air_time,
    {num('DISTANCE')}                    AS distance,
    {num('CARRIER_DELAY')}               AS carrier_delay,
    {num('WEATHER_DELAY')}               AS weather_delay,
    {num('NAS_DELAY')}                   AS nas_delay,
    {num('SECURITY_DELAY')}              AS security_delay,
    {num('LATE_AIRCRAFT_DELAY')}         AS late_aircraft_delay
"""


def convert(zip_path: Path) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        # 1. Extract the CSV into a temporary folder (deleted automatically at the end)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        csv_path = next(Path(tmp).glob("*.csv"))

        # 2. Open an in-memory DuckDB and define a view over the CSV (nothing is loaded yet)
        con = duckdb.connect()
        con.execute(
            f"""
            CREATE VIEW flights AS
            {SELECT_SQL}
            FROM read_csv('{csv_path.as_posix()}', header = true, all_varchar = true, nullstr = '')
            """
        )

        # 3. Name the output file after the month contained in the data
        year, month = con.execute(
            "SELECT year(min(flight_date)), month(min(flight_date)) FROM flights"
        ).fetchone()
        out_path = PARQUET_DIR / f"ontime_{year}_{month:02d}.parquet"

        # 4. Write the Parquet file (ZSTD = good compression)
        con.execute(f"COPY flights TO '{out_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        n_rows = con.execute(f"SELECT count(*) FROM '{out_path.as_posix()}'").fetchone()[0]
        con.close()  # release the CSV before the temp folder is deleted (needed on Windows)

    zip_mb = zip_path.stat().st_size / 1e6
    parquet_mb = out_path.stat().st_size / 1e6
    print(f"{zip_path.name}: {n_rows:,} rows -> {out_path.name} ({zip_mb:.1f} MB zip -> {parquet_mb:.1f} MB parquet)")
    return out_path


def main() -> None:
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    zips = sorted(RAW_DIR.glob("*.zip"))
    if not zips:
        raise SystemExit(f"No ZIP files found in {RAW_DIR}")
    for zip_path in zips:
        convert(zip_path)


if __name__ == "__main__":
    main()