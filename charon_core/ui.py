import json
import logging
import os
import time

import nuke
from functools import partial

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
        QCheckBox,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QHeaderView,
        QMenu,
        QStyledItemDelegate,
        QAbstractItemView,
        QStyle,
    )
    from PySide6.QtCore import Qt, QTimer, QRect
    from PySide6.QtGui import QPainter, QColor, QFont
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
        QCheckBox,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QHeaderView,
        QMenu,
        QStyledItemDelegate,
        QAbstractItemView,
        QStyle,
    )
    from PySide2.QtCore import Qt, QTimer, QRect
    from PySide2.QtGui import QPainter, QColor, QFont
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

SCENE_NODE_TABLE_STYLE = """
QTableWidget {
    background-color: #2c2c2c;
    alternate-background-color: #343434;
    color: #e2e2e2;
    gridline-color: #3d3d3d;
    border: 1px solid #3d3d3d;
    selection-background-color: #3d566f;
    selection-color: #f0f0f0;
}
QTableWidget::item {
    padding: 4px 6px;
}
QTableCornerButton::section {
    background-color: #2c2c2c;
    border: 1px solid #3d3d3d;
}
QHeaderView::section {
    background-color: #373737;
    color: #d3d3d3;
    padding: 6px 4px;
    border: 1px solid #3d3d3d;
}
"""


