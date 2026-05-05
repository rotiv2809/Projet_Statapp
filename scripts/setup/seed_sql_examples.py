"""Write the curated few-shot examples into the local JSON retrieval store."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from project root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.sql.example_bank import EXAMPLES
from app.agents.sql.retrieval import add_example, count_examples


def main() -> None:
    print("Writing retrieval examples to data/rag_examples.json ...")
    before = count_examples()
    for example in EXAMPLES:
        add_example(str(example["question"]), str(example["sql"]))
    after = count_examples()
    print(f"Done. Examples in store: {before} → {after}")


if __name__ == "__main__":
    main()
