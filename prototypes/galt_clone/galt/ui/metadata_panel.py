from ..qt_compat import QtWidgets, QtCore, QtGui, exec_dialog
import os
import json
from pathlib import Path
from .. import config
from ..metadata_manager import (
    get_galt_config,
    create_default_galt_file,
    update_galt_config,
    get_software_for_host,
    get_metadata_path,
)
from ..charon_metadata import write_charon_metadata
from .dialogs import MetadataDialog, CharonMetadataDialog
from ..settings import user_settings_db
from .custom_widgets import create_tag_badge
from datetime import datetime


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
    software_changed = QtCore.Signal(str, list)  # script_path, new_software_list
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
        self.charon_node_count_value = QtWidgets.QLabel()
        self.charon_node_count_value.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)

        self.charon_info_form.addRow("Workflow JSON:", self.charon_workflow_value)
        self.charon_info_form.addRow("Last Updated:", self.charon_last_changed_value)
        self.charon_info_form.addRow("Node Count:", self.charon_node_count_value)

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
            
        conf = get_galt_config(script_folder)
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
        existing_conf = get_galt_config(self.script_folder)
        if existing_conf and existing_conf.get("charon_meta"):
            return
        if existing_conf:
            # Keep all existing software, but ensure the current host is included
            all_software = existing_conf.get("software", [self.host])
            if self.host not in all_software:
                all_software.append(self.host)
        else:
            all_software = [self.host]
        
        # Track what changed for granular signals
        old_entry = existing_conf.get("entry", "") if existing_conf else ""
        new_entry = self.entry_dropdown.currentText() if self.entry_dropdown.currentIndex() >= 0 else ""
        entry_changed = old_entry != new_entry
        
        # Start with existing config to preserve all fields (like tags)
        new_config = existing_conf.copy() if existing_conf else {}
        
        # Update only the fields this method should touch
        new_config["software"] = all_software
        new_config["entry"] = new_entry
        
        # Update the metadata file
        if update_galt_config(self.script_folder, new_config):
            # Emit granular signal if entry changed
            if entry_changed:
                self.entry_changed.emit(self.script_folder, new_entry)

    def edit_software_selection(self):
        """Open dialog to edit software selection for existing metadata"""
        if not self.script_folder:
            return
            
        conf = get_galt_config(self.script_folder)
        if not conf:
            return

        if conf.get("charon_meta"):
            self._edit_charon_metadata(conf)
            return
            
        # Store script path locally since it might change during dialog execution
        script_folder = self.script_folder
        
        # Get current software list and script type
        old_software_list = conf.get("software", [])
        current_script_type = conf.get("script_type", "python")
        
        # Create dialog with current software and script type pre-selected (only visible software)
        from ..utilities import get_visible_software_list
        dialog = MetadataDialog(get_visible_software_list(), config.SCRIPT_TYPES, script_path=script_folder, parent=self)
        for software in old_software_list:
            if software in dialog.software_checkboxes:
                dialog.software_checkboxes[software].setChecked(True)
        
        # Set current script type
        if hasattr(dialog, 'script_type_combo'):
            script_type_index = dialog.script_type_combo.findText(current_script_type.capitalize())
            if script_type_index >= 0:
                dialog.script_type_combo.setCurrentIndex(script_type_index)
        
        # Set current run_on_main value
        current_run_on_main = conf.get("run_on_main", True)
        dialog.run_on_main_checkbox.setChecked(current_run_on_main)
        
        # Set current mirror_prints value (with backward compatibility)
        current_mirror_prints = conf.get("mirror_prints", conf.get("intercept_prints", config.DEFAULT_METADATA["mirror_prints"]))
        dialog.mirror_prints_checkbox.setChecked(current_mirror_prints)
        
        if exec_dialog(dialog) == QtWidgets.QDialog.Accepted:
            new_software_list = dialog.selected_software()
            new_script_type = dialog.selected_script_type()
            new_run_on_main = dialog.run_on_main_thread()
            new_mirror_prints = dialog.mirror_prints()
            
            # --- Handle Hotkey Deletion ---
            # Determine which software were removed
            removed_software = set(old_software_list) - set(new_software_list)
            if removed_software:
                from ..settings import user_settings_db
                for sw in removed_software:
                    # For each removed software, delete any associated hotkey
                    user_settings_db.remove_hotkey_for_script_software(script_folder, sw)

            # --- Update Metadata File (clean up to current shape) ---
            # Re-read the config to get the latest tags (in case they were changed while dialog was open)
            latest_conf = get_galt_config(script_folder)
            
            new_config = {
                "software": new_software_list,
                "entry": latest_conf.get("entry", "main.py") if latest_conf else conf.get("entry", "main.py"),
                "script_type": new_script_type,
                "run_on_main": new_run_on_main,
                "mirror_prints": new_mirror_prints
            }
            # Remove deprecated fields (display, intercept_prints) by not copying them
            
            # Preserve existing tags from the LATEST config
            new_config["tags"] = latest_conf.get("tags", []) if latest_conf else []
            
            # --- Emit Signal for UI Refresh ---
            # Use the local script_folder variable that was saved before dialog execution
            if script_folder and update_galt_config(script_folder, new_config):
                # Emit granular signal for software change
                if old_software_list != new_software_list:
                    self.software_changed.emit(script_folder, new_software_list)

    def create_metadata(self):
        if not self.script_folder:
            return
        # Get only visible software for display
        from ..utilities import get_visible_software_list
        dialog = MetadataDialog(get_visible_software_list(), config.SCRIPT_TYPES, parent=self)
        if exec_dialog(dialog) == QtWidgets.QDialog.Accepted:
            selected_software_list = dialog.selected_software()
            selected_script_type = dialog.selected_script_type()
            selected_run_on_main = dialog.run_on_main_thread()
            selected_mirror_prints = dialog.mirror_prints()
        else:
            return
            
        # Determine default entry file
        default_entry = ""
        
        # Check for Python files first
        py_files = [f for f in os.listdir(self.script_folder) if f.endswith(".py")]
        if py_files and "main.py" in py_files:
            default_entry = "main.py"
        elif py_files:
            default_entry = py_files[0]
        
        # If no Python files and any selected software is Maya, check for MEL files
        elif any(sw.lower() == "maya" for sw in selected_software_list):
            mel_files = [f for f in os.listdir(self.script_folder) if f.endswith(".mel")]
            if mel_files:
                default_entry = mel_files[0]
        
        default_config = {
            "software": selected_software_list,
            "entry": default_entry,
            "script_type": selected_script_type,
            "run_on_main": selected_run_on_main,
            "mirror_prints": selected_mirror_prints
        }
        
        if create_default_galt_file(self.script_folder, default_config=default_config):
            self.update_metadata(self.script_folder)
            self.metadata_changed.emit()
    def _show_charon_metadata(self, conf, script_folder):
        charon = conf.get("charon_meta", {})
        self._update_ui(state="charon_view", script_folder=script_folder, parent_folder=os.path.dirname(script_folder))

        display_name = Path(script_folder).name
        self.charon_title.setText(display_name)
        raw_display = charon.get("display_name")
        if raw_display and raw_display != display_name:
            self.charon_title.setToolTip(raw_display)
        else:
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

        last_changed = charon.get("last_changed")
        if last_changed:
            try:
                parsed = datetime.fromisoformat(last_changed.replace("Z", "+00:00"))
                display_last_changed = parsed.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
                if display_last_changed.endswith("UTC"):
                    display_last_changed = display_last_changed
                elif parsed.tzinfo:
                    display_last_changed = parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
            except ValueError:
                display_last_changed = last_changed
        else:
            display_last_changed = "-"
        self.charon_last_changed_value.setText(display_last_changed)

        node_count = "-"
        if workflow_exists:
            try:
                with open(workflow_path, "r", encoding="utf-8") as wf_handle:
                    workflow_data = json.load(wf_handle)
                    nodes = workflow_data.get("nodes")
                    if isinstance(nodes, dict):
                        node_count = str(len(nodes))
            except Exception:
                node_count = "?"  # Indicate unreadable
        self.charon_node_count_value.setText(node_count)

        dependencies = charon.get("dependencies") or []
        self._clear_layout(self.charon_dependencies_layout)
        if dependencies:
            for dep in dependencies:
                name = dep.get("name") or dep.get("repo") or "Dependency"
                repo = dep.get("repo")
                ref = dep.get("ref")
                label = QtWidgets.QLabel()
                label.setTextFormat(QtCore.Qt.TextFormat.RichText)
                if repo:
                    link = f'<a href="{repo}">{name}</a>'
                else:
                    link = name
                suffix = f" <span style='color:palette(mid);'>({ref})</span>" if ref else ""
                label.setText(f"{link}{suffix}")
                label.setOpenExternalLinks(True)
                label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextBrowserInteraction)
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
        dialog = CharonMetadataDialog(charon_meta, parent=self)
        if exec_dialog(dialog) != QtWidgets.QDialog.Accepted:
            return

        updates = dialog.get_metadata()
        updated_meta = charon_meta.copy()
        updated_meta.update(updates)
        if not updated_meta.get("workflow_file"):
            updated_meta["workflow_file"] = charon_meta.get("workflow_file") or "workflow.json"

        old_tags = conf.get("tags", [])
        new_tags = updated_meta.get("tags", [])

        if write_charon_metadata(self.script_folder, updated_meta) is None:
            QtWidgets.QMessageBox.warning(self, "Update Failed", "Could not write workflow metadata.")
            return

        added = [tag for tag in new_tags if tag not in old_tags]
        removed = [tag for tag in old_tags if tag not in new_tags]

        self.update_metadata(self.script_folder)
        if added or removed:
            self.tags_updated.emit(self.script_folder, added, removed)
        self.metadata_changed.emit()
