from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_PORT = 8188


def ensure_playwright_installed() -> None:
    """Install Playwright + Chromium for the active interpreter when missing."""
    try:
        import playwright  # type: ignore  # noqa: F401
        return
    except ImportError:
        pass

    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])


def _port_open(port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_port(proc: subprocess.Popen, port: int, timeout: float = 180.0) -> bool:
    """Wait until a TCP port accepts connections or the process exits."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2.0):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def start_comfy_server(comfy_dir: Path, python_exe: str | None = None) -> subprocess.Popen:
    """
    Launch ComfyUI headlessly using the given interpreter.

    The server is shut down by the caller; this function only waits for port readiness.
    """
    python_bin = python_exe or sys.executable
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    command = [
        str(python_bin),
        "-u",
        str(comfy_dir / "main.py"),
        "--disable-auto-launch",
    ]
    proc = subprocess.Popen(
        command,
        cwd=str(comfy_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _wait_for_port(proc, DEFAULT_PORT):
        proc.terminate()
        raise RuntimeError("ComfyUI server did not start listening on port 8188")
    return proc


async def export_workflow(playwright, workflow_path: Path, output_path: Path) -> None:
    """Drive the real ComfyUI frontend and export the workflow via graphToPrompt."""
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    await page.goto("http://127.0.0.1:8188", wait_until="load", timeout=120000)
    await page.wait_for_function(
        "window.comfyAPI && window.comfyAPI.app && window.comfyAPI.app.app && "
        "window.comfyAPI.app.app.graph",
        timeout=120000,
    )
    await page.wait_for_function(
        "window.LiteGraph && window.LiteGraph.registered_node_types && "
        "Object.keys(window.LiteGraph.registered_node_types).length > 0",
        timeout=240000,
    )

    with open(workflow_path, "r", encoding="utf-8") as handle:
        workflow_json = json.load(handle)

    prompt = await page.evaluate(
        """async ({ workflow }) => {
          const app = window.comfyAPI.app.app;
          await app.loadGraphData(workflow, true);
          const res = await app.graphToPrompt(app.graph);
          return res.output;
        }""",
        {"workflow": workflow_json},
    )

    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(prompt, handle, indent=2)

    await browser.close()


def run_export_sync(workflow_path: str, output_path: str, comfy_dir: str) -> None:
    """Run the browser export end-to-end using the current interpreter."""
    ensure_playwright_installed()
    proc: subprocess.Popen | None = None
    reuse_existing = _port_open(DEFAULT_PORT)
    if not reuse_existing:
        proc = start_comfy_server(Path(comfy_dir))
    try:
        from playwright.async_api import async_playwright

        async def _runner() -> None:
            async with async_playwright() as p:
                await export_workflow(p, Path(workflow_path), Path(output_path))

        asyncio.run(_runner())
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export ComfyUI web workflow JSON to API JSON using the real frontend."
    )
    parser.add_argument("--workflow", required=True, help="Path to the web workflow JSON.")
    parser.add_argument("--output", required=True, help="Where to write the API JSON.")
    parser.add_argument(
        "--comfy-dir",
        required=True,
        help="Path to the ComfyUI directory (folder containing main.py).",
    )
    args = parser.parse_args()
    run_export_sync(args.workflow, args.output, args.comfy_dir)


if __name__ == "__main__":
    main()
