from __future__ import annotations

import copy
import json
import os
from urllib.parse import urlparse
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..qt_compat import QtCore, QtGui, QtWidgets
from ..paths import resolve_comfy_environment
from ..charon_logger import system_debug
from ..validation_resolver import (
    ResolutionResult,
    determine_expected_model_path,
    find_local_model_matches,
    find_shared_model_matches,
    format_model_reference_for_workflow,
    resolve_missing_custom_nodes,
    resolve_missing_models,
)
from ..validation_cache import load_validation_log, save_validation_log
from ..workflow_overrides import replace_workflow_model_paths, save_workflow_override
from ..workflow_local_store import append_validation_resolve_entry


SUCCESS_COLOR = "#228B22"
VALIDATION_COLUMN_WIDTHS = (120, 80, 160, 80)
ACTION_BUTTON_WIDTH = 90
MODEL_CATEGORY_PREFIXES = {
    "diffusion_models",
    "checkpoints",
    "unet",
    "unets",
    "text_encoders",
    "text-encoders",
    "clip",
    "clip_vision",
    "clip-vision",
    "loras",
    "vae",
    "vae_approx",
    "vae-approx",
    "embeddings",
    "controlnet",
    "hypernetworks",
    "upscale_models",
    "upscale",
    "motion_models",
    "motion_loras",
    "styles",
    "style_models",
    "ipadapter",
}


