from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ..qt_compat import QtCore, QtWidgets
from ..validation_resolver import (
    ResolutionResult,
    resolve_missing_custom_nodes,
    resolve_missing_models,
)


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
            detail_label = QtWidgets.QLabel(str(detail))
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
