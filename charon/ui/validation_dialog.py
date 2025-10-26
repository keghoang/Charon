from __future__ import annotations

import copy
import json
import os
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
        self._revalidate_button = button_box.addButton("Revalidate", QtWidgets.QDialogButtonBox.ActionRole)
        button_box.rejected.connect(self.reject)
        self._revalidate_button.clicked.connect(self._handle_revalidate_clicked)
        layout.addWidget(button_box)

        self.resize(720, 540)

    def _create_issue_widget(self, issue: Dict[str, Any]) -> Optional[QtWidgets.QWidget]:
        key = str(issue.get("key") or "")
        if key == "models":
            return self._create_models_issue_widget(issue)
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
        table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        table.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        table.verticalHeader().setDefaultSectionSize(26)
        table.setStyleSheet(
            "QTableWidget { font-size: 12px; }"
            "QPushButton { padding: 2px 8px; font-size: 11px; }"
        )
        table.setColumnWidth(1, 80)
        table.setColumnWidth(3, 140)
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
        resolved_signatures: List[tuple] = []
        resolved_names: set[str] = set()
        for entry in resolved_entries or []:
            if not isinstance(entry, dict):
                continue
            signature = entry.get("signature")
            if isinstance(signature, (list, tuple)) and len(signature) == 3:
                resolved_signatures.append(tuple(signature))
            else:
                reference_name = entry.get("reference")
                if isinstance(reference_name, str) and reference_name:
                    resolved_names.add(reference_name)
        filtered: List[Dict[str, Any]] = []
        for item in missing or []:
            if not isinstance(item, dict):
                continue
            signature = (
                item.get("name"),
                item.get("category"),
                item.get("node_type"),
            )
            if signature in resolved_signatures:
                continue
            name_value = item.get("name")
            if isinstance(name_value, str) and name_value in resolved_names:
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
            table.setSpan(0, 0, 1, 3)
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
            button.setMaximumWidth(110)
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
        category = reference.get("category")
        if isinstance(category, str) and category:
            category_root = os.path.join(models_root, category)
            if os.path.isdir(category_root):
                try:
                    rel = os.path.relpath(abs_path, category_root)
                    if not rel.startswith(".."):
                        return self._normalize_workflow_value(rel)
                except ValueError:
                    pass
        if models_root and os.path.isdir(models_root):
            try:
                rel = os.path.relpath(abs_path, models_root)
                if not rel.startswith(".."):
                    return self._normalize_workflow_value(rel)
            except ValueError:
                pass
        fallback = format_model_reference_for_workflow(abs_path, comfy_dir)
        return self._normalize_workflow_value(fallback)

    def _normalize_workflow_value(self, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            return normalized
        normalized = normalized.replace("\\", "/")
        if os.sep == "\\":
            normalized = normalized.replace("/", "\\")
        return normalized

    def _apply_status_style(self, item: QtWidgets.QTableWidgetItem, status: str) -> None:
        status = (status or "").lower()
        color_map = {
            "found": SUCCESS_COLOR,
            "missing": "#B22222",
            "resolved": SUCCESS_COLOR,
            "copied": SUCCESS_COLOR,
        }
        text = {
            "found": "Found",
            "missing": "Missing",
            "resolved": "Resolved",
            "copied": "Copied",
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
            button.setText(status_text)
            button.setEnabled(False)
            if status_text.lower() in {"resolved", "copied"}:
                button.setStyleSheet(
                    "QPushButton {"
                    " background-color: #228B22;"
                    " color: white;"
                    " border: none;"
                    " border-radius: 4px;"
                    "}"
                )
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
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        thread.start()
        progress.exec()
        thread.wait()

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
        signature_value = row_info.get("reference_signature")
        if isinstance(signature_value, tuple):
            signature_payload: Optional[List[Optional[str]]] = list(signature_value)
        elif isinstance(signature_value, list):
            signature_payload = list(signature_value)
        else:
            signature_payload = None
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
                break
        else:
            payload = {"path": abs_path, "status": status}
            if reference_name:
                payload["reference"] = reference_name
            if workflow_value:
                payload["workflow_value"] = workflow_value
            if signature_payload is not None:
                payload["signature"] = signature_payload
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
            signature = row_info.get("reference_signature")
            if isinstance(signature, tuple):
                target_name, target_category, target_node = signature
                for i, item in enumerate(list(missing)):
                    if not isinstance(item, dict):
                        continue
                    if (
                        item.get("name") == target_name
                        and item.get("category") == target_category
                        and item.get("node_type") == target_node
                    ):
                        missing.pop(i)
                        break
            elif isinstance(reference, dict):
                target_name = reference.get("name")
                target_category = reference.get("category")
                target_node = reference.get("node_type")
                for i, item in enumerate(list(missing)):
                    if not isinstance(item, dict):
                        continue
                    if (
                        item.get("name") == target_name
                        and item.get("category") == target_category
                        and item.get("node_type") == target_node
                    ):
                        missing.pop(i)
                        break
            data["missing"] = [entry for entry in missing if isinstance(entry, dict)]

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
    def _notify_manual_download(self, file_name: str, models_root: str) -> None:
        if file_name:
            message = (
                f"Could not locate '{file_name}'. Please download it manually and place it under "
                "your ComfyUI/models directory."
            )
            if models_root:
                message += (
                    f"\nSuggested destination: {self._format_model_display_path(os.path.join(models_root, file_name), models_root)}"
                )
        else:
            message = (
                "Could not locate the referenced model. Please download it manually and place it "
                "under your ComfyUI/models directory."
            )
        QtWidgets.QMessageBox.information(self, "Model Missing", message)
        self._append_issue_note("models", message)

    # ---------------------------------------------------------------- Actions
    def _handle_revalidate_clicked(self) -> None:
        self.done(1)

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

    def _resolve_model_entry(self, row: int, row_info: Dict[str, Any]) -> bool:
        reference = row_info.get("reference") or {}
        original_name = str(reference.get("name") or "").strip()
        models_root = row_info.get("models_root") or ""
        comfy_dir = (self._comfy_info or {}).get("comfy_dir") or ""
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
                title="Copy Shared Model",
                prompt="A matching model was found in the shared repository. Choose which file to copy.",
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
                answer = QtWidgets.QMessageBox.question(
                    self,
                    "Copy Model",
                    (
                        f"Copy '{file_name}' to your ComfyUI models folder?\n\n"
                        f"Destination:\n{destination_display}"
                    ),
                    QtWidgets.QMessageBox.StandardButton.Yes
                    | QtWidgets.QMessageBox.StandardButton.No,
                )
                if answer == QtWidgets.QMessageBox.StandardButton.Yes:
                    success, message = self._copy_shared_model(selected, expected_path)
                    if success:
                        note = f"Copied {file_name} to {destination_display}."
                        self._mark_model_resolved(
                            row,
                            "Copied",
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
                        QtWidgets.QMessageBox.warning(self, "Copy Failed", message)
                else:
                    self._append_issue_note("models", "Copy canceled by user.")

        self._notify_manual_download(file_name, models_root)
        return False
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
