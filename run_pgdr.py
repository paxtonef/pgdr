#!/usr/bin/env python3
"""Quick launcher — no install needed. Run: python3 run_pgdr.py run --help"""
import sys
from pathlib import Path

src = Path(__file__).parent / "src"
sys.path.insert(0, str(src))

from pgdr.cli import main

if __name__ == "__main__":
    main()
