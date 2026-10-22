"""Offline measurement, including real localhost HTTP. Never reads .env or calls an LLM."""
import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import socket
import statistics
import sys
import time

os.environ["DIACRITIZER_SKIP_DOTENV"] = "1"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx
import uvicorn

from app.config import Endpoint, Settings
from app.main import create_app
from app.providers import PHRASES
from app.validation import validate


def validation_measure(n):
    counts = dict.fromkeys(("added_word", "removed_word", "changed_letter", "markdown", "json", "translation"), 0)
    good = 0
    for i in range(n):
        source = f"ذهب الولد إلى المدرسة {i}"
        correct = f"ذَهَبَ الْوَلَدُ إِلَى الْمَدْرَسَةِ {i}"
        corruptions = {
            "added_word": correct + " إضافي", "removed_word": correct.replace("الْوَلَدُ ", ""),
            "changed_letter": correct.replace("ذ", "ز", 1), "markdown": "```\n" + correct + "\n```",
            "json": json.dumps({"text": correct}, ensure_ascii=False), "translation": f"The boy went to school {i}",
        }
        good += validate(source, correct).valid
        for name, output in corruptions.items():
            counts[name] += not validate(source, output).valid
    print("| Validator case | Result |")
    print("| --- | --- |")
    for name, rejected in counts.items():
        print(f"| {name} rejected | {rejected}/{n} |")
    print(f"| All bad outputs rejected | {sum(counts.values())}/{6 * n} |")
    print(f"| Correct outputs accepted | {good}/{n} |")
    assert good == n and sum(counts.values()) == 6 * n


async def latency_measure(n):
    cfg = Settings("measure-only", "", Endpoint("unused", "", "", ""), None, True, 1, 0, 5000,
                   ROOT / "data" / "measure.db")
    # Bind before starting the server to avoid a port allocation race.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(cfg), log_level="error", access_log=False, log_config=None))
    server_task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if server_task.done():
                await server_task
                raise RuntimeError("Server stopped before startup")
            if time.monotonic() > deadline:
                raise RuntimeError("Server startup timed out")
            await asyncio.sleep(0.01)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            async def call(text):
                start = time.perf_counter()
                response = await client.post("/v1/diacritize", headers={"X-Service-Key": "measure-only"}, json={"text": text})
                response.raise_for_status()
                assert response.json()["output"] == PHRASES[text]
                return (time.perf_counter() - start) * 1000
            for _ in range(10):
                await call(next(iter(PHRASES)))
            phrases = list(PHRASES)
            samples = [await call(phrases[i % len(phrases)]) for i in range(n)]
        ordered = sorted(samples)
        p95 = ordered[max(0, (95 * n + 99) // 100 - 1)]
        print("\n| Fake HTTP latency | Result |")
        print("| --- | --- |")
        print(f"| Successful measured requests | {n}/{n} |")
        print(f"| Median | {statistics.median(samples):.2f} ms |")
        print(f"| p95 (nearest rank) | {p95:.2f} ms |")
        print(f"| Mean | {statistics.mean(samples):.2f} ms |")
    finally:
        server.should_exit = True
        await server_task
        sock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=200, help="cases per corruption category and good cases")
    parser.add_argument("--requests", type=int, default=100, help="serial HTTP requests after 10 warmups")
    args = parser.parse_args()
    if min(args.n, args.requests) < 1:
        parser.error("counts must be positive")
    logging.getLogger("diacritizer").disabled = True
    validation_measure(args.n)
    asyncio.run(latency_measure(args.requests))
