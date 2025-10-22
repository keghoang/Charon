from __future__ import annotations

import json
import os
import time
from typing import Dict, Optional

from ..qt_compat import QtWidgets, QtCore, Qt, QtGui
from .. import config
from ..galt_logger import system_debug, system_warning, system_error
from .. import scene_nodes_runtime as runtime


class _ProgressDelegate(QtWidgets.QStyledItemDelegate):
    """Render table progress cells with lightweight progress bars."""

    BASE_COLOR_EVEN = QtGui.QColor("#2c2c2c")
    BASE_COLOR_ODD = QtGui.QColor("#343434")
    SELECTION_COLOR = QtGui.QColor("#3d566f")
    TEXT_COLOR = QtGui.QColor("#f4f4f4")
    BORDER_COLOR = QtGui.QColor("#4a4a4a")
    ERROR_COLOR = QtGui.QColor("#c94d4d")
    COMPLETE_COLOR = QtGui.QColor("#3d995b")
    ACTIVE_COLOR = QtGui.QColor("#d0a23f")
    IDLE_COLOR = QtGui.QColor("#565656")

    def paint(self, painter, option, index):
        progress_data = index.data(Qt.UserRole)
        if progress_data is None:
            super().paint(painter, option, index)
            return

        progress, status, state = progress_data
        painter.save()

        base_color = self.BASE_COLOR_ODD if index.row() % 2 else self.BASE_COLOR_EVEN
        painter.fillRect(option.rect, self.SELECTION_COLOR if option.state & QtWidgets.QStyle.State_Selected else base_color)

        rect = option.rect.adjusted(4, 6, -4, -6)
        painter.setPen(QtGui.QPen(self.BORDER_COLOR, 1))
        painter.drawRect(rect)

        bar_rect = rect.adjusted(1, 1, -1, -1)
        fill_ratio = max(0.0, min(float(progress), 1.0))
        bar_width = int(bar_rect.width() * fill_ratio)

        if fill_ratio < 0:
            fill_color = self.ERROR_COLOR
        elif state == "Completed":
            fill_color = self.COMPLETE_COLOR
        elif state == "Processing":
            fill_color = self.ACTIVE_COLOR
        else:
            fill_color = self.IDLE_COLOR

        fill_rect = QtCore.QRect(bar_rect.left(), bar_rect.top(), max(0, bar_width), bar_rect.height())
        painter.fillRect(fill_rect, fill_color)

        painter.setPen(self.TEXT_COLOR)
        painter.drawText(rect, Qt.AlignCenter, status)
        painter.restore()


