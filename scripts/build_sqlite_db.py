from __future__ import annotations
import argparse, sqlite3, hashlib, json
from pathlib import Path
import pandas as pd

def sha256_file(path: Path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def read_csv_auto(path: Path):
    # auto delimiter + encoding
    for enc in ["utf-8", "latin1"]:
        try:
            return pd.read_csv(path, sep=None, engine="python", encoding=enc)
        except Exception:
            pass
    return pd.read_csv(path, sep=",", encoding="latin1")

def create_index_if_exists(cur: sqlite3.Cursor, table: str, col: str):
    cur.execute(f"PRAGMA table_info({table});")
    cols = {r[1] for r in cur.fetchall()}
    if col in cols:
        cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_{col} ON {table}({col});")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client_csv", required=True)
    ap.add_argument("--dossier_csv", required=True)
    ap.add_argument("--transaction_csv", required=True)
    ap.add_argument("--sqlite", required=True)
    ap.add_argument("--out_meta", default="logs/build_db_meta.json")
    args = ap.parse_args()

    client_csv = Path(args.client_csv)
    dossier_csv = Path(args.dossier_csv)
    transaction_csv = Path(args.transaction_csv)
    sqlite_path = Path(args.sqlite)
    out_meta = Path(args.out_meta)

    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    out_meta.parent.mkdir(parents=True, exist_ok=True)

    # Load CSVs
    clients = read_csv_auto(client_csv)
    dossiers = read_csv_auto(dossier_csv)
    transactions = read_csv_auto(transaction_csv)

    # Rebuild DB from scratch for reproducibility
    if sqlite_path.exists():
        sqlite_path.unlink()

    con = sqlite3.connect(str(sqlite_path))
    try:
        clients.to_sql("clients", con, if_exists="replace", index=False)
        dossiers.to_sql("dossiers", con, if_exists="replace", index=False)
        transactions.to_sql("transactions", con, if_exists="replace", index=False)

        cur = con.cursor()
        create_index_if_exists(cur, "dossiers", "client_id")
        create_index_if_exists(cur, "transactions", "client_id")
        create_index_if_exists(cur, "transactions", "dossier_id")
        create_index_if_exists(cur, "transactions", "date_transaction")
        con.commit()

        # Sanity counts
        cur.execute("SELECT COUNT(*) FROM clients"); c_clients = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM dossiers"); c_dossiers = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM transactions"); c_tx = cur.fetchone()[0]
    finally:
        con.close()

    meta = {
        "inputs": {
            "client_csv": str(client_csv),
            "dossier_csv": str(dossier_csv),
            "transaction_csv": str(transaction_csv),
            "client_sha256": sha256_file(client_csv),
            "dossier_sha256": sha256_file(dossier_csv),
            "transaction_sha256": sha256_file(transaction_csv),
        },
        "output": {
            "sqlite": str(sqlite_path),
            "sqlite_sha256": sha256_file(sqlite_path),
            "row_counts": {
                "clients": int(c_clients),
                "dossiers": int(c_dossiers),
                "transactions": int(c_tx),
            },
        },
    }
    out_meta.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print("Built DB:", sqlite_path)
    print("Row counts:", meta["output"]["row_counts"])
    print("DB sha256:", meta["output"]["sqlite_sha256"])
    print("Wrote metadata:", out_meta)

if __name__ == "__main__":
    main()