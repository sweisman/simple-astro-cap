#!/usr/bin/env python3
"""Simple Astro Cap launcher."""
import sys
sys.path.insert(0, "/site/repo/simple-astro-cap/src")
from simple_astro_cap.app import run
sys.exit(run(sys.argv))