class SceneNodesPanel(QtWidgets.QWidget):
    """Prototype Scene Nodes panel mirroring production behaviour."""

    REFRESH_INTERVAL_MS = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh_nodes)

        self._last_snapshot: Dict[str, Dict[str, object]] = {}
        self._node_cache: Dict[str, runtime.SceneNodeInfo] = {}
        self._auto_import_enabled = True
        self._footer_text: Optional[str] = None

        self._build_ui()
        self.refresh_nodes()
        self._timer.start()

    # ------------------------------------------------------------------ UI setup

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        margin = getattr(config, "UI_WINDOW_MARGINS", 4)
        layout.setContentsMargins(margin, margin, margin, margin)
        layout.setSpacing(getattr(config, "UI_ELEMENT_SPACING", 6))

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setSpacing(6)

        title = QtWidgets.QLabel("CharonOp Nodes in Scene")
        title.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.refresh_button = QtWidgets.QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_nodes)
        header_layout.addWidget(self.refresh_button)

        self.auto_refresh_button = QtWidgets.QPushButton("Auto Refresh (On)")
        self.auto_refresh_button.setCheckable(True)
        self.auto_refresh_button.setChecked(True)
        self.auto_refresh_button.toggled.connect(self._toggle_auto_refresh)
        header_layout.addWidget(self.auto_refresh_button)

        self.auto_import_checkbox = QtWidgets.QCheckBox("Auto-import outputs")
        self.auto_import_checkbox.setChecked(True)
        self.auto_import_checkbox.toggled.connect(self._apply_auto_import)
        header_layout.addWidget(self.auto_import_checkbox)

        layout.addLayout(header_layout)

        self.table = QtWidgets.QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Node", "Status", "Workflow", "Actions"])
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #2c2c2c;
                alternate-background-color: #343434;
                color: #e2e2e2;
                gridline-color: #3d3d3d;
                border: 1px solid #3d3d3d;
                selection-background-color: #3d566f;
                selection-color: #f0f0f0;
            }
            QHeaderView::section {
                background-color: #373737;
                color: #d3d3d3;
                padding: 6px 4px;
                border: 1px solid #3d3d3d;
            }
        """)
        delegate = _ProgressDelegate(self.table)
        self.table.setItemDelegateForColumn(1, delegate)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.resizeSection(0, 160)
        header.resizeSection(1, 220)
        header.resizeSection(2, 160)

        vertical_header = self.table.verticalHeader()
        if vertical_header:
            vertical_header.setSectionResizeMode(QtWidgets.QHeaderView.Fixed)
            vertical_header.setDefaultSectionSize(32)
            vertical_header.hide()

        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemDoubleClicked.connect(self._on_double_click)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        layout.addWidget(self.table)

        self.info_label = QtWidgets.QLabel("")
        self.info_label.setWordWrap(False)
        self.info_label.setStyleSheet("color: #a0a0a0; font-size: 11px;")
        self.info_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.info_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.info_label.setFixedHeight(18)
        layout.addWidget(self.info_label)

    # ------------------------------------------------------------------ Refresh logic

    def refresh_nodes(self):
        infos = runtime.list_scene_nodes()
        self._node_cache = {info.name: info for info in infos}

        snapshot: Dict[str, Dict[str, object]] = {}
        for info in infos:
            snapshot[info.name] = {
                "status": info.status,
                "state": info.state,
                "progress": info.progress,
                "workflow": info.workflow_name,
                "updated": info.updated_at,
                "output": info.output_path,
                "auto": info.auto_import,
            }

        if snapshot != self._last_snapshot:
            self._last_snapshot = snapshot
            self._populate_table(infos)

        self._sync_auto_import_checkbox(infos)
        self._apply_footer_text()

    def _populate_table(self, infos):
        self.table.setRowCount(len(infos))
        for row, info in enumerate(infos):
            name_item = QtWidgets.QTableWidgetItem(info.name)
            name_item.setData(Qt.UserRole, info.name)
            tooltip = self._build_tooltip(info)
            if tooltip:
                name_item.setToolTip(tooltip)
            self.table.setItem(row, 0, name_item)

            status_item = QtWidgets.QTableWidgetItem()
            status_text = self._format_status_text(info)
            status_item.setText(status_text)
            status_item.setData(Qt.UserRole, (info.progress, status_text, info.state))
            if tooltip:
                status_item.setToolTip(tooltip)
            self.table.setItem(row, 1, status_item)

            workflow_item = QtWidgets.QTableWidgetItem(info.workflow_name)
            workflow_item.setToolTip(info.workflow_path or "")
            self.table.setItem(row, 2, workflow_item)

            actions_widget = QtWidgets.QWidget()
            actions_layout = QtWidgets.QHBoxLayout(actions_widget)
            actions_layout.setContentsMargins(0, 0, 0, 0)
            actions_layout.setSpacing(4)
            import_btn = QtWidgets.QPushButton("Import Output")
            import_btn.setEnabled(bool(info.output_path))
            import_btn.clicked.connect(lambda _=False, name=info.name: self._import_output(name))
            if info.output_path:
                import_btn.setToolTip(info.output_path)
            else:
                import_btn.setToolTip("Output not available yet")
            actions_layout.addWidget(import_btn)
            actions_layout.addStretch()
            self.table.setCellWidget(row, 3, actions_widget)

        self.table.resizeRowsToContents()

    # ------------------------------------------------------------------ UI helpers

    def _build_tooltip(self, info: runtime.SceneNodeInfo) -> str:
        lines = []
        lines.append(f"State: {info.state}")
        if info.status and info.state.lower() != info.status.lower():
            lines.append(f"Message: {info.status}")
        if info.auto_import is not None:
            lines.append(f"Auto Import: {'Enabled' if info.auto_import else 'Disabled'}")
        if info.updated_at:
            lines.append(f"Updated: {self._format_timestamp(info.updated_at)}")
        if info.output_path:
            lines.append(f"Output: {info.output_path}")
        payload = info.payload or {}
        elapsed = payload.get("elapsed_time")
        if isinstance(elapsed, (int, float)):
            lines.append(f"Elapsed: {elapsed:.1f}s")
        prompt_id = payload.get("prompt_id")
        if prompt_id:
            lines.append(f"Prompt ID: {prompt_id}")
        last_error = payload.get("last_error") or payload.get("error")
        if last_error:
            lines.append(f"Last Error: {last_error}")
        return "\n".join(lines)

    def _format_status_text(self, info: runtime.SceneNodeInfo) -> str:
        if info.progress >= 1.0:
            return f"{info.status or 'Completed'} (100%)"
        if info.progress > 0:
            return f"{info.status or 'Processing'} ({info.progress:.0%})"
        if info.progress < 0:
            return info.status or "Error"
        return info.status or info.state or "Ready"

    def _format_timestamp(self, timestamp: float) -> str:
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(timestamp)))
        except Exception:
            return ""

    def _sync_auto_import_checkbox(self, infos):
        if not infos:
            return
        combined = all(info.auto_import for info in infos)
        if combined != self._auto_import_enabled:
            self._auto_import_enabled = combined
        if self.auto_import_checkbox.isChecked() != combined:
            self.auto_import_checkbox.blockSignals(True)
            self.auto_import_checkbox.setChecked(combined)
            self.auto_import_checkbox.blockSignals(False)

    # ------------------------------------------------------------------ Slots

    def _toggle_auto_refresh(self, enabled: bool):
        label = "Auto Refresh (On)" if enabled else "Auto Refresh (Off)"
        if self.auto_refresh_button.text() != label:
            self.auto_refresh_button.setText(label)
        if enabled:
            self._timer.start()
            system_debug("Scene Nodes auto-refresh enabled.")
        else:
            self._timer.stop()
            system_debug("Scene Nodes auto-refresh disabled.")

    def _apply_auto_import(self, enabled: bool):
        for info in self._node_cache.values():
            runtime.set_auto_import(info.node, enabled, info.payload)
        self._auto_import_enabled = enabled
        self.refresh_nodes()

    def _on_selection_changed(self):
        node_name = self._selected_node_name()
        if not node_name:
            self._footer_text = None
            self.info_label.setText("")
            self.info_label.setToolTip("")
            return

        info = self._node_cache.get(node_name)
        if not info:
            self._footer_text = None
            self.info_label.setText("")
            self.info_label.setToolTip("")
            return

        if info.workflow_path:
            text = f"Workflow: {info.workflow_name} — {info.workflow_path}"
        else:
            text = f"Node: {info.name}"

        self._footer_text = text
        self._apply_footer_text()
        self.info_label.setToolTip(info.workflow_path or "")

    def _show_context_menu(self, position):
        item = self.table.itemAt(position)
        if not item:
            return

        name = item.data(Qt.UserRole)
        info = self._node_cache.get(name)
        if not info:
            return

        menu = QtWidgets.QMenu(self)

        process_action = menu.addAction("Process Node…")
        process_action.triggered.connect(lambda: self._process_node(info.node))
        if info.state.lower() == "processing":
            process_action.setEnabled(False)
            process_action.setText("Process Node… (Running)")

        open_results = menu.addAction("Open Results Folder")
        open_results.triggered.connect(lambda: self._open_results_folder(info))

        menu.addSeparator()
        misc_menu = menu.addMenu("Misc")

        open_workflow = misc_menu.addAction("Open Workflow Location")
        open_workflow.triggered.connect(lambda: self._open_workflow_location(info))

        copy_prompt = misc_menu.addAction("Copy Converted Workflow")
        copy_prompt.triggered.connect(lambda: self._copy_converted_workflow(info))

        copy_info = misc_menu.addAction("Copy Info")
        copy_info.triggered.connect(lambda: self._copy_node_info(info))

        menu.exec_(self.table.viewport().mapToGlobal(position))

    def _on_double_click(self, item):
        if not item:
            return
        name = item.data(Qt.UserRole)
        info = self._node_cache.get(name)
        if not info:
            return
        try:
            import nuke  # type: ignore
        except Exception:
            system_warning("Nuke module unavailable; cannot center on node.")
            return

        try:
            for node in nuke.selectedNodes():
                node.setSelected(False)
            info.node.setSelected(True)
            nuke.zoom(
                1.0,
                [
                    info.node.xpos() + info.node.screenWidth() // 2,
                    info.node.ypos() + info.node.screenHeight() // 2,
                ],
            )
            system_debug(f"Centered on {info.name}")
        except Exception as exc:
            system_warning(f"Failed to center on {info.name}: {exc}")

    # ------------------------------------------------------------------ Node actions

    def _selected_node_name(self) -> Optional[str]:
        current_row = self.table.currentRow()
        if current_row < 0:
            return None
        item = self.table.item(current_row, 0)
        if not item:
            return None
        return item.data(Qt.UserRole)

    def _process_node(self, node):
        reply = QtWidgets.QMessageBox.question(
            self,
            "Confirm Processing",
            f"Process node '{node.name()}' with ComfyUI?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply != QtWidgets.QMessageBox.Yes:
            return
        try:
            knob = node.knob("process")
            if knob:
                knob.execute()
                system_debug(f"Processing started for {node.name()}")
            else:
                QtWidgets.QMessageBox.warning(self, "Process Node", "Process knob not found.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Process Node", f"Failed to process node: {exc}")
            system_error(f"Failed to process {node.name()}: {exc}")

    def _import_output(self, node_name: str):
        info = self._node_cache.get(node_name)
        if not info:
            return
        output_path = info.output_path
        if not output_path:
            QtWidgets.QMessageBox.warning(self, "Import Output", "No output available yet.")
            return
        normalized = output_path.replace("\\", "/")
        if not os.path.exists(output_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Import Output",
                f"Output not found:\n{output_path}\nIt may have been moved or deleted.",
            )
            return

        try:
            import nuke  # type: ignore
        except Exception:
            QtWidgets.QMessageBox.critical(self, "Import Output", "Nuke is not available.")
            return

        def create_read():
            try:
                read_node = nuke.createNode("Read")
                read_node["file"].setValue(normalized)
                read_node.setXpos(info.node.xpos() + 200)
                read_node.setYpos(info.node.ypos())
                read_node.setSelected(True)
                system_debug(f"Imported output for {info.name} -> {output_path}")
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "Import Output", f"Failed to import output: {exc}")
                system_error(f"Failed to import output for {info.name}: {exc}")

        try:
            nuke.executeInMainThread(create_read)
        except Exception:
            create_read()

    def _open_results_folder(self, info: runtime.SceneNodeInfo):
        temp_dir = info.payload.get("temp_root") if info.payload else None
        if not temp_dir:
            temp_dir = getattr(info.node.knob("charon_temp_dir"), "value", lambda: "")()
        if not temp_dir:
            QtWidgets.QMessageBox.warning(self, "Results Folder", "Temp directory not configured on node.")
            return
        results_dir = os.path.join(temp_dir, "results")
        try:
            if not os.path.exists(results_dir):
                os.makedirs(results_dir, exist_ok=True)
            os.startfile(results_dir)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Results Folder", f"Failed to open folder: {exc}")

    def _open_workflow_location(self, info: runtime.SceneNodeInfo):
        workflow_path = info.workflow_path
        if not workflow_path:
            QtWidgets.QMessageBox.information(self, "Workflow Location", "Workflow path not available.")
            return
        if not os.path.exists(workflow_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Workflow Location",
                f"Workflow file not found:\n{workflow_path}",
            )
            return
        os.system(f'explorer /select,"{workflow_path}"')

    def _copy_converted_workflow(self, info: runtime.SceneNodeInfo):
        try:
            knob = info.node.knob("workflow_data")
            if not knob:
                QtWidgets.QMessageBox.warning(self, "Copy Workflow", "No workflow data found on node.")
                return
            data = knob.value()
            if not data:
                QtWidgets.QMessageBox.warning(self, "Copy Workflow", "Workflow data is empty.")
                return
            QtWidgets.QApplication.clipboard().setText(data)
            QtWidgets.QMessageBox.information(self, "Copy Workflow", "Converted workflow copied to clipboard.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Copy Workflow", f"Failed to copy workflow: {exc}")

    def _copy_node_info(self, info: runtime.SceneNodeInfo):
        lines = [
            f"Node: {info.name}",
            f"Status: {info.status}",
            f"State: {info.state}",
            f"Progress: {info.progress:.1%}",
        ]
        if info.workflow_name:
            lines.append(f"Workflow: {info.workflow_name}")
        if info.workflow_path:
            lines.append(f"Path: {info.workflow_path}")
        if info.output_path:
            lines.append(f"Output: {info.output_path}")
        if info.updated_at:
            lines.append(f"Updated: {self._format_timestamp(info.updated_at)}")
        payload = info.payload or {}
        last_error = payload.get("last_error") or payload.get("error")
        if last_error:
            lines.append(f"Last Error: {last_error}")
        prompt_id = payload.get("prompt_id")
        if prompt_id:
            lines.append(f"Prompt ID: {prompt_id}")
        auto = "Enabled" if info.auto_import else "Disabled"
        lines.append(f"Auto Import: {auto}")

        QtWidgets.QApplication.clipboard().setText("\n".join(lines))
        QtWidgets.QMessageBox.information(self, "Copy Info", "Node information copied to clipboard.")

    # ------------------------------------------------------------------ Helpers

    def _apply_footer_text(self):
        if not getattr(self, "info_label", None):
            return
        if not self._footer_text:
            self.info_label.setText("")
            return
        metrics = self.info_label.fontMetrics()
        width = max(self.info_label.width(), 200)
        elided = metrics.elidedText(self._footer_text, Qt.ElideMiddle, width)
        self.info_label.setText(elided)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_footer_text()
