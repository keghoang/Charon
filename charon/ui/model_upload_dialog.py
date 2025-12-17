from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

from ..qt_compat import QtCore, QtGui, QtWidgets
from ..charon_logger import system_debug, system_warning, system_error
from ..model_transfer_manager import TransferState, manager as transfer_manager
from ..config import WORKFLOW_REPOSITORY_ROOT

# Reuse styling from validation dialog for consistency
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
    QFrame#Card {{
        background-color: {COLORS['bg_card']};
        border: 1px solid {COLORS['border']};
        border-radius: 8px;
    }}
    QPushButton#ActionBtn {{
        background-color: {COLORS['btn_bg']};
        border: 1px solid {COLORS['border']};
        border-radius: 6px;
        padding: 6px 12px;
        font-size: 13px;
        color: {COLORS['text_main']};
    }}
    QPushButton#ActionBtn:hover {{
        background-color: {COLORS['bg_hover']};
    }}
    QPushButton#ActionBtn:disabled {{
        color: {COLORS['text_sub']};
        border-color: {COLORS['bg_hover']};
    }}
    QPushButton#PrimaryBtn {{
        background-color: {COLORS['success']};
        border: 1px solid {COLORS['success']};
        border-radius: 6px;
        padding: 8px 16px;
        font-size: 14px;
        font-weight: 600;
        color: #ffffff;
    }}
    QPushButton#PrimaryBtn:hover {{
        background-color: #16a34a;
        border-color: #16a34a;
    }}
    QPushButton#PrimaryBtn:disabled {{
        background-color: {COLORS['bg_hover']};
        border-color: {COLORS['bg_hover']};
        color: {COLORS['text_sub']};
    }}
"""

def _build_icon(name: str) -> QtGui.QIcon:
    size = 32
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

    if name == "upload":
        # Simple upload arrow icon
        pen = QtGui.QPen(QtGui.QColor(COLORS["text_main"]), 2)
        painter.setPen(pen)
        path = QtGui.QPainterPath()
        path.moveTo(16, 22)
        path.lineTo(16, 6)
        path.lineTo(10, 12)
        path.moveTo(16, 6)
        path.lineTo(22, 12)
        painter.drawPath(path)
        painter.drawLine(8, 26, 24, 26)

    elif name == "check":
        pen = QtGui.QPen(QtGui.QColor(COLORS["success"]), 2.5)
        painter.setPen(pen)
        path = QtGui.QPainterPath()
        path.moveTo(6, 16)
        path.lineTo(13, 23)
        path.lineTo(26, 9)
        painter.drawPath(path)

    elif name == "exists":
        # Info icon for existing files
        pen = QtGui.QPen(QtGui.QColor(COLORS["text_sub"]), 2)
        painter.setPen(pen)
        painter.drawEllipse(4, 4, 24, 24)
        painter.drawLine(16, 10, 16, 22)
        painter.drawPoint(16, 8)

    painter.end()
    return QtGui.QIcon(pixmap)


class ModelRow(QtWidgets.QWidget):
    def __init__(
        self,
        source_path: str,
        dest_path: str,
        exists: bool,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.source_path = source_path
        self.dest_path = dest_path
        self.exists = exists
        self.transfer_state: Optional[TransferState] = None

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(15, 12, 15, 12)
        layout.setSpacing(12)

        self.icon_lbl = QtWidgets.QLabel()
        icon_name = "exists" if exists else "upload"
        self.icon_lbl.setPixmap(_build_icon(icon_name).pixmap(24, 24))
        self.icon_lbl.setFixedSize(24, 24)

        text_widget = QtWidgets.QWidget()
        text_v = QtWidgets.QVBoxLayout(text_widget)
        text_v.setContentsMargins(0, 0, 0, 0)
        text_v.setSpacing(2)

        file_name = os.path.basename(source_path)
        self.lbl_title = QtWidgets.QLabel(file_name)
        self.lbl_title.setStyleSheet(f"font-size: 14px; color: {COLORS['text_main']};")

        status_text = "Already exists in Global Repo" if exists else "Ready to upload"
        self.lbl_sub = QtWidgets.QLabel(status_text)
        self.lbl_sub.setStyleSheet(f"font-size: 12px; color: {COLORS['text_sub']};")
        self.lbl_sub.setWordWrap(True)

        text_v.addWidget(self.lbl_title)
        text_v.addWidget(self.lbl_sub)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(4)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                background-color: {COLORS['bg_hover']};
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background-color: {COLORS['success']};
                border-radius: 2px;
            }}
        """)
        text_v.addWidget(self.progress_bar)

        layout.addWidget(self.icon_lbl)
        layout.addWidget(text_widget, 1)

    def update_progress(self, state: TransferState) -> None:
        self.transfer_state = state
        self.progress_bar.show()
        
        if state.in_progress:
            self.progress_bar.setValue(state.percent)
            self.lbl_sub.setText(f"Uploading... {state.percent}%")
        elif state.error:
            self.lbl_sub.setStyleSheet(f"color: {COLORS['danger']};")
            self.lbl_sub.setText(f"Error: {state.error}")
            self.progress_bar.hide()
        else:
            self.progress_bar.setValue(100)
            self.lbl_sub.setStyleSheet(f"color: {COLORS['success']};")
            self.lbl_sub.setText("Upload Complete")
            self.icon_lbl.setPixmap(_build_icon("check").pixmap(24, 24))


