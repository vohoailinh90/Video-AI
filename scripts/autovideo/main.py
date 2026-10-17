"""Entry point: python3 scripts/autovideo/main.py <command> ... (see cli.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autovideo.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
