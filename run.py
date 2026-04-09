#!/usr/bin/env python3
"""Simple Astro Cap launcher."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from simple_astro_cap.app import run
sys.exit(run(sys.argv))
