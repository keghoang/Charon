from __future__ import annotations

import copy
import json
import os
import urllib.request
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
    install_custom_nodes_via_playwright,
    resolve_missing_custom_nodes,
    resolve_missing_models,
)
from ..workflow_overrides import replace_workflow_model_paths, save_workflow_override
from ..workflow_local_store import write_validation_resolve_status


SUCCESS_COLOR = "#228B22"
VALIDATION_COLUMN_WIDTHS = (260, 100)
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


COLORS = {
    "bg_main": "#212529",
    "bg_card": "#17191d",
    "bg_hover": "#3f3f46",
    "text_main": "#f4f4f5",
    "text_sub": "#a1a1aa",
    "danger": "#ef4444",
    "success": "#22c55e",
    "restart": "#f97316",
    "restart_hover": "#fb923c",
    "border": "#3f3f46",
    "btn_bg": "#27272a",
}

STYLESHEET = f"""
    QDialog {{
        background-color: {COLORS['bg_main']};
        font-family: 'Segoe UI', 'Inter', sans-serif;
    }}
    QLabel {{
        color: {COLORS['text_main']};
    }}
    QLabel#Heading {{
        font-size: 20px;
        font-weight: 700;
    }}
    QLabel#SubHeading {{
        font-size: 15px;
        color: {COLORS['text_sub']};
    }}
    QLabel#SectionLabel {{
        font-size: 15px;
        font-weight: 600;
        margin-bottom: 6px;
        margin-top: 15px;
    }}
    QFrame#SuccessCard {{
        background-color: {COLORS['bg_card']};
        border-radius: 6px;
    }}
    QFrame#IssueGroup {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
    }}
    QPushButton#ResolveBtn {{
        background-color: transparent;
        border: 1px solid {COLORS['border']};
        border-radius: 4px;
        color: {COLORS['text_main']};
        font-size: 13px;
        padding: 4px 10px; 
    }}
    QPushButton#ResolveBtn:hover {{
        background-color: {COLORS['bg_hover']};
    }}
    QPushButton#ResolveBtn:disabled {{
        color: {COLORS['text_sub']};
        border-color: {COLORS['bg_hover']};
    }}
    QPushButton#FooterBtn {{
        background-color: {COLORS['btn_bg']};
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        padding: 10px;
        font-size: 14px;
        font-weight: 500;
        color: {COLORS['text_main']};
    }}
    QPushButton#FooterBtn:hover {{
        background-color: {COLORS['bg_hover']};
        border-color: {COLORS['text_sub']};
    }}
    QPushButton#RestartNotice {{
        background-color: {COLORS['restart']};
        border: 1px solid {COLORS['restart_hover']};
        border-radius: 6px;
        padding: 10px;
        font-size: 14px;
        font-weight: 600;
        color: #ffffff;
    }}
    QPushButton#RestartNotice:hover {{
        background-color: {COLORS['restart_hover']};
        border-color: {COLORS['restart_hover']};
    }}
"""


def _build_icon(name: str) -> QtGui.QIcon:
    size = 48 if "header" in name else 32
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    if name == "header_error":
        painter.setBrush(QtGui.QColor(COLORS["danger"]))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 40, 40)
        pen = QtGui.QPen(QtCore.Qt.GlobalColor.white, 3)
        painter.setPen(pen)
        painter.drawLine(14, 14, 26, 26)
        painter.drawLine(26, 14, 14, 26)

    elif name == "header_success":
        painter.setBrush(QtGui.QColor(COLORS["success"]))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawEllipse(0, 0, 40, 40)
        pen = QtGui.QPen(QtCore.Qt.GlobalColor.white, 3)
        painter.setPen(pen)
        path = QtGui.QPainterPath()
        path.moveTo(10, 20)
        path.lineTo(18, 28)
        path.lineTo(30, 12)
        painter.drawPath(path)

    elif name == "check":
        pen = QtGui.QPen(QtGui.QColor(COLORS["success"]), 2.5)
        painter.setPen(pen)
        path = QtGui.QPainterPath()
        path.moveTo(6, 16)
        path.lineTo(13, 23)
        path.lineTo(26, 9)
        painter.drawPath(path)

    elif name == "issue":
        circle_pen = QtGui.QPen(QtGui.QColor(COLORS["danger"]), 2)
        painter.setPen(circle_pen)
        painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        painter.drawEllipse(3, 3, 26, 26)
        painter.setBrush(QtGui.QColor(COLORS["danger"]))
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.drawEllipse(16 - 1, 22, 2, 2)
        painter.drawRoundedRect(16 - 1, 9, 2, 10, 1, 1)

    painter.end()
    return QtGui.QIcon(pixmap)


