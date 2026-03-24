from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from app.pipeline import run_data_pipeline

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run StatApp Text2SQL pipeline once.")
    parser.add_argument("--db", default="data/statapp.sqlite", help="Path to SQLite database.")
    parser.add_argument("--question", required=True, help="Natural-language question for the pipeline.")
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON output.",
    )
    return parser


def main() -> None:
    load_dotenv()
    args = _build_parser().parse_args()

    result = run_data_pipeline(db_path=args.db, question=args.question)
    if args.compact:
        print(json.dumps(result, ensure_ascii=False))
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
