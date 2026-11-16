"""Make repo-root packages (engines, connectors) importable when pytest runs from apps/api."""
import sys
from pathlib import Path

ROOT=str(Path(__file__).resolve().parents[3])
if ROOT not in sys.path:sys.path.insert(0,ROOT)
