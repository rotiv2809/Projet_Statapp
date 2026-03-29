from __future__ import annotations

import argparse
import json
import uuid

from dotenv import load_dotenv

from app.logging_utils import configure_logging
from app.pipeline import invoke_graph_pipeline

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
    configure_logging()
    args = _build_parser().parse_args()

    result, _prior = invoke_graph_pipeline(
        db_path=args.db,
        question=args.question,
        thread_id="cli-{}".format(uuid.uuid4()),
    )
    if args.compact:
        print(json.dumps(result, ensure_ascii=False))
        return
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
