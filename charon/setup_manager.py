from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Tuple, Optional, Callable, Dict

from .paths import resolve_comfy_environment, get_charon_temp_dir
from .charon_logger import system_error, system_info, system_debug

# Type definition for progress callback: (progress_percent, status_message) -> None
ProgressCallback = Callable[[int, str], None]

class SetupManager:
    """
    Manages the detection and installation of dependencies for Charon.
    Decouples the installation logic from the UI.
    """

    def __init__(self, comfy_path: str):
        self.comfy_path = comfy_path
        self.env = resolve_comfy_environment(self.comfy_path)
        self.python_exe = self.env.get("python_exe")
        self.comfy_dir = self.env.get("comfy_dir")
        
        # Resolve paths
        self.custom_nodes_dir = os.path.join(self.comfy_dir or "", "custom_nodes")
        self.manager_dir = os.path.join(self.custom_nodes_dir, "ComfyUI-Manager")
        self.kjnodes_dir = os.path.join(self.custom_nodes_dir, "ComfyUI-KJNodes")
        self.charon_dir = os.path.join(self.custom_nodes_dir, "ComfyUI-Charon")
        
        # Source for Charon (if running from source)
        self.charon_src = Path(__file__).resolve().parents[1] / "custom_nodes" / "comfyUI" / "ComfyUI-Charon"

    def _log(self, message: str) -> None:
        """Internal logging helper."""
        # File logging disabled per request
        return

    def _run_command(self, cmd: List[str], timeout: int = 600) -> Tuple[bool, str]:
        """Runs a command and returns (success, stdout/stderr/error_msg)."""
        try:
            # We capture output now instead of using DEVNULL for better debugging
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=True,
                timeout=timeout,
            )
            return True, process.stdout
        except subprocess.CalledProcessError as exc:
            err_msg = f"Command failed: {' '.join(cmd)}\nReturn Code: {exc.returncode}\nOutput: {exc.stdout}\nError: {exc.stderr}"
            self._log(err_msg)
            return False, err_msg
        except Exception as exc:
            err_msg = f"Execution failed: {str(exc)}"
            self._log(err_msg)
            return False, err_msg

    def _module_available(self, module_name: str) -> bool:
        if not self.python_exe or not os.path.exists(self.python_exe):
            return False
        try:
            subprocess.run(
                [self.python_exe, "-c", f"import {module_name}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=10,
            )
            return True
        except Exception:
            return False

    def _playwright_available(self) -> bool:
        if not self.python_exe or not os.path.exists(self.python_exe):
            return False
        try:
            subprocess.run(
                [self.python_exe, "-m", "playwright", "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=10,
            )
            return True
        except Exception:
            return False

    def _has_folder(self, parent_dir: str, folder_name: str) -> bool:
        """Checks if a folder exists within parent_dir (case-insensitive check)."""
        if not os.path.exists(parent_dir):
            return False
        try:
            for entry in os.listdir(parent_dir):
                path = os.path.join(parent_dir, entry)
                if os.path.isdir(path) and entry.lower() == folder_name.lower():
                    return True
        except OSError:
            pass
        return False

    def check_dependencies(self) -> Dict[str, str]:
        """
        Checks the status of all dependencies.
        Returns a dict mapping dependency name to status ('missing', 'found', 'error').
        """
        if not self.python_exe or not os.path.exists(self.python_exe):
            return {"python": "missing"}

        statuses = {}
        
        # Python Modules
        statuses["playwright"] = "found" if self._playwright_available() else "missing"
        statuses["trimesh"] = "found" if self._module_available("trimesh") else "missing"

        # Custom Nodes
        if self.comfy_dir:
            statuses["manager"] = "found" if self._has_folder(self.custom_nodes_dir, "ComfyUI-Manager") else "missing"
            statuses["kjnodes"] = "found" if self._has_folder(self.custom_nodes_dir, "ComfyUI-KJNodes") else "missing"
            statuses["charon"] = "found" if self._has_folder(self.custom_nodes_dir, "ComfyUI-Charon") else "missing"
        else:
            statuses["manager"] = "error"
            statuses["kjnodes"] = "error"
            statuses["charon"] = "error"

        return statuses

    def _download_and_extract_zip(self, repo_url: str, dest_dir: str, branch: str = "main") -> Tuple[bool, str]:
        """Downloads and extracts a zip from GitHub as a fallback for git clone."""
        try:
            url = f"{repo_url.rstrip('/')}/archive/refs/heads/{branch}.zip"
            download_root = Path(get_charon_temp_dir()) / "downloads"
            ts = int(time.time())
            download_root.mkdir(parents=True, exist_ok=True)
            
            zip_name = f"{Path(dest_dir).name}_{ts}.zip"
            zip_path = download_root / zip_name
            extract_root = download_root / f"{Path(dest_dir).name}_{ts}"
            
            self._log(f"Downloading zip from {url} to {zip_path}")
            
            with urllib.request.urlopen(url) as resp:
                zip_path.write_bytes(resp.read())
            
            extract_root.mkdir(parents=True, exist_ok=True)
            shutil.unpack_archive(str(zip_path), str(extract_root))
            
            candidates = [p for p in extract_root.iterdir() if p.is_dir()]
            if not candidates:
                return False, "Downloaded archive missing expected folder."
            
            src_dir = candidates[0]
            shutil.rmtree(dest_dir, ignore_errors=True)
            shutil.copytree(src_dir, dest_dir)
            
            return True, ""
        except Exception as exc:
            self._log(f"Zip download failed: {exc}")
            return False, str(exc)

    def _append_requirements_tasks(self, tasks: List, node_dir: str, label: str) -> None:
        """Helper to add pip install tasks for custom nodes."""
        if not self.python_exe:
            return
            
        path = Path(node_dir)
        req_path = path / "requirements.txt"
        if req_path.exists():
             tasks.append(
                (
                    f"Installing {label} dependencies...",
                    [self.python_exe, "-m", "pip", "install", "-r", str(req_path)],
                )
            )
        
        install_script = path / "install.py"
        if install_script.exists():
            tasks.append(
                (
                    f"Running {label} install.py...",
                    [self.python_exe, str(install_script)],
                )
            )

    def install_dependencies(self, callback: Optional[ProgressCallback] = None) -> Tuple[bool, List[str], str]:
        """
        Performs the installation of missing dependencies.
        Returns (success, messages_log, error_message).
        """
        messages: List[str] = []
        
        def update(progress: int, msg: str):
            messages.append(msg)
            if callback:
                callback(progress, msg)
            self._log(f"[Progress {progress}%] {msg}")

        if not self.python_exe:
            return False, messages, "ComfyUI Python environment not found."

        update(5, "Checking current status...")
        current_status = self.check_dependencies()
        
        git_path = shutil.which("git")
        if not git_path:
            update(5, "Git not found in PATH. Will use ZIP download fallback.")
        
        tasks: List[Tuple[str, List[str] | None]] = [] # (Label, Command or None for internal action)

        # 1. Playwright
        if current_status.get("playwright") == "missing":
            tasks.append(("Installing Playwright Python pkg...", [self.python_exe, "-m", "pip", "install", "playwright"]))
            tasks.append(("Installing Playwright Browsers...", [self.python_exe, "-m", "playwright", "install", "chromium"]))

        # 2. Trimesh
        if current_status.get("trimesh") == "missing":
            tasks.append(("Installing trimesh...", [self.python_exe, "-m", "pip", "install", "trimesh"]))

        # 3. ComfyUI-Manager
        if current_status.get("manager") == "missing":
            if git_path:
                tasks.append(( 
                    "Cloning ComfyUI-Manager...",
                    [git_path, "clone", "https://github.com/Comfy-Org/ComfyUI-Manager", self.manager_dir]
                ))
            else:
                tasks.append(("Downloading ComfyUI-Manager (ZIP)...", None)) # Special handler for zip
            
            # We need to install requirements AFTER cloning/downloading
            # We can't add the command yet because the file doesn't exist. 
            # We will handle this dynamically in the loop or add a special task type.
            # For simplicity, we'll add a "Post-Install" task that checks for requirements.txt dynamically.
            tasks.append(("Installing Manager requirements...", ["__DYNAMIC_REQ__", self.manager_dir, "ComfyUI-Manager"]))

        # 4. ComfyUI-KJNodes
        if current_status.get("kjnodes") == "missing":
            if git_path:
                tasks.append(( 
                    "Cloning ComfyUI-KJNodes...",
                    [git_path, "clone", "https://github.com/kijai/ComfyUI-KJNodes", self.kjnodes_dir]
                ))
            else:
                tasks.append(("Downloading ComfyUI-KJNodes (ZIP)...", None))
            
            tasks.append(("Installing KJNodes requirements...", ["__DYNAMIC_REQ__", self.kjnodes_dir, "ComfyUI-KJNodes"]))

        # 5. ComfyUI-Charon
        if current_status.get("charon") == "missing":
            if self.charon_src.exists():
                tasks.append(("Installing ComfyUI-Charon...", ["__INTERNAL_COPY__"]))
                tasks.append(("Installing Charon requirements...", ["__DYNAMIC_REQ__", self.charon_dir, "ComfyUI-Charon"]))
            else:
                update(10, "Warning: Charon source not found, skipping install.")

        if not tasks:
            update(100, "All dependencies are already installed.")
            return True, messages, ""

        # Execute Tasks
        total_tasks = len(tasks)
        for idx, (label, cmd) in enumerate(tasks):
            progress = 10 + int((idx / total_tasks) * 80)
            update(progress, label)
            
            ok = True
            err = ""
            
            # Handle Special Commands
            if cmd is None: # ZIP Download fallback (inferred from label context, but let's be safer)
                if "ComfyUI-Manager" in label:
                    ok, err = self._download_and_extract_zip("https://github.com/Comfy-Org/ComfyUI-Manager", self.manager_dir)
                elif "ComfyUI-KJNodes" in label:
                    ok, err = self._download_and_extract_zip("https://github.com/kijai/ComfyUI-KJNodes", self.kjnodes_dir)
            
            elif cmd == ["__INTERNAL_COPY__"]:
                try:
                    Path(self.charon_dir).parent.mkdir(parents=True, exist_ok=True)
                    shutil.rmtree(self.charon_dir, ignore_errors=True)
                    shutil.copytree(self.charon_src, self.charon_dir)
                except Exception as exc:
                    ok = False
                    err = str(exc)

            elif len(cmd) > 0 and cmd[0] == "__DYNAMIC_REQ__":
                # Dynamic check for requirements.txt / install.py
                target_dir = cmd[1]
                node_label = cmd[2]
                sub_tasks = []
                self._append_requirements_tasks(sub_tasks, target_dir, node_label)
                
                for sub_label, sub_cmd in sub_tasks:
                    update(progress, sub_label)
                    sub_ok, sub_err = self._run_command(sub_cmd)
                    if not sub_ok:
                        ok = False
                        err = sub_err
                        break
            
            else:
                # Standard subprocess command
                ok, err = self._run_command(cmd)

            if not ok:
                update(progress, f"Failed: {label}")
                return False, messages, err

        update(100, "Setup completed successfully.")
        return True, messages, ""
