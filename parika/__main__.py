"""
Allows running PARIKA as `python -m parika`.

Delegates to the native PARIKA Console, matching the `parika` console
script installed by `pyproject.toml`.
"""

from parika.console.app import main

if __name__ == "__main__":
    raise SystemExit(main())
