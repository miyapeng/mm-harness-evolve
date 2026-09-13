"""Active benchmark adapters; archived imports remain available for historical readers."""

from pathlib import Path

# Only Design2Code and Claw-Eval-MM have retained implementations here.
# Frozen runs keep their own package tree and never need this live compatibility path.
__path__.append(str(Path(__file__).resolve().parents[1] / "archive/benchmarks"))
