"""kvlens command line: `serve` (no deps) and `capture` / `events` (need vLLM).

The capture subcommands import vLLM lazily inside their `run()`, so `serve`
works from a plain `pip install kvlens` with no heavy dependencies.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import socketserver
from pathlib import Path

from . import __version__


def _serve(args: argparse.Namespace) -> None:
    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(args.dir)
    )
    with socketserver.ThreadingTCPServer(("", args.port), handler) as httpd:
        url = f"http://localhost:{args.port}"
        print(f"Serving {args.dir}/ at {url}  (Ctrl-C to stop)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="kvlens", description=__doc__)
    p.add_argument("--version", action="version", version=f"kvlens {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    srv = sub.add_parser("serve", help="serve the static viz (no vLLM needed)")
    srv.add_argument("--dir", type=Path, default=Path("web"))
    srv.add_argument("--port", type=int, default=8000)
    srv.set_defaults(fn=_serve)

    cap = sub.add_parser("capture", help="replay traces → web/run.json (needs vLLM)")
    ev = sub.add_parser(
        "events", help="capture KV events → web/kv_events.json (needs vLLM)"
    )
    scr = sub.add_parser("scrub", help="strip real text from a capture for sharing")
    # Import lazily so building the parser (and `serve`) never imports vLLM.
    from . import capture, events, scrub

    capture.add_args(cap)
    cap.set_defaults(fn=capture.run)
    events.add_args(ev)
    ev.set_defaults(fn=events.run)
    scrub.add_args(scr)
    scr.set_defaults(fn=scrub.run)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
