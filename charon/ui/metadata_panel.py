from ..qt_compat import QtWidgets, QtCore, exec_dialog
import os
from pathlib import Path
from urllib.parse import urlparse
from .. import config
from ..metadata_manager import (
    get_charon_config,
    update_charon_config,
    get_metadata_path,
    invalidate_metadata_path,
)
from ..charon_metadata import write_charon_metadata
from ..charon_logger import system_debug
from .dialogs import CharonMetadataDialog
from .custom_widgets import create_tag_badge
from datetime import datetime, timezone, timedelta
from ..workflow_local_store import get_validated_workflow_path, load_workflow_state

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
except Exception:  # pragma: no cover - Python < 3.9 fallback
    ZoneInfo = None
    ZoneInfoNotFoundError = Exception  # type: ignore

if ZoneInfo:
    try:
        EASTERN_TIMEZONE = ZoneInfo("America/New_York")
    except ZoneInfoNotFoundError:
        EASTERN_TIMEZONE = timezone(timedelta(hours=-5))
else:  # pragma: no cover - fallback for environments without zoneinfo
    EASTERN_TIMEZONE = timezone(timedelta(hours=-5))


def _extract_repo_name(repo_url: str) -> str:
    """Return a human-friendly repository name derived from the URL."""
    if not repo_url:
        return "Dependency"

    parsed = urlparse(repo_url)
    path = (parsed.path or "").rstrip("/")
    if not path:
        return repo_url

    name = path.split("/")[-1] or repo_url
    if name.endswith(".git"):
        name = name[:-4]
    return name or "Dependency"


def _normalize_dependency_for_display(dep) -> tuple[str, str, str]:
    """Return (name, repo_url, ref) tuple ready for UI consumption."""
    repo_url = ""
    name = ""
    ref = ""

    if isinstance(dep, str):
        repo_url = dep.strip()
    elif isinstance(dep, dict):
        repo_url = (dep.get("repo") or dep.get("url") or "").strip()
        name = (dep.get("name") or "").strip()
        ref = (dep.get("ref") or "").strip()

    if not name:
        name = _extract_repo_name(repo_url)
    if not repo_url and not name:
        name = "Dependency"
    return name, repo_url, ref


def _format_last_changed(value: str) -> str:
    """Format ISO timestamp into EST without displaying the timezone label."""
    if not value:
        return "-"

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    localized = parsed.astimezone(EASTERN_TIMEZONE)
    return localized.strftime("%Y-%m-%d %H:%M:%S")


class HorizontalScrollArea(QtWidgets.QScrollArea):
    """Custom scroll area that scrolls horizontally with mouse wheel."""
    
    def wheelEvent(self, event):
        """Override wheel event to scroll horizontally."""
        # Get the horizontal scrollbar
        h_bar = self.horizontalScrollBar()
        if h_bar.isVisible() or h_bar.maximum() > 0:
            # Scroll horizontally
            delta = -event.angleDelta().y() / 4  # Adjust scroll speed
            h_bar.setValue(int(h_bar.value() + delta))
            event.accept()
        else:
            # Let parent handle if no horizontal scrolling needed
            super().wheelEvent(event)