class CheckRow(QtWidgets.QWidget):
    def __init__(self, text: str, ok: bool = True, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(12)

        icon_lbl = QtWidgets.QLabel()
        icon_name = "check" if ok else "issue"
        icon_lbl.setPixmap(_build_icon(icon_name).pixmap(24, 24))
        icon_lbl.setFixedSize(24, 24)

        txt_lbl = QtWidgets.QLabel(text)
        txt_lbl.setStyleSheet("font-size: 14px;")

        layout.addWidget(icon_lbl)
        layout.addWidget(txt_lbl)
        layout.addStretch()


class IssueRow(QtWidgets.QWidget):
    def __init__(
        self,
        title: str,
        subtitle: str,
        *,
        success_text: str = "Item resolved",
        show_separator: bool = False,
        resolve_handler=None,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._resolve_handler = resolve_handler
        self._success_text = success_text
        self._is_resolving = False

        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        container = QtWidgets.QWidget()
        row_h = QtWidgets.QHBoxLayout(container)
        row_h.setContentsMargins(15, 15, 15, 15)
        row_h.setSpacing(12)

        self.icon_lbl = QtWidgets.QLabel()
        self.icon_lbl.setPixmap(_build_icon("issue").pixmap(24, 24))
        self.icon_lbl.setFixedSize(24, 24)

        text_widget = QtWidgets.QWidget()
        text_v = QtWidgets.QVBoxLayout(text_widget)
        text_v.setContentsMargins(0, 0, 0, 0)
        text_v.setSpacing(2)
        text_v.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)

        self.lbl_title = QtWidgets.QLabel(title)
        self.lbl_title.setStyleSheet("font-size: 14px; color: {0};".format(COLORS["text_main"]))

        self.lbl_sub = QtWidgets.QLabel(subtitle)
        self.lbl_sub.setStyleSheet("font-size: 13px; color: {0};".format(COLORS["text_sub"]))
        self.lbl_sub.setWordWrap(True)

        text_v.addWidget(self.lbl_title)
        text_v.addWidget(self.lbl_sub)

        self.btn_resolve = QtWidgets.QPushButton("Resolve")
        self.btn_resolve.setObjectName("ResolveBtn")
        self.btn_resolve.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.btn_resolve.setFixedSize(90, 32)
        self.btn_resolve.clicked.connect(self._on_resolve_clicked)

        row_h.addWidget(self.icon_lbl)
        row_h.addWidget(text_widget)
        row_h.addWidget(self.btn_resolve)

        self.layout.addWidget(container)

        if show_separator:
            line = QtWidgets.QFrame()
            line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
            line.setStyleSheet(f"background-color: {COLORS['border']}; border: none; max-height: 1px;")
            self.layout.addWidget(line)

        self.dots = 0
        self.anim_timer = QtCore.QTimer(self)
        self.anim_timer.timeout.connect(self._update_dots)

    # ------------------------------------------------------------------ UI helpers
    def _on_resolve_clicked(self) -> None:
        if self._is_resolving:
            return
        self.start_install_animation()
        if callable(self._resolve_handler):
            self._resolve_handler()

    def start_install_animation(self) -> None:
        self._is_resolving = True
        self.btn_resolve.setEnabled(False)
        self.btn_resolve.setFixedWidth(110)
        self.btn_resolve.setText("Resolving")
        self.dots = 0
        self.anim_timer.start(400)

    def reset_to_idle(self) -> None:
        self.anim_timer.stop()
        self._is_resolving = False
        self.btn_resolve.setEnabled(True)
        self.btn_resolve.setFixedWidth(90)
        self.btn_resolve.setText("Resolve")

    def mark_as_successful(self, message: Optional[str] = None, detail: Optional[str] = None) -> None:
        self.anim_timer.stop()
        self._is_resolving = False
        self.icon_lbl.setPixmap(_build_icon("check").pixmap(24, 24))
        self.btn_resolve.hide()
        if detail and str(detail).strip():
            self.lbl_sub.setText(str(detail).strip())
            self.lbl_sub.show()
        else:
            self.lbl_sub.hide()
        self.lbl_title.setText(message or self._success_text)

    def _update_dots(self) -> None:
        self.dots = (self.dots + 1) % 4
        self.btn_resolve.setText(f"Resolving{'.' * self.dots}")



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
    comfy_restart_requested = QtCore.Signal()
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
        self.setStyleSheet(STYLESHEET)
        self._payload = payload or {}
        self._comfy_path = comfy_path or ""
        self._workflow_bundle = workflow_bundle or {}
        self._issue_lookup: Dict[str, Dict[str, Any]] = {}
        self._issue_widgets: Dict[str, Dict[str, Any]] = {}
        self._issue_rows: Dict[str, List[IssueRow]] = {"models": [], "custom_nodes": []}
        self._checks_layout: Optional[QtWidgets.QVBoxLayout] = None
        self._issues_layout: Optional[QtWidgets.QVBoxLayout] = None
        self._success_checks_layout: Optional[QtWidgets.QVBoxLayout] = None
        self._stack: Optional[QtWidgets.QStackedWidget] = None
        self._header_title: Optional[QtWidgets.QLabel] = None
        self._header_subtitle: Optional[QtWidgets.QLabel] = None
        self._header_icon: Optional[QtWidgets.QLabel] = None
        self._auto_resolve_button: Optional[QtWidgets.QPushButton] = None
        self._success_title: Optional[QtWidgets.QLabel] = None
        self._success_subtitle: Optional[QtWidgets.QLabel] = None
        self._dependencies_cache: Optional[List[Dict[str, Any]]] = None
        self._workflow_folder: Optional[str] = None
        restart_flag = False
        if isinstance(self._payload, dict):
            restart_flag = bool(
                self._payload.get("restart_required") or self._payload.get("requires_restart")
            )
        self._restart_required = restart_flag
        self._restart_in_progress = False
        self._restart_anim_state = 0
        self._restart_anim_timer = QtCore.QTimer(self)
        self._restart_anim_timer.setInterval(400)
        self._restart_anim_timer.timeout.connect(self._tick_restart_animation)
        self._connection_online = False
        self._connection_widget: Optional[QtWidgets.QWidget] = None
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
        if not self._workflow_folder:
            workflow_info = self._payload.get("workflow") if isinstance(self._payload, dict) else {}
            if isinstance(workflow_info, dict):
                self._workflow_folder = workflow_info.get("folder") or None

        self._custom_node_package_map: Optional[Dict[str, str]] = None

        self._sanitize_custom_node_issue()
        self._sanitize_model_issue()
        self._build_ui()
        if self._restart_required:
            self._show_restart_cta("ComfyUI")

    def restart_required(self) -> bool:
        """Return whether a ComfyUI restart is still needed to finish resolving."""
        return bool(getattr(self, "_restart_required", False))

    def _sanitize_custom_node_issue(self) -> None:
        """Deduplicate missing custom nodes when loading cached payloads."""
        issues = self._payload.get("issues") if isinstance(self._payload, dict) else None
        if not isinstance(issues, list):
            return
        for issue in issues:
            if not isinstance(issue, dict) or issue.get("key") != "custom_nodes":
                continue
            data = issue.get("data")
            if not isinstance(data, dict):
                continue

            data.pop("raw_missing", None)
            missing_source = data.get("missing_packs") or []
            normalized_packs: list[dict] = []
            missing_names: list[str] = []
            missing_repos: list[str] = []
            unresolved_repos: list[str] = []
            node_repo_map: dict[str, str] = {}
            node_package_map: dict[str, str] = {}
            node_meta_map: dict[str, dict] = {}
            unresolved_nodes: list[str] = []
            existing_missing = [
                str(entry).strip()
                for entry in data.get("missing") or []
                if isinstance(entry, str) and str(entry).strip()
            ]

            if isinstance(missing_source, list):
                for pack in missing_source:
                    if not isinstance(pack, dict):
                        continue
                    repo = str(pack.get("repo") or "").strip()
                    pack_status = str(pack.get("resolve_status") or "").strip()
                    pack_method = str(pack.get("resolve_method") or "").strip()
                    pack_failed = str(pack.get("resolve_failed") or "").strip()
                    nodes = []
                    for node in pack.get("nodes") or []:
                        if not isinstance(node, dict):
                            continue
                        cls = str(node.get("class_type") or "").strip()
                        if repo and cls:
                            node_repo_map.setdefault(cls.lower(), repo)
                        pack_meta = pack.get("pack_meta") if isinstance(pack.get("pack_meta"), dict) else {}
                        if pack_meta and cls:
                            title_value = str(pack_meta.get("title") or "").strip()
                            if title_value:
                                node_package_map.setdefault(cls.lower(), title_value)
                            node_meta_map.setdefault(cls.lower(), pack_meta)
                        node_status = str(node.get("resolve_status") or "").strip()
                        node_method = str(node.get("resolve_method") or "").strip()
                        node_failed = str(node.get("resolve_failed") or "").strip()
                        if cls:
                            missing_names.append(cls)
                        nodes.append(
                            {
                                "class_type": cls,
                                "id": node.get("id"),
                            }
                        )
                        if not pack_status and node_status:
                            pack_status = node_status
                            pack_method = node_method if node_status == "success" else ""
                            pack_failed = node_failed if node_status == "failed" else ""
                    normalized_pack = dict(pack)
                    normalized_pack["repo"] = repo
                    normalized_pack["nodes"] = nodes
                    normalized_pack["resolve_status"] = pack_status
                    normalized_pack["resolve_method"] = pack_method if pack_status == "success" else ""
                    normalized_pack["resolve_failed"] = pack_failed if pack_status == "failed" else ""
                    normalized_packs.append(normalized_pack)
                    if repo:
                        missing_repos.append(repo)
                    if pack_status != "success":
                        if repo:
                            unresolved_repos.append(repo)
                        unresolved_nodes.extend([n.get("class_type") or "" for n in nodes if n.get("class_type")])

            if normalized_packs:
                data["missing_packs"] = normalized_packs
                data["missing_repos"] = unresolved_repos or data.get("missing_repos") or []
                data["node_repos"] = node_repo_map or data.get("node_repos") or {}
                data["node_packages"] = node_package_map or data.get("node_packages") or {}
                data["node_meta"] = node_meta_map or data.get("node_meta") or {}

            def _dedupe_str_list(values: list) -> list:
                seen = set()
                deduped = []
                for value in values or []:
                    normalized = str(value).strip()
                    if not normalized:
                        continue
                    key = normalized.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(value)
                return deduped

            # Dedupe by class_type (case-insensitive)
            data.pop("missing", None)
            data["required"] = _dedupe_str_list(data.get("required") or missing_names)
            if normalized_packs:
                data["missing"] = _dedupe_str_list(unresolved_nodes)
                data["missing_repos"] = _dedupe_str_list(unresolved_repos)
            else:
                data["missing"] = _dedupe_str_list(existing_missing or missing_names)
                data["missing_repos"] = _dedupe_str_list(data.get("missing_repos") or missing_repos)

            missing_entries = data.get("missing") or []
            unresolved_packs = [
                p for p in data.get("missing_packs") or [] if str(p.get("resolve_status") or "").strip() != "success"
            ]
            issue["ok"] = len(missing_entries) == 0
            if issue["ok"]:
                methods = [
                    str(p.get("resolve_method") or "").strip()
                    for p in data.get("missing_packs") or []
                    if str(p.get("resolve_method") or "").strip()
                ]
                method_fragment = f" Resolved via: {'; '.join(methods)}." if methods else ""
                issue["summary"] = f"All custom nodes resolved.{method_fragment}"
                issue["details"] = issue.get("details") or []
            else:
                issue["summary"] = f"Missing {len(missing_entries)} custom node(s)."
                detail_lines: list[str] = []
                missing_lookup = {str(entry).strip().lower() for entry in missing_entries if str(entry).strip()}
                for pack in unresolved_packs or data.get("missing_packs") or []:
                    if not isinstance(pack, dict):
                        continue
                    repo = pack.get("repo")
                    pack_ids: list[str] = []
                    for pid in pack.get("pack_ids") or []:
                        if isinstance(pid, str) and pid.strip():
                            pack_ids.append(pid.strip())
                    single_pack = pack.get("pack") or pack.get("pack_id")
                    if isinstance(single_pack, str) and single_pack.strip():
                        pack_ids.append(single_pack.strip())
                    for node in pack.get("nodes") or []:
                        if not isinstance(node, dict):
                            continue
                        cls = node.get("class_type") or "Unknown node"
                        if missing_lookup and cls.strip().lower() not in missing_lookup:
                            continue
                        aux_id = node.get("aux_id")
                        detail = f"{cls}"
                        if repo:
                            detail += f" -> {repo}"
                        elif pack_ids:
                            detail += f" -> {', '.join(pack_ids)}"
                        if aux_id:
                            detail += f" (aux_id: {aux_id})"
                        detail_lines.append(detail)

                if detail_lines:
                    issue["details"] = detail_lines

    def _sanitize_model_issue(self) -> None:
        issues = self._payload.get("issues") if isinstance(self._payload, dict) else None
        if not isinstance(issues, list):
            return
        for issue in issues:
            if not isinstance(issue, dict) or issue.get("key") != "models":
                continue
            data = issue.get("data")
            if not isinstance(data, dict):
                continue
            models_root = data.get("models_root") or ""
            if not isinstance(models_root, str):
                models_root = ""
            normalized_missing: list[dict] = []
            for entry in data.get("missing_models") or []:
                if not isinstance(entry, dict):
                    continue
                normalized = dict(entry)
                normalized.setdefault("resolve_status", "")
                normalized.setdefault("resolve_method", "")
                normalized.setdefault("resolve_failed", "")
                dirs: list[str] = []
                for path in normalized.get("attempted_directories") or []:
                    if not isinstance(path, str):
                        continue
                    abs_path = os.path.abspath(path if os.path.isabs(path) else os.path.join(models_root, path))
                    if abs_path not in dirs:
                        dirs.append(abs_path)
                if dirs:
                    normalized["attempted_directories"] = dirs
                normalized_missing.append(normalized)
            data["missing_models"] = normalized_missing
            unresolved_models = [
                e for e in normalized_missing if str(e.get("resolve_status") or "").strip() != "success"
            ]
            issue["ok"] = len(unresolved_models) == 0
            if issue["ok"]:
                methods = [
                    str(e.get("resolve_method") or "").strip() for e in normalized_missing if e.get("resolve_method")
                ]
                method_fragment = f" Resolved via: {'; '.join(methods)}." if methods else ""
                issue["summary"] = f"All required model files resolved.{method_fragment}"
            else:
                issue["summary"] = f"Missing {len(unresolved_models)} model file(s)."

    # --------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        self._stack = QtWidgets.QStackedWidget(self)
        failed_page = self._build_failed_page()
        success_page = self._build_success_page()
        self._stack.addWidget(failed_page)
        self._stack.addWidget(success_page)

        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._stack)

        self._populate_sections()
        self._update_overall_state()
        self.resize(520, 620)

    def _build_failed_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(10)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setSpacing(15)

        self._header_icon = QtWidgets.QLabel()
        self._header_icon.setPixmap(_build_icon("header_error").pixmap(40, 40))
        self._header_icon.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)

        text_stack = QtWidgets.QVBoxLayout()
        text_stack.setSpacing(0)

        self._header_title = QtWidgets.QLabel("Validation Failed")
        self._header_title.setObjectName("Heading")
        self._header_subtitle = QtWidgets.QLabel("Issues need attention")
        self._header_subtitle.setObjectName("SubHeading")

        text_stack.addWidget(self._header_title)
        text_stack.addWidget(self._header_subtitle)
        header_layout.addWidget(self._header_icon)
        header_layout.addLayout(text_stack)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        layout.addSpacing(10)

        lbl_checks = QtWidgets.QLabel("Checks")
        lbl_checks.setObjectName("SectionLabel")
        layout.addWidget(lbl_checks)

        check_card = QtWidgets.QFrame()
        check_card.setObjectName("SuccessCard")
        self._checks_layout = QtWidgets.QVBoxLayout(check_card)
        self._checks_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(check_card)

        lbl_issues = QtWidgets.QLabel("Issues")
        lbl_issues.setObjectName("SectionLabel")
        layout.addWidget(lbl_issues)

        issue_group = QtWidgets.QFrame()
        issue_group.setObjectName("IssueGroup")
        self._issues_layout = QtWidgets.QVBoxLayout(issue_group)
        self._issues_layout.setContentsMargins(0, 0, 0, 0)
        self._issues_layout.setSpacing(0)
        layout.addWidget(issue_group)
        layout.addSpacing(20)

        self._restart_button = QtWidgets.QPushButton("Press to Restart ComfyUI to finish resolving")
        self._restart_button.setObjectName("RestartNotice")
        self._restart_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._restart_button.hide()
        self._restart_button.clicked.connect(self._on_restart_clicked)
        layout.addWidget(self._restart_button)
        layout.addSpacing(10)

        footer = QtWidgets.QHBoxLayout()
        footer.setSpacing(15)

        self._auto_resolve_button = QtWidgets.QPushButton("✨ Auto-resolve All")
        self._auto_resolve_button.setObjectName("FooterBtn")
        self._auto_resolve_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._auto_resolve_button.clicked.connect(self._auto_resolve_all)

        btn_close = QtWidgets.QPushButton("Close")
        btn_close.setObjectName("FooterBtn")
        btn_close.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        btn_close.clicked.connect(self.close)

        footer.addWidget(self._auto_resolve_button)
        footer.addWidget(btn_close)
        layout.addLayout(footer)

        return page

    def _build_success_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(10)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.setSpacing(15)

        icon_lbl = QtWidgets.QLabel()
        icon_lbl.setPixmap(_build_icon("header_success").pixmap(40, 40))
        icon_lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)

        text_stack = QtWidgets.QVBoxLayout()
        text_stack.setSpacing(0)

        self._success_title = QtWidgets.QLabel("Validation Successful!")
        self._success_title.setObjectName("Heading")
        self._success_subtitle = QtWidgets.QLabel("All requirements found")
        self._success_subtitle.setObjectName("SubHeading")

        text_stack.addWidget(self._success_title)
        text_stack.addWidget(self._success_subtitle)
        header_layout.addWidget(icon_lbl)
        header_layout.addLayout(text_stack)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        layout.addSpacing(10)

        lbl_checks = QtWidgets.QLabel("Checks")
        lbl_checks.setObjectName("SectionLabel")
        layout.addWidget(lbl_checks)

        check_card = QtWidgets.QFrame()
        check_card.setObjectName("SuccessCard")
        self._success_checks_layout = QtWidgets.QVBoxLayout(check_card)
        self._success_checks_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(check_card)
        layout.addStretch()

        footer = QtWidgets.QHBoxLayout()
        btn_done = QtWidgets.QPushButton("Done")
        btn_done.setObjectName("FooterBtn")
        btn_done.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        btn_done.clicked.connect(self.accept)
        footer.addWidget(btn_done)
        layout.addLayout(footer)
        return page

    def _populate_sections(self) -> None:
        supported_keys = {"models", "custom_nodes"}
        issues = [
            issue
            for issue in (self._payload.get("issues") or [])
            if isinstance(issue, dict) and str(issue.get("key") or "") in supported_keys
        ]
        self._issue_lookup = {str(issue.get("key") or ""): issue for issue in issues}
        self._issue_widgets = {}
        self._issue_rows = {"models": [], "custom_nodes": []}

        if self._checks_layout:
            self._clear_layout(self._checks_layout)
        if self._issues_layout:
            self._clear_layout(self._issues_layout)
        if self._success_checks_layout:
            self._clear_layout(self._success_checks_layout)

        self._populate_issue_section(issues)
        self._refresh_check_rows()

    def _remaining_rows(self, key: str) -> int:
        widget_info = self._issue_widgets.get(key) or {}
        rows = widget_info.get("rows") or {}
        remaining = 0
        for row_info in rows.values():
            if row_info.get("resolved"):
                continue
            remaining += 1
        return remaining

    def _refresh_check_rows(self) -> None:
        checks = [
            ("All models found", self._remaining_rows("models") == 0, "Models need attention"),
            ("All custom nodes found", self._remaining_rows("custom_nodes") == 0, "Custom nodes need attention"),
        ]

        for layout in (self._checks_layout, self._success_checks_layout):
            if not layout:
                continue
            self._clear_layout(layout)
            for passed_text, ok, pending_text in checks:
                text = passed_text if ok else pending_text
                layout.addWidget(CheckRow(text, ok=ok))

    def _populate_issue_section(self, issues: List[Dict[str, Any]]) -> None:
        if not self._issues_layout:
            return
        added_rows = False
        for issue in issues:
            key = str(issue.get("key") or "")
            if key == "models":
                added_rows = self._build_model_issue_rows(issue) or added_rows
            elif key == "custom_nodes":
                added_rows = self._build_custom_node_issue_rows(issue) or added_rows
        if not added_rows:
            placeholder = QtWidgets.QLabel("No validation issues reported.")
            placeholder.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self._issues_layout.addWidget(placeholder)

    def _build_model_issue_rows(self, issue: Dict[str, Any]) -> bool:
        data = issue.get("data") or {}
        temp_table = QtWidgets.QTableWidget(self)
        temp_table.setVisible(False)
        row_mapping = self._populate_models_table(temp_table, data)
        status_label = QtWidgets.QLabel()
        status_label.hide()
        self._issue_widgets["models"] = {
            "status_label": status_label,
            "rows": row_mapping,
            "table": temp_table,
        }
        self._refresh_models_issue_status()

        if not row_mapping:
            return False

        ordered_rows = sorted(row_mapping.items(), key=lambda item: item[0])
        total = len(ordered_rows)
        for position, (idx, row_info) in enumerate(ordered_rows):
            reference = row_info.get("reference") or {}
            name_value = reference.get("name") or reference.get("path") or ""
            folder_path = row_info.get("folder_path") or reference.get("folder_path") or ""
            url_value = (
                row_info.get("url")
                or reference.get("url")
                or reference.get("raw", {}).get("url")
            )
            category_value = row_info.get("category") or reference.get("category") or ""
            directory_invalid = bool(
                row_info.get("directory_invalid") or reference.get("directory_invalid")
            )
            display_source = folder_path or name_value
            display_name = (
                os.path.basename(display_source) or os.path.basename(name_value) or "Model"
            )
            models_root = row_info.get("models_root") or ""
            target_hint = display_source or models_root
            subtitle_parts = []
            if category_value:
                subtitle_parts.append(f"Folder: {category_value}")
            if directory_invalid:
                subtitle_parts.append("Directory invalid")
            if url_value:
                subtitle_parts.append(f"URL: {url_value}")
            subtitle = " | ".join(subtitle_parts) if subtitle_parts else "Model location"
            issue_row = IssueRow(
                f"Missing model: {display_name}",
                subtitle,
                success_text=f"{display_name} resolved",
                show_separator=(position < total - 1),
                resolve_handler=lambda row_index=idx: self._handle_model_auto_resolve(row_index),
            )
            row_info["issue_row"] = issue_row
            row_info["button"] = issue_row.btn_resolve
            row_info["success_text"] = f"{display_name} resolved"
            if row_info.get("resolved"):
                issue_row.mark_as_successful(
                    row_info.get("success_text"),
                    detail=row_info.get("resolve_method") or None,
                )
            self._issue_rows.setdefault("models", []).append(issue_row)
            self._issues_layout.addWidget(issue_row)
        return True

    def _build_custom_node_issue_rows(self, issue: Dict[str, Any]) -> bool:
        data = issue.get("data") or {}
        temp_table = QtWidgets.QTableWidget(self)
        temp_table.setVisible(False)
        row_mapping = self._populate_custom_nodes_table(temp_table, data)
        status_label = QtWidgets.QLabel()
        status_label.hide()
        self._issue_widgets["custom_nodes"] = {
            "status_label": status_label,
            "summary_label": QtWidgets.QLabel(),
            "rows": row_mapping,
            "table": temp_table,
        }
        self._refresh_custom_nodes_issue_status()

        if not row_mapping:
            return False

        ordered_rows = sorted(row_mapping.items(), key=lambda item: item[0])
        total = len(ordered_rows)
        for position, (idx, row_info) in enumerate(ordered_rows):
            package_display = row_info.get("package_name") or row_info.get("node_name") or "Custom node"
            repo_url = row_info.get("manager_repo") or ""
            subtitle = repo_url or "Install missing package into custom_nodes"
            issue_row = IssueRow(
                f"Missing node: {package_display}",
                subtitle,
                success_text=f"{package_display} installed",
                show_separator=(position < total - 1),
                resolve_handler=lambda row_index=idx: self._handle_custom_node_auto_resolve(row_index),
            )
            row_info["issue_row"] = issue_row
            row_info["button"] = issue_row.btn_resolve
            row_info["success_text"] = f"{package_display} installed"
            if row_info.get("resolved"):
                issue_row.mark_as_successful(
                    row_info.get("success_text"),
                    detail=row_info.get("resolve_method") or "",
                )
            self._issue_rows.setdefault("custom_nodes", []).append(issue_row)
            self._issues_layout.addWidget(issue_row)
        return True

    def _clear_layout(self, layout: QtWidgets.QLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())  # type: ignore[arg-type]

    def _update_overall_state(self) -> None:
        total_missing = 0
        for key in ("models", "custom_nodes"):
            widget_info = self._issue_widgets.get(key) or {}
            rows = widget_info.get("rows") or {}
            for row_info in rows.values():
                if row_info.get("resolved"):
                    continue
                total_missing += 1

        restart_required = bool(self._restart_required)
        has_resolved_history = False
        for key in ("models", "custom_nodes"):
            widget_info = self._issue_widgets.get(key) or {}
            rows = widget_info.get("rows") or {}
            for row_info in rows.values():
                if row_info.get("resolved"):
                    has_resolved_history = True
                    break
            if has_resolved_history:
                break

        if self._header_subtitle:
            subtitle_text = "All issues resolved" if total_missing == 0 else f"{total_missing} issue(s) need attention"
            if restart_required and total_missing == 0:
                subtitle_text = "Restart ComfyUI to finish resolving"
            self._header_subtitle.setText(subtitle_text)
        if self._header_title:
            self._header_title.setText("Validation Successful" if total_missing == 0 else "Validation Failed")
        if self._header_icon:
            icon_name = "header_success" if total_missing == 0 else "header_error"
            self._header_icon.setPixmap(_build_icon(icon_name).pixmap(40, 40))

        if self._success_subtitle:
            self._success_subtitle.setText("All requirements found")

        if self._stack:
            target = 1 if (total_missing == 0 and not restart_required and not has_resolved_history) else 0
            self._stack.setCurrentIndex(target)
        self._refresh_check_rows()

    def _auto_resolve_all(self) -> None:
        if not self._auto_resolve_button:
            return
        self._auto_resolve_button.setText("Resolving...")
        self._auto_resolve_button.setEnabled(False)
        QtWidgets.QApplication.processEvents()
        for key in ("custom_nodes", "models"):
            self._handle_auto_resolve(key)
        self._auto_resolve_button.setText("✨ Auto-resolve All")
        self._auto_resolve_button.setEnabled(True)
        self._populate_sections()
        self._update_overall_state()


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
        missing = data.get("missing_models") or []
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
                data["missing_models"] = missing
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
            folder_path = str(reference.get("folder_path") or reference.get("path") or "").strip()
            category_value = str(reference.get("category") or reference.get("directory") or "").strip()
            display_source = folder_path or name
            display_name = os.path.basename(display_source) or os.path.basename(name) or "Unknown Model"
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
            if folder_path and not reference.get("path"):
                reference["path"] = folder_path
            if folder_path and not reference.get("folder_path"):
                reference["folder_path"] = folder_path
            name_item = QtWidgets.QTableWidgetItem(display_name)
            resolve_status = str(reference.get("resolve_status") or "").strip().lower()
            resolve_method = str(reference.get("resolve_method") or "").strip()
            resolved_flag = resolve_status in {"success", "resolved", "copied"}
            if resolved_flag and resolve_method:
                name_item.setText(f"{display_name}\n{resolve_method}")
                name_item.setTextAlignment(
                    QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
                )
                name_item.setToolTip(f"{display_name}\n{resolve_method}")
            table.setItem(row, 0, name_item)
            status_text = "Resolved" if resolved_flag else "Missing"
            status_item = QtWidgets.QTableWidgetItem(status_text)
            self._apply_status_style(status_item, status_text)
            if resolved_flag and resolve_method:
                status_item.setText(f"{status_text}\n{resolve_method}")
                status_item.setToolTip(resolve_method)
                status_item.setTextAlignment(
                    QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
                )
            else:
                status_item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            table.setItem(row, 1, status_item)
            location_text = display_source or name or "Not provided"
            location_item = QtWidgets.QTableWidgetItem(location_text)
            url_value = reference.get("url") or (raw_data.get("url") if isinstance(raw_data, dict) else "")
            tooltip_parts = [location_text]
            if url_value:
                tooltip_parts.append(url_value)
            if resolve_method:
                tooltip_parts.append(f"Resolved via: {resolve_method}")
            location_item.setToolTip("\n".join([part for part in tooltip_parts if part]))
            if reference.get("directory_invalid"):
                location_item.setForeground(QtGui.QBrush(QtGui.QColor("#DAA520")))
            else:
                location_item.setForeground(
                    QtGui.QBrush(QtGui.QColor(SUCCESS_COLOR if resolved_flag else "#B22222"))
                )
            table.setItem(row, 2, location_item)
            button: Optional[QtWidgets.QPushButton]
            if resolved_flag:
                button = QtWidgets.QPushButton("Resolved")
                button.setEnabled(False)
                button.setStyleSheet(
                    "QPushButton {"
                    " background-color: #228B22;"
                    " color: white;"
                    " border: none;"
                    " border-radius: 4px;"
                    " padding: 2px 8px;"
                    " }"
                )
            else:
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
                    category_value,
                    reference.get("node_type"),
                ),
                "button": button,
                "status_item": status_item,
                "location_item": location_item,
                "models_root": models_root,
                "row_index": row,
                "reference_index": index,
                "original_location": location_text,
                "category": category_value,
                "folder_path": folder_path,
                "url": url_value,
                "directory_invalid": bool(reference.get("directory_invalid")),
                "model_paths": data.get("model_paths") or {},
                "resolved": resolved_flag,
                "resolve_method": resolve_method,
            }
            row += 1

        table.resizeRowsToContents()
        return row_mapping

    def _populate_custom_nodes_table(
        self,
        table: QtWidgets.QTableWidget,
        data: Dict[str, Any],
    ) -> Dict[int, Dict[str, Any]]:
        packs = data.get("missing_packs") or []
        pack_method_lookup: Dict[str, str] = {}
        if isinstance(packs, list):
            for pack in packs:
                if not isinstance(pack, dict):
                    continue
                status_value = str(pack.get("resolve_status") or "").strip().lower()
                method_value = str(pack.get("resolve_method") or "").strip()
                repo_key = str(pack.get("repo") or "").strip().lower()
                pack_key = (
                    str(pack.get("pack") or pack.get("pack_name") or pack.get("pack_id") or "").strip().lower()
                )
                for key in (repo_key, pack_key):
                    if key and status_value == "success" and method_value:
                        pack_method_lookup.setdefault(key, method_value)
        required = data.get("required") or []
        if not required and isinstance(packs, list):
            for pack in packs:
                if not isinstance(pack, dict):
                    continue
                for node in pack.get("nodes") or []:
                    if not isinstance(node, dict):
                        continue
                    node_type = str(node.get("class_type") or "").strip()
                    if node_type:
                        required.append(node_type)
        missing_entries = data.get("missing") if data.get("missing") is not None else required
        repo_lookup = data.get("node_repos") or {}
        package_overrides = data.get("node_packages") or {}
        aux_repos = data.get("aux_repos") or {}
        node_meta = data.get("node_meta") or {}

        self._ensure_custom_node_package_map()

        filtered_required: List[Tuple[str, str]] = []
        skip_nodes: set[str] = set()
        for node_name in required:
            node_type = str(node_name).strip()
            if not node_type:
                continue
            node_key_lower = node_type.lower()
            inferred_package = repo_lookup.get(node_key_lower) or aux_repos.get(node_key_lower) or ""
            package_name = self._package_for_node_type(node_type) or inferred_package or "Unknown package"
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

        if not filtered_required:
            table.setRowCount(1)
            table.setColumnHidden(1, True)
            placeholder = QtWidgets.QTableWidgetItem("No custom node data reported.")
            placeholder.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            table.setItem(0, 0, placeholder)
            table.setSpan(0, 0, 1, 2)
            return {}

        table.setColumnHidden(1, False)

        groups: Dict[str, Dict[str, Any]] = {}
        for node_type, package_name in filtered_required:
            node_key_lower = node_type.lower()
            repo_url = repo_lookup.get(node_key_lower) or ""
            meta_info = node_meta.get(node_key_lower) or {}
            repo_display = (
                meta_info.get("package_display")
                or package_overrides.get(node_key_lower)
                or self._repo_display_name(repo_url)
            )
            display_name = package_name or repo_display or "Unknown package"
            normalized_key = (display_name or "").strip().lower()
            pkg_entry = groups.setdefault(
                normalized_key,
                {
                    "package_display": display_name,
                    "repo_url": repo_url,
                    "repo_display": repo_display,
                    "author": meta_info.get("author") or "",
                    "last_update": meta_info.get("last_update") or "",
                    "nodes": [],
                    "resolve_method": "",
                },
            )
            if not pkg_entry.get("package_display"):
                pkg_entry["package_display"] = display_name
            if repo_url and not pkg_entry.get("repo_url"):
                pkg_entry["repo_url"] = repo_url
                pkg_entry["repo_display"] = repo_display
            if not pkg_entry.get("author") and meta_info.get("author"):
                pkg_entry["author"] = meta_info["author"]
            if not pkg_entry.get("last_update") and meta_info.get("last_update"):
                pkg_entry["last_update"] = meta_info["last_update"]
            if not pkg_entry.get("resolve_method"):
                lookup_keys = [
                    repo_url.strip().lower(),
                    (display_name or "").strip().lower(),
                    (repo_display or "").strip().lower(),
                ]
                for key in lookup_keys:
                    if key and key in pack_method_lookup:
                        pkg_entry["resolve_method"] = pack_method_lookup[key]
                        break
            pkg_entry["nodes"].append(node_type)

        ordered_packages = sorted(groups.values(), key=lambda x: (x.get("package_display") or "").lower())
        table.setRowCount(len(ordered_packages))

        row_mapping: Dict[int, Dict[str, Any]] = {}
        row = 0
        for info in ordered_packages:
            repo_url = info.get("repo_url") or ""
            repo_display = info.get("repo_display") or self._repo_display_name(repo_url)
            package_display = info.get("package_display") or repo_display or "Unknown package"
            missing_nodes = [n for n in info["nodes"] if n.lower() in missing_set]
            author_value = info.get("author") or ""
            last_update_value = info.get("last_update") or ""
            resolve_method = info.get("resolve_method") or ""

            name_text = package_display
            if resolve_method:
                name_text = f"{package_display}\n{resolve_method}"
            name_item = QtWidgets.QTableWidgetItem(name_text)
            tooltip_parts = [repo_url or package_display]
            if resolve_method:
                tooltip_parts.append(f"Resolved via: {resolve_method}")
            name_item.setToolTip("\n".join([part for part in tooltip_parts if part]))
            if missing_nodes:
                name_item.setForeground(QtGui.QBrush(QtGui.QColor("#B22222")))
            else:
                name_item.setForeground(QtGui.QBrush(QtGui.QColor(SUCCESS_COLOR)))
            table.setItem(row, 0, name_item)

            if missing_nodes:
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
                table.setCellWidget(row, 1, button)
                row_mapping[row] = {
                    "node_name": ", ".join(missing_nodes) or package_display,
                    "package_name": package_display,
                    "manager_repo": repo_url,
                    "manager_repo_display": repo_display or package_display,
                    "status_item": name_item,
                    "package_item": name_item,
                    "button": button,
                    "dependency": None,
                    "resolved": False,
                    "missing_nodes": missing_nodes,
                    "resolve_method": resolve_method or "Installed",
                }
            else:
                placeholder_widget = QtWidgets.QWidget()
                table.setCellWidget(row, 1, placeholder_widget)
                row_mapping[row] = {
                    "node_name": package_display,
                    "package_name": package_display,
                    "manager_repo": repo_url,
                    "manager_repo_display": repo_display or package_display,
                    "status_item": name_item,
                    "package_item": name_item,
                    "button": None,
                    "dependency": None,
                    "resolved": True,
                    "missing_nodes": [],
                    "resolve_method": resolve_method or "Installed",
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
        missing = data.get("missing_models") or []
        unresolved: List[Dict[str, Any]] = []
        for entry in missing:
            if not isinstance(entry, dict):
                continue
            status_value = str(entry.get("resolve_status") or "").strip().lower()
            if status_value in {"success", "resolved", "copied"}:
                continue
            unresolved.append(entry)
        missing_count = len(unresolved)
        status_label = widget_info.get("status_label")
        if missing_count:
            issue["ok"] = False
            if isinstance(status_label, QtWidgets.QLabel):
                status_label.setText("\u2717 Failed")
                status_label.setStyleSheet("font-weight: bold; color: #B22222;")
            issue["summary"] = f"Missing {missing_count} model file(s)."
        else:
            issue["ok"] = True
            if isinstance(status_label, QtWidgets.QLabel):
                status_label.setText("\u2713 Passed")
                status_label.setStyleSheet("font-weight: bold; color: #228B22;")
            issue["summary"] = "All required model files located."
            issue["details"] = []
        self._update_overall_state()

    def _refresh_custom_nodes_issue_status(self) -> None:
        issue = self._issue_lookup.get("custom_nodes")
        widget_info = self._issue_widgets.get("custom_nodes")
        if not issue or not widget_info:
            return

        data = issue.get("data") or {}
        missing = data.get("missing") or []
        unknown_nodes = data.get("unknown_nodes") or []
        status_label = widget_info.get("status_label")
        summary_label = widget_info.get("summary_label")

        if missing:
            issue["ok"] = False
            if isinstance(status_label, QtWidgets.QLabel):
                status_label.setText("\u2717 Failed")
                status_label.setStyleSheet("font-weight: bold; color: #B22222;")
            summary_text = f"Missing {len(missing)} custom node type(s)."
        elif unknown_nodes:
            issue["ok"] = True
            if isinstance(status_label, QtWidgets.QLabel):
                status_label.setText("\u26A0 Warning")
                status_label.setStyleSheet("font-weight: bold; color: #DAA520;")
            summary_text = f"{len(unknown_nodes)} unknown custom node class(es) detected."
        else:
            issue["ok"] = True
            if isinstance(status_label, QtWidgets.QLabel):
                status_label.setText("\u2713 Passed")
                status_label.setStyleSheet("font-weight: bold; color: #228B22;")
            summary_text = "All custom nodes found."

        if isinstance(summary_label, QtWidgets.QLabel):
            summary_label.setText(summary_text)
            if missing:
                summary_label.setStyleSheet("")
            else:
                summary_label.setStyleSheet("font-weight: bold;")
        issue["summary"] = summary_text
        self._update_overall_state()


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

    @staticmethod
    def _repo_display_name(repo: str) -> str:
        if not repo:
            return ""
        parsed = urlparse(repo)
        path = (parsed.path or "").rstrip("/")
        if path:
            name = path.split("/")[-1]
        else:
            name = os.path.basename(repo.rstrip("/"))
        if name.endswith(".git"):
            name = name[:-4]
        return name or repo

    @staticmethod
    def _normalize_repo_identifier(value: str) -> str:
        if not value:
            return ""
        return value.strip().rstrip("/").lower()

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
        method_detail = row_info.get("resolve_method") or note or display_text
        row_info["resolve_method"] = method_detail
        issue_row = row_info.get("issue_row")
        models_widget = self._issue_widgets.get("models") or {}
        rows_mapping: Dict[Any, Dict[str, Any]] = models_widget.get("rows") or {}
        target_idx = row_info.get("reference_index")
        system_debug(
            "[Validation] Model resolve UI sync | "
            f"row={row} target_idx={target_idx} method='{method_detail}' "
            f"has_issue_row={isinstance(issue_row, IssueRow)} rows={len(rows_mapping)}"
        )
        if issue_row is None:
            for row_data in rows_mapping.values():
                if not isinstance(row_data, dict):
                    continue
                candidate = row_data.get("issue_row")
                if not isinstance(candidate, IssueRow):
                    continue
                if target_idx is None or row_data.get("reference_index") == target_idx:
                    issue_row = candidate
                    row_info["issue_row"] = candidate
                    system_debug("[Validation] Model resolve UI sync | issue_row backfilled from rows mapping")
                    break
        if isinstance(issue_row, IssueRow):
            issue_row.mark_as_successful(
                row_info.get("success_text") or status_text,
                detail=method_detail or None,
            )
            if method_detail and hasattr(issue_row, "lbl_sub"):
                issue_row.lbl_sub.setText(method_detail)
                issue_row.lbl_sub.show()
                issue_row.lbl_sub.adjustSize()
                issue_row.lbl_sub.repaint()
            issue_row.adjustSize()
            issue_row.updateGeometry()
            issue_row.repaint()
            try:
                QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
            except Exception:
                pass
        # Also update any other IssueRow entries that share this reference index.
        if target_idx is not None:
            for row_data in rows_mapping.values():
                if not isinstance(row_data, dict):
                    continue
                if row_data.get("reference_index") != target_idx:
                    continue
                row_data["resolve_method"] = method_detail
                candidate = row_data.get("issue_row")
                if isinstance(candidate, IssueRow):
                    candidate.mark_as_successful(
                        row_data.get("success_text") or status_text,
                        detail=method_detail or None,
                    )
                    if method_detail and hasattr(candidate, "lbl_sub"):
                        candidate.lbl_sub.setText(method_detail)
                        candidate.lbl_sub.show()
                        candidate.lbl_sub.adjustSize()
                        candidate.lbl_sub.repaint()
                    candidate.adjustSize()
                    candidate.updateGeometry()
                    candidate.repaint()
                    try:
                        QtWidgets.QApplication.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents)
                    except Exception:
                        pass
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
            reference["resolve_status"] = "success"
            reference["resolve_method"] = method_detail
            reference["resolve_failed"] = ""
        # Avoid duplicating the resolve method in a separate note when already resolved.
        if note and lower_status not in {"resolved", "copied"}:
            self._append_issue_note("models", note)
        # Update backing payload so reopen pulls resolved state from cache.
        issues = self._payload.get("issues") if isinstance(self._payload, dict) else None
        if isinstance(issues, list):
            for issue in issues:
                if not isinstance(issue, dict) or issue.get("key") != "models":
                    continue
                data = issue.get("data") or {}
                if not isinstance(data, dict):
                    continue
                missing_list = data.get("missing_models")
                idx = row_info.get("reference_index")
                if isinstance(missing_list, list) and isinstance(idx, int) and 0 <= idx < len(missing_list):
                    entry = missing_list[idx]
                    if isinstance(entry, dict):
                        entry["resolve_status"] = "success"
                        entry["resolve_method"] = method_detail
                        entry["resolve_failed"] = ""
                break
        if self._workflow_folder:
            try:
                write_validation_resolve_status(self._workflow_folder, self._payload, overwrite=True)
            except Exception:
                pass
        self._refresh_models_issue_status()
        self._refresh_models_issue_status()
        issue_info = self._issue_lookup.get("models") or {}
        issue_data = issue_info.get("data") if isinstance(issue_info, dict) else {}
        missing_after = issue_data.get("missing_models") if isinstance(issue_data, dict) else None
        remaining_unresolved: Any = "unknown"
        if isinstance(missing_after, list):
            remaining_unresolved = 0
            for entry in missing_after:
                if not isinstance(entry, dict):
                    continue
                status_value = str(entry.get("resolve_status") or "").strip().lower()
                if status_value in {"success", "resolved", "copied"}:
                    continue
                remaining_unresolved += 1
        if self._workflow_folder:
            try:
                write_validation_resolve_status(self._workflow_folder, self._payload, overwrite=True)
                system_debug(
                    f"[Validation] Persisted resolve status after model update | path='{self._workflow_folder}'"
                )
            except Exception as exc:
                system_warning(f"Failed to persist resolve status after model update: {exc}")
        else:
            system_debug("[Validation] Skipped resolve status persist; workflow folder unavailable")
        system_debug(
            "[Validation] Completed mark model resolved | "
            f"row={row} remaining_missing={remaining_unresolved} "
            f"issue_ok={issue_info.get('ok') if isinstance(issue_info, dict) else 'unknown'}"
        )
        self._update_overall_state()

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

        missing = data.get("missing_models")
        if isinstance(missing, list):
            status_lower = status.lower()
            resolve_status_value = "success" if status_lower in {"resolved", "copied"} else status_lower
            resolve_method_value = str(row_info.get("resolve_method") or "").strip() or status
            updated_missing = False

            def _update_missing_entry(entry: Dict[str, Any]) -> None:
                nonlocal updated_missing
                if not isinstance(entry, dict):
                    return
                entry["resolve_status"] = resolve_status_value
                entry["resolve_method"] = resolve_method_value if resolve_status_value == "success" else ""
                entry["resolve_failed"] = "" if resolve_status_value == "success" else entry.get("resolve_failed") or ""
                updated_missing = True

            missing_entry = row_info.get("missing_entry")
            if isinstance(missing_entry, dict):
                _update_missing_entry(missing_entry)

            if not updated_missing:
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
                        _update_missing_entry(candidate)

                if not updated_missing:
                    for item in list(missing):
                        if _matches_entry(item):
                            _update_missing_entry(item)
                            break

                normalized_candidates = {
                    self._normalize_identifier(abs_path),
                    self._normalize_identifier(os.path.basename(abs_path)),
                    workflow_value_norm,
                    self._normalize_identifier(reference_name),
                }
                normalized_candidates = {value for value in normalized_candidates if value}

                if not updated_missing and normalized_candidates:
                    for entry in list(missing):
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
                            _update_missing_entry(entry)
                            break

                if updated_missing:
                    system_debug(
                        "[Validation] Updated missing entry resolve fields | "
                        f"row={row_index} remaining_missing={len(missing)}"
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
        issue = self._issue_lookup.get("custom_nodes") or {}
        issue_data = issue.get("data") or {}
        extra_packages = issue_data.get("node_packages") or {}
        for key, value in extra_packages.items():
            normalized = (key or "").strip().lower()
            if normalized and normalized not in mapping and value:
                mapping[normalized] = value
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
        url_button = dialog.addButton(
            "Install via URL...",
            QtWidgets.QMessageBox.ButtonRole.ActionRole,
        )
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
        if dialog.clickedButton() == url_button:
            if self._prompt_and_install_repo_url(package_display, row_info):
                return True

        self._append_issue_note(
            "custom_nodes",
            f"Manual install required for {package_display}. Install under custom_nodes and restart ComfyUI.",
        )
        return False

    def _prompt_and_install_repo_url(self, package_display: str, row_info: Dict[str, Any]) -> bool:
        """Ask user for a repo URL and attempt installation via Manager."""
        repo_url, ok = QtWidgets.QInputDialog.getText(
            self,
            "Install Custom Node",
            f"Enter the Git URL for {package_display}:",
            QtWidgets.QLineEdit.Normal,
            "",
        )
        if not ok or not repo_url.strip():
            return False

        from ..validation_resolver import install_custom_nodes_via_playwright

        install_result = install_custom_nodes_via_playwright(
            self._comfy_path,
            [repo_url.strip()],
        )
        resolved = bool(install_result.resolved)
        note = "; ".join(install_result.resolved or install_result.failed or install_result.notes or [])
        if note:
            self._append_issue_note("custom_nodes", note)
        if resolved:
            return True
        if install_result.failed:
            QtWidgets.QMessageBox.warning(
                self,
                "Install Failed",
                "\n".join(install_result.failed),
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
            self._refresh_models_issue_status()
        elif issue_key == "custom_nodes":
            dependencies = self._load_dependencies()
            result = resolve_missing_custom_nodes(data, self._comfy_path, dependencies)
            self._report_resolution(issue_key, result)
            self._refresh_custom_nodes_issue_status()
        self._update_overall_state()

    def _handle_model_auto_resolve(self, row: int) -> None:
        widget_info = self._issue_widgets.get("models")
        if not widget_info:
            return
        rows: Dict[int, Dict[str, Any]] = widget_info.get("rows") or {}
        row_info = rows.get(row)
        if not row_info or row_info.get("resolved"):
            return
        issue_row = row_info.get("issue_row")
        button: Optional[QtWidgets.QPushButton] = row_info.get("button")
        if isinstance(issue_row, IssueRow):
            issue_row.start_install_animation()
        if button and button is not getattr(issue_row, "btn_resolve", None):
            button.setEnabled(False)
        try:
            resolved = self._resolve_model_entry(row, row_info)
            if isinstance(issue_row, IssueRow):
                if resolved:
                    detail_text = row_info.get("resolve_method") or None
                    issue_row.mark_as_successful(
                        row_info.get("success_text"),
                        detail=detail_text,
                    )
                else:
                    issue_row.reset_to_idle()
            elif button and not resolved:
                button.setEnabled(True)
        except Exception as exc:  # pragma: no cover - defensive guard
            if isinstance(issue_row, IssueRow):
                issue_row.reset_to_idle()
            elif button:
                button.setEnabled(True)
            QtWidgets.QMessageBox.warning(self, "Auto Resolve Failed", str(exc))
        self._update_overall_state()

    def _handle_custom_node_auto_resolve(self, row: int) -> None:
        widget_info = self._issue_widgets.get("custom_nodes")
        if not widget_info:
            return
        rows: Dict[int, Dict[str, Any]] = widget_info.get("rows") or {}
        row_info = rows.get(row)
        if not row_info or row_info.get("resolved"):
            return
        issue_row = row_info.get("issue_row")
        button: Optional[QtWidgets.QPushButton] = row_info.get("button")
        if isinstance(issue_row, IssueRow):
            issue_row.start_install_animation()
        if button and button is not getattr(issue_row, "btn_resolve", None):
            button.setEnabled(False)
        try:
            if self._resolve_custom_node_entry(row, row_info):
                # Mark all rows from the same package as resolved to avoid duplicate installs.
                package_row = row
                row_info["resolved"] = True
                other_rows = row_info.get("package_rows") or []
                for r_idx in [package_row] + other_rows:
                    table = self._issue_widgets.get("custom_nodes", {}).get("table")
                    if not table:
                        continue
                    # Status column update
                    status_item = table.item(r_idx, 0)
                    if isinstance(status_item, QtWidgets.QTableWidgetItem):
                        resolved_label = "Resolved"
                        method_text = row_info.get("resolve_method") or ""
                        if method_text:
                            resolved_label = f"{resolved_label}\\n{method_text}"
                            status_item.setToolTip(method_text)
                        status_item.setText(resolved_label)
                        self._apply_status_style(status_item, "Resolved")
                    # Package column update (header row only)
                    if r_idx == package_row:
                        pkg_item = table.item(r_idx, 2)
                        if isinstance(pkg_item, QtWidgets.QTableWidgetItem):
                            pkg_item.setForeground(QtGui.QBrush(QtGui.QColor(SUCCESS_COLOR)))
                        # Disable any buttons (header row)
                        cell_button = table.cellWidget(r_idx, 3)
                        if isinstance(cell_button, QtWidgets.QPushButton):
                            cell_button.setText("Resolved")
                            cell_button.setEnabled(False)
                            cell_button.setStyleSheet(
                                "QPushButton {"
                                " background-color: #228B22;"
                                " color: white;"
                                " border-radius: 4px;"
                                " padding: 2px 8px;"
                                " }"
                            )
                if isinstance(issue_row, IssueRow):
                    issue_row.mark_as_successful(
                        row_info.get("success_text"),
                        detail=row_info.get("resolve_method") or None,
                    )
                self._refresh_custom_nodes_issue_status()
            elif button:
                button.setEnabled(True)
                if isinstance(issue_row, IssueRow):
                    issue_row.reset_to_idle()
        except Exception as exc:  # pragma: no cover - defensive guard
            if isinstance(issue_row, IssueRow):
                issue_row.reset_to_idle()
            elif button:
                button.setEnabled(True)
            QtWidgets.QMessageBox.warning(self, "Custom Node Resolve Failed", str(exc))
        self._update_overall_state()

    def _resolve_model_entry(self, row: int, row_info: Dict[str, Any]) -> bool:
        reference = row_info.get("reference") or {}
        original_name = str(reference.get("name") or "").strip()
        system_debug(
            "[Validation] Auto-resolve: begin | "
            f"row={row} name='{original_name}' category='{reference.get('category')}' "
            f"node_type='{reference.get('node_type')}' "
            f"attempted_dirs={reference.get('attempted_directories')} "
            f"attempted_cats={reference.get('attempted_categories')} "
            f"url='{reference.get('url') or ''}'"
        )
        system_debug(
            "[Validation] Attempting model auto-resolve | "
            f"row={row} name='{original_name}' models_root='{row_info.get('models_root')}'"
        )
        models_root = row_info.get("models_root") or ""
        comfy_dir = (self._comfy_info or {}).get("comfy_dir") or ""
        expected_path: Optional[str] = None
        notified_manual = False
        local_matches = find_local_model_matches(reference, models_root)
        system_debug(
            "[Validation] Auto-resolve: local scan complete | "
            f"row={row} matches={len(local_matches) if local_matches else 0}"
        )
        if local_matches:
            selected = self._select_candidate_path(
                local_matches,
                title="Select Model",
                prompt="Choose the model file to reference in this workflow.",
                models_root=models_root,
            )
            if selected:
                system_debug(
                    "[Validation] Auto-resolve: local selection made | "
                    f"row={row} selected='{selected}'"
                )
                workflow_value = self._compute_workflow_value(reference, selected, models_root, comfy_dir)
                display_text = self._format_model_display_path(selected, models_root)
                success, message = self._apply_model_override(original_name, workflow_value)
                if success:
                    note = f"Selected local model: {display_text}"
                    row_info["resolve_method"] = row_info.get("resolve_method") or note
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
                    self._refresh_models_issue_status()
                    return True
                if message:
                    QtWidgets.QMessageBox.warning(self, "Workflow Update Failed", message)
            else:
                system_debug("[Validation] Auto-resolve: local selection skipped/canceled")
        else:
            system_debug("[Validation] Auto-resolve: no local matches found")

        file_name = os.path.basename(original_name) or os.path.basename(str(reference.get("name") or ""))
        shared_matches = find_shared_model_matches(file_name)
        system_debug(
            "[Validation] Auto-resolve: shared repo lookup complete | "
            f"row={row} matches={len(shared_matches) if shared_matches else 0}"
        )
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
                system_debug(
                    "[Validation] Auto-resolve: shared repo selection made | "
                    f"row={row} selected='{selected}'"
                )
                expected_path = determine_expected_model_path(reference, models_root, comfy_dir)
                system_debug(
                    "[Validation] Auto-resolve: computed expected path from shared repo | "
                    f"row={row} expected='{expected_path}' models_root='{models_root}' comfy_dir='{comfy_dir}'"
                )
                if not expected_path:
                    if models_root:
                        expected_path = os.path.join(models_root, file_name)
                    else:
                        expected_path = os.path.join(os.path.dirname(selected), file_name)
                    system_debug(
                        "[Validation] Auto-resolve: fallback expected path | "
                        f"row={row} expected='{expected_path}'"
                    )
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
                        row_info["resolve_method"] = row_info.get("resolve_method") or note
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
                system_debug("[Validation] Auto-resolve: shared repo download canceled by user")
        else:
            system_debug("[Validation] Auto-resolve: no shared repo matches found")
        url_value = str(row_info.get("url") or reference.get("url") or "").strip()
        if url_value and not notified_manual and not local_matches and not shared_matches:
            expected_path = expected_path or determine_expected_model_path(reference, models_root, comfy_dir)
            if not expected_path:
                expected_path = os.path.join(models_root or "", file_name)
            if expected_path:
                system_debug(
                    "[Validation] Auto-resolve: attempting direct URL download | "
                    f"row={row} url='{url_value}' dest='{expected_path}'"
                )
                destination_display = self._format_model_display_path(expected_path, models_root)
                try:
                    os.makedirs(os.path.dirname(expected_path), exist_ok=True)
                    temp_path = f"{expected_path}.download"
                    urllib.request.urlretrieve(url_value, temp_path)
                    os.replace(temp_path, expected_path)
                    note = f"Downloaded {file_name} from URL to {destination_display}."
                    row_info["resolve_method"] = row_info.get("resolve_method") or note
                    workflow_value = self._compute_workflow_value(reference, expected_path, models_root, comfy_dir)
                    self._mark_model_resolved(
                        row,
                        "Resolved",
                        destination_display,
                        note,
                        workflow_value,
                        resolved_path=expected_path,
                    )
                    self._record_resolved_model(expected_path, "Resolved", row_info, workflow_value)
                    self._refresh_models_issue_status()
                    return True
                except Exception as exc:
                    system_debug(
                        "[Validation] Auto-resolve: URL download failed | "
                        f"row={row} url='{url_value}' error='{exc}'"
                    )
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Download Failed",
                        f"Could not download model from URL.\n\nURL: {url_value}\nError: {exc}",
                    )
        elif not url_value:
            system_debug("[Validation] Auto-resolve: no URL provided for missing model")
        if not notified_manual:
            if expected_path and os.path.exists(expected_path):
                system_debug(
                    "[Validation] Auto-resolve: found model already at expected path | "
                    f"row={row} path='{expected_path}'"
                )
                workflow_value = self._compute_workflow_value(reference, expected_path, models_root, comfy_dir)
                destination_display = self._format_model_display_path(expected_path, models_root)
                system_debug(
                    "[Validation] Detected model already present at expected path | "
                    f"path='{expected_path}'"
                )
                note = f"Found existing model at {destination_display}."
                row_info["resolve_method"] = row_info.get("resolve_method") or note
                self._mark_model_resolved(
                    row,
                    "Resolved",
                    destination_display,
                    note,
                    workflow_value,
                    resolved_path=expected_path,
                )
                self._record_resolved_model(expected_path, "Resolved", row_info, workflow_value)
                self._refresh_models_issue_status()
                return True
            system_debug("[Validation] Auto-resolve: no automated resolution found; notifying manual download")
            self._notify_manual_download(file_name, models_root, expected_path)
        return False


    def _resolve_custom_node_entry(self, row: int, row_info: Dict[str, Any]) -> bool:
        node_name = str(row_info.get("node_name") or "").strip()
        package_name = str(row_info.get("package_name") or "").strip()
        manager_repo = str(row_info.get("manager_repo") or "").strip()
        dependency = row_info.get("dependency")

        if manager_repo:
            return self._install_custom_node_via_playwright(row_info, manager_repo)

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

    def _install_custom_node_via_playwright(self, row_info: Dict[str, Any], repo_url: str) -> bool:
        if not self._comfy_path:
            QtWidgets.QMessageBox.warning(
                self,
                "Install Custom Node",
                "ComfyUI path is not configured. Open the Charon panel and set the launch path.",
            )
            return False

        display_name = (
            row_info.get("manager_repo_display")
            or row_info.get("package_name")
            or row_info.get("node_name")
            or repo_url
        )

        result = install_custom_nodes_via_playwright(self._comfy_path, [repo_url])
        if result.failed and not result.resolved and not result.skipped:
            QtWidgets.QMessageBox.warning(
                self,
                "Installation Failed",
                result.failed[0] if result.failed else "The running ComfyUI session could not install the custom node.",
            )
            return False

        if result.resolved:
            row_info["resolve_method"] = result.resolved[0]
        elif result.notes:
            row_info["resolve_method"] = result.notes[0]
        else:
            row_info["resolve_method"] = row_info.get("resolve_method") or "Installed via Playwright"
        self._mark_custom_node_resolved(row_info, None, prompt_restart=False)
        self._update_resolve_status_payload(
            "custom_nodes",
            result,
            target_repo=repo_url,
            target_pack=row_info.get("package_name"),
        )
        self._show_restart_cta(display_name)
        return True

    def _mark_custom_node_resolved(
        self,
        row_info: Dict[str, Any],
        note: Optional[str] = None,
        *,
        prompt_restart: bool = True,
    ) -> None:
        method_detail = row_info.get("resolve_method") or note or "Installed"
        row_info["resolve_method"] = method_detail
        status_item = row_info.get("status_item")
        if isinstance(status_item, QtWidgets.QTableWidgetItem):
            resolved_label = "Resolved"
            if method_detail:
                resolved_label = f"{resolved_label}\n{method_detail}"
                status_item.setToolTip(method_detail)
            self._apply_status_style(status_item, "Resolved")
            status_item.setText(resolved_label)

        package_item = row_info.get("package_item")
        package_name = row_info.get("package_name") or "Installed"
        if isinstance(package_item, QtWidgets.QTableWidgetItem):
            display_text = f"{package_name} (installed)"
            if method_detail:
                display_text = f"{display_text}\n{method_detail}"
                package_item.setToolTip(method_detail)
            package_item.setText(display_text)
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

        issue_row = row_info.get("issue_row")
        if isinstance(issue_row, IssueRow):
            issue_row.mark_as_successful(
                row_info.get("success_text") or "Installed",
                detail=row_info.get("resolve_method") or None,
            )
        row_info["resolved"] = True

        node_name = row_info.get("node_name")
        issue = self._issue_lookup.get("custom_nodes")
        if issue:
            data = issue.get("data") or {}
            missing = data.get("missing") or []
            normalized_missing = {
                self._normalize_identifier(entry): entry
                for entry in missing
                if isinstance(entry, str)
            }

            # Header rows bundle multiple nodes; clear all matched entries so the issue status updates.
            resolved_nodes: set[str] = set()
            for entry in row_info.get("missing_nodes") or []:
                normalized = self._normalize_identifier(entry)
                if normalized:
                    resolved_nodes.add(normalized)
            if not resolved_nodes:
                for part in str(node_name or "").split(","):
                    normalized = self._normalize_identifier(part)
                    if normalized:
                        resolved_nodes.add(normalized)
            if not resolved_nodes:
                normalized = self._normalize_identifier(node_name)
                if normalized:
                    resolved_nodes.add(normalized)

            for resolved_key in resolved_nodes:
                normalized_missing.pop(resolved_key, None)

            data["missing"] = list(normalized_missing.values())
            repo = row_info.get("manager_repo")
            if repo:
                repo_key = self._normalize_repo_identifier(repo)
                current_missing = data.get("missing_repos") or []
                data["missing_repos"] = [
                    entry for entry in current_missing if self._normalize_repo_identifier(entry) != repo_key
                ]
                current_disabled = data.get("disabled_repos") or []
                data["disabled_repos"] = [
                    entry for entry in current_disabled if self._normalize_repo_identifier(entry) != repo_key
                ]

        if note and "Restart ComfyUI" not in note:
            self._append_issue_note("custom_nodes", note)

        self._refresh_custom_nodes_issue_status()
        self._update_overall_state()
        if prompt_restart:
            display_name = row_info.get("package_name") or row_info.get("node_name") or "Custom node"
            self._show_restart_cta(display_name)
        return False

    def _show_restart_cta(self, package_display: str) -> None:
        self._restart_required = True
        self._restart_in_progress = False
        btn = getattr(self, "_restart_button", None)
        if btn is not None:
            btn.setText("Press to Restart ComfyUI to finish resolving")
            btn.setToolTip(f"Restart to load {package_display}")
            btn.show()
            btn.setEnabled(True)
        self._update_overall_state()

    def _on_restart_clicked(self) -> None:
        self._restart_in_progress = True
        btn = getattr(self, "_restart_button", None)
        if btn is not None:
            btn.setText("Restarting")
            btn.setEnabled(False)
        self._start_restart_animation()
        self.comfy_restart_requested.emit()
        self._update_overall_state()

    def attach_connection_widget(self, widget: QtWidgets.QWidget) -> None:
        self._connection_widget = widget
        if hasattr(widget, "connection_status_changed"):
            try:
                widget.connection_status_changed.connect(self._handle_connection_status_changed)  # type: ignore[attr-defined]
            except Exception:
                pass
        if hasattr(widget, "restart_state_changed"):
            try:
                widget.restart_state_changed.connect(self._handle_restart_state_changed)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _handle_connection_status_changed(self, connected: bool) -> None:
        self._connection_online = bool(connected)

    def _handle_restart_state_changed(self, restarting: bool) -> None:
        if restarting:
            self._restart_required = True
            self._restart_in_progress = True
            btn = getattr(self, "_restart_button", None)
            if btn is not None:
                btn.show()
                btn.setEnabled(False)
                btn.setText("Restarting")
            self._start_restart_animation()
        else:
            was_restarting = self._restart_in_progress
            self._restart_in_progress = False
            if was_restarting:
                self._on_restart_completed()
            elif self._restart_required:
                self._stop_restart_animation()
                btn = getattr(self, "_restart_button", None)
                if btn is not None:
                    btn.show()
                    btn.setEnabled(True)
                    btn.setText("Press to Restart ComfyUI to finish resolving")
            else:
                self._on_restart_completed()
        self._update_overall_state()

    def _on_restart_completed(self) -> None:
        self._restart_required = False
        self._restart_in_progress = False
        self._stop_restart_animation()
        btn = getattr(self, "_restart_button", None)
        if btn is not None:
            btn.hide()
            btn.setEnabled(True)
            btn.setText("Press to Restart ComfyUI to finish resolving")
        self._update_overall_state()

    def _start_restart_animation(self) -> None:
        self._restart_anim_state = 0
        if not self._restart_anim_timer.isActive():
            self._restart_anim_timer.start()

    def _stop_restart_animation(self) -> None:
        self._restart_anim_timer.stop()
        self._restart_anim_state = 0
        btn = getattr(self, "_restart_button", None)
        if btn is not None:
            btn.setText("Press to Restart ComfyUI to finish resolving")

    def _tick_restart_animation(self) -> None:
        btn = getattr(self, "_restart_button", None)
        if btn is None:
            return
        self._restart_anim_state = (self._restart_anim_state + 1) % 4
        dots = "." * self._restart_anim_state
        btn.setText(f"Restarting{dots}")

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
            self._update_resolve_status_payload(issue_key, result)

    # ---------------------------------------------------------------- Helpers
    def _update_resolve_status_payload(
        self,
        issue_key: str,
        result: ResolutionResult,
        *,
        target_repo: Optional[str] = None,
        target_pack: Optional[str] = None,
    ) -> None:
        issues = self._payload.get("issues") if isinstance(self._payload, dict) else None
        if not isinstance(issues, list):
            return
        status = ""
        if result.failed:
            status = "failed"
        elif result.resolved:
            status = "success"
        method_text = "\n".join(result.resolved) if status == "success" else ""
        failed_text = "\n".join(result.failed) if status == "failed" else ""

        update_snapshot: Dict[str, Any] = {}

        for issue in issues:
            if not isinstance(issue, dict) or issue.get("key") != issue_key:
                continue
            data = issue.get("data") or {}
            if not isinstance(data, dict):
                continue
            if issue_key == "models":
                for entry in data.get("missing") or []:
                    if not isinstance(entry, dict):
                        continue
                    if status:
                        entry["resolve_status"] = status
                        entry["resolve_method"] = method_text if status == "success" else ""
                        entry["resolve_failed"] = failed_text if status == "failed" else ""
                        update_snapshot = {
                            "resolve_status": entry.get("resolve_status"),
                            "resolve_method": entry.get("resolve_method"),
                            "resolve_failed": entry.get("resolve_failed"),
                        }
            elif issue_key == "custom_nodes":
                packs = data.get("missing_packs") or []
                for pack in packs:
                    if not isinstance(pack, dict):
                        continue
                    repo_val = str(pack.get("repo") or "").strip().lower()
                    pack_name = str(pack.get("pack") or pack.get("pack_name") or "").strip().lower()
                    if target_repo or target_pack:
                        match_repo = target_repo and repo_val and repo_val == target_repo.strip().lower()
                        match_pack = target_pack and pack_name and pack_name == target_pack.strip().lower()
                        if not (match_repo or match_pack):
                            continue
                    if status:
                        pack["resolve_status"] = status
                        pack["resolve_method"] = method_text if status == "success" else ""
                        pack["resolve_failed"] = failed_text if status == "failed" else ""
                        update_snapshot = {
                            "resolve_status": pack.get("resolve_status"),
                            "resolve_method": pack.get("resolve_method"),
                            "resolve_failed": pack.get("resolve_failed"),
                            "repo": pack.get("repo"),
                            "pack": pack.get("pack"),
                        }
                    sanitized_nodes = []
                    for node in pack.get("nodes") or []:
                        if not isinstance(node, dict):
                            continue
                        node_copy = dict(node)
                        node_copy.pop("resolve_status", None)
                        node_copy.pop("resolve_method", None)
                        node_copy.pop("resolve_failed", None)
                        sanitized_nodes.append(node_copy)
                    pack["nodes"] = sanitized_nodes
        if self._workflow_folder:
            try:
                write_validation_resolve_status(self._workflow_folder, self._payload, overwrite=True)
                if update_snapshot:
                    system_debug(
                        f"[Validation] Installation completed for '{issue_key}'. "
                        f"validation_resolve_status update: {update_snapshot}"
                    )
            except Exception as exc:
                system_warning(
                    f"Failed to persist validation resolve status after auto-resolve: {exc}"
                )
        else:
            system_debug("[Validation] Skipped resolve status persist; workflow folder unavailable")

    def _append_issue_note(self, issue_key: str, message: str) -> None:
        widget_info = self._issue_widgets.get(issue_key)
        if not widget_info:
            return
        label = QtWidgets.QLabel(message)
        label.setWordWrap(True)
        frame = widget_info.get("frame")
        if isinstance(frame, QtWidgets.QFrame) and frame.layout():
            frame.layout().addWidget(label)
            return
        if self._issues_layout:
            self._issues_layout.addWidget(label)

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

        note = None
        if result.resolved:
            note = result.resolved[0]
            row_info["resolve_method"] = note
        elif result.skipped:
            note = result.skipped[0]
            row_info["resolve_method"] = note or row_info.get("resolve_method") or "Installed"
        else:
            row_info["resolve_method"] = row_info.get("resolve_method") or "Installed"

        self._mark_custom_node_resolved(row_info, note, prompt_restart=False)
        self._update_resolve_status_payload(
            "custom_nodes",
            result,
            target_repo=normalized.get("repo"),
            target_pack=normalized.get("name"),
        )
        row_info["dependency"] = normalized
        self._show_restart_cta(dep_display)
        return True

    def _prompt_restart_after_install(self, package_display: str) -> None:
        # Deprecated modal prompt; use inline restart button instead.
        self._show_restart_cta(package_display)
