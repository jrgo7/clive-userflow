"""`python -m clive.studio` / `uv run clive-studio`."""

from __future__ import annotations

import argparse

from clive.studio.server import serve


def main() -> None:
    parser = argparse.ArgumentParser(prog="clive-studio", description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--no-browser", action="store_true", help="do not open a browser window on start"
    )
    args = parser.parse_args()
    serve(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