class ProgressBarDelegate(QStyledItemDelegate):
    """Custom delegate to render progress bars in table cells."""

    BASE_COLOR_EVEN = QColor("#2c2c2c")
    BASE_COLOR_ODD = QColor("#343434")
    SELECTION_COLOR = QColor("#3d566f")
    TEXT_COLOR = QColor("#f4f4f4")
    BORDER_COLOR = QColor("#4a4a4a")
    ERROR_COLOR = QColor("#c94d4d")
    COMPLETE_COLOR = QColor("#3d995b")
    ACTIVE_COLOR = QColor("#d0a23f")
    IDLE_COLOR = QColor("#565656")

    def paint(self, painter, option, index):
        progress_data = index.data(Qt.UserRole)
        if progress_data is None:
            super().paint(painter, option, index)
            return

        progress, status = progress_data
        original_progress = progress
        rect = option.rect

        painter.save()
        painter.setPen(Qt.NoPen)

        if option.state & QStyle.State_Selected:
            background = self.SELECTION_COLOR
        else:
            background = (
                self.BASE_COLOR_EVEN if index.row() % 2 == 0 else self.BASE_COLOR_ODD
            )
        painter.fillRect(rect, background)

        if original_progress < 0:
            bar_color = self.ERROR_COLOR
            progress = 1.0
        elif progress >= 1.0:
            bar_color = self.COMPLETE_COLOR
        elif progress > 0:
            bar_color = self.ACTIVE_COLOR
        else:
            bar_color = self.IDLE_COLOR

        if progress > 0:
            inner_rect = QRect(rect)
            inner_rect.adjust(1, 1, -1, -1)
            width = int(inner_rect.width() * min(progress, 1.0))
            if width > 0:
                bar_rect = QRect(
                    inner_rect.left(),
                    inner_rect.top(),
                    width,
                    inner_rect.height(),
                )
                painter.fillRect(bar_rect, bar_color)

        painter.setPen(self.BORDER_COLOR)
        border_rect = QRect(rect)
        border_rect.adjust(0, 0, -1, -1)
        painter.drawRect(border_rect)

        pen_color = QColor(self.TEXT_COLOR)
        if option.state & QStyle.State_Selected:
            pen_color = QColor("#fdfdfd")
        painter.setPen(pen_color)
        font = option.font
        font.setPointSize(9)
        painter.setFont(font)

        status_text = status or ""
        display_text = status_text
        if 0 < progress < 1.0:
            display_text = f"{status_text} ({progress:.0%})".strip()
        elif progress >= 1.0 and status_text:
            display_text = f"{status_text} (100%)"

        painter.drawText(rect, Qt.AlignCenter, display_text)
        painter.restore()

    def sizeHint(self, option, index):
        return super().sizeHint(option, index)


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
        
        # Monitoring attributes
        self.nodes_table = None
        self.selected_node_name = ""
        self.workflow_footer = None
        self.auto_refresh_button = None
        self.auto_import_checkbox = None
        self.auto_import_enabled = True
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_nodes_table)
        self.last_node_data = {}
        
        self.init_ui()
        extend_sys_path_with_comfy(self.comfyui_path_edit.text())
        self.auto_test_connection()
        self.load_default_workflow()

    def log(self, message, level="INFO"):
        timestamp = time.strftime("%H:%M:%S")
        print(f"[{timestamp}] [{level}] {message}")

    def init_ui(self):
        self.setWindowTitle("Charon - v1.0")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setGeometry(100, 100, 800, 600)

        main_layout = QVBoxLayout()
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        main_layout.addWidget(self.tab_widget)
        
        # Create workflow generation tab
        workflow_tab = QWidget()
        self.tab_widget.addTab(workflow_tab, "Workflow")
        self.init_workflow_tab(workflow_tab)
        
        # Create scene monitoring tab
        monitoring_tab = QWidget()
        self.tab_widget.addTab(monitoring_tab, "Scene Nodes")
        self.init_monitoring_tab(monitoring_tab)
        
        # Footer for workflow breadcrumb
        self.workflow_footer = QLabel("")
        self.workflow_footer.setStyleSheet("color: #666; font-size: 10px; padding: 4px;")
        self.workflow_footer.setAlignment(Qt.AlignLeft)
        main_layout.addWidget(self.workflow_footer)
        
        self.setLayout(main_layout)
        self.populate_workflows(load=False)
    
    def init_workflow_tab(self, parent):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)

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
        layout.addWidget(conn_group)

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
        layout.addWidget(workflow_group)

        # Node generation
        spawn_group = QGroupBox("Generate CharonOp Node")
        spawn_layout = QVBoxLayout()
        spawn_layout.addWidget(QLabel("Create a CharonOp node in the Node Graph with the selected workflow:"))
        self.spawn_node_btn = QPushButton("Generate CharonOp Node")
        self.spawn_node_btn.clicked.connect(self.spawn_charon_node)
        spawn_layout.addWidget(self.spawn_node_btn)
        spawn_group.setLayout(spawn_layout)
        layout.addWidget(spawn_group)

        parent.setLayout(layout)
    
    def init_monitoring_tab(self, parent):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Header with refresh controls and space for future filters
        header_layout = QVBoxLayout()
        
        # Top row: title and controls
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("CharonOp Nodes in Scene:"))
        top_row.addStretch()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_nodes_table)
        top_row.addWidget(refresh_btn)
        
        auto_refresh_btn = QPushButton("Auto Refresh")
        auto_refresh_btn.setCheckable(True)
        auto_refresh_btn.toggled.connect(self.toggle_auto_refresh)
        top_row.addWidget(auto_refresh_btn)
        self.auto_refresh_button = auto_refresh_btn

        auto_import_checkbox = QCheckBox("Auto-import outputs")
        auto_import_checkbox.setChecked(True)
        auto_import_checkbox.toggled.connect(self.on_auto_import_toggled)
        top_row.addWidget(auto_import_checkbox)
        self.auto_import_checkbox = auto_import_checkbox
        
        header_layout.addLayout(top_row)
        
        # Space for future filter row (search box, status chips, etc.)
        # This can be uncommented and populated later without major restructuring:
        # filter_row = QHBoxLayout()
        # filter_row.addWidget(QLabel("Filter:"))
        # search_edit = QLineEdit()
        # search_edit.setPlaceholderText("Search nodes...")
        # filter_row.addWidget(search_edit)
        # status_filter = QComboBox()
        # status_filter.addItems(["All", "Ready", "Processing", "Completed", "Error"])
        # filter_row.addWidget(status_filter)
        # filter_row.addStretch()
        # header_layout.addLayout(filter_row)
        
        layout.addLayout(header_layout)
        
        # Table for CharonOp nodes
        self.nodes_table = QTableWidget()
        self.nodes_table.setColumnCount(4)
        self.nodes_table.setHorizontalHeaderLabels(["Node Name", "Status", "Workflow", "Actions"])
        self.nodes_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.nodes_table.setAlternatingRowColors(True)
        self.nodes_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.nodes_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.nodes_table.setFocusPolicy(Qt.NoFocus)
        self.nodes_table.setStyleSheet(SCENE_NODE_TABLE_STYLE)
        
        # Set up progress bar delegate for status column
        progress_delegate = ProgressBarDelegate()
        self.nodes_table.setItemDelegateForColumn(1, progress_delegate)
        
        # Configure table
        header = self.nodes_table.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setStretchLastSection(True)
        header.resizeSection(0, 150)
        header.resizeSection(1, 200)
        header.resizeSection(2, 150)
        
        vertical_header = self.nodes_table.verticalHeader()
        if vertical_header:
            vertical_header.setVisible(False)
            vertical_header.setDefaultSectionSize(28)
        
        self.nodes_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.nodes_table.customContextMenuRequested.connect(self.show_context_menu)
        self.nodes_table.itemSelectionChanged.connect(self.on_node_selection_changed)
        self.nodes_table.itemDoubleClicked.connect(self.on_node_double_clicked)
        
        layout.addWidget(self.nodes_table)
        parent.setLayout(layout)
        
        # Start with an initial refresh
        auto_refresh_btn.setChecked(True)
        self.refresh_nodes_table()
    
    def get_status_payload(self, node):
        """Return the parsed status payload stored on the node."""
        if not node:
            return {}
        raw_value = None
        try:
            raw_value = node.metadata("charon/status_payload")
        except Exception:
            raw_value = None
        if not raw_value:
            try:
                knob = node.knob('charon_status_payload')
                if knob:
                    raw_value = knob.value()
            except Exception:
                raw_value = None
        if not raw_value:
            return {}
        try:
            return json.loads(raw_value)
        except Exception as exc:
            self.log(f"Could not parse status payload for {node.name()}: {exc}", "WARNING")
            return {}

    def read_node_auto_import(self, node):
        """Determine if auto-import is enabled for the given node."""
        try:
            knob = node.knob('charon_auto_import')
            if knob is not None:
                try:
                    return bool(int(knob.value()))
                except Exception:
                    return bool(knob.value())
        except Exception:
            pass
        try:
            meta = node.metadata('charon/auto_import')
            if isinstance(meta, str):
                lowered = meta.strip().lower()
                if lowered in {'0', 'false', 'off', 'no'}:
                    return False
                if lowered in {'1', 'true', 'on', 'yes'}:
                    return True
            elif meta is not None:
                return bool(meta)
        except Exception:
            pass
        payload = self.get_status_payload(node)
        if payload:
            auto_val = payload.get('auto_import')
            if isinstance(auto_val, bool):
                return auto_val
            if isinstance(auto_val, (int, float)):
                return bool(auto_val)
        return True

    def set_node_auto_import(self, node, enabled):
        """Persist the auto-import preference on the node."""
        value_num = 1 if enabled else 0
        try:
            knob = node.knob('charon_auto_import')
            if knob is not None:
                knob.setValue(value_num)
        except Exception:
            pass
        try:
            node.setMetaData('charon/auto_import', '1' if enabled else '0')
        except Exception:
            pass
        payload = self.get_status_payload(node)
        if payload:
            payload['auto_import'] = enabled
            try:
                node.setMetaData('charon/status_payload', json.dumps(payload))
            except Exception:
                pass

    @staticmethod
    def format_timestamp(timestamp):
        """Format a timestamp float into a human-readable string."""
        if not timestamp:
            return ""
        try:
            ts = float(timestamp)
        except Exception:
            return ""
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        except Exception:
            return ""

    def refresh_nodes_table(self):
        """Refresh the CharonOp nodes table with current status."""
        if not self.nodes_table:
            return
        
        try:
            # Find all CharonOp nodes in the current script
            charon_nodes = []
            for node in nuke.allNodes():
                if node.Class() == "Group" and node.name().startswith("CharonOp_"):
                    charon_nodes.append(node)
            
            # Track which rows need updates to avoid unnecessary repaints
            current_data = {}
            auto_import_values = []

            for node in charon_nodes:
                try:
                    status_raw = node.knob('charon_status').value()
                    progress = node.knob('charon_progress').value()
                    workflow_path = ""
                    try:
                        workflow_path = node.knob('workflow_path').value()
                    except:
                        pass
                    payload = self.get_status_payload(node)
                    display_status = payload.get('message') or status_raw
                    lifecycle = payload.get('state')
                    if not lifecycle:
                        if progress < 0:
                            lifecycle = "Error"
                        elif progress >= 1.0:
                            lifecycle = "Completed"
                        elif display_status and "process" in display_status.lower():
                            lifecycle = "Processing"
                        else:
                            lifecycle = status_raw or "Ready"
                    updated_at = payload.get('updated_at')
                    output_path = payload.get('output_path')
                    auto_import = payload.get('auto_import')
                    if auto_import is None:
                        auto_import = self.read_node_auto_import(node)
                    auto_import_values.append(auto_import)
                    
                    # Extract workflow name from metadata/knob/path
                    workflow_name = ""
                    try:
                        workflow_name = node.metadata('charon/workflow_name') or ""
                    except Exception:
                        workflow_name = ""
                    if not workflow_name:
                        try:
                            name_knob = node.knob('charon_workflow_name')
                            if name_knob:
                                workflow_name = name_knob.value()
                        except Exception:
                            workflow_name = ""
                    if not workflow_name and payload.get('workflow_name'):
                        workflow_name = payload.get('workflow_name')
                    if not workflow_name and workflow_path:
                        workflow_name = os.path.splitext(os.path.basename(workflow_path))[0]
                    if not workflow_name:
                        workflow_name = node.name()
                    
                    current_data[node.name()] = {
                        'node': node,
                        'status': display_status,
                        'status_raw': status_raw,
                        'state': lifecycle,
                        'progress': progress,
                        'workflow': workflow_name,
                        'updated_at': updated_at,
                        'payload': payload,
                        'output_path': output_path,
                        'auto_import': auto_import,
                    }
                except Exception as e:
                    self.log(f"Error reading node data for {node.name()}: {e}", "WARNING")
            
            if auto_import_values:
                combined = all(auto_import_values)
                if combined != self.auto_import_enabled:
                    self.auto_import_enabled = combined
                if (
                    self.auto_import_checkbox
                    and self.auto_import_checkbox.isChecked() != combined
                ):
                    self.auto_import_checkbox.blockSignals(True)
                    self.auto_import_checkbox.setChecked(combined)
                    self.auto_import_checkbox.blockSignals(False)

            # Only update table if data changed
            if current_data != self.last_node_data:
                self.last_node_data = current_data
                self.update_nodes_table(current_data)
        except Exception as e:
            self.log(f"Error refreshing nodes table: {e}", "ERROR")
    
    def update_nodes_table(self, node_data):
        """Update the table with node data."""
        self.nodes_table.setRowCount(len(node_data))
        
        for row, (node_name, data) in enumerate(node_data.items()):
            # Node name
            name_item = QTableWidgetItem(node_name)
            self.nodes_table.setItem(row, 0, name_item)
            
            # Status with progress bar
            status_item = QTableWidgetItem()
            progress = data['progress']
            status_display = data['status']
            lifecycle = data.get('state')
            payload = data.get('payload') or {}
            auto_import = data.get('auto_import')
            output_path = data.get('output_path') or payload.get('output_path')
            if not output_path:
                try:
                    knob = data['node'].knob('charon_last_output')
                    if knob:
                        value = knob.value()
                        if value:
                            output_path = value
                except Exception:
                    pass
            if not output_path:
                try:
                    meta_path = data['node'].metadata('charon/last_output')
                    if meta_path:
                        output_path = meta_path
                except Exception:
                    pass
            if output_path:
                output_path = str(output_path).strip()
            
            # Store progress data for custom delegate
            status_item.setData(Qt.UserRole, (progress, status_display))
            if progress > 0 and progress < 1.0:
                status_text = f"{status_display} ({progress:.0%})"
            elif progress >= 1.0 and status_display:
                status_text = f"{status_display} (100%)"
            else:
                status_text = status_display or data.get('status_raw', '')
            status_item.setText(status_text)

            tooltip_lines = []
            if lifecycle:
                tooltip_lines.append(f"State: {lifecycle}")
            message = payload.get('message')
            if message and message != lifecycle:
                tooltip_lines.append(f"Message: {message}")
            if auto_import is not None:
                tooltip_lines.append(f"Auto Import: {'Enabled' if auto_import else 'Disabled'}")
            updated_at = payload.get('updated_at') or data.get('updated_at')
            formatted_time = self.format_timestamp(updated_at)
            if formatted_time:
                tooltip_lines.append(f"Updated: {formatted_time}")
            if output_path:
                tooltip_lines.append(f"Output: {output_path}")
            elapsed = payload.get('elapsed_time')
            if isinstance(elapsed, (int, float)) and elapsed >= 0:
                tooltip_lines.append(f"Elapsed: {elapsed:.1f}s")
            last_error = payload.get('last_error') or payload.get('error')
            if last_error:
                tooltip_lines.append(f"Error: {last_error}")
            prompt_id = payload.get('prompt_id')
            if prompt_id:
                tooltip_lines.append(f"Prompt ID: {prompt_id}")
            if tooltip_lines:
                status_item.setToolTip("\n".join(tooltip_lines))
            self.nodes_table.setItem(row, 1, status_item)
            
            # Workflow
            workflow_item = QTableWidgetItem(data['workflow'])
            self.nodes_table.setItem(row, 2, workflow_item)
            
            # Actions column with import button
            actions_item = QTableWidgetItem("")
            self.nodes_table.setItem(row, 3, actions_item)
            actions_widget = QWidget()
            actions_layout = QHBoxLayout()
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(4)
            actions_layout.setAlignment(Qt.AlignCenter)

            import_button = QPushButton("Import Output")
            import_button.setEnabled(bool(output_path))
            import_button.clicked.connect(partial(self.import_node_output, data['node']))
            if output_path:
                import_button.setToolTip(output_path)
            else:
                import_button.setToolTip("Output not available yet")
            actions_layout.addWidget(import_button)
            actions_widget.setLayout(actions_layout)
            self.nodes_table.setCellWidget(row, 3, actions_widget)
            
            # Store node reference for context menu
            name_item.setData(Qt.UserRole, data['node'])
            if tooltip_lines:
                name_item.setToolTip("\n".join(tooltip_lines))
    
    def toggle_auto_refresh(self, enabled):
        """Toggle automatic table refresh."""
        if self.auto_refresh_button:
            label = "Auto Refresh (On)" if enabled else "Auto Refresh (Off)"
            if self.auto_refresh_button.text() != label:
                self.auto_refresh_button.setText(label)
        if enabled:
            self.refresh_timer.start(2000)  # Refresh every 2 seconds
            self.log("Auto-refresh enabled (2s interval)")
        else:
            self.refresh_timer.stop()
            self.log("Auto-refresh disabled")

    def on_auto_import_toggled(self, enabled):
        """Toggle automatic Read-node creation when jobs finish."""
        self.auto_import_enabled = enabled
        for node in nuke.allNodes():
            if node.Class() == "Group" and node.name().startswith("CharonOp_"):
                self.set_node_auto_import(node, enabled)
        self.refresh_nodes_table()
    
    def on_node_selection_changed(self):
        """Handle node selection change to update footer."""
        current_row = self.nodes_table.currentRow()
        if current_row >= 0:
            name_item = self.nodes_table.item(current_row, 0)
            if name_item:
                node = name_item.data(Qt.UserRole)
                if node:
                    self.selected_node_name = node.name()
                    self.update_workflow_footer(node)
                    return
        
        self.selected_node_name = ""
        self.workflow_footer.setText("")
    
    def update_workflow_footer(self, node):
        """Update the workflow breadcrumb footer for selected node."""
        try:
            workflow_path = node.knob('workflow_path').value()
            if workflow_path:
                workflow_name = os.path.splitext(os.path.basename(workflow_path))[0]
                footer_text = f"Workflow: {workflow_name} | Path: {workflow_path}"
                self.workflow_footer.setText(footer_text)
                # Set tooltip with full path
                self.workflow_footer.setToolTip(workflow_path)
            else:
                self.workflow_footer.setText(f"Node: {node.name()} | No workflow path available")
        except Exception as e:
            self.workflow_footer.setText(f"Node: {node.name()} | Error reading workflow info")
    
    def show_context_menu(self, position):
        """Show context menu for selected CharonOp node."""
        item = self.nodes_table.itemAt(position)
        if not item:
            return
        
        # Get the node from the first column (name)
        row = item.row()
        name_item = self.nodes_table.item(row, 0)
        if not name_item:
            return
        
        node = name_item.data(Qt.UserRole)
        if not node:
            return
        
        menu = QMenu(self)
        
        # Process Node action with confirmation
        process_action = menu.addAction("Process Node…")
        process_action.triggered.connect(lambda: self.process_node_with_confirmation(node))
        
        # Check if node is currently processing to disable action
        try:
            payload = self.get_status_payload(node)
            lifecycle = payload.get('state') or node.knob('charon_status').value()
            if isinstance(lifecycle, str) and lifecycle.lower().startswith("processing"):
                process_action.setEnabled(False)
                process_action.setText("Process Node… (Running)")
        except Exception:
            pass
        
        # Open Results Folder
        results_action = menu.addAction("Open Results Folder")
        results_action.triggered.connect(lambda: self.open_results_folder(node))
        
        menu.addSeparator()
        
        # Misc submenu
        misc_menu = menu.addMenu("Misc")
        
        # Open Workflow Location
        workflow_action = misc_menu.addAction("Open Workflow Location")
        workflow_action.triggered.connect(lambda: self.open_workflow_location(node))
        
        # Copy Converted API Workflow
        copy_api_action = misc_menu.addAction("Copy Converted API Workflow")
        copy_api_action.triggered.connect(lambda: self.copy_converted_workflow(node))
        
        # Copy Info
        copy_info_action = misc_menu.addAction("Copy Info")
        copy_info_action.triggered.connect(lambda: self.copy_node_info(node))
        
        menu.exec_(self.nodes_table.mapToGlobal(position))
    
    def process_node_with_confirmation(self, node):
        """Process node with confirmation dialog."""
        reply = QMessageBox.question(
            self, 
            "Confirm Processing",
            f"Process node '{node.name()}' with ComfyUI?\n\nThis will render connected inputs and submit the workflow.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # Execute the node's process knob
                process_knob = node.knob('process')
                if process_knob:
                    process_knob.execute()
                    self.log(f"Started processing {node.name()}")
                else:
                    QMessageBox.warning(self, "Error", "Process knob not found on node")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to process node: {e}")
                self.log(f"Error processing {node.name()}: {e}", "ERROR")
    
    def import_node_output(self, node):
        """Import the latest output for a node into the script as a Read node."""
        try:
            payload = self.get_status_payload(node)
            output_path = (payload or {}).get('output_path')
            if not output_path:
                try:
                    knob = node.knob('charon_last_output')
                    if knob:
                        output_path = knob.value()
                except Exception:
                    output_path = None
            if not output_path:
                try:
                    meta_path = node.metadata('charon/last_output')
                    if meta_path:
                        output_path = meta_path
                except Exception:
                    output_path = None
            if not output_path:
                QMessageBox.warning(self, "Import Output", "No output available for this node yet.")
                return
            output_path = output_path.strip()
            if not os.path.exists(output_path):
                QMessageBox.warning(
                    self,
                    "Import Output",
                    f"Output file not found:\n{output_path}\n\nIt may have been moved or deleted.",
                )
                return

            sanitized_path = output_path.replace("\\", "/")

            def create_read():
                try:
                    read_node = nuke.createNode('Read')
                    read_node['file'].setValue(sanitized_path)
                    read_node.setXpos(node.xpos() + 200)
                    read_node.setYpos(node.ypos())
                    read_node.setSelected(True)
                    self.log(f"Imported output for {node.name()} -> {output_path}")
                except Exception as exc:
                    self.log(f"Error importing output: {exc}", "ERROR")
                    QMessageBox.critical(self, "Error", f"Failed to import output: {exc}")

            nuke.executeInMainThread(create_read)

        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to import output: {exc}")
            self.log(f"Error importing output for {node.name()}: {exc}", "ERROR")
    
    def open_results_folder(self, node):
        """Open the results folder for the node."""
        try:
            temp_dir = node.knob('charon_temp_dir').value()
            if temp_dir:
                results_dir = os.path.join(temp_dir, 'results')
                if os.path.exists(results_dir):
                    os.startfile(results_dir)  # Windows-specific
                else:
                    os.makedirs(results_dir, exist_ok=True)
                    os.startfile(results_dir)
            else:
                QMessageBox.warning(self, "Error", "Temp directory not found on node")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open results folder: {e}")
    
    def open_workflow_location(self, node):
        """Open the workflow file location in Explorer."""
        try:
            workflow_path = node.knob('workflow_path').value()
            if workflow_path and os.path.exists(workflow_path):
                # Open Explorer with file selected
                os.system(f'explorer /select,"{workflow_path}"')
            else:
                QMessageBox.warning(self, "Error", "Workflow file not found")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open workflow location: {e}")
    
    def copy_converted_workflow(self, node):
        """Copy the converted API workflow to clipboard."""
        try:
            workflow_data = node.knob('workflow_data').value()
            if workflow_data:
                clipboard = QApplication.clipboard()
                clipboard.setText(workflow_data)
                QMessageBox.information(self, "Success", "Converted workflow copied to clipboard")
            else:
                QMessageBox.warning(self, "Error", "No workflow data found on node")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to copy workflow: {e}")
    
    def copy_node_info(self, node):
        """Copy node information to clipboard."""
        try:
            info_lines = [
                f"Node: {node.name()}",
                f"Class: {node.Class()}",
                f"Status: {node.knob('charon_status').value()}",
                f"Progress: {node.knob('charon_progress').value():.1%}",
            ]
            payload = self.get_status_payload(node)
            if payload:
                lifecycle = payload.get('state')
                if lifecycle:
                    info_lines.append(f"State: {lifecycle}")
                message = payload.get('message')
                if message and message != lifecycle:
                    info_lines.append(f"Message: {message}")
                auto_import = payload.get('auto_import')
                if auto_import is not None:
                    info_lines.append(f"Auto Import: {'Enabled' if auto_import else 'Disabled'}")
                updated = self.format_timestamp(payload.get('updated_at'))
                if updated:
                    info_lines.append(f"Updated: {updated}")
                prompt_id = payload.get('prompt_id')
                if prompt_id:
                    info_lines.append(f"Prompt ID: {prompt_id}")
                elapsed = payload.get('elapsed_time')
                if isinstance(elapsed, (int, float)):
                    info_lines.append(f"Elapsed: {elapsed:.1f}s")
                output_path = payload.get('output_path')
                if output_path:
                    info_lines.append(f"Output: {output_path}")
                last_error = payload.get('last_error') or payload.get('error')
                if last_error:
                    info_lines.append(f"Last Error: {last_error}")
            
            try:
                workflow_path = node.knob('workflow_path').value()
                if workflow_path:
                    info_lines.append(f"Workflow: {os.path.basename(workflow_path)}")
                    info_lines.append(f"Path: {workflow_path}")
            except:
                pass
            
            try:
                temp_dir = node.knob('charon_temp_dir').value()
                if temp_dir:
                    info_lines.append(f"Temp Dir: {temp_dir}")
            except:
                pass
            
            info_text = "\n".join(info_lines)
            clipboard = QApplication.clipboard()
            clipboard.setText(info_text)
            QMessageBox.information(self, "Success", "Node information copied to clipboard")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to copy node info: {e}")
    
    def on_node_double_clicked(self, item):
        """Handle double-click on node to center it in the node graph."""
        try:
            # Get the node from the first column (name)
            row = item.row()
            name_item = self.nodes_table.item(row, 0)
            if not name_item:
                return
            
            node = name_item.data(Qt.UserRole)
            if not node:
                return
            
            # Center the node graph on this node
            # Clear current selection and select this node
            for n in nuke.selectedNodes():
                n.setSelected(False)
            
            node.setSelected(True)
            
            # Center the view on the node
            # This uses Nuke's viewer centering functionality
            nuke.zoom(1.0, [node.xpos() + node.screenWidth()//2, node.ypos() + node.screenHeight()//2])
            
            self.log(f"Centered view on {node.name()}")
            
        except Exception as e:
            self.log(f"Error centering on node: {e}", "ERROR")

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

        self.set_node_auto_import(node, self.auto_import_enabled)

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
        self.refresh_nodes_table()
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
    node = nuke.thisNode()
    payload_raw = None
    try:
        payload_raw = node.metadata('charon/status_payload')
    except Exception:
        payload_raw = None
    if not payload_raw:
        try:
            knob = node.knob('charon_status_payload')
            if knob:
                payload_raw = knob.value()
        except Exception:
            payload_raw = None
    print('Status:', node.knob('charon_status').value())
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
            print('Payload:')
            print(json.dumps(payload, indent=2))
        except Exception:
            print('Payload (raw):', payload_raw)
    else:
        print('Payload: <empty>')
    result_dir = os.path.join({json.dumps(temp_root)}, 'results')
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
                    widget.setWindowFlag(Qt.WindowStaysOnTopHint, True)
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
