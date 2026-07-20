from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_PORT = 8188

def ensure_playwright_installed() -> None:
    """Install Playwright + Chromium for the active interpreter when missing."""
    try:
        import playwright  # type: ignore  # noqa: F401
        return
    except ImportError:
        pass

    subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True, timeout=600)
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True, timeout=600)


def _port_open(port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _comfy_health_ok(port: int, timeout: float = 3.0) -> bool:
    url = f"http://127.0.0.1:{port}/system_stats"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, urllib.error.URLError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and (
        "system" in payload or "devices" in payload
    )


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


async def inspect_workflow(playwright, workflow_path: Path) -> list[dict]:
    """
    Drive the real ComfyUI frontend to inspect the workflow widgets.
    Returns a list of node definitions with their resolved widget names.
    """
    browser = await playwright.chromium.launch(headless=True)
    page = await browser.new_page()

    try:
        # Navigate to ComfyUI
        await page.goto("http://127.0.0.1:8188", wait_until="load", timeout=60000)
        
        # Wait for the app and graph to be ready
        await page.wait_for_function(
            "window.comfyAPI && window.comfyAPI.app && window.comfyAPI.app.app && "
            "window.comfyAPI.app.app.graph",
            timeout=60000,
        )
        
        # Wait for node definitions to be loaded
        await page.wait_for_function(
            "window.LiteGraph && window.LiteGraph.registered_node_types && "
            "Object.keys(window.LiteGraph.registered_node_types).length > 0",
            timeout=60000,
        )

        with open(workflow_path, "r", encoding="utf-8") as handle:
            workflow_json = json.load(handle)

        # Execute inspection script in browser context
        nodes_data = await page.evaluate(
            """async ({ workflow }) => {
                const app = window.comfyAPI.app.app;
                
                // Load the graph
                await app.loadGraphData(workflow, true);
                
                // Give it a moment for widgets to settle if needed (though loadGraphData is usually synchronous for structure)
                // Some custom nodes might create widgets async, but usually they are created on configure.
                
                const result = [];
                for (const node of app.graph._nodes) {
                    const nodeData = {
                        node_id: String(node.id),
                        type: node.type,
                        title: node.title,
                        widgets: []
                    };
                    
                    if (node.widgets) {
                        for (let i = 0; i < node.widgets.length; i++) {
                            const w = node.widgets[i];
                            // We only care about input widgets that are likely serialized.
                            // We ignore converted widgets (which become inputs) for now, 
                            // as charon usually maps `widgets_values` which are persistent settings.
                            nodeData.widgets.push({
                                name: w.name,
                                type: w.type,
                                value: w.value
                            });
                        }
                    }
                    result.push(nodeData);
                }
                return result;
            }""",
            {"workflow": workflow_json},
        )
        return nodes_data
    finally:
        await browser.close()


def run_inspection_sync(workflow_path: str, comfy_dir: str) -> None:
    """Run the inspection end-to-end."""
    ensure_playwright_installed()
    proc: subprocess.Popen | None = None
    reuse_existing = _port_open(DEFAULT_PORT)
    if reuse_existing and not _comfy_health_ok(DEFAULT_PORT):
        raise RuntimeError(
            "Port 8188 is already in use, but it does not look like a ComfyUI server."
        )
    
    if not reuse_existing:
        proc = start_comfy_server(Path(comfy_dir))
        
    try:
        from playwright.async_api import async_playwright

        async def _runner() -> None:
            async with async_playwright() as p:
                data = await inspect_workflow(p, Path(workflow_path))
                print(json.dumps(data))

        asyncio.run(_runner())
    finally:
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect workflow widgets using Playwright and ComfyUI frontend.")
    parser.add_argument("--workflow", required=True, help="Path to the workflow JSON file.")
    parser.add_argument("--comfy-dir", required=True, help="Path to the ComfyUI directory.")
    args = parser.parse_args()

    try:
        run_inspection_sync(args.workflow, args.comfy_dir)
    except Exception as exc:
        # Print error as JSON to be safely parsed by caller
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
