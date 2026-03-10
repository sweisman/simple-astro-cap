"""Entry point: python -m simple_astro_cap"""

import sys

from simple_astro_cap.app import run


def main() -> int:
    return run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
