import json
import logging
import os
import time

import nuke

try:
    from PySide6.QtWidgets import (
        QApplication,
        QFileDialog,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
        QComboBox,
    )
    from PySide6.QtCore import Qt
    PYSIDE_VERSION = 6
except ImportError:
    from PySide2.QtWidgets import (
        QApplication,
        QFileDialog,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTextEdit,
        QVBoxLayout,
        QWidget,
        QComboBox,
    )
    from PySide2.QtCore import Qt
    PYSIDE_VERSION = 2

from .comfy_client import ComfyUIClient
from .paths import get_charon_temp_dir, extend_sys_path_with_comfy, resolve_comfy_environment
from .processor_script import build_processor_script
from .workflow_analysis import (
    analyze_workflow_inputs,
    validate_workflow,
    workflow_display_text,
    analyze_ui_workflow_inputs,
    validate_ui_workflow,
    workflow_display_text_ui,
)
from .workflow_loader import list_workflows, load_workflow
from .workflow_pipeline import convert_workflow
from .node_factory import create_charon_group_node


logger = logging.getLogger(__name__)


class CharonPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.comfyui_url = "http://127.0.0.1:8188"
        self.client = None
        self.workflow_data = {}
        self.raw_workflow = {}
        self.workflow_inputs = []
        self.workflow_cache = {}
        self.current_workflow_path = ""
        self.current_workflow_name = ""
        self.init_ui()
        extend_sys_path_with_comfy(self.comfyui_path_edit.text())
        self.auto_test_connection()
        self.load_default_workflow()

    def log(self, message, level="INFO"):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")

    def init_ui(self):
        self.setWindowTitle("Charon - v1.0")
        self.setGeometry(100, 100, 700, 500)

        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # Connection group
        conn_group = QGroupBox("ComfyUI Connection")
        conn_layout = QVBoxLayout()

        url_layout = QHBoxLayout()
        url_layout.addWidget(QLabel("ComfyUI URL:"))
        self.url_edit = QLineEdit(self.comfyui_url)
        url_layout.addWidget(self.url_edit)
        self.test_btn = QPushButton("Test Connection")
        self.test_btn.clicked.connect(self.test_connection)
        url_layout.addWidget(self.test_btn)
        self.connection_status = QLabel("⚪ Disconnected")
        self.connection_status.setStyleSheet("color: #ff6b6b; font-weight: bold;")
        url_layout.addWidget(self.connection_status)
        conn_layout.addLayout(url_layout)

        exe_layout = QHBoxLayout()
        exe_layout.addWidget(QLabel("ComfyUI Path:"))
        self.comfyui_path_edit = QLineEdit()
        self.comfyui_path_edit.setPlaceholderText("Path to run_nvidia_gpu.bat or main.py...")
        self.comfyui_path_edit.setText(r"D:\ComfyUI_windows_portable_nvidia\ComfyUI_windows_portable\run_nvidia_gpu.bat")
        exe_layout.addWidget(self.comfyui_path_edit)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self.browse_comfyui_path)
        exe_layout.addWidget(browse_btn)
        launch_btn = QPushButton("Launch ComfyUI")
        launch_btn.clicked.connect(self.launch_comfyui)
        exe_layout.addWidget(launch_btn)
        conn_layout.addLayout(exe_layout)

        conn_group.setLayout(conn_layout)
        main_layout.addWidget(conn_group)

        # Workflow group
        workflow_group = QGroupBox("Workflow Selection")
        workflow_layout = QVBoxLayout()

        repo_layout = QHBoxLayout()
        repo_layout.addWidget(QLabel("Workflow Repository:"))
        self.workflow_combo = QComboBox()
        repo_layout.addWidget(self.workflow_combo)
        self.workflow_combo.currentTextChanged.connect(self.on_workflow_changed)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_workflows)
        repo_layout.addWidget(refresh_btn)
        workflow_layout.addLayout(repo_layout)

        custom_layout = QHBoxLayout()
        custom_layout.addWidget(QLabel("Custom Workflow:"))
        self.custom_path_edit = QLineEdit()
        self.custom_path_edit.setReadOnly(True)
        custom_layout.addWidget(self.custom_path_edit)
        custom_btn = QPushButton("Browse…")
        custom_btn.clicked.connect(self.browse_custom_workflow)
        custom_layout.addWidget(custom_btn)
        workflow_layout.addLayout(custom_layout)

        self.workflow_display = QTextEdit()
        self.workflow_display.setReadOnly(True)
        self.workflow_display.setPlaceholderText("No workflow selected")
        self.workflow_display.setMaximumHeight(140)
        workflow_layout.addWidget(self.workflow_display)
        workflow_group.setLayout(workflow_layout)
        main_layout.addWidget(workflow_group)

        # Node generation
        spawn_group = QGroupBox("Generate CharonOp Node")
        spawn_layout = QVBoxLayout()
        spawn_layout.addWidget(QLabel("Create a CharonOp node in the Node Graph with the selected workflow:"))
        self.spawn_node_btn = QPushButton("Generate CharonOp Node")
        self.spawn_node_btn.clicked.connect(self.spawn_charon_node)
        spawn_layout.addWidget(self.spawn_node_btn)
        spawn_group.setLayout(spawn_layout)
        main_layout.addWidget(spawn_group)

        self.setLayout(main_layout)
        self.populate_workflows(load=False)

    # Connection helpers
    def auto_test_connection(self):
        self.client = ComfyUIClient(self.comfyui_url)
        if self.client.test_connection():
            self.update_connection_status(True)
            self.log("ComfyUI connection successful (auto-test)")
        else:
            self.update_connection_status(False)
            self.log("ComfyUI connection failed (auto-test)", "WARNING")

    def update_connection_status(self, connected):
        if connected:
            self.connection_status.setText("🟢 Connected")
            self.connection_status.setStyleSheet("color: #51cf66; font-weight: bold;")
        else:
            self.connection_status.setText("🔴 Disconnected")
            self.connection_status.setStyleSheet("color: #ff6b6b; font-weight: bold;")

    def test_connection(self):
        url = self.url_edit.text().strip()
        self.client = ComfyUIClient(url)
        if self.client.test_connection():
            stats = self.client.get_system_stats()
            if stats:
                info = "Connection successful!\\n\\nSystem Info:\\n"
                info += f"CPU: {stats.get('system', {}).get('cpu_count', 'Unknown')} cores\\n"
                info += f"RAM: {stats.get('system', {}).get('ram_total_gb', 'Unknown')} GB\\n"
                info += f"VRAM: {stats.get('system', {}).get('vram_total_gb', 'Unknown')} GB"
                QMessageBox.information(self, "Success", info)
            else:
                QMessageBox.information(self, "Success", "Connection to ComfyUI successful!")
            self.comfyui_url = url
            self.update_connection_status(True)
        else:
            QMessageBox.warning(self, "Warning", "Failed to connect to ComfyUI. Please check if ComfyUI is running.")
            self.update_connection_status(False)

    # Workflow loading
    def refresh_workflows(self):
        self.populate_workflows(load=True)

    def populate_workflows(self, *, load=True):
        workflows = list_workflows()
        current_path = self.workflow_combo.currentData()
        if not current_path and self.current_workflow_path:
            current_path = self.current_workflow_path

        self.workflow_combo.blockSignals(True)
        self.workflow_combo.clear()
        for display, path in workflows:
            self.workflow_combo.addItem(display, path)

        if workflows:
            target_path = current_path or workflows[0][1]
            target_abs = os.path.abspath(target_path)
            selected_index = 0
            for idx, (_, candidate) in enumerate(workflows):
                if os.path.abspath(candidate) == target_abs:
                    selected_index = idx
                    break
            self.workflow_combo.setCurrentIndex(selected_index)

        self.workflow_combo.blockSignals(False)

        if load and workflows:
            path = self.workflow_combo.currentData()
            if path:
                self.load_workflow(path, preset=True)

    def load_default_workflow(self):
        path = self.workflow_combo.currentData()
        if path:
            self.load_workflow(path, preset=True)

    def on_workflow_changed(self, _name):
        path = self.workflow_combo.currentData()
        if path:
            self.load_workflow(path, preset=True)

    def browse_custom_workflow(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ComfyUI Workflow JSON",
            "",
            "JSON Files (*.json);;All Files (*.*)",
        )
        if file_path:
            self.load_workflow(file_path, preset=False)

    def load_workflow(self, path, preset=True):
        try:
            self.log(f"Loading workflow: {path}")
            raw = load_workflow(path)
            self.raw_workflow = raw
            cache_key = os.path.abspath(path) if path else ""
            if cache_key:
                entry = self.workflow_cache.setdefault(cache_key, {})
                if os.path.exists(cache_key):
                    current_mtime = os.path.getmtime(cache_key)
                    if entry.get("mtime") and entry["mtime"] != current_mtime:
                        entry.pop("prompt", None)
                        entry.pop("debug_path", None)
                    entry["mtime"] = current_mtime
            self.current_workflow_path = cache_key

            if self._is_api_workflow(raw):
                self.log("Workflow appears to be pre-converted (API format)")
                self.workflow_data = raw
                self.workflow_inputs = analyze_workflow_inputs(raw)
                if cache_key:
                    cache_entry = self.workflow_cache.setdefault(cache_key, {})
                    cache_entry["prompt"] = raw
                    cache_entry.setdefault("debug_path", "provided")
                ok, message = validate_workflow(raw)
                if not ok:
                    self.log(message, "WARNING")
                    QMessageBox.warning(self, "Workflow Warning", message)
                display_text = workflow_display_text(
                    os.path.splitext(os.path.basename(path))[0],
                    os.path.basename(path),
                    raw,
                )
            else:
                self.workflow_data = raw
                self.workflow_inputs = analyze_ui_workflow_inputs(raw)
                ok, message = validate_ui_workflow(raw)
                if not ok:
                    self.log(message, "WARNING")
                    QMessageBox.warning(self, "Workflow Warning", message)
                name = os.path.splitext(os.path.basename(path))[0]
                display_text = workflow_display_text_ui(
                    name,
                    os.path.basename(path),
                    raw,
                )

            self.current_workflow_name = os.path.splitext(os.path.basename(path))[0]
            self.workflow_display.setText(display_text)
            if not preset:
                self.custom_path_edit.setText(path)

            if isinstance(raw, dict):
                if "nodes" in raw and isinstance(raw.get("nodes"), list):
                    node_count = len(raw["nodes"])
                else:
                    node_count = len(raw)
            else:
                node_count = 0
            self.log(f"Workflow loaded (nodes: {node_count})")
        except json.JSONDecodeError as exc:
            QMessageBox.critical(self, "JSON Error", f"Invalid JSON file: {exc}")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to load workflow: {exc}")
            raise

    def convert_workflow_on_request(self, raw_workflow=None, source_path=None):
        data = raw_workflow or self.workflow_data
        if not isinstance(data, dict):
            raise RuntimeError("Workflow data is unavailable or invalid.")

        if self._is_api_workflow(data):
            return data

        comfy_path = self.comfyui_path_edit.text().strip()
        if not comfy_path:
            raise RuntimeError("Please set the ComfyUI path before converting workflows.")

        cache_key = os.path.abspath(source_path) if source_path else ""
        cache_entry = self.workflow_cache.get(cache_key) if cache_key else None

        if cache_entry:
            cache_mtime = cache_entry.get("mtime")
            if cache_mtime and cache_key and os.path.exists(cache_key):
                current_mtime = os.path.getmtime(cache_key)
                if current_mtime != cache_mtime:
                    cache_entry.pop("prompt", None)
                    cache_entry["mtime"] = current_mtime
            cached_prompt = cache_entry.get("prompt")
            if cached_prompt and self._is_api_workflow(cached_prompt):
                return cached_prompt

        converted = convert_workflow(data, comfy_path=comfy_path)
        debug_filename = self._build_debug_filename(source_path)
        debug_path = self.write_debug_prompt(converted, debug_filename)

        if cache_key:
            cache_entry = self.workflow_cache.setdefault(cache_key, {})
            cache_entry["prompt"] = converted
            cache_entry["debug_path"] = debug_path

        self.log(f"Converted workflow on demand ({len(converted)} nodes)")
        self.log(f"Saved converted prompt to: {debug_path}")
        return converted

    def _build_debug_filename(self, source_path):
        if source_path:
            basename = os.path.splitext(os.path.basename(source_path))[0]
            return f"{basename}_converted.json"
        timestamp = int(time.time())
        return f"workflow_converted_{timestamp}.json"

    @staticmethod
    def _is_api_workflow(data):
        if not isinstance(data, dict):
            return False
        if not data:
            return False
        for value in data.values():
            if not isinstance(value, dict) or "class_type" not in value:
                return False
        return True

    def write_debug_prompt(self, prompt_data, filename):
        try:
            from .paths import get_charon_temp_dir

            root = get_charon_temp_dir()
            debug_dir = os.path.join(root, "debug")
            os.makedirs(debug_dir, exist_ok=True)
            debug_path = os.path.join(debug_dir, filename)
            with open(debug_path, "w", encoding="utf-8") as handle:
                json.dump(prompt_data, handle, indent=2)
            return debug_path
        except Exception as exc:
            self.log(f"Could not write debug prompt: {exc}", "WARNING")
            return "unavailable"

    # Node creation
    def spawn_charon_node(self):
        if not self.workflow_data:
            QMessageBox.warning(self, "Warning", "Please load a workflow first")
            return

        inputs = self.workflow_inputs or [
            {
                "name": "Primary Image",
                "type": "image",
                "node_id": "primary",
                "description": "Main input image",
            }
        ]

        temp_root = get_charon_temp_dir()
        process_script = build_processor_script()
        menu_script = self.build_menu_script(temp_root)

        node, inputs_with_index = create_charon_group_node(
            nuke=nuke,
            workflow_name=self.current_workflow_name or "Custom",
            workflow_data=self.workflow_data,
            inputs=inputs,
            temp_dir=temp_root,
            process_script=process_script,
            menu_script=menu_script,
            workflow_path=self.current_workflow_path,
        )

        selected = nuke.selectedNodes()
        if selected:
            avg_x = int(sum(n.xpos() + n.screenWidth() // 2 for n in selected) / len(selected))
            avg_y = int(sum(n.ypos() + n.screenHeight() // 2 for n in selected) / len(selected))
        else:
            root = nuke.root()
            avg_x = int(root.xpos())
            avg_y = int(root.ypos())

        node.setXpos(avg_x)
        node.setYpos(avg_y)

        QMessageBox.information(
            self,
            "Success",
            f"CharonOp node created!\\n\\nNode: {node.name()}\\nInputs: {len(inputs_with_index)}",
        )

    def build_menu_script(self, temp_root):
        return f"""# CharonOp Menu Script
import os
import json
import time

def show_info():
    node = nuke.thisNode()
    data = node.knob('workflow_data').value()
    mapping = node.knob('input_mapping').value()
    print('Workflow nodes:', len(json.loads(data)) if data else 0)
    if mapping:
        inputs = json.loads(mapping)
        print('Inputs:')
        for item in inputs:
            print(' -', item.get('name'), ':', item.get('description'))

def monitor_status():
    temp_root = {json.dumps(temp_root)}
    status_dir = os.path.join(temp_root, 'status')
    result_dir = os.path.join(temp_root, 'results')
    print('Status files:', os.listdir(status_dir) if os.path.exists(status_dir) else [])
    print('Result files:', os.listdir(result_dir) if os.path.exists(result_dir) else [])

menu = nuke.choice('CharonOp Menu', 'Choose Option', ['Show Workflow Info', 'Monitor Status'])
if menu == 0:
    show_info()
else:
    monitor_status()
"""

    # Utilities
    def browse_comfyui_path(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select ComfyUI Launch File",
            "",
            "Batch Files (*.bat);;Python Scripts (*.py);;All Files (*.*)",
        )
        if file_path:
            self.comfyui_path_edit.setText(file_path)
            extend_sys_path_with_comfy(file_path)
            self.try_reimport_nodes()

    def try_reimport_nodes(self):
        try:
            import importlib

            importlib.invalidate_caches()
            importlib.import_module("nodes")
            self.log("Re-imported ComfyUI nodes after path update")
        except Exception as exc:
            self.log(f"Could not import nodes module: {exc}", "WARNING")

    def launch_comfyui(self):
        path = self.comfyui_path_edit.text().strip()
        if not path:
            QMessageBox.warning(self, "Warning", "Please specify the path to ComfyUI launch file")
            return
        if not os.path.exists(path):
            QMessageBox.critical(self, "Error", f"File not found: {path}")
            return
        try:
            import subprocess

            base_dir = os.path.dirname(path)
            if path.endswith(".bat"):
                subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", path], cwd=base_dir, shell=True)
            elif path.endswith(".py"):
                subprocess.Popen(["python", path, "--api"], cwd=base_dir, shell=False)
            else:
                subprocess.Popen([path], cwd=base_dir, shell=True)
            QMessageBox.information(self, "Success", "ComfyUI is launching...")
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to launch ComfyUI: {exc}")


def create_charon_panel():
    app = QApplication.instance()
    if app:
        for widget in app.topLevelWidgets():
            if isinstance(widget, CharonPanel):
                try:
                    widget.show()
                    widget.raise_()
                    widget.activateWindow()
                except Exception:
                    widget.show()
                print("Charon is already running. Reusing existing instance.")
                return widget

    panel = CharonPanel()
    panel.show()
    try:
        panel.raise_()
        panel.activateWindow()
    except Exception:
        pass
    return panel
