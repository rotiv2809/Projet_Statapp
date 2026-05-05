"""Export expert corrections from corrections_log as fine-tuning training data.

Usage:
    python scripts/export_finetuning_data.py --db data/statapp.sqlite --out data/finetune.jsonl
    python scripts/export_finetuning_data.py --db data/statapp.sqlite --out data/finetune.jsonl --format alpaca

Output formats:
  jsonl (default) — one JSON object per line, OpenAI-style chat completion format:
    {"messages": [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]}

  alpaca — instruction-following format used by many open-weight fine-tuning frameworks:
    {"instruction": ..., "input": ..., "output": ...}

  pairs — minimal (question, sql) pairs:
    {"prompt": ..., "completion": ...}
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


_SYSTEM_PROMPT = (
    "You are an expert SQL assistant. "
    "Given a natural language question about a business database, "
    "generate a correct and safe SQLite SELECT query. "
    "Output only the SQL query, no explanation."
)


def _read_corrections(db_path: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT question, generated_sql, corrected_sql, timestamp, user
            FROM corrections_log
            ORDER BY timestamp ASC
            """
        )
        rows = cur.fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    return [
        {
            "question": row[0],
            "generated_sql": row[1],
            "corrected_sql": row[2],
            "timestamp": row[3],
            "user": row[4],
        }
        for row in rows
        if (row[0] or "").strip() and (row[2] or "").strip()
    ]


def _to_jsonl(record: dict) -> dict:
    return {
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": record["question"].strip()},
            {"role": "assistant", "content": record["corrected_sql"].strip()},
        ]
    }


def _to_alpaca(record: dict) -> dict:
    return {
        "instruction": "Translate the following natural language question into a SQLite SELECT query.",
        "input": record["question"].strip(),
        "output": record["corrected_sql"].strip(),
    }


def _to_pairs(record: dict) -> dict:
    return {
        "prompt": record["question"].strip(),
        "completion": record["corrected_sql"].strip(),
    }


_FORMATTERS = {
    "jsonl": _to_jsonl,
    "alpaca": _to_alpaca,
    "pairs": _to_pairs,
}


def export(db_path: str, out_path: str, fmt: str) -> int:
    corrections = _read_corrections(db_path)
    if not corrections:
        print("No corrections found in {}.".format(db_path), file=sys.stderr)
        return 0

    formatter = _FORMATTERS[fmt]
    output = Path(out_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as f:
        for record in corrections:
            f.write(json.dumps(formatter(record), ensure_ascii=False) + "\n")

    print(
        "Exported {} correction(s) to {} (format: {}).".format(
            len(corrections), output, fmt
        )
    )
    return len(corrections)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export expert corrections as fine-tuning data.")
    parser.add_argument(
        "--db",
        default="data/statapp.sqlite",
        help="Path to the SQLite database (default: data/statapp.sqlite)",
    )
    parser.add_argument(
        "--out",
        default="data/finetune.jsonl",
        help="Output file path (default: data/finetune.jsonl)",
    )
    parser.add_argument(
        "--format",
        choices=list(_FORMATTERS),
        default="jsonl",
        help="Output format: jsonl (OpenAI chat), alpaca, or pairs (default: jsonl)",
    )
    args = parser.parse_args()

    count = export(db_path=args.db, out_path=args.out, fmt=args.format)
    if count == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
