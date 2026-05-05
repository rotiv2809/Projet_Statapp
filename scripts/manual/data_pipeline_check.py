"""Manual pipeline check. Not part of the automated pytest suite."""

from dotenv import load_dotenv

load_dotenv()

from app.pipeline.data_pipeline import run_data_pipeline  # noqa: E402

DB = "data/statapp.sqlite"

tests = [
    "How many clients are there by commune (top 10 communes)?",
]

for q in tests:
    print("\n" + "=" * 90)
    print("Q:", q)
    res = run_data_pipeline(DB, q)
    print(res)