class ModelUploadDialog(QtWidgets.QDialog):
    transfer_update = QtCore.Signal(object, object)

    def __init__(
        self,
        models: List[Tuple[str, str]],  # List of (source_path, category)
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Upload Models to Global Repo")
        self.setStyleSheet(STYLESHEET)
        self.resize(500, 600)

        # Determine Global Repo Models Path
        # Assuming models/ sibling to workflows/
        repo_root = Path(WORKFLOW_REPOSITORY_ROOT)
        if repo_root.name.lower() == "workflows":
            self.global_models_root = repo_root.parent / "shared_models"
        else:
            self.global_models_root = repo_root / "shared_models"

        self.models_to_upload: List[ModelRow] = []
        self._setup_ui()
        self._populate_models(models)
        
        self.transfer_update.connect(self._handle_transfer_update)

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header
        header = QtWidgets.QLabel("Upload Models")
        header.setObjectName("Heading")
        layout.addWidget(header)

        sub = QtWidgets.QLabel(f"Target: {self.global_models_root}")
        sub.setObjectName("SubHeading")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        # List
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        
        self.list_container = QtWidgets.QWidget()
        self.list_layout = QtWidgets.QVBoxLayout(self.list_container)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch()
        
        scroll.setWidget(self.list_container)
        
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        card_layout = QtWidgets.QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.addWidget(scroll)
        
        layout.addWidget(card, 1)

        # Footer
        footer = QtWidgets.QHBoxLayout()
        footer.addStretch()
        
        self.btn_cancel = QtWidgets.QPushButton("Close")
        self.btn_cancel.setObjectName("ActionBtn")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_upload = QtWidgets.QPushButton("Start Upload")
        self.btn_upload.setObjectName("PrimaryBtn")
        self.btn_upload.clicked.connect(self._start_upload)
        
        footer.addWidget(self.btn_cancel)
        footer.addWidget(self.btn_upload)
        layout.addLayout(footer)

    def _populate_models(self, models: List[Tuple[str, str]]) -> None:
        # Clear existing
        while self.list_layout.count() > 1:
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        count_uploadable = 0
        
        for source, category in models:
            if not os.path.exists(source):
                continue
                
            file_name = os.path.basename(source)
            # Construct dest path: GlobalRepo/models/category/filename
            if category:
                dest = self.global_models_root / category / file_name
            else:
                dest = self.global_models_root / file_name
                
            exists = dest.exists()
            if not exists:
                count_uploadable += 1
                
            row = ModelRow(str(source), str(dest), exists)
            self.models_to_upload.append(row)
            self.list_layout.insertWidget(self.list_layout.count() - 1, row)

        if count_uploadable == 0:
            self.btn_upload.setText("Nothing to Upload")
            self.btn_upload.setEnabled(False)
        else:
            self.btn_upload.setText(f"Upload {count_uploadable} Files")

    def _start_upload(self) -> None:
        self.btn_upload.setEnabled(False)
        self.btn_cancel.setEnabled(False) # Prevent closing during upload init
        
        for row in self.models_to_upload:
            if row.exists:
                continue
                
            # Subscribe to transfer manager
            listener_id = id(row)
            
            # Start Copy
            transfer_manager.start_copy(
                source=row.source_path,
                destination=row.dest_path,
            )
            
            # Subscribe for updates
            transfer_manager.subscribe(row.dest_path, listener_id, 
                lambda state, r=row: self.transfer_update.emit(r, state))

        self.btn_cancel.setEnabled(True)
        self.btn_upload.setText("Uploading...")

    def _handle_transfer_update(self, row: ModelRow, state: TransferState) -> None:
        row.update_progress(state)
        
        # Check if all done
        all_done = True
        for r in self.models_to_upload:
            if not r.exists and (not r.transfer_state or r.transfer_state.in_progress):
                all_done = False
                break
        
        if all_done:
            self.btn_upload.setText("Upload Complete")
            self.btn_cancel.setText("Close")

    def closeEvent(self, event) -> None:
        # Cancel all active transfers
        transfer_manager.cancel_all()
        
        # Unsubscribe from everything
        for row in self.models_to_upload:
            if row.dest_path:
                try:
                    transfer_manager.unsubscribe(row.dest_path, id(row))
                except:
                    pass
        super().closeEvent(event)