class _FileCopyWorker(QtCore.QObject):
    progress = QtCore.Signal(int)
    finished = QtCore.Signal(bool, str)
    failed = QtCore.Signal(str)
    canceled = QtCore.Signal()

    def __init__(self, source: str, destination: str, parent: Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._source = source
        self._destination = destination
        self._cancel_requested = False

    @QtCore.Slot()
    def run(self) -> None:
        try:
            self._copy_with_progress()
        except Exception as exc:  # pragma: no cover - filesystem guard
            self.failed.emit(str(exc))

    def cancel(self) -> None:
        self._cancel_requested = True

    def _copy_with_progress(self) -> None:
        if not os.path.isfile(self._source):
            self.failed.emit("Source model file no longer exists.")
            return
        os.makedirs(os.path.dirname(self._destination), exist_ok=True)
        total = os.path.getsize(self._source)
        copied = 0
        chunk_size = 4 * 1024 * 1024
        temp_path = f"{self._destination}.tmp"

        try:
            with open(self._source, "rb") as src, open(temp_path, "wb") as dest:
                while True:
                    if self._cancel_requested:
                        self.canceled.emit()
                        return
                    chunk = src.read(chunk_size)
                    if not chunk:
                        break
                    dest.write(chunk)
                    copied += len(chunk)
                    percent = int((copied / total) * 100) if total else 0
                    self.progress.emit(min(percent, 100))
            os.replace(temp_path, self._destination)
            self.finished.emit(True, self._destination)
        finally:
            if os.path.exists(temp_path) and (self._cancel_requested or not os.path.exists(self._destination)):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


class ValidationResolveDialog(QtWidgets.QDialog):
    """Display validation results with auto-resolve helpers."""

    SUPPORTED_KEYS = {"models", "custom_nodes"}

    def __init__(
        self,
        payload: Dict[str, Any],
        *,
        workflow_name: str,
        comfy_path: str,
        workflow_bundle: Optional[Dict[str, Any]] = None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Validation Result - {workflow_name}")
        self._payload = payload or {}
        self._comfy_path = comfy_path or ""
        self._workflow_bundle = workflow_bundle or {}
        self._issue_lookup: Dict[str, Dict[str, Any]] = {}
        self._issue_widgets: Dict[str, Dict[str, Any]] = {}
        self._dependencies_cache: Optional[List[Dict[str, Any]]] = None
        self._workflow_folder: Optional[str] = None
        self._comfy_info = {}
        if self._comfy_path:
            try:
                self._comfy_info = resolve_comfy_environment(self._comfy_path) or {}
            except Exception:  # pragma: no cover - defensive guard
                self._comfy_info = {}
        workflow_payload = None
        if isinstance(self._workflow_bundle, dict):
            workflow_payload = self._workflow_bundle.get("workflow")
        self._workflow_override: Optional[Dict[str, Any]] = (
            copy.deepcopy(workflow_payload) if isinstance(workflow_payload, dict) else None
        )
        if isinstance(self._workflow_bundle, dict):
            self._workflow_folder = self._workflow_bundle.get("folder") or None

        self._load_cached_resolutions()
        self._custom_node_package_map: Optional[Dict[str, str]] = None

        self._build_ui()

    # --------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        intro = QtWidgets.QLabel(
            "Review the checklist below. Failed checks include auto-resolve helpers "
            "when possible."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        layout.addWidget(scroll)

        container = QtWidgets.QWidget()
        self._issues_layout = QtWidgets.QVBoxLayout(container)
        self._issues_layout.setContentsMargins(0, 0, 0, 0)
        self._issues_layout.setSpacing(10)
        scroll.setWidget(container)

        issues = self._payload.get("issues") or []
        if not issues:
            placeholder = QtWidgets.QLabel("No validation data available.")
            placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self._issues_layout.addWidget(placeholder)
        else:
            for issue in issues:
                if not isinstance(issue, dict):
                    continue
                widget = self._create_issue_widget(issue)
                if widget:
                    self._issues_layout.addWidget(widget)
            self._issues_layout.addStretch(1)

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, parent=self)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.resize(500, 540)

    def _create_issue_widget(self, issue: Dict[str, Any]) -> Optional[QtWidgets.QWidget]:
        key = str(issue.get("key") or "")
        if key == "models":
            return self._create_models_issue_widget(issue)
        if key == "custom_nodes":
            return self._create_custom_nodes_issue_widget(issue)
        return self._create_generic_issue_widget(issue)

    def _create_generic_issue_widget(self, issue: Dict[str, Any]) -> Optional[QtWidgets.QWidget]:
        key = str(issue.get("key") or "")
        label = str(issue.get("label") or "Check")
        summary = str(issue.get("summary") or "")
        details = issue.get("details") or []
        ok = bool(issue.get("ok"))

        frame = QtWidgets.QFrame(self)
        frame.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(10, 10, 10, 10)
        frame_layout.setSpacing(6)

        header_layout = QtWidgets.QHBoxLayout()
        status_label = QtWidgets.QLabel("\u2713 Passed" if ok else "\u2717 Failed")
        status_label.setStyleSheet(f"font-weight: bold; color: {'#228B22' if ok else '#B22222'};")
        title_label = QtWidgets.QLabel(label)
        title_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(status_label)
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        frame_layout.addLayout(header_layout)

        if summary:
            summary_label = QtWidgets.QLabel(summary)
            summary_label.setWordWrap(True)
            frame_layout.addWidget(summary_label)
        else:
            summary_label = None

        detail_labels: List[QtWidgets.QLabel] = []
        for detail in details:
            text = str(detail)
            if text.lower().startswith("cannot find"):
                continue
            detail_label = QtWidgets.QLabel(text)
            detail_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
            detail_label.setWordWrap(True)
            detail_labels.append(detail_label)
            frame_layout.addWidget(detail_label)

        auto_button = None
        if not ok and key in self.SUPPORTED_KEYS:
            auto_button = QtWidgets.QPushButton("Auto Resolve")
            auto_button.clicked.connect(lambda _checked=False, k=key: self._handle_auto_resolve(k))
            frame_layout.addWidget(auto_button, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

        self._issue_lookup[key] = issue
        self._issue_widgets[key] = {
            "frame": frame,
            "status_label": status_label,
            "summary_label": summary_label,
            "detail_labels": detail_labels,
            "button": auto_button,
        }
        return frame

    def _create_models_issue_widget(self, issue: Dict[str, Any]) -> Optional[QtWidgets.QWidget]:
        key = str(issue.get("key") or "")
        label = str(issue.get("label") or "Models")
        details = issue.get("details") or []
        ok = bool(issue.get("ok"))

        frame = QtWidgets.QFrame(self)
        frame.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(10, 10, 10, 10)
        frame_layout.setSpacing(6)

        header_layout = QtWidgets.QHBoxLayout()
        status_label = QtWidgets.QLabel("\u2713 Passed" if ok else "\u2717 Failed")
        status_label.setStyleSheet(f"font-weight: bold; color: {'#228B22' if ok else '#B22222'};")
        title_label = QtWidgets.QLabel(label)
        title_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(status_label)
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        frame_layout.addLayout(header_layout)

        detail_labels: List[QtWidgets.QLabel] = []
        for detail in details:
            text = str(detail)
            lowered = text.lower()
            if lowered.startswith("cannot find") or lowered.startswith("confirm the files exist"):
                continue
            detail_label = QtWidgets.QLabel(text)
            detail_label.setTextFormat(QtCore.Qt.TextFormat.RichText)
            detail_label.setWordWrap(True)
            detail_labels.append(detail_label)
            frame_layout.addWidget(detail_label)

        table = QtWidgets.QTableWidget(frame)
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Model", "Status", "Location", "Action"])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(False)
        for column in range(4):
            mode = (
                QtWidgets.QHeaderView.ResizeMode.Fixed
                if column in (2, 3)
                else QtWidgets.QHeaderView.ResizeMode.Interactive
            )
            table.horizontalHeader().setSectionResizeMode(column, mode)
        table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setTextElideMode(QtCore.Qt.TextElideMode.ElideMiddle)
        table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        table.verticalHeader().setDefaultSectionSize(26)
        table.setStyleSheet(
            "QTableWidget { font-size: 12px; }"
            "QPushButton { padding: 2px 8px; font-size: 11px; }"
        )
        for column, width in enumerate(VALIDATION_COLUMN_WIDTHS):
            table.setColumnWidth(column, width)
        frame_layout.addWidget(table)

        data = issue.get("data") or {}
        row_mapping = self._populate_models_table(table, data)

        self._issue_lookup[key] = issue
        self._issue_widgets[key] = {
            "frame": frame,
            "status_label": status_label,
            "detail_labels": detail_labels,
            "table": table,
            "rows": row_mapping,
        }
        self._refresh_models_issue_status()
        return frame

    def _create_custom_nodes_issue_widget(self, issue: Dict[str, Any]) -> Optional[QtWidgets.QWidget]:
        key = str(issue.get("key") or "")
        label = str(issue.get("label") or "Custom Nodes")
        ok = bool(issue.get("ok"))

        frame = QtWidgets.QFrame(self)
        frame.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        frame_layout = QtWidgets.QVBoxLayout(frame)
        frame_layout.setContentsMargins(10, 10, 10, 10)
        frame_layout.setSpacing(6)

        header_layout = QtWidgets.QHBoxLayout()
        status_label = QtWidgets.QLabel("\u2713 Passed" if ok else "\u2717 Failed")
        status_label.setStyleSheet(f"font-weight: bold; color: {'#228B22' if ok else '#B22222'};")
        title_label = QtWidgets.QLabel(label)
        title_label.setStyleSheet("font-weight: bold;")
        header_layout.addWidget(status_label)
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        frame_layout.addLayout(header_layout)

        summary_label = QtWidgets.QLabel(issue.get("summary") or "")
        summary_label.setWordWrap(True)
        frame_layout.addWidget(summary_label)

        table = QtWidgets.QTableWidget(frame)
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Node", "Status", "Package", "Action"])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(False)
        for column in range(4):
            mode = (
                QtWidgets.QHeaderView.ResizeMode.Fixed
                if column in (2, 3)
                else QtWidgets.QHeaderView.ResizeMode.Interactive
            )
            table.horizontalHeader().setSectionResizeMode(column, mode)
        table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        table.setTextElideMode(QtCore.Qt.TextElideMode.ElideMiddle)
        table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        table.verticalHeader().setDefaultSectionSize(26)
        table.setStyleSheet(
            "QTableWidget { font-size: 12px; }"
            "QPushButton { padding: 2px 8px; font-size: 11px; }"
        )
        for column, width in enumerate(VALIDATION_COLUMN_WIDTHS):
            table.setColumnWidth(column, width)
        frame_layout.addWidget(table)

        data = issue.get("data") or {}
        row_mapping = self._populate_custom_nodes_table(table, data)

        self._issue_lookup[key] = issue
        self._issue_widgets[key] = {
            "frame": frame,
            "status_label": status_label,
            "summary_label": summary_label,
            "table": table,
            "rows": row_mapping,
        }
        self._refresh_custom_nodes_issue_status()
        return frame

    def _load_cached_resolutions(self) -> None:
        if not self._workflow_folder:
            return
        cached = load_validation_log(self._workflow_folder)
        models_cache = cached.get("models") if isinstance(cached, dict) else {}
        if not isinstance(models_cache, dict):
            models_cache = {}
        resolved_entries = models_cache.get("resolved_entries") or []
        if not resolved_entries:
            return
        issues = self._payload.get("issues") or []
        for issue in issues:
            if issue.get("key") != "models":
                continue
            data = issue.setdefault("data", {})
            existing = data.get("resolved_entries") or []
            if not existing:
                data["resolved_entries"] = copy.deepcopy(resolved_entries)
            else:
                existing_paths = {
                    str(entry.get("path") or "").replace("\\", "/").lower()
                    for entry in existing
                    if isinstance(entry, dict)
                }
                for entry in resolved_entries:
                    if not isinstance(entry, dict):
                        continue
                    path_value = str(entry.get("path") or "")
                    if not path_value:
                        continue
                    normalized = path_value.replace("\\", "/").lower()
                    if normalized not in existing_paths:
                        existing.append(copy.deepcopy(entry))
                        existing_paths.add(normalized)

            resolved_list = data.get("resolved_entries") or []
            found = data.setdefault("found", [])
            for entry in resolved_list:
                if not isinstance(entry, dict):
                    continue
                path_value = entry.get("path")
                if path_value and path_value not in found:
                    found.append(path_value)

            missing = data.get("missing") or []
            data["missing"] = self._filter_missing_with_resolved(missing, resolved_list)
            break

    def _filter_missing_with_resolved(
        self,
        missing: Iterable[Dict[str, Any]],
        resolved_entries: Iterable[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        resolved_signatures: set[Tuple[str, str, str]] = set()
        resolved_matchers: set[str] = set()
        for entry in resolved_entries or []:
            if not isinstance(entry, dict):
                continue
            signature = entry.get("signature")
            if isinstance(signature, (list, tuple)) and len(signature) == 3:
                normalized_signature = tuple(
                    self._normalize_identifier(part) for part in signature
                )
                resolved_signatures.add(normalized_signature)  # type: ignore[arg-type]
            reference_name = entry.get("reference")
            original_reference = entry.get("original_reference")
            workflow_value = entry.get("workflow_value")
            path_value = entry.get("path")
            resolved_path = entry.get("resolved_path")
            for value in (
                reference_name,
                original_reference,
                workflow_value,
                path_value,
                resolved_path,
            ):
                normalized = self._normalize_identifier(value)
                if normalized:
                    resolved_matchers.add(normalized)
            for value in (path_value, resolved_path):
                if isinstance(value, str) and value:
                    normalized = self._normalize_identifier(os.path.basename(value))
                    if normalized:
                        resolved_matchers.add(normalized)
        filtered: List[Dict[str, Any]] = []
        for item in missing or []:
            if not isinstance(item, dict):
                continue
            signature_tuple = (
                self._normalize_identifier(item.get("name")),
                self._normalize_identifier(item.get("category")),
                self._normalize_identifier(item.get("node_type")),
            )
            if signature_tuple in resolved_signatures:
                continue
            candidate_values = {
                self._normalize_identifier(item.get("name")),
                self._normalize_identifier(os.path.basename(str(item.get("name") or ""))),
                self._normalize_identifier(item.get("path")),
            }
            raw_payload = item.get("raw")
            if isinstance(raw_payload, dict):
                candidate_values.add(self._normalize_identifier(raw_payload.get("name")))
                candidate_values.add(self._normalize_identifier(raw_payload.get("path")))
            candidate_values = {value for value in candidate_values if value}
            if candidate_values & resolved_matchers:
                continue
            filtered.append(item)
        return filtered

    def _populate_models_table(
        self,
        table: QtWidgets.QTableWidget,
        data: Dict[str, Any],
    ) -> Dict[int, Dict[str, Any]]:
        models_root = data.get("models_root") or ""
        found = data.get("found") or []
        missing = data.get("missing") or []
        if not missing:
            resolver_data = data.get("resolver") or {}
            resolver_missing = resolver_data.get("missing") or []
            fallback_missing: List[Dict[str, Any]] = []
            for entry in resolver_missing:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name") or entry.get("path") or ""
                fallback_missing.append(
                    {
                        "name": name,
                        "category": entry.get("category"),
                        "node_type": entry.get("node_type"),
                        "reason": entry.get("reason"),
                        "resolver_missing": True,
                        "raw": dict(entry),
                    }
                )
            if fallback_missing:
                missing = fallback_missing
                data["missing"] = missing
        resolved_entries = data.get("resolved_entries") or []

        resolved_lookup: Dict[str, Dict[str, str]] = {}
        for entry in resolved_entries:
            if not isinstance(entry, dict):
                continue
            entry_path = str(entry.get("path") or "")
            if not entry_path:
                continue
            normalized_path = entry_path.replace("\\", "/").lower()
            info = {
                "status": str(entry.get("status") or "Resolved"),
                "reference": str(entry.get("reference") or ""),
                "workflow_value": str(entry.get("workflow_value") or ""),
            }
            resolved_lookup[normalized_path] = info
            workflow_value = entry.get("workflow_value")
            if isinstance(workflow_value, str) and workflow_value:
                normalized_value = workflow_value.replace("\\", "/").lower()
                resolved_lookup[normalized_value] = info
        total_rows = len(found) + len(missing)
        if total_rows == 0:
            table.setRowCount(1)
            table.setColumnHidden(3, True)
            placeholder = QtWidgets.QTableWidgetItem("No model data reported.")
            placeholder.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            table.setItem(0, 0, placeholder)
            table.setSpan(0, 0, 1, 4)
            return {}

        table.setColumnHidden(3, False)
        table.setRowCount(total_rows)
        row_mapping: Dict[int, Dict[str, Any]] = {}

        row = 0
        for path in found:
            display = self._format_model_display_path(path, models_root)
            file_name = os.path.basename(path) or display
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(file_name))
            normalized_path = path.replace("\\", "/").lower()
            resolved_info = resolved_lookup.get(normalized_path)
            status_text = (resolved_info.get("status") or "Resolved") if resolved_info else "Found"
            status_item = QtWidgets.QTableWidgetItem(status_text)
            self._apply_status_style(status_item, status_text)
            table.setItem(row, 1, status_item)
            location_item = QtWidgets.QTableWidgetItem(display)
            location_item.setToolTip(display)
            font = location_item.font()
            if resolved_info:
                font.setBold(True)
                location_item.setFont(font)
                location_item.setForeground(QtGui.QBrush(QtGui.QColor(SUCCESS_COLOR)))
            else:
                font.setBold(False)
                location_item.setFont(font)
                location_item.setForeground(QtGui.QBrush(QtGui.QColor("#FFFFFF")))
            table.setItem(row, 2, location_item)
            placeholder_widget = QtWidgets.QWidget()
            table.setCellWidget(row, 3, placeholder_widget)
            row += 1

        for index, reference in enumerate(missing):
            name = str(reference.get("name") or "").strip()
            display_name = os.path.basename(name) if name else "Unknown Model"
            raw_data = reference.get("raw")
            if isinstance(raw_data, dict):
                searched_dirs = raw_data.get("searched")
                if isinstance(searched_dirs, list):
                    allowed_dirs = [
                        str(item) for item in searched_dirs if isinstance(item, str)
                    ]
                    if allowed_dirs:
                        reference.setdefault("attempted_directories", allowed_dirs)
                attempted_categories = raw_data.get("attempted")
                if isinstance(attempted_categories, list):
                    reference.setdefault(
                        "attempted_categories",
                        [
                            str(item)
                            for item in attempted_categories
                            if isinstance(item, str)
                        ],
                    )
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(display_name))
            status_item = QtWidgets.QTableWidgetItem("Missing")
            self._apply_status_style(status_item, "Missing")
            table.setItem(row, 1, status_item)
            location_text = name or "Not provided"
            location_item = QtWidgets.QTableWidgetItem(location_text)
            location_item.setToolTip(location_text)
            location_item.setForeground(QtGui.QBrush(QtGui.QColor("#B22222")))
            table.setItem(row, 2, location_item)
            button = QtWidgets.QPushButton("Resolve")
            button.setFixedHeight(24)
            button.setMaximumWidth(ACTION_BUTTON_WIDTH)
            button.setStyleSheet(
                "QPushButton {"
                " background-color: #B22222;"
                " color: white;"
                " border: none;"
                " border-radius: 4px;"
                " padding: 2px 8px;"
                " }"
                "QPushButton:hover {"
                " background-color: #9B1C1C;"
                " }"
                "QPushButton:disabled {"
                " background-color: #888888;"
                " color: #EEEEEE;"
                " }"
            )
            button.clicked.connect(lambda _checked=False, r=row: self._handle_model_auto_resolve(r))
            table.setCellWidget(row, 3, button)
            row_mapping[row] = {
                "reference": dict(reference),
                "missing_entry": reference,
                "reference_signature": (
                    reference.get("name"),
                    reference.get("category"),
                    reference.get("node_type"),
                ),
                "button": button,
                "status_item": status_item,
                "location_item": location_item,
                "models_root": models_root,
                "row_index": row,
                "reference_index": index,
                "original_location": location_text,
            }
            row += 1

        table.resizeRowsToContents()
        return row_mapping

    def _populate_custom_nodes_table(
        self,
        table: QtWidgets.QTableWidget,
        data: Dict[str, Any],
    ) -> Dict[int, Dict[str, Any]]:
        required = data.get("required") or []
        missing_entries = data.get("missing") or []
        dependencies = self._load_dependencies()

        self._ensure_custom_node_package_map()

        filtered_required: List[Tuple[str, str]] = []
        skip_nodes: set[str] = set()
        for node_name in required:
            node_type = str(node_name).strip()
            if not node_type:
                continue
            package_name = self._package_for_node_type(node_type) or "Unknown package"
            if package_name.lower() == "comfy-core":
                skip_nodes.add(node_type.lower())
                continue
            filtered_required.append((node_type, package_name))

        if skip_nodes and missing_entries:
            filtered_missing = [
                entry
                for entry in missing_entries
                if not (isinstance(entry, str) and entry.strip().lower() in skip_nodes)
            ]
            if len(filtered_missing) != len(missing_entries):
                data["missing"] = filtered_missing
                missing_entries = filtered_missing

        missing_set = {
            str(item).strip().lower()
            for item in missing_entries
            if isinstance(item, str) and item.strip()
        }

        row_count = len(filtered_required)
        if row_count == 0:
            table.setRowCount(1)
            table.setColumnHidden(3, True)
            placeholder = QtWidgets.QTableWidgetItem("No custom node data reported.")
            placeholder.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            table.setItem(0, 0, placeholder)
            table.setSpan(0, 0, 1, 4)
            return {}

        table.setColumnHidden(3, False)
        table.setRowCount(row_count)

        row_mapping: Dict[int, Dict[str, Any]] = {}
        for row, (node_type, package_name) in enumerate(filtered_required):
            package_display = package_name
            status_value = "Available"
            dependency = None

            node_item = QtWidgets.QTableWidgetItem(node_type or "Unknown Node")
            node_item.setToolTip(node_type or "Unknown Node")
            table.setItem(row, 0, node_item)

            status_item = QtWidgets.QTableWidgetItem(status_value.title())
            self._apply_status_style(status_item, status_value)
            table.setItem(row, 1, status_item)

            package_item = QtWidgets.QTableWidgetItem(package_display)
            package_item.setToolTip(package_display)

            node_key = node_type.lower()
            if node_key in missing_set:
                status_value = "Missing"
                status_item.setText(status_value.title())
                self._apply_status_style(status_item, status_value)
                package_item.setText(f"{package_display} (not installed)")
                package_item.setForeground(QtGui.QBrush(QtGui.QColor("#B22222")))
                dependency = self._match_dependency_for_package(package_name, node_type, dependencies)
            else:
                package_item.setForeground(QtGui.QBrush(QtGui.QColor(SUCCESS_COLOR)))

            table.setItem(row, 2, package_item)

            if status_value == "Missing":
                button = QtWidgets.QPushButton("Resolve")
                button.setFixedHeight(24)
                button.setMaximumWidth(ACTION_BUTTON_WIDTH)
                button.setStyleSheet(
                    "QPushButton {"
                    " background-color: #B22222;"
                    " color: white;"
                    " border: none;"
                    " border-radius: 4px;"
                    " padding: 2px 8px;"
                    " }"
                    "QPushButton:hover {"
                    " background-color: #9B1C1C;"
                    " }"
                    "QPushButton:disabled {"
                    " background-color: #228B22;"
                    " color: white;"
                    " border-radius: 4px;"
                    " }"
                )
                button.clicked.connect(lambda _checked=False, r=row: self._handle_custom_node_auto_resolve(r))
                table.setCellWidget(row, 3, button)
                row_mapping[row] = {
                    "node_name": node_type,
                    "package_name": package_name,
                    "status_item": status_item,
                    "package_item": package_item,
                    "button": button,
                    "dependency": dependency,
                    "resolved": False,
                }
            else:
                placeholder_widget = QtWidgets.QWidget()
                table.setCellWidget(row, 3, placeholder_widget)

        table.resizeRowsToContents()
        return row_mapping

    def _refresh_models_issue_status(self) -> None:
        issue = self._issue_lookup.get("models")
        widget_info = self._issue_widgets.get("models")
        if not issue or not widget_info:
            return
        data = issue.get("data") or {}
        missing = data.get("missing") or []
        status_label = widget_info.get("status_label")
        if missing:
            issue["ok"] = False
            if isinstance(status_label, QtWidgets.QLabel):
                status_label.setText("\u2717 Failed")
                status_label.setStyleSheet("font-weight: bold; color: #B22222;")
            issue["summary"] = f"Missing {len(missing)} model file(s)."
        else:
            issue["ok"] = True
            if isinstance(status_label, QtWidgets.QLabel):
                status_label.setText("\u2713 Passed")
                status_label.setStyleSheet("font-weight: bold; color: #228B22;")
            issue["summary"] = "All required model files located."
            issue["details"] = []

    def _refresh_custom_nodes_issue_status(self) -> None:
        issue = self._issue_lookup.get("custom_nodes")
        widget_info = self._issue_widgets.get("custom_nodes")
        if not issue or not widget_info:
            return

        data = issue.get("data") or {}
        missing = data.get("missing") or []
        status_label = widget_info.get("status_label")
        summary_label = widget_info.get("summary_label")

        if missing:
            issue["ok"] = False
            if isinstance(status_label, QtWidgets.QLabel):
                status_label.setText("\u2717 Failed")
                status_label.setStyleSheet("font-weight: bold; color: #B22222;")
            summary_text = f"Missing {len(missing)} custom node type(s)."
        else:
            issue["ok"] = True
            if isinstance(status_label, QtWidgets.QLabel):
                status_label.setText("\u2713 Passed")
                status_label.setStyleSheet("font-weight: bold; color: #228B22;")
            summary_text = "All required custom nodes installed."

        if isinstance(summary_label, QtWidgets.QLabel):
            summary_label.setText(summary_text)
            if missing:
                summary_label.setStyleSheet("")
            else:
                summary_label.setStyleSheet("font-weight: bold;")
        issue["summary"] = summary_text


    def _persist_resolved_cache(self) -> None:
        if not self._workflow_folder:
            return
        issue = self._issue_lookup.get("models")
        if not issue:
            return
        data = issue.get("data") or {}
        resolved_entries = data.get("resolved_entries")
        if not isinstance(resolved_entries, list):
            return
        save_validation_log(
            self._workflow_folder,
            {"models": {"resolved_entries": resolved_entries}},
        )
        system_debug(
            f"[Validation] Persisted resolved cache for '{self._workflow_folder}': "
            + json.dumps(resolved_entries, indent=2)
        )

    def _format_model_display_path(self, path: str, models_root: str) -> str:
        path = str(path or "").strip()
        if not path:
            return ""
        absolute = os.path.abspath(path)
        if models_root:
            models_root_abs = os.path.abspath(models_root)
            try:
                rel = os.path.relpath(absolute, models_root_abs)
                if not rel.startswith(".."):
                    return f"models/{rel.replace(os.sep, '/')}"
            except ValueError:
                pass
        return absolute.replace("\\", "/")

    def _compute_workflow_value(
        self,
        reference: Dict[str, Any],
        abs_path: str,
        models_root: str,
        comfy_dir: Optional[str],
    ) -> str:
        abs_path = os.path.abspath(abs_path)
        original_name = str(reference.get("name") or "")
        normalized_original = original_name.replace("\\", "/").strip()
        prefer_simple_name = bool(normalized_original) and "/" not in normalized_original
        simple_value = self._normalize_workflow_value(os.path.basename(abs_path))

        def _finalize(candidate: str) -> str:
            stripped = self._strip_category_prefix(candidate)
            normalized_candidate = self._normalize_workflow_value(stripped)
            if prefer_simple_name and simple_value:
                if "/" in stripped or "\\" in stripped:
                    return simple_value
                if "/" in normalized_candidate or "\\" in normalized_candidate:
                    return simple_value
            return normalized_candidate

        category = reference.get("category")
        if isinstance(category, str) and category:
            category_root = os.path.join(models_root, category)
            if os.path.isdir(category_root):
                try:
                    rel = os.path.relpath(abs_path, category_root)
                    if not rel.startswith(".."):
                        return _finalize(rel)
                except ValueError:
                    pass
        if models_root and os.path.isdir(models_root):
            try:
                rel = os.path.relpath(abs_path, models_root)
                if not rel.startswith(".."):
                    return _finalize(rel)
            except ValueError:
                pass
        fallback = format_model_reference_for_workflow(abs_path, comfy_dir)
        return _finalize(fallback)

    def _normalize_workflow_value(self, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            return normalized
        normalized = normalized.replace("\\", "/")
        if os.sep == "\\":
            normalized = normalized.replace("/", "\\")
        return normalized

    def _strip_category_prefix(self, value: str) -> str:
        normalized = (value or "").replace("\\", "/").lstrip("/")
        if not normalized:
            return normalized
        lowered = normalized.lower()
        if lowered.startswith("models/"):
            parts = normalized.split("/", 1)
            normalized = parts[1] if len(parts) > 1 else ""
        segments = [segment for segment in normalized.split("/") if segment]
        if len(segments) <= 1:
            return normalized
        first_lower = segments[0].lower()
        if first_lower in MODEL_CATEGORY_PREFIXES:
            trimmed = "/".join(segments[1:])
            if trimmed:
                return trimmed
        return normalized

    @staticmethod
    def _normalize_identifier(value: Any) -> str:
        if value is None:
            return ""
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        if not value:
            return ""
        return value.replace("\\", "/").lower()

    def _apply_status_style(self, item: QtWidgets.QTableWidgetItem, status: str) -> None:
        status = (status or "").lower()
        color_map = {
            "found": SUCCESS_COLOR,
            "missing": "#B22222",
            "resolved": SUCCESS_COLOR,
            "copied": SUCCESS_COLOR,
            "available": SUCCESS_COLOR,
            "installed": SUCCESS_COLOR,
        }
        text = {
            "found": "Found",
            "missing": "Missing",
            "resolved": "Resolved",
            "copied": "Copied",
            "available": "Available",
            "installed": "Installed",
        }.get(status, item.text())
        item.setText(text)
        color = color_map.get(status)
        if color:
            item.setForeground(QtGui.QBrush(QtGui.QColor(color)))
        else:
            item.setForeground(QtGui.QBrush(QtGui.QColor("#000000")))
        item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

    def _mark_model_resolved(
        self,
        row: int,
        status_text: str,
        display_text: str,
        note: str,
        workflow_value: Optional[str] = None,
        resolved_path: Optional[str] = None,
    ) -> None:
        system_debug(
            "[Validation] Mark model resolved requested | "
            f"row={row} status='{status_text}' display='{display_text}' "
            f"workflow_value='{workflow_value}' resolved_path='{resolved_path}'"
        )
        widget_info = self._issue_widgets.get("models")
        if not widget_info:
            return
        rows: Dict[int, Dict[str, Any]] = widget_info.get("rows") or {}
        row_info = rows.get(row)
        if not row_info:
            return
        status_item = row_info.get("status_item")
        if isinstance(status_item, QtWidgets.QTableWidgetItem):
            self._apply_status_style(status_item, status_text)
        location_item = row_info.get("location_item")
        if isinstance(location_item, QtWidgets.QTableWidgetItem):
            location_item.setText(display_text)
            location_item.setToolTip(display_text)
            font = location_item.font()
            original = row_info.get("original_location") or ""
            if original and original != display_text:
                font.setBold(True)
                location_item.setFont(font)
                location_item.setForeground(QtGui.QBrush(QtGui.QColor(SUCCESS_COLOR)))
            else:
                font.setBold(False)
                location_item.setFont(font)
                location_item.setForeground(QtGui.QBrush(QtGui.QColor("#FFFFFF")))
            row_info["original_location"] = display_text
        button = row_info.get("button")
        if isinstance(button, QtWidgets.QPushButton):
            lower_status = status_text.lower()
            is_resolved_state = lower_status in {"resolved", "copied"}
            if is_resolved_state:
                button.setStyleSheet(
                    "QPushButton {"
                    " background-color: #228B22;"
                    " color: white;"
                    " border: none;"
                    " border-radius: 4px;"
                    " padding: 2px 8px;"
                    "}"
                    "QPushButton:disabled {"
                    " background-color: #228B22;"
                    " color: white;"
                    " border: none;"
                    " border-radius: 4px;"
                    " padding: 2px 8px;"
                    "}"
                )
            else:
                button.setStyleSheet(
                    "QPushButton {"
                    " background-color: #2f3542;"
                    " color: #f0f0f0;"
                    " border-radius: 4px;"
                    " padding: 2px 8px;"
                    "}"
                    "QPushButton:disabled {"
                    " background-color: #2f3542;"
                    " color: #f0f0f0;"
                    " border-radius: 4px;"
                    " padding: 2px 8px;"
                    "}"
                )
            button.setText(status_text)
            button.setEnabled(False)
            if is_resolved_state:
                try:
                    style = button.style()
                    style.unpolish(button)
                    style.polish(button)
                except Exception:
                    pass
                button.update()
                button.repaint()
        row_info["resolved"] = True
        if isinstance(row_info, dict):
            if workflow_value:
                row_info["workflow_value"] = workflow_value
            else:
                row_info.pop("workflow_value", None)
            if resolved_path:
                row_info["resolved_path"] = resolved_path
        reference = row_info.get("reference")
        if isinstance(reference, dict):
            effective_value = workflow_value or display_text
            reference["name"] = effective_value
        if note:
            self._append_issue_note("models", note)
        if self._workflow_folder:
            entry = {
                "event": "model_resolved",
                "status": status_text,
                "display_path": display_text,
                "workflow_value": workflow_value,
                "note": note,
                "reference": reference,
                "reference_signature": row_info.get("reference_signature"),
                "resolved_path": resolved_path or display_text,
            }
            append_validation_resolve_entry(self._workflow_folder, entry)
        self._refresh_models_issue_status()
        self._refresh_models_issue_status()
        issue_info = self._issue_lookup.get("models") or {}
        issue_data = issue_info.get("data") if isinstance(issue_info, dict) else {}
        missing_after = issue_data.get("missing") if isinstance(issue_data, dict) else None
        system_debug(
            "[Validation] Completed mark model resolved | "
            f"row={row} remaining_missing={len(missing_after) if isinstance(missing_after, list) else 'unknown'} "
            f"issue_ok={issue_info.get('ok') if isinstance(issue_info, dict) else 'unknown'}"
        )

    def _apply_model_override(self, original_value: str, new_value: str) -> Tuple[bool, str]:
        original_value = (original_value or "").strip()
        if not original_value:
            return False, "Original model reference is empty."
        if not isinstance(self._workflow_override, dict):
            return False, "Workflow data is unavailable."
        replacements = [(original_value, new_value)]
        replaced = replace_workflow_model_paths(self._workflow_override, replacements)
        if not replaced:
            return False, "No matching model reference found inside workflow.json."
        folder = ""
        if isinstance(self._workflow_bundle, dict):
            folder = self._workflow_bundle.get("folder") or ""
        if not folder:
            return False, "Workflow folder is unknown; cannot store override."
        try:
            save_workflow_override(folder, self._workflow_override, parent=self)
        except Exception as exc:  # pragma: no cover - defensive guard
            return False, str(exc)
        if isinstance(self._workflow_bundle, dict):
            self._workflow_bundle["workflow"] = self._workflow_override
        return True, ""

    def _copy_shared_model(self, source: str, destination: str) -> Tuple[bool, Optional[str]]:
        progress = QtWidgets.QProgressDialog("Copying model...", "Cancel", 0, 100, self)
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        worker = _FileCopyWorker(source, destination)
        thread = QtCore.QThread(self)
        worker.moveToThread(thread)

        result = {"success": False, "message": None}

        def _handle_finished(_success: bool, _dest: str) -> None:
            result["success"] = True
            result["message"] = _dest
            progress.setValue(100)
            progress.accept()
            thread.quit()

        def _handle_failed(message: str) -> None:
            result["success"] = False
            result["message"] = message
            progress.reject()
            thread.quit()

        def _handle_canceled() -> None:
            result["success"] = False
            result["message"] = "Copy canceled."
            progress.reject()
            thread.quit()

        worker.progress.connect(progress.setValue)
        worker.finished.connect(_handle_finished)
        worker.failed.connect(_handle_failed)
        worker.canceled.connect(_handle_canceled)
        progress.canceled.connect(worker.cancel)
        thread.started.connect(worker.run)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        thread.start()
        progress.exec()

        return bool(result["success"]), result["message"]

    def _select_candidate_path(
        self,
        candidates: List[str],
        *,
        title: str,
        prompt: str,
        models_root: Optional[str] = None,
    ) -> Optional[str]:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        display_items = [
            self._format_model_display_path(path, models_root or "")
            if models_root
            else path.replace("\\", "/")
            for path in candidates
        ]
        item, ok = QtWidgets.QInputDialog.getItem(self, title, prompt, display_items, 0, False)
        if ok:
            try:
                index = display_items.index(item)
                return candidates[index]
            except ValueError:
                return None
        return None

    def _record_resolved_model(
        self,
        abs_path: str,
        status: str,
        row_info: Dict[str, Any],
        workflow_value: Optional[str],
    ) -> None:
        issue = self._issue_lookup.get("models")
        if not issue:
            return
        data = issue.setdefault("data", {})
        found = data.setdefault("found", [])
        if abs_path and abs_path not in found:
            found.append(abs_path)
        resolved_entries = data.setdefault("resolved_entries", [])
        normalized_path = abs_path.replace("\\", "/").lower()
        reference = row_info.get("reference") or {}
        reference_name = str(reference.get("name") or "")
        row_index = row_info.get("row_index")
        signature_value = row_info.get("reference_signature")
        if isinstance(signature_value, tuple):
            signature_payload: Optional[List[Optional[str]]] = list(signature_value)
        elif isinstance(signature_value, list):
            signature_payload = list(signature_value)
        else:
            signature_payload = None
        original_signature_tuple: Optional[Tuple[str, Optional[str], Optional[str]]] = None
        if signature_payload is not None and len(signature_payload) == 3:
            original_signature_tuple = tuple(signature_payload)  # type: ignore[arg-type]
        for entry in resolved_entries:
            existing_path = str(entry.get("path") or "").replace("\\", "/").lower()
            if existing_path == normalized_path:
                entry["status"] = status
                if reference_name:
                    entry["reference"] = reference_name
                if workflow_value:
                    entry["workflow_value"] = workflow_value
                if signature_payload is not None:
                    entry["signature"] = signature_payload
                if original_signature_tuple and original_signature_tuple[0]:
                    entry["original_reference"] = original_signature_tuple[0]
                break
        else:
            payload = {"path": abs_path, "status": status}
            if reference_name:
                payload["reference"] = reference_name
            if workflow_value:
                payload["workflow_value"] = workflow_value
            if signature_payload is not None:
                payload["signature"] = signature_payload
                if signature_payload and signature_payload[0]:
                    payload["original_reference"] = signature_payload[0]
            elif reference_name:
                payload["original_reference"] = reference_name
            resolved_entries.append(payload)

        try:
            debug_payload = {
                "path": abs_path,
                "status": status,
                "workflow_value": workflow_value,
                "reference": reference_name,
            }
            system_debug(f"[Validation] Recorded resolved model: {json.dumps(debug_payload)}")
        except Exception:
            system_debug("[Validation] Recorded resolved model.")

        missing = data.get("missing")
        if isinstance(missing, list):
            removed = False
            missing_entry = row_info.get("missing_entry")
            if isinstance(missing_entry, dict):
                for i, entry in enumerate(list(missing)):
                    if entry is missing_entry:
                        missing.pop(i)
                        removed = True
                        row_info["missing_entry"] = None
                        break

            if removed:
                updated_missing = [entry for entry in missing if isinstance(entry, dict)]
                data["missing"] = updated_missing
                system_debug(
                    "[Validation] Removed missing entry via object identity | "
                    f"row={row_index} remaining_missing={len(updated_missing)}"
                )
            else:
                signature = row_info.get("reference_signature")
                target_name: Optional[str]
                target_category: Optional[str]
                target_node: Optional[str]
                if isinstance(signature, (tuple, list)) and len(signature) == 3:
                    target_name = signature[0]
                    target_category = signature[1]
                    target_node = signature[2]
                elif isinstance(reference, dict):
                    target_name = reference.get("name")
                    target_category = reference.get("category")
                    target_node = reference.get("node_type")
                else:
                    target_name = target_category = target_node = None

                target_name_norm = self._normalize_identifier(target_name)
                target_category_norm = self._normalize_identifier(target_category)
                target_node_norm = self._normalize_identifier(target_node)
                workflow_value_norm = self._normalize_identifier(workflow_value)

                def _matches_entry(entry: Dict[str, Any]) -> bool:
                    if not isinstance(entry, dict):
                        return False
                    entry_name_norm = self._normalize_identifier(entry.get("name"))
                    entry_category_norm = self._normalize_identifier(entry.get("category"))
                    entry_node_norm = self._normalize_identifier(entry.get("node_type"))
                    if target_name_norm:
                        candidates = {entry_name_norm}
                        raw_payload = entry.get("raw")
                        if isinstance(raw_payload, dict):
                            candidates.add(self._normalize_identifier(raw_payload.get("name")))
                            candidates.add(self._normalize_identifier(raw_payload.get("path")))
                        candidates.add(self._normalize_identifier(entry.get("path")))
                        candidates.add(self._normalize_identifier(os.path.basename(str(entry.get("name") or ""))))
                        if workflow_value_norm:
                            candidates.add(workflow_value_norm)
                        candidates = {value for value in candidates if value}
                        if target_name_norm not in candidates:
                            return False
                    if target_category_norm and entry_category_norm != target_category_norm:
                        return False
                    if target_node_norm and entry_node_norm != target_node_norm:
                        return False
                    return True

                ref_index = row_info.get("reference_index")
                if isinstance(ref_index, int) and 0 <= ref_index < len(missing):
                    candidate = missing[ref_index]
                    if _matches_entry(candidate):
                        missing.pop(ref_index)
                        removed = True

                if not removed:
                    for i, item in enumerate(list(missing)):
                        if _matches_entry(item):
                            missing.pop(i)
                            removed = True
                            break

                normalized_candidates = {
                    self._normalize_identifier(abs_path),
                    self._normalize_identifier(os.path.basename(abs_path)),
                    workflow_value_norm,
                    self._normalize_identifier(reference_name),
                }
                normalized_candidates = {value for value in normalized_candidates if value}

                if not removed and normalized_candidates:
                    fallback_removed = False
                    for i, entry in enumerate(list(missing)):
                        if not isinstance(entry, dict):
                            continue
                        entry_candidates = {
                            self._normalize_identifier(entry.get("name")),
                            self._normalize_identifier(os.path.basename(str(entry.get("name") or ""))),
                            self._normalize_identifier(entry.get("path")),
                        }
                        raw_payload = entry.get("raw")
                        if isinstance(raw_payload, dict):
                            entry_candidates.add(self._normalize_identifier(raw_payload.get("name")))
                            entry_candidates.add(self._normalize_identifier(raw_payload.get("path")))
                        entry_candidates = {value for value in entry_candidates if value}
                        if entry_candidates & normalized_candidates:
                            missing.pop(i)
                            fallback_removed = True
                    removed = fallback_removed

                filtered_missing = [entry for entry in missing if isinstance(entry, dict)]
                data["missing"] = filtered_missing
                if removed:
                    system_debug(
                        "[Validation] Removed missing entry via signature/normalized match | "
                        f"row={row_index} remaining_missing={len(filtered_missing)}"
                    )
                else:
                    try:
                        debug_name = signature_value[0] if signature_payload else reference_name
                    except Exception:
                        debug_name = reference_name
                    system_debug(
                        "[Validation] Could not reconcile resolved model with missing list; "
                        f"name='{debug_name}', workflow_value='{workflow_value}'."
                    )

        resolver_info = data.get("resolver")
        if isinstance(resolver_info, dict):
            ref_index = row_info.get("reference_index")
            resolver_missing = resolver_info.get("missing")
            if isinstance(resolver_missing, list):
                filtered = []
                for entry in resolver_missing:
                    if not isinstance(entry, dict):
                        continue
                    if isinstance(ref_index, int) and entry.get("index") == ref_index:
                        continue
                    name_value = entry.get("name")
                    category_value = entry.get("category")
                    node_value = entry.get("node_type")
                    signature = row_info.get("reference_signature")
                    if (
                        isinstance(signature, tuple)
                        and name_value == signature[0]
                        and category_value == signature[1]
                        and node_value == signature[2]
                    ):
                        continue
                    filtered.append(entry)
                resolver_info["missing"] = filtered
                if not filtered:
                    resolver_info["missing"] = []
            resolver_invalid = resolver_info.get("invalid")
            if isinstance(resolver_invalid, list) and isinstance(ref_index, int):
                resolver_info["invalid"] = [
                    entry
                    for entry in resolver_invalid
                    if not (isinstance(entry, dict) and entry.get("index") == ref_index)
                ]
    def _ensure_custom_node_package_map(self) -> None:
        if self._custom_node_package_map is not None:
            return
        mapping: Dict[str, str] = {}
        workflow = (self._workflow_bundle or {}).get("workflow")
        if isinstance(workflow, dict):
            nodes = workflow.get("nodes")
            if isinstance(nodes, list):
                for node in nodes:
                    node_type = str(node.get("type") or "").strip().lower()
                    props = node.get("properties") or {}
                    package = str(props.get("cnr_id") or "").strip()
                    if node_type and package and node_type not in mapping:
                        mapping[node_type] = package
        self._custom_node_package_map = mapping

    def _package_for_node_type(self, node_type: str) -> str:
        if not node_type:
            return ""
        self._ensure_custom_node_package_map()
        lookup = self._custom_node_package_map or {}
        return lookup.get(node_type.lower(), "")

    def _match_dependency_for_package(
        self,
        package_name: str,
        node_name: str,
        dependencies: Optional[Iterable[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        deps = dependencies if dependencies is not None else self._load_dependencies()
        if not deps:
            return None
        package_key = (package_name or "").lower()
        node_key = (node_name or "").lower()
        for dep in deps:
            if not isinstance(dep, dict):
                continue
            name = str(dep.get("name") or "").strip().lower()
            repo = str(dep.get("repo") or "").strip().lower()
            candidates = [value for value in (name, repo) if value]
            if package_key and any(package_key in value for value in candidates):
                return dep
            if node_key and any(node_key in value for value in candidates):
                return dep
        return None

    def _notify_custom_node_manual_install(self, row_info: Dict[str, Any]) -> bool:
        node_name = str(row_info.get("node_name") or "").strip()
        package_name = str(row_info.get("package_name") or "").strip()
        package_display = package_name or node_name or "the required package"
        message = (
            f"Could not locate an installation repository for <b>{package_display}</b>.<br>"
            "Install the package manually under <b>custom_nodes</b> in your ComfyUI directory, "
            "restart ComfyUI, then click Resolve again."
        )
        dialog = QtWidgets.QMessageBox(self)
        dialog.setIcon(QtWidgets.QMessageBox.Icon.Information)
        dialog.setWindowTitle("Manual Installation Required")
        dialog.setTextFormat(QtCore.Qt.TextFormat.RichText)
        dialog.setText(message)
        overrides = self._metadata_dependency_overrides()
        override_button = None
        ok_button = dialog.addButton(QtWidgets.QMessageBox.StandardButton.Ok)
        if overrides:
            override_button = dialog.addButton(
                "Install from Metadata...",
                QtWidgets.QMessageBox.ButtonRole.ActionRole,
            )
            dialog.setDefaultButton(ok_button)
        dialog.exec()

        if override_button and dialog.clickedButton() == override_button:
            selected = self._prompt_dependency_override(package_display, overrides)
            if selected and self._install_dependency_from_metadata(row_info, selected):
                return True

        self._append_issue_note(
            "custom_nodes",
            f"Manual install required for {package_display}. Install under custom_nodes and restart ComfyUI.",
        )
        return False

    def _notify_manual_download(
        self,
        file_name: str,
        models_root: str,
        expected_path: Optional[str] = None,
    ) -> None:
        display_name = file_name or "the required model"
        if expected_path:
            destination_display = self._format_model_display_path(expected_path, models_root)
        elif models_root and file_name:
            destination_display = self._format_model_display_path(
                os.path.join(models_root, file_name), models_root
            )
        else:
            destination_display = "your ComfyUI/models directory"

        destination_fragment = f'<span style="color:#228B22;">{destination_display}</span>'
        message = (
            f"Could not locate <b>{display_name}</b>.<br>"
            "Please download it manually, place it under "
            f"{destination_fragment}.<br>"
            "After that, click Resolve again."
        )

        dialog = QtWidgets.QMessageBox(self)
        dialog.setIcon(QtWidgets.QMessageBox.Icon.Information)
        dialog.setWindowTitle("Model Missing")
        dialog.setTextFormat(QtCore.Qt.TextFormat.RichText)
        dialog.setText(message)
        dialog.setStandardButtons(QtWidgets.QMessageBox.StandardButton.Ok)
        dialog.exec()

        note_text = (
            f"Could not locate {display_name}. "
            f"Please download it manually and place it under {destination_display}. "
            "After that, click Resolve again."
        )
        self._append_issue_note("models", note_text)

    # ---------------------------------------------------------------- Actions
    def _handle_auto_resolve(self, issue_key: str) -> None:
        issue = self._issue_lookup.get(issue_key) or {}
        data = issue.get("data") or {}
        if issue_key == "models":
            result = resolve_missing_models(data, self._comfy_path)
            self._report_resolution(issue_key, result)
        elif issue_key == "custom_nodes":
            dependencies = self._load_dependencies()
            result = resolve_missing_custom_nodes(data, self._comfy_path, dependencies)
            self._report_resolution(issue_key, result)

    def _handle_model_auto_resolve(self, row: int) -> None:
        widget_info = self._issue_widgets.get("models")
        if not widget_info:
            return
        rows: Dict[int, Dict[str, Any]] = widget_info.get("rows") or {}
        row_info = rows.get(row)
        if not row_info or row_info.get("resolved"):
            return
        button: Optional[QtWidgets.QPushButton] = row_info.get("button")
        if button:
            button.setEnabled(False)
        try:
            resolved = self._resolve_model_entry(row, row_info)
            if not resolved and button:
                button.setEnabled(True)
        except Exception as exc:  # pragma: no cover - defensive guard
            if button:
                button.setEnabled(True)
            QtWidgets.QMessageBox.warning(self, "Auto Resolve Failed", str(exc))

    def _handle_custom_node_auto_resolve(self, row: int) -> None:
        widget_info = self._issue_widgets.get("custom_nodes")
        if not widget_info:
            return
        rows: Dict[int, Dict[str, Any]] = widget_info.get("rows") or {}
        row_info = rows.get(row)
        if not row_info or row_info.get("resolved"):
            return
        button: Optional[QtWidgets.QPushButton] = row_info.get("button")
        if button:
            button.setEnabled(False)
        try:
            if not self._resolve_custom_node_entry(row, row_info) and button:
                button.setEnabled(True)
        except Exception as exc:  # pragma: no cover - defensive guard
            if button:
                button.setEnabled(True)
            QtWidgets.QMessageBox.warning(self, "Custom Node Resolve Failed", str(exc))

    def _resolve_model_entry(self, row: int, row_info: Dict[str, Any]) -> bool:
        reference = row_info.get("reference") or {}
        original_name = str(reference.get("name") or "").strip()
        system_debug(
            "[Validation] Attempting model auto-resolve | "
            f"row={row} name='{original_name}' models_root='{row_info.get('models_root')}'"
        )
        models_root = row_info.get("models_root") or ""
        comfy_dir = (self._comfy_info or {}).get("comfy_dir") or ""
        expected_path: Optional[str] = None
        notified_manual = False
        local_matches = find_local_model_matches(reference, models_root)
        if local_matches:
            selected = self._select_candidate_path(
                local_matches,
                title="Select Model",
                prompt="Choose the model file to reference in this workflow.",
                models_root=models_root,
            )
            if selected:
                workflow_value = self._compute_workflow_value(reference, selected, models_root, comfy_dir)
                display_text = self._format_model_display_path(selected, models_root)
                success, message = self._apply_model_override(original_name, workflow_value)
                if success:
                    note = ""
                    system_debug(
                        "[Validation] Local model resolved | "
                        f"selected='{selected}' workflow_value='{workflow_value}'"
                    )
                    self._mark_model_resolved(
                        row,
                        "Resolved",
                        display_text,
                        note,
                        workflow_value,
                        resolved_path=selected,
                    )
                    self._record_resolved_model(selected, "Resolved", row_info, workflow_value)
                    self._persist_resolved_cache()
                    self._refresh_models_issue_status()
                    return True
                if message:
                    QtWidgets.QMessageBox.warning(self, "Workflow Update Failed", message)

        file_name = os.path.basename(original_name) or os.path.basename(str(reference.get("name") or ""))
        shared_matches = find_shared_model_matches(file_name)
        if shared_matches:
            selected = self._select_candidate_path(
                shared_matches,
                title="Download Model from Global Repo",
                prompt=(
                    "Could not locate model in your local ComfyUI folder.\n\n"
                    f"{file_name} is available in the Global Repo. Download it?"
                ),
            )
            if selected:
                expected_path = determine_expected_model_path(reference, models_root, comfy_dir)
                if not expected_path:
                    if models_root:
                        expected_path = os.path.join(models_root, file_name)
                    else:
                        expected_path = os.path.join(os.path.dirname(selected), file_name)
                workflow_value = self._compute_workflow_value(reference, expected_path, models_root, comfy_dir)
                destination_display = self._format_model_display_path(expected_path, models_root)
                download_text = (
                    "Could not locate model in your local ComfyUI folder.<br>"
                    f"<b>{file_name}</b> is available in the Global Repo. Download it?<br><br>"
                    "Destination:<br>"
                    f'<span style="color:#228B22;">{destination_display}</span>'
                )
                msg_box = QtWidgets.QMessageBox(self)
                msg_box.setIcon(QtWidgets.QMessageBox.Icon.Question)
                msg_box.setWindowTitle("Download Model from Global Repo")
                msg_box.setTextFormat(QtCore.Qt.TextFormat.RichText)
                msg_box.setText(download_text)
                msg_box.setStandardButtons(
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
                )
                msg_box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Yes)
                answer = msg_box.exec()

                if answer == QtWidgets.QMessageBox.StandardButton.Yes:
                    success, message = self._copy_shared_model(selected, expected_path)
                    if success:
                        note = f"Downloaded {file_name} to {destination_display}."
                        notified_manual = True
                        system_debug(
                            "[Validation] Global Repo copy completed | "
                            f"source='{selected}' destination='{expected_path}'"
                        )
                        self._mark_model_resolved(
                            row,
                            "Resolved",
                            destination_display,
                            note,
                            workflow_value,
                            resolved_path=expected_path,
                        )
                        self._record_resolved_model(expected_path, "Copied", row_info, workflow_value)
                        self._persist_resolved_cache()
                        self._refresh_models_issue_status()
                        return True
                    if message:
                        system_debug(
                            "[Validation] Global Repo copy failed | "
                            f"source='{selected}' destination='{expected_path}' message='{message}'"
                        )
                        QtWidgets.QMessageBox.warning(self, "Copy Failed", message)
                else:
                    self._append_issue_note("models", "Copy canceled by user.")
                    self._notify_manual_download(file_name, models_root, expected_path)
                    notified_manual = True
        if not notified_manual:
            if expected_path and os.path.exists(expected_path):
                workflow_value = self._compute_workflow_value(reference, expected_path, models_root, comfy_dir)
                destination_display = self._format_model_display_path(expected_path, models_root)
                system_debug(
                    "[Validation] Detected model already present at expected path | "
                    f"path='{expected_path}'"
                )
                self._mark_model_resolved(
                    row,
                    "Resolved",
                    destination_display,
                    "",
                    workflow_value,
                    resolved_path=expected_path,
                )
                self._record_resolved_model(expected_path, "Resolved", row_info, workflow_value)
                self._persist_resolved_cache()
                self._refresh_models_issue_status()
                return True
            self._notify_manual_download(file_name, models_root, expected_path)
        return False


    def _resolve_custom_node_entry(self, row: int, row_info: Dict[str, Any]) -> bool:
        node_name = str(row_info.get("node_name") or "").strip()
        package_name = str(row_info.get("package_name") or "").strip()
        dependency = row_info.get("dependency")

        if dependency and isinstance(dependency, dict):
            normalized_dep = self._normalize_dependency_entry(dependency)
            if not normalized_dep:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Install Custom Node",
                    "The workflow metadata does not provide a usable repository URL for this dependency.",
                )
                return False
            repo = normalized_dep.get("repo") or ""
            dep_display = normalized_dep.get("name") or package_name or node_name or "Dependency"
            prompt = (
                f"A recommended Git repository was found for <b>{dep_display}</b>:<br>"
                f"<span style='color:#228B22;'>{repo or 'Repository URL unavailable'}</span><br><br>"
                "Install it into your custom_nodes folder?"
            )
            dialog = QtWidgets.QMessageBox(self)
            dialog.setIcon(QtWidgets.QMessageBox.Icon.Question)
            dialog.setWindowTitle("Install Custom Node")
            dialog.setTextFormat(QtCore.Qt.TextFormat.RichText)
            dialog.setText(prompt)
            dialog.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
            )
            dialog.setDefaultButton(QtWidgets.QMessageBox.StandardButton.Yes)
            if dialog.exec() != QtWidgets.QMessageBox.StandardButton.Yes:
                return False

            if self._install_dependency_from_metadata(row_info, normalized_dep):
                return True
            return False

        if self._notify_custom_node_manual_install(row_info):
            return True
        return False

    def _mark_custom_node_resolved(self, row_info: Dict[str, Any], note: Optional[str] = None) -> None:
        status_item = row_info.get("status_item")
        if isinstance(status_item, QtWidgets.QTableWidgetItem):
            self._apply_status_style(status_item, "Resolved")

        package_item = row_info.get("package_item")
        package_name = row_info.get("package_name") or "Installed"
        if isinstance(package_item, QtWidgets.QTableWidgetItem):
            package_item.setText(f"{package_name} (installed)")
            package_item.setForeground(QtGui.QBrush(QtGui.QColor(SUCCESS_COLOR)))

        button = row_info.get("button")
        if isinstance(button, QtWidgets.QPushButton):
            button.setText("Resolved")
            button.setEnabled(False)
            button.setStyleSheet(
                "QPushButton {"
                " background-color: #228B22;"
                " color: white;"
                " border-radius: 4px;"
                " padding: 2px 8px;"
                " }"
            )

        row_info["resolved"] = True

        node_name = row_info.get("node_name")
        issue = self._issue_lookup.get("custom_nodes")
        if issue:
            data = issue.get("data") or {}
            missing = data.get("missing") or []
            data["missing"] = [entry for entry in missing if entry != node_name]

        if note:
            self._append_issue_note("custom_nodes", note)

        self._refresh_custom_nodes_issue_status()
        return False

    def _report_resolution(self, issue_key: str, result: ResolutionResult) -> None:
        widget_info = self._issue_widgets.get(issue_key)
        if widget_info and widget_info.get("button"):
            widget_info["button"].setEnabled(False)

        messages: List[str] = []
        if result.resolved:
            messages.append("\n".join(result.resolved))
        if result.skipped:
            messages.append("\n".join(result.skipped))
        if result.failed:
            messages.append("\n".join(result.failed))
        if result.notes:
            messages.append("\n".join(result.notes))

        text = "\n\n".join(filter(None, messages)) or "No action was taken."

        QtWidgets.QMessageBox.information(self, "Auto Resolve", text)
        self._append_issue_note(issue_key, text)
        if self._workflow_folder:
            try:
                entry_payload = result.to_dict()
            except Exception:
                entry_payload = result.__dict__
            append_validation_resolve_entry(
                self._workflow_folder,
                {
                    "event": f"issue_auto_resolve:{issue_key}",
                    "message": text,
                    "result": entry_payload,
                },
            )

    # ---------------------------------------------------------------- Helpers
    def _append_issue_note(self, issue_key: str, message: str) -> None:
        widget_info = self._issue_widgets.get(issue_key)
        if not widget_info:
            return
        label = QtWidgets.QLabel(message)
        label.setWordWrap(True)
        frame: QtWidgets.QFrame = widget_info["frame"]
        frame.layout().addWidget(label)

    def _load_dependencies(self) -> List[Dict[str, Any]]:
        if self._dependencies_cache is not None:
            return self._dependencies_cache
        metadata = {}
        if isinstance(self._workflow_bundle, dict):
            metadata = self._workflow_bundle.get("metadata") or {}
        dependencies: Iterable[Dict[str, Any]] = metadata.get("dependencies") or []
        if not dependencies:
            charon_meta = metadata.get("charon_meta") or {}
            dependencies = charon_meta.get("dependencies") or []
        self._dependencies_cache = list(dependencies)
        return self._dependencies_cache

    def _metadata_dependency_overrides(self) -> List[Dict[str, Any]]:
        overrides: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()
        for dep in self._load_dependencies():
            normalized = self._normalize_dependency_entry(dep)
            if not normalized:
                continue
            repo = normalized.get("repo")
            if not repo:
                continue
            key = repo.lower()
            if key in seen_urls:
                continue
            overrides.append(normalized)
            seen_urls.add(key)
        return overrides

    def _normalize_dependency_entry(self, dependency: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(dependency, dict):
            return None
        repo = str(dependency.get("repo") or dependency.get("url") or "").strip()
        if not repo:
            return None
        name = str(dependency.get("name") or "").strip()
        if not name:
            parsed = urlparse(repo)
            path = (parsed.path or "").rstrip("/")
            if path:
                name = path.split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
        if not name:
            tail = os.path.basename(repo.rstrip("/"))
            if tail.endswith(".git"):
                tail = tail[:-4]
            name = tail or repo
        normalized: Dict[str, Any] = {"repo": repo}
        if name:
            normalized["name"] = name
        ref = str(dependency.get("ref") or "").strip()
        if ref:
            normalized["ref"] = ref
        return normalized

    def _prompt_dependency_override(
        self,
        package_display: str,
        overrides: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        items: List[str] = []
        mapping: Dict[str, Dict[str, Any]] = {}
        for dep in overrides:
            repo = dep.get("repo")
            if not repo:
                continue
            name = dep.get("name") or ""
            label = repo
            if name and name.strip() and name.lower() not in repo.lower():
                label = f"{name} - {repo}"
            mapping[label] = dep
            items.append(label)
        if not items:
            return None
        selection, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Select Repository",
            (
                "Select a repository URL from the workflow metadata to install.\n"
                f"Missing package: {package_display}"
            ),
            items,
            0,
            False,
        )
        if ok and selection:
            return mapping.get(selection)
        return None

    def _install_dependency_from_metadata(
        self,
        row_info: Dict[str, Any],
        dependency: Dict[str, Any],
    ) -> bool:
        normalized = self._normalize_dependency_entry(dependency)
        if not normalized:
            QtWidgets.QMessageBox.warning(
                self,
                "Installation Failed",
                "The selected repository entry is missing a valid URL.",
            )
            return False

        node_name = str(row_info.get("node_name") or "").strip()
        package_name = str(row_info.get("package_name") or "").strip()
        dep_display = normalized.get("name") or package_name or node_name or "Dependency"

        result = resolve_missing_custom_nodes(
            {"missing": [node_name] if node_name else []},
            self._comfy_path,
            dependencies=[normalized],
        )
        if result.failed:
            QtWidgets.QMessageBox.warning(
                self,
                "Installation Failed",
                result.failed[0] if result.failed else "Could not install the dependency.",
            )
            return False

        note = ""
        if result.resolved:
            note = result.resolved[0]
        elif result.skipped:
            note = result.skipped[0]
        if not note:
            note = f"{dep_display} installed. Restart ComfyUI to load the new node."

        self._mark_custom_node_resolved(row_info, note)
        row_info["dependency"] = normalized
        QtWidgets.QMessageBox.information(
            self,
            "Installation Complete",
            (
                f"{dep_display} has been cloned into your ComfyUI custom_nodes directory.\n"
                "Restart ComfyUI to load the new node."
            ),
        )
        return True
