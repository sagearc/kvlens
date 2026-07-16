"""Optional live server: static files + an SSE stream of view-model frames.

``kvlens serve`` stays a zero-dependency stdlib static server (see cli.py). This
module is imported only for the opt-in ``--replay`` / ``--live`` modes (the
``[serve]`` extra), so a plain install never needs FastAPI.

Both modes speak one SSE protocol the browser's ``EventSource`` consumes (see
``web/transport.js``): a ``{"type":"meta", ...}`` message, then
``{"type":"frame", "t", "s", "vm", "contentDelta"}`` messages. The ``vm`` is the
exact view-model shape shipped in the static artifact and derived by tree.py, so
live and replay render 1:1 with the committed demo.
"""

from __future__ import annotations

import asyncio
import json
import threading
from argparse import Namespace
from collections.abc import AsyncIterator, Callable
from pathlib import Path

MessageSource = Callable[[], AsyncIterator[dict]]


def _encode_sse(message: dict) -> str:
    """Format one message as a server-sent-events data frame."""
    return f"data: {json.dumps(message, separators=(',', ':'))}\n\n"


def build_app(web_dir: Path, message_source: MessageSource):
    """FastAPI app serving ``web_dir`` plus a ``/events`` SSE stream.

    ``message_source`` returns a fresh async generator of message dicts for each
    client connection.
    """
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI()

    @app.get("/events")
    async def events():
        async def event_stream() -> AsyncIterator[str]:
            async for message in message_source():
                yield _encode_sse(message)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )

    # Mounted last so /events wins; html=True serves index.html at "/".
    app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")
    return app


def _view_model_block_hashes(view_model: dict) -> list[str]:
    """Every block hash referenced by a frame's view-model (for content deltas)."""
    block_hashes: list[str] = []

    def collect(items: list[dict]) -> None:
        for item in items:
            if item["kind"] == "run":
                block_hashes.extend(block_hash for block_hash, _ in item["blocks"])
                block_hashes.extend(block_hash for block_hash, _ in item["stubBlocks"])
            elif item["kind"] == "branch":
                collect(item["body"])

    collect(view_model["roots"])
    return block_hashes


async def _replay_source(
    artifact_path: Path, seconds_per_frame: float
) -> AsyncIterator[dict]:
    """Stream a pre-derived artifact's frames over SSE on a timer.

    Exercises the full live wire format + client rendering without vLLM — handy
    for developing the transport against the committed sample.
    """
    artifact = json.loads(Path(artifact_path).read_text())
    content = artifact.get("content", {})
    yield {"type": "meta", "meta": artifact["meta"]}
    sent_hashes: set[str] = set()
    for frame in artifact["frames"]:
        new_hashes = [
            block_hash
            for block_hash in _view_model_block_hashes(frame["vm"])
            if block_hash in content and block_hash not in sent_hashes
        ]
        sent_hashes.update(new_hashes)
        content_delta = {block_hash: content[block_hash] for block_hash in new_hashes}
        yield {
            "type": "frame",
            "t": frame["t"],
            "s": frame["s"],
            "vm": frame["vm"],
            "contentDelta": content_delta,
        }
        await asyncio.sleep(seconds_per_frame)


def _live_source(args: Namespace) -> AsyncIterator[dict]:
    """Async generator draining live vLLM frames produced on a worker thread.

    ``events.run_live`` drives the (blocking) engine on a thread and hands each
    message back to the event loop via a thread-safe queue.
    """
    from . import events

    loop = asyncio.get_running_loop()
    message_queue: asyncio.Queue = asyncio.Queue()
    stream_done = object()

    def emit(message: dict) -> None:
        loop.call_soon_threadsafe(message_queue.put_nowait, message)

    def worker() -> None:
        try:
            events.run_live(args, emit)
        finally:
            loop.call_soon_threadsafe(message_queue.put_nowait, stream_done)

    threading.Thread(target=worker, daemon=True).start()

    async def message_stream() -> AsyncIterator[dict]:
        while True:
            message = await message_queue.get()
            if message is stream_done:
                break
            yield message

    return message_stream()


def serve(args: Namespace) -> None:
    """Run the FastAPI server in ``--replay`` or ``--live`` mode."""
    import uvicorn

    web_dir = Path(args.dir)
    if args.live:

        def message_source() -> AsyncIterator[dict]:
            return _live_source(args)

        mode = "live vLLM"
    else:

        def message_source() -> AsyncIterator[dict]:
            return _replay_source(Path(args.data), args.interval)

        mode = f"replay of {args.data}"
    app = build_app(web_dir, message_source)
    print(
        f"Serving {web_dir}/ at http://localhost:{args.port}  "
        f"(SSE /events: {mode}, Ctrl-C to stop)"
    )
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="warning")
