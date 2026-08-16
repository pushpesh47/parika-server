"""
Allows running the Console as `python -m parika.console`.
"""

from .app import main

if __name__ == "__main__":
    raise SystemExit(main())