class MetadataPanel(QtWidgets.QWidget):
    metadata_changed = QtCore.Signal()  # Keep for backward compatibility
    script_created = QtCore.Signal(str)  # Emits script path when new script is created
    
    # Granular signals for specific changes
    entry_changed = QtCore.Signal(str, str)  # script_path, new_entry
    tags_updated = QtCore.Signal(str, list, list)  # script_path, added_tags, removed_tags

    def __init__(self, host="None", parent=None):
        super(MetadataPanel, self).__init__(parent)
        self.host = host  # Store the host parameter
        self.script_folder = None
        self.parent_folder = None
        
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)
        
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        
        # --- Metadata Controls (initially hidden) ---
        self.metadata_controls_widget = QtWidgets.QWidget()
        metadata_layout = QtWidgets.QHBoxLayout(self.metadata_controls_widget)
        metadata_layout.setContentsMargins(0, 0, 0, 0)

        # Tags scroll area (clips tags and allows horizontal scrolling)
        self.tags_scroll = HorizontalScrollArea()
        self.tags_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tags_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tags_scroll.setWidgetResizable(True)
        self.tags_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.tags_scroll.setMaximumWidth(200)  # Limit width to prevent expanding
        self.tags_scroll.setFixedHeight(30)  # Match the height of other controls
        
        # Tags container (flow layout for tag badges)
        self.tags_container = QtWidgets.QWidget()
        self.tags_layout = QtWidgets.QHBoxLayout(self.tags_container)
        self.tags_layout.setContentsMargins(0, 0, 10, 0)  # Add right margin
        self.tags_layout.setSpacing(5)
        
        self.tags_scroll.setWidget(self.tags_container)
        
        self.entry_label = QtWidgets.QLabel("Entry File:")
        self.entry_dropdown = QtWidgets.QComboBox()
        
        self.entry_dropdown.currentTextChanged.connect(self.on_metadata_updated)

        metadata_layout.addWidget(self.tags_scroll)
        metadata_layout.addWidget(self.entry_label)
        metadata_layout.addWidget(self.entry_dropdown)
        
        main_layout.addWidget(self.metadata_controls_widget)
        self.metadata_controls_widget.setVisible(False)

        # --- Charon metadata viewer ---
        self.charon_widget = QtWidgets.QWidget()
        charon_layout = QtWidgets.QVBoxLayout(self.charon_widget)
        charon_layout.setContentsMargins(0, 0, 0, 0)
        charon_layout.setSpacing(6)

        self.charon_title = QtWidgets.QLabel()
        title_font = self.charon_title.font()
        title_font.setPointSize(title_font.pointSize() + 2)
        title_font.setBold(True)
        self.charon_title.setFont(title_font)

        self.charon_description = QtWidgets.QLabel()
        self.charon_description.setWordWrap(True)
        self.charon_description.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)

        self.charon_info_form = QtWidgets.QFormLayout()
        self.charon_info_form.setContentsMargins(0, 0, 0, 0)
        self.charon_info_form.setSpacing(4)

        self.charon_workflow_value = QtWidgets.QLabel()
        self.charon_workflow_value.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.charon_last_changed_value = QtWidgets.QLabel()
        self.charon_last_changed_value.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)

        self.charon_info_form.addRow("Last Updated:", self.charon_last_changed_value)

        self.charon_dependencies_label = QtWidgets.QLabel("Dependencies:")
        self.charon_dependencies_list_container = QtWidgets.QWidget()
        self.charon_dependencies_layout = QtWidgets.QVBoxLayout(self.charon_dependencies_list_container)
        self.charon_dependencies_layout.setContentsMargins(0, 0, 0, 0)
        self.charon_dependencies_layout.setSpacing(2)

        self.charon_tags_label = QtWidgets.QLabel("Tags:")
        self.charon_tags_container = QtWidgets.QWidget()
        self.charon_tags_layout = QtWidgets.QHBoxLayout(self.charon_tags_container)
        self.charon_tags_layout.setContentsMargins(0, 0, 0, 0)
        self.charon_tags_layout.setSpacing(6)

        charon_layout.addWidget(self.charon_title)
        charon_layout.addWidget(self.charon_description)
        charon_layout.addLayout(self.charon_info_form)
        charon_layout.addWidget(self.charon_dependencies_label)
        charon_layout.addWidget(self.charon_dependencies_list_container)
        charon_layout.addWidget(self.charon_tags_label)
        charon_layout.addWidget(self.charon_tags_container)
        charon_layout.addStretch()

        main_layout.addWidget(self.charon_widget)
        self.charon_widget.setVisible(False)
        
        self.show_default_message()

    def _update_ui(self, state, script_folder=None, parent_folder=None):
        """Update the UI based on the current context."""
        self.script_folder = script_folder
        self.parent_folder = parent_folder

        # Show metadata controls only when editing metadata
        self.metadata_controls_widget.setVisible(state == "edit_metadata")
        self.charon_widget.setVisible(state == "charon_view")

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def show_default_message(self, parent_folder=None):
        self.parent_folder = parent_folder
        self._update_ui(state="create_script", parent_folder=self.parent_folder)

    def update_metadata(self, script_folder):
        self.script_folder = script_folder
        
        if not script_folder:
            return
            
        meta_path = get_metadata_path(script_folder)
        if not os.path.exists(meta_path):
            self._update_ui(state="create_script", script_folder=script_folder)
            return
            
        conf = get_charon_config(script_folder)
        if conf is None:
            self._update_ui(state="create_script", script_folder=script_folder)
            return

        if conf.get("charon_meta"):
            self._show_charon_metadata(conf, script_folder)
            return
            
        # If we have metadata, show the metadata view and populate it
        # Calculate parent folder for the script
        parent_folder = os.path.dirname(script_folder)
        self._update_ui(state="edit_metadata", script_folder=script_folder, parent_folder=parent_folder)
        self._populate_metadata_controls(conf, script_folder)

    def _populate_metadata_controls(self, conf, script_folder):
        """Populate the controls with data from the config."""
        # Block signals to prevent on_metadata_updated from firing prematurely
        self.entry_dropdown.blockSignals(True)

        # --- Setup entry dropdown ---
        self.entry_dropdown.clear()
        entries = self.get_entry_files(script_folder)
        self.entry_dropdown.addItems(entries)
        current_entry = conf.get("entry", "main.py")
        index = self.entry_dropdown.findText(current_entry)
        if index >= 0:
            self.entry_dropdown.setCurrentIndex(index)
        else:
            self.entry_dropdown.setCurrentIndex(-1)

        # --- Setup tags display ---
        # Clear existing tag badges
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        # Add tag badges
        tags = conf.get("tags", [])
        if tags:
            for tag in sorted(tags):
                tag_label = create_tag_badge(tag)
                self.tags_layout.addWidget(tag_label)
        
        # Add stretch to push tags to the left
        self.tags_layout.addStretch()

        # Unblock signals now that setup is complete
        self.entry_dropdown.blockSignals(False)
        
    def get_entry_files(self, script_folder):
        """Get all supported script files in the folder"""
        # Collect all supported file extensions
        extensions = []
        for ext_list in config.SCRIPT_TYPES.values():
            extensions.extend(ext_list)
        
        # Get files with matching extensions
        entry_files = []
        for f in os.listdir(script_folder):
            for ext in extensions:
                if f.endswith(ext):
                    entry_files.append(f)
                    break
        
        return entry_files

    def on_metadata_updated(self):
        if not self.script_folder:
            return
        
        # Get the existing metadata to preserve all software
        existing_conf = get_charon_config(self.script_folder)
        if not existing_conf or existing_conf.get("charon_meta"):
            return

        old_entry = existing_conf.get("entry", "")
        new_entry = self.entry_dropdown.currentText() if self.entry_dropdown.currentIndex() >= 0 else ""
        entry_changed = old_entry != new_entry
        
        new_config = existing_conf.copy()
        
        new_config["entry"] = new_entry
        
        # Update the metadata file
        if update_charon_config(self.script_folder, new_config):
            # Emit granular signal if entry changed
            if entry_changed:
                self.entry_changed.emit(self.script_folder, new_entry)

    def edit_metadata(self):
        """Open the metadata editor for the current workflow."""
        if not self.script_folder:
            return

        conf = get_charon_config(self.script_folder)
        if not conf:
            return

        if conf.get("charon_meta"):
            self._edit_charon_metadata(conf)
            return

        # Legacy `.charon.json` metadata is ignored; no editing support.

    def create_metadata(self):
        """Create Charon metadata for the current workflow."""
        if not self.script_folder:
            return

        initial_meta = {
            "workflow_file": self._guess_workflow_file(self.script_folder),
            "description": "",
            "dependencies": [],
            "tags": [],
            "parameters": [],
        }
        dest_json = os.path.join(self.script_folder, initial_meta["workflow_file"])
        dialog = CharonMetadataDialog(initial_meta, workflow_path=dest_json, parent=self)
        if exec_dialog(dialog) != QtWidgets.QDialog.Accepted:
            return

        updates = initial_meta.copy()
        updates.update(dialog.get_metadata() or {})
        if not updates.get("workflow_file"):
            updates["workflow_file"] = initial_meta["workflow_file"]
        system_debug(f"Creating metadata with parameters: {updates.get('parameters')}")

        if write_charon_metadata(self.script_folder, updates) is None:
            QtWidgets.QMessageBox.warning(self, "Create Failed", "Could not write workflow metadata.")
            return

        invalidate_metadata_path(self.script_folder)
        self.update_metadata(self.script_folder)
        self.metadata_changed.emit()


    def _guess_workflow_file(self, script_folder: str) -> str:
        """Return a likely workflow JSON filename for a folder."""
        preferred = ("workflow.json", "workflow.charon.json")
        for candidate in preferred:
            if os.path.exists(os.path.join(script_folder, candidate)):
                return candidate

        for entry in os.listdir(script_folder):
            if entry.lower().endswith(".json"):
                return entry

        return "workflow.json"

    def _show_charon_metadata(self, conf, script_folder):
        charon = conf.get("charon_meta", {})
        self._update_ui(state="charon_view", script_folder=script_folder, parent_folder=os.path.dirname(script_folder))

        display_name = Path(script_folder).name
        self.charon_title.setText(display_name)
        self.charon_title.setToolTip("")

        description = charon.get("description") or "No description provided."
        self.charon_description.setText(description)

        workflow_file = charon.get("workflow_file") or "workflow.json"
        workflow_path = os.path.join(script_folder, workflow_file)
        workflow_exists = os.path.exists(workflow_path)
        workflow_text = workflow_file
        if workflow_exists:
            workflow_text = f"{workflow_file}"
        else:
            workflow_text = f"{workflow_file} (missing)"
        self.charon_workflow_value.setText(workflow_text)
        self.charon_workflow_value.setToolTip(workflow_path if workflow_exists else "")

        display_last_changed = _format_last_changed(charon.get("last_changed"))
        self.charon_last_changed_value.setText(display_last_changed)

        dependencies = conf.get("dependencies") or []
        self._clear_layout(self.charon_dependencies_layout)
        if dependencies:
            for dep in dependencies:
                name, repo_url, ref = _normalize_dependency_for_display(dep)
                label = QtWidgets.QLabel()
                label.setTextFormat(QtCore.Qt.TextFormat.RichText)
                if repo_url:
                    link = f'<a href="{repo_url}" style="color: white;">{name}</a>'
                else:
                    link = f"<span style='color: white;'>{name}</span>"
                suffix = f" <span style='color: palette(mid);'>({ref})</span>" if ref else ""
                label.setText(f"{link}{suffix}")
                label.setOpenExternalLinks(True)
                label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextBrowserInteraction)
                label.setStyleSheet("color: white;")
                self.charon_dependencies_layout.addWidget(label)
            self.charon_dependencies_label.setVisible(True)
            self.charon_dependencies_list_container.setVisible(True)
        else:
            self.charon_dependencies_label.setVisible(False)
            self.charon_dependencies_list_container.setVisible(False)

        tags = conf.get("tags", [])
        self._clear_layout(self.charon_tags_layout)
        if tags:
            for tag in tags:
                badge = create_tag_badge(tag)
                self.charon_tags_layout.addWidget(badge)
            spacer = QtWidgets.QSpacerItem(1, 1, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
            self.charon_tags_layout.addItem(spacer)
            self.charon_tags_label.setVisible(True)
            self.charon_tags_container.setVisible(True)
        else:
            self.charon_tags_label.setVisible(False)
            self.charon_tags_container.setVisible(False)

    def _edit_charon_metadata(self, conf):
        charon_meta = conf.get("charon_meta", {}).copy()
        charon_meta.setdefault("workflow_file", conf.get("workflow_file") or "workflow.json")
        charon_meta.setdefault("parameters", conf.get("parameters") or [])
        workflow_file = charon_meta.get("workflow_file") or conf.get("workflow_file") or "workflow.json"
        state = load_workflow_state(self.script_folder)
        use_local_override = bool(state.get("validated"))
        local_override_path = get_validated_workflow_path(self.script_folder, ensure_dir=True)
        if use_local_override and os.path.exists(local_override_path):
            workflow_path = local_override_path
        else:
            workflow_path = os.path.join(self.script_folder, workflow_file)
        dialog = CharonMetadataDialog(charon_meta, workflow_path=workflow_path, parent=self)
        if exec_dialog(dialog) != QtWidgets.QDialog.Accepted:
            return

        updates = dialog.get_metadata()
        updated_meta = charon_meta.copy()
        updated_meta.update(updates)
        if not updated_meta.get("workflow_file"):
            updated_meta["workflow_file"] = charon_meta.get("workflow_file") or "workflow.json"
        updated_meta["last_changed"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        system_debug(f"Updating metadata parameters: {updated_meta.get('parameters')}")

        old_tags = conf.get("tags", [])
        new_tags = updated_meta.get("tags", [])

        if write_charon_metadata(self.script_folder, updated_meta) is None:
            QtWidgets.QMessageBox.warning(self, "Update Failed", "Could not write workflow metadata.")
            return
        invalidate_metadata_path(self.script_folder)

        added = [tag for tag in new_tags if tag not in old_tags]
        removed = [tag for tag in old_tags if tag not in new_tags]

        self.update_metadata(self.script_folder)
        if added or removed:
            self.tags_updated.emit(self.script_folder, added, removed)
        self.metadata_changed.emit()



