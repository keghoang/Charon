"""
Tiny Mode Widget

Condensed CharonBoard surface that tracks the most relevant CharonOp progress.
"""

from __future__ import annotations

import os
from typing import Dict, Iterable, List, Optional

from ..qt_compat import QtWidgets, QtCore, QtGui
from .. import scene_nodes_runtime as runtime
from ..charon_logger import system_warning

# Import config with fallback
try:
    from .. import config
except ImportError:
    # Fallback for CLI usage
    class FallbackConfig:
        TINY_MODE_WIDTH = 250
        TINY_MODE_HEIGHT = 140
        TINY_MODE_MIN_WIDTH = 180
        TINY_MODE_MIN_HEIGHT = 120
    config = FallbackConfig()


class TinyModeWidget(QtWidgets.QWidget):
    """Compact widget that mirrors key CharonBoard state."""

    REFRESH_INTERVAL_MS = 2000

    exit_tiny_mode = QtCore.Signal()
    open_settings = QtCore.Signal()
    open_charon_board = QtCore.Signal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(config.TINY_MODE_MIN_WIDTH, config.TINY_MODE_MIN_HEIGHT)
        self._host: str = "None"
        self._latest_infos: List[runtime.SceneNodeInfo] = []
        self._info_lookup: Dict[str, runtime.SceneNodeInfo] = {}
        self._attached_comfy_widget: Optional[QtWidgets.QWidget] = None
        self._primed: bool = False
        self._has_displayed_nodes: bool = False
        self._empty_refresh_count: int = 0

        self._build_ui()

        self._refresh_timer = QtCore.QTimer(self)
        self._refresh_timer.setInterval(self.REFRESH_INTERVAL_MS)
        self._refresh_timer.timeout.connect(self._refresh_snapshot)
        self._refresh_timer.start()

    # ------------------------------------------------------------------ Public API

    def set_host(self, host: str) -> None:
        """Store the detected host to align behaviour with main UI."""
        self._host = host or "None"

    def prime_from_nodes(self, infos: Iterable[runtime.SceneNodeInfo]) -> None:
        """Seed the list before first refresh to avoid empty flashes."""
        self._apply_snapshot(infos, mark_primed=True)

    def update_from_scene_nodes(
        self, infos: Iterable[runtime.SceneNodeInfo]
    ) -> None:
        """Consume an externally provided snapshot of scene nodes."""
        self._apply_snapshot(infos, mark_primed=True)

    # ------------------------------------------------------------------ Qt events

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        menu = QtWidgets.QMenu(self)
        target_info = None
        if hasattr(self, "node_list") and self.node_list.isVisible():
            list_pos = self.node_list.viewport().mapFromGlobal(event.globalPos())
            item = self.node_list.itemAt(list_pos)
            if item:
                node_name = item.data(QtCore.Qt.UserRole)
                target_info = self._info_lookup.get(node_name)
        if target_info is None and self._latest_infos:
            target_info = self._latest_infos[0] if self._latest_infos else None

        if target_info:
            execute_action = menu.addAction("Execute")
            execute_action.triggered.connect(
                lambda _, info=target_info: self._execute_node(info)
            )

            import_action = menu.addAction("Import Output")
            import_action.setEnabled(self._has_output_path(target_info))
            import_action.triggered.connect(
                lambda _, info=target_info: self._import_output(info)
            )

            open_results = menu.addAction("Open Output Folder")
            open_results.setEnabled(self._has_output_path(target_info))
            open_results.triggered.connect(
                lambda _, info=target_info: self._open_output_folder(info)
            )
        else:
            menu.addAction("No CharonOps detected").setEnabled(False)

        if not menu.isEmpty():
            menu.addSeparator()

        open_board = menu.addAction("Open Full CharonBoard")
        open_board.triggered.connect(self.open_charon_board.emit)

        menu.addSeparator()
        exit_action = menu.addAction("Exit Tiny Mode")
        exit_action.setShortcutVisibleInContextMenu(True)
        exit_action.triggered.connect(self.exit_tiny_mode.emit)

        settings_action = menu.addAction("Settings...")
        settings_action.triggered.connect(self.open_settings.emit)

        menu.exec(event.globalPos())

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            child = self.childAt(event.pos())
            if child and hasattr(self, "node_list"):
                if child is self.node_list or self.node_list.isAncestorOf(child):
                    event.ignore()
                    return
            self.open_charon_board.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------ UI setup

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        surface_frame = QtWidgets.QFrame()
        surface_frame.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        surface_frame.setObjectName("tiny-mode-surface")
        surface_layout = QtWidgets.QVBoxLayout(surface_frame)
        surface_layout.setContentsMargins(0, 0, 0, 0)
        surface_layout.setSpacing(6)

        card_frame = QtWidgets.QFrame()
        card_frame.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        card_frame.setObjectName("tiny-mode-card")
        card_layout = QtWidgets.QStackedLayout(card_frame)
        card_layout.setContentsMargins(0, 0, 0, 0)

        self.empty_state_widget = QtWidgets.QWidget()
        self.empty_state_widget.setObjectName("tiny-mode-empty")
        empty_layout = QtWidgets.QVBoxLayout(self.empty_state_widget)
        empty_layout.setContentsMargins(12, 16, 12, 16)
        empty_layout.setSpacing(4)
        empty_layout.setAlignment(QtCore.Qt.AlignCenter)
        self.empty_state_label = QtWidgets.QLabel("Loading CharonOps...")
        self.empty_state_label.setAlignment(QtCore.Qt.AlignCenter)
        self.empty_state_label.setWordWrap(True)
        empty_font = self.empty_state_label.font()
        empty_font.setPointSize(max(9, empty_font.pointSize()))
        self.empty_state_label.setFont(empty_font)
        empty_layout.addStretch(1)
        empty_layout.addWidget(self.empty_state_label, 0, QtCore.Qt.AlignCenter)
        empty_layout.addStretch(1)

        self.node_list = QtWidgets.QListWidget()
        self.node_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.node_list.setFocusPolicy(QtCore.Qt.NoFocus)
        self.node_list.setUniformItemSizes(True)
        self.node_list.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.node_list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.node_list.setSpacing(6)
        self.node_list.itemDoubleClicked.connect(self._on_node_item_double_clicked)

        card_layout.addWidget(self.empty_state_widget)
        card_layout.addWidget(self.node_list)
        self._card_layout = card_layout

        surface_layout.addWidget(card_frame, 1)
        layout.addWidget(surface_frame, 1)

        footer_layout = QtWidgets.QHBoxLayout()
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.setSpacing(4)
        footer_layout.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self._comfy_placeholder_label = QtWidgets.QLabel("ComfyUI controls attach when Tiny Mode is active.")
        placeholder_font = self._comfy_placeholder_label.font()
        placeholder_font.setPointSize(max(8, placeholder_font.pointSize() - 1))
        self._comfy_placeholder_label.setFont(placeholder_font)
        self._comfy_placeholder_label.setStyleSheet("color: palette(mid);")
        self._comfy_placeholder_label.setWordWrap(True)
        footer_layout.addWidget(self._comfy_placeholder_label, 1)
        layout.addLayout(footer_layout)
        self._comfy_footer_layout = footer_layout

        self.setStyleSheet(
            """
            #tiny-mode-card {
                background-color: rgba(15, 23, 42, 0.85);
                border: 1px solid rgba(94, 106, 128, 0.4);
                border-radius: 8px;
            }
            #tiny-mode-card QListWidget {
                background-color: transparent;
                border: none;
            }
            #tiny-mode-empty QLabel {
                color: rgba(226, 232, 240, 0.8);
            }
            """
        )

    def attach_comfy_footer(self, widget: QtWidgets.QWidget) -> None:
        """Attach the shared ComfyUI footer widget to tiny mode."""
        if widget is None:
            return
        if self._attached_comfy_widget is widget:
            widget.setVisible(True)
            return

        if self._attached_comfy_widget is not None:
            self._comfy_footer_layout.removeWidget(self._attached_comfy_widget)
            self._attached_comfy_widget.setParent(None)
            self._attached_comfy_widget = None

        self._comfy_placeholder_label.hide()
        self._attached_comfy_widget = widget
        widget.setParent(self)
        if hasattr(widget, "set_compact_mode"):
            try:
                widget.set_compact_mode(True)
            except Exception:
                pass
        widget.setVisible(True)
        self._comfy_footer_layout.addWidget(widget, 0)

    def detach_comfy_footer(self) -> Optional[QtWidgets.QWidget]:
        """Detach the ComfyUI footer widget and return it for reattachment."""
        widget = self._attached_comfy_widget
        if widget is None:
            return None
        self._comfy_footer_layout.removeWidget(widget)
        widget.setParent(None)
        if hasattr(widget, "set_compact_mode"):
            try:
                widget.set_compact_mode(False)
            except Exception:
                pass
        self._attached_comfy_widget = None
        self._comfy_placeholder_label.show()
        return widget

    # ------------------------------------------------------------------ Refresh logic

    def _refresh_snapshot(self) -> None:
        try:
            infos = runtime.list_scene_nodes()
        except Exception as exc:
            system_warning(f"Tiny mode snapshot failed: {exc}")
            infos = []
        self.update_from_scene_nodes(infos)

    def _apply_snapshot(
        self, infos: Iterable[runtime.SceneNodeInfo], *, mark_primed: bool
    ) -> None:
        if mark_primed:
            self._primed = True
        normalized = list(infos) if infos else []
        self._latest_infos = sorted(normalized, key=self._priority_key)
        self._info_lookup = {
            info.name: info for info in normalized if getattr(info, "name", None)
        }
        if normalized:
            self._has_displayed_nodes = True
            self._empty_refresh_count = 0
        elif self._primed:
            self._empty_refresh_count += 1
        self._rebuild_node_list()

    def _rebuild_node_list(self) -> None:
        if not hasattr(self, "node_list"):
            return

        self.node_list.setUpdatesEnabled(False)
        self.node_list.clear()

        if not self._latest_infos:
            if hasattr(self, "empty_state_label"):
                if self._primed and (self._has_displayed_nodes or self._empty_refresh_count >= 2):
                    self.empty_state_label.setText("No CharonOps found")
                else:
                    self.empty_state_label.setText("Loading CharonOps...")
            if hasattr(self, "_card_layout") and hasattr(self, "empty_state_widget"):
                self._card_layout.setCurrentWidget(self.empty_state_widget)
            self.node_list.setUpdatesEnabled(True)
            return

        if hasattr(self, "_card_layout"):
            self._card_layout.setCurrentWidget(self.node_list)

        for info in self._latest_infos:
            item = QtWidgets.QListWidgetItem()
            item.setData(QtCore.Qt.UserRole, info.name)
            row_widget = _NodeRowWidget(self)
            row_widget.update_from_info(
                info,
                self._format_node_title(info),
                self._format_status_text(info),
            )
            item.setSizeHint(row_widget.sizeHint())
            self.node_list.addItem(item)
            self.node_list.setItemWidget(item, row_widget)

        self.node_list.setUpdatesEnabled(True)

    def _on_node_item_double_clicked(self, item: QtWidgets.QListWidgetItem) -> None:
        if item is None:
            return
        node_name = item.data(QtCore.Qt.UserRole)
        info = self._info_lookup.get(node_name)
        if not info:
            return
        self._focus_node(info)

    def _focus_node(self, info: runtime.SceneNodeInfo) -> None:
        if info is None:
            return

        focused = False
        node = getattr(info, "node", None)
        if node is not None:
            try:
                import nuke  # type: ignore
            except Exception:
                nuke = None
            if nuke is not None:
                try:
                    for existing in nuke.selectedNodes():
                        existing.setSelected(False)
                    node.setSelected(True)
                    width = 0
                    height = 0
                    try:
                        width = node.screenWidth()
                        height = node.screenHeight()
                    except Exception:
                        pass
                    center = [
                        node.xpos() + int(width / 2),
                        node.ypos() + int(height / 2),
                    ]
                    nuke.zoom(1.0, center)
                    focused = True
                except Exception as exc:
                    system_warning(f"Failed to focus node {info.name}: {exc}")

        if not focused:
            try:
                from .window_manager import WindowManager  # type: ignore
            except Exception:
                WindowManager = None
            if WindowManager is not None:
                try:
                    focused = WindowManager.focus_charon_board_node(info.name)
                except Exception:
                    focused = False

        if not focused:
            system_warning(f"Could not focus CharonOp {info.name}.")

    def _priority_key(self, info: runtime.SceneNodeInfo) -> tuple:
        state_lower = (info.state or "").lower()
        if info.progress < 0 or state_lower == "error":
            rank = 0
        elif state_lower == "processing":
            rank = 1
        elif info.progress > 0:
            rank = 2
        elif info.progress >= 1.0 or state_lower == "completed":
            rank = 3
        else:
            rank = 4
        updated = float(info.updated_at or 0.0)
        progress = float(info.progress if info.progress >= 0 else 0.0)
        return (rank, -updated, -progress)

    # ------------------------------------------------------------------ Helpers

    def _format_node_title(self, info: runtime.SceneNodeInfo) -> str:
        title = info.name or ""
        prefix = getattr(runtime, "NODE_PREFIX", "CharonOp_")
        if title.startswith(prefix):
            title = title[len(prefix) :]
        return title or "Unnamed CharonOp"

    def _format_status_text(self, info: runtime.SceneNodeInfo) -> str:
        status = info.status or info.state or "Ready"
        if info.progress < 0:
            return status
        if info.progress >= 1.0:
            return f"{status} (100%)"
        if info.progress > 0:
            return f"{status} ({info.progress:.0%})"
        return status

    def _has_output_path(self, info: runtime.SceneNodeInfo) -> bool:
        if info.output_path and os.path.exists(info.output_path):
            return True
        payload = info.payload or {}
        temp_root = payload.get("temp_root")
        if temp_root:
            candidate = os.path.join(temp_root, "results")
            if os.path.isdir(candidate):
                return True
        return False

    # ------------------------------------------------------------------ Context actions

    def _open_output_folder(self, info: Optional[runtime.SceneNodeInfo] = None) -> None:
        if not info:
            return
        folder = self._resolve_output_folder(info)
        if not folder:
            QtWidgets.QMessageBox.information(
                self,
                "Output Folder",
                "Unable to locate a results directory for this CharonOp.",
            )
            return
        if not QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder)):
            try:
                os.startfile(folder)
            except Exception as exc:
                QtWidgets.QMessageBox.critical(
                    self, "Output Folder", f"Failed to open folder: {exc}"
                )

    def _open_workflow_location(self, info: Optional[runtime.SceneNodeInfo] = None) -> None:
        if not info or not info.workflow_path:
            QtWidgets.QMessageBox.information(
                self,
                "Workflow Location",
                "Workflow path not available.",
            )
            return
        workflow_path = info.workflow_path
        if not os.path.exists(workflow_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Workflow Location",
                f"Workflow file not found:\n{workflow_path}",
            )
            return
        try:
            os.system(f'explorer /select,"{workflow_path}"')
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self, "Workflow Location", f"Failed to reveal workflow: {exc}"
            )

    def _copy_node_summary(self, info: Optional[runtime.SceneNodeInfo] = None) -> None:
        if not info:
            return
        lines = [
            f"Node: {info.name}",
            f"State: {info.state}",
            f"Status: {info.status}",
            f"Progress: {max(0.0, info.progress) * 100:.1f}%",
        ]
        if info.workflow_name:
            lines.append(f"Workflow: {info.workflow_name}")
        if info.workflow_path:
            lines.append(f"Workflow Path: {info.workflow_path}")
        if info.output_path:
            lines.append(f"Output Path: {info.output_path}")
        payload = info.payload or {}
        last_error = payload.get("last_error") or payload.get("error")
        if last_error:
            lines.append(f"Last Error: {last_error}")
        QtWidgets.QApplication.clipboard().setText("\n".join(lines))

    def _resolve_output_folder(self, info: runtime.SceneNodeInfo) -> Optional[str]:
        candidates = []
        if info.output_path:
            candidates.append(info.output_path)
        payload = info.payload or {}
        temp_root = payload.get("temp_root")
        if temp_root:
            candidates.append(os.path.join(temp_root, "results"))
        for path in candidates:
            if not path:
                continue
            resolved = path
            if os.path.isfile(resolved):
                resolved = os.path.dirname(resolved)
            if os.path.isdir(resolved):
                return resolved
        return None


class _NodeRowWidget(QtWidgets.QWidget):
    """Lightweight widget showing a node name with progress feedback."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(2)

        self.name_label = QtWidgets.QLabel("")
        name_font = self.name_label.font()
        name_font.setBold(True)
        self.name_label.setFont(name_font)
        self.name_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self.name_label)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setMinimumHeight(14)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.progress_bar)

        self._node_name: str = ""

    @property
    def node_name(self) -> str:
        return self._node_name

    def update_from_info(
        self,
        info: runtime.SceneNodeInfo,
        display_name: str,
        status_text: str,
    ) -> None:
        self._node_name = info.name
        self.name_label.setText(display_name)

        tooltip = info.workflow_path or info.workflow_name or ""
        self.name_label.setToolTip(tooltip)
        self.progress_bar.setToolTip(status_text)

        progress_value = 0
        if info.progress >= 0:
            progress_value = max(0, min(int(info.progress * 100), 100))
        self.progress_bar.setValue(progress_value)
        self.progress_bar.setFormat(status_text)
