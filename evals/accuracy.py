"""Run the backend accuracy evaluator from the project root.

This wrapper lets both commands work:

- from the project root: python -m evals.accuracy
- from backend/: python -m evals.accuracy
"""

from backend.evals.accuracy import main


if __name__ == "__main__":
    raise SystemExit(main())
