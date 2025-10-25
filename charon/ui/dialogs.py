from ..qt_compat import (QtWidgets, QtCore, QtGui, Qt, WindowContextHelpButtonHint, WindowCloseButtonHint, StrongFocus,
                         Key_Escape, Key_Control, Key_Shift, Key_Alt, ShiftModifier,
                         Key_Exclam, Key_At, Key_NumberSign, Key_Dollar, Key_Percent,
                         Key_AsciiCircum, Key_Ampersand, Key_Asterisk, Key_ParenLeft,
                         Key_ParenRight, Key_1, Key_2, Key_3, Key_4, Key_5, Key_6,
                         Key_7, Key_8, Key_9, Key_0)
from ..qt_compat import exec_dialog
import os
from .. import utilities
from ..input_mapping import (
    discover_prompt_widget_parameters,
    load_workflow_document,
    WorkflowLoadError,
    ExposableNode,
    ExposableAttribute,
)
from ..charon_logger import system_debug
from .custom_widgets import create_tag_badge
from typing import Dict, Any, List, Optional, Tuple
import hashlib
import json

_CACHE_SCHEMA_VERSION = 1
_CACHE_FILENAME = "input_mapping_cache.json"
_MEMORY_CACHE: Dict[str, Tuple[str, Tuple[ExposableNode, ...]]] = {}


def _cache_key(path: str) -> str:
    return os.path.abspath(path)


def _cache_directory(path: str) -> str:
    base_dir = os.path.dirname(os.path.abspath(path))
    return os.path.join(base_dir, ".charon_cache")


def _cache_file_path(path: str) -> str:
    return os.path.join(_cache_directory(path), _CACHE_FILENAME)


def _compute_workflow_hash(path: str) -> Optional[str]:
    try:
        hasher = hashlib.sha1()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                hasher.update(chunk)
        return hasher.hexdigest()
    except OSError:
        return None


def _serialize_candidates(candidates: Tuple[ExposableNode, ...]) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    for node in candidates or ():
        serialized.append(
            {
                "node_id": node.node_id,
                "name": node.name,
                "attributes": [
                    {
                        "key": attr.key,
                        "label": attr.label,
                        "value": attr.value,
                        "value_type": attr.value_type,
                        "preview": attr.preview,
                        "aliases": list(attr.aliases or []),
                        "node_default": attr.node_default,
                    }
                    for attr in node.attributes or ()
                ],
            }
        )
    return serialized


def _deserialize_candidates(serialized: List[Dict[str, Any]]) -> Tuple[ExposableNode, ...]:
    nodes: List[ExposableNode] = []
    for node_entry in serialized or []:
        attributes: List[ExposableAttribute] = []
        for attr_entry in node_entry.get("attributes") or []:
            attributes.append(
                ExposableAttribute(
                    key=str(attr_entry.get("key") or ""),
                    label=str(attr_entry.get("label") or ""),
                    value=attr_entry.get("value"),
                    value_type=str(attr_entry.get("value_type") or "string"),
                    preview=str(attr_entry.get("preview") or ""),
                    aliases=tuple(attr_entry.get("aliases") or []),
                    node_default=attr_entry.get("node_default"),
                )
            )
        nodes.append(
            ExposableNode(
                node_id=str(node_entry.get("node_id") or ""),
                name=str(node_entry.get("name") or ""),
                attributes=tuple(attributes),
            )
        )
    return tuple(nodes)


def _get_cached_parameters(path: Optional[str]) -> Optional[Tuple[ExposableNode, ...]]:
    if not path:
        return None
    abs_path = _cache_key(path)
    workflow_hash = _compute_workflow_hash(abs_path)
    if workflow_hash is None:
        return None

    memory_entry = _MEMORY_CACHE.get(abs_path)
    if memory_entry and memory_entry[0] == workflow_hash:
        return memory_entry[1]

    cache_file = _cache_file_path(abs_path)
    if not os.path.exists(cache_file):
        return None

    try:
        with open(cache_file, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return None

    if payload.get("schema") != _CACHE_SCHEMA_VERSION:
        return None
    if payload.get("workflow_hash") != workflow_hash:
        return None

    try:
        candidates = _deserialize_candidates(payload.get("nodes") or [])
    except Exception:
        return None

    _MEMORY_CACHE[abs_path] = (workflow_hash, candidates)
    return candidates


def _store_cached_parameters(path: Optional[str], data) -> None:
    if not path:
        return
    abs_path = _cache_key(path)
    workflow_hash = _compute_workflow_hash(abs_path)
    if workflow_hash is None:
        return

    candidates = tuple(data or ())
    payload = {
        "schema": _CACHE_SCHEMA_VERSION,
        "workflow_hash": workflow_hash,
        "nodes": _serialize_candidates(candidates),
    }

    cache_dir = _cache_directory(abs_path)
    cache_file = _cache_file_path(abs_path)

    try:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except Exception as exc:
        system_debug(f"Failed to write parameter cache: {exc}")
    else:
        _MEMORY_CACHE[abs_path] = (workflow_hash, candidates)


def _resolve_parameter_default(value: Any, value_type: str, node_default: Any) -> Any:
    if value is None:
        return node_default

    kind = (value_type or "").lower()
    if kind == "integer":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        try:
            return int(value)
        except (TypeError, ValueError):
            return node_default
    if kind == "float":
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return node_default
    return value if value is not None else node_default


class _ParameterDiscoveryWorker(QtCore.QObject):
    finished = QtCore.Signal(object, object)

    def __init__(self, workflow_path: Optional[str]) -> None:
        super().__init__()
        self._workflow_path = workflow_path

    @QtCore.Slot()
    def run(self) -> None:
        if not self._workflow_path:
            self.finished.emit(tuple(), None)
            return

        try:
            workflow_document = load_workflow_document(self._workflow_path)
        except Exception as exc:
            self.finished.emit(tuple(), str(exc))
            return

        try:
            candidates = discover_prompt_widget_parameters(workflow_document)
        except Exception as exc:
            self.finished.emit(tuple(), str(exc))
            return

        self.finished.emit(candidates, None)

class BaseMetadataDialog(QtWidgets.QDialog):
    """Base dialog for metadata operations with software selection and validation."""
    
    def __init__(self, software_list, script_types=None, parent=None):
        super(BaseMetadataDialog, self).__init__(parent)
        self.setWindowFlag(WindowContextHelpButtonHint, False)
        self.setWindowFlag(WindowCloseButtonHint, True)
        self.setMinimumWidth(350)
        
        self.software_list = software_list
        self.script_types = script_types
        
        layout = QtWidgets.QVBoxLayout(self)
        
        # Instructions label
        label = QtWidgets.QLabel("Select software for this script (select at least one):")
        layout.addWidget(label)
        
        # Create scroll area for software checkboxes
        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setMaximumHeight(150)
        
        # Create widget to hold software checkboxes
        software_widget = QtWidgets.QWidget()
        software_layout = QtWidgets.QVBoxLayout(software_widget)
        software_layout.setContentsMargins(0, 0, 0, 0)
        
        # Create checkboxes for each software
        self.software_checkboxes = {}
        for software in software_list:
            checkbox = QtWidgets.QCheckBox(software)
            self.software_checkboxes[software] = checkbox
            software_layout.addWidget(checkbox)
        
        # Add stretch to push checkboxes to top
        software_layout.addStretch()
        
        # Set the widget for scroll area
        scroll_area.setWidget(software_widget)
        layout.addWidget(scroll_area)
        
        # Store reference to layout for subclasses to insert elements
        self.main_layout = layout
        
        # Add script type selection if provided
        if script_types:
            layout.addSpacing(10)
            
            # Script type section
            script_type_label = QtWidgets.QLabel("Script Type:")
            layout.addWidget(script_type_label)
            
            # Create dropdown for script types
            self.script_type_combo = QtWidgets.QComboBox()
            for script_type in script_types.keys():
                self.script_type_combo.addItem(script_type.capitalize())
            
            # Set Python as default
            python_index = self.script_type_combo.findText("Python")
            if python_index >= 0:
                self.script_type_combo.setCurrentIndex(python_index)
            
            layout.addWidget(self.script_type_combo)
        
        # Add run_on_main checkbox
        layout.addSpacing(10)
        self.run_on_main_checkbox = QtWidgets.QCheckBox("Run on main thread (required for Qt/GUI scripts)")
        self.run_on_main_checkbox.setChecked(True)  # Default to True for safety
        self.run_on_main_checkbox.setToolTip(
            "Enable this for scripts that create GUI windows or use Qt widgets.\n"
            "Disable this for pure computation scripts that need to run in the background."
        )
        layout.addWidget(self.run_on_main_checkbox)
        
        # Add mirror_prints checkbox
        self.mirror_prints_checkbox = QtWidgets.QCheckBox("Mirror prints to terminal")
        self.mirror_prints_checkbox.setChecked(True)  # Default to True
        self.mirror_prints_checkbox.setToolTip(
            "Enable this to mirror script output to the terminal.\n"
            "Output always appears in the execution dialog.\n"
            "When enabled: Output appears in both dialog AND terminal.\n"
            "When disabled: Output appears ONLY in dialog."
        )
        layout.addWidget(self.mirror_prints_checkbox)
        
        # Add validation message
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        layout.addWidget(separator)
        self.validation_label = QtWidgets.QLabel("")
        layout.addWidget(self.validation_label)
        
        # Buttons
        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        layout.addWidget(button_box)
        
        # Connect signals
        button_box.accepted.connect(self.validate_and_accept)
        button_box.rejected.connect(self.reject)
        
        # Connect checkbox changes to validation
        for checkbox in self.software_checkboxes.values():
            checkbox.toggled.connect(self.update_validation)

    def update_validation(self):
        """Update validation message and OK button state - to be overridden by subclasses"""
        selected_count = sum(1 for checkbox in self.software_checkboxes.values() if checkbox.isChecked())
        
        if selected_count == 0:
            self.validation_label.setText("Please select at least one software.")
            self.validation_label.setVisible(True)
            # Disable OK button
            ok_button = self.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok)
            ok_button.setEnabled(False)
        else:
            self.validation_label.setText(f"Selected: {selected_count} software")
            self.validation_label.setVisible(True)
            # Enable OK button
            ok_button = self.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok)
            ok_button.setEnabled(True)

    def validate_and_accept(self):
        """Validate that at least one software is selected before accepting"""
        selected_count = sum(1 for checkbox in self.software_checkboxes.values() if checkbox.isChecked())
        if selected_count > 0:
            self.accept()
        else:
            self.validation_label.setText("Please select at least one software.")
            self.validation_label.setVisible(True)

    def selected_software(self):
        """Return list of selected software"""
        return [software for software, checkbox in self.software_checkboxes.items() if checkbox.isChecked()]
    
    def selected_script_type(self):
        """Return the selected script type"""
        if hasattr(self, 'script_type_combo'):
            return self.script_type_combo.currentText().lower()
        return "python"  # Default fallback
    
    def run_on_main_thread(self):
        """Return whether the script should run on main thread"""
        return self.run_on_main_checkbox.isChecked()
    
    def mirror_prints(self):
        """Return whether the script should mirror prints to terminal"""
        return self.mirror_prints_checkbox.isChecked()

class MetadataDialog(BaseMetadataDialog):
    def __init__(self, software_list, script_types=None, script_path=None, parent=None):
        super(MetadataDialog, self).__init__(software_list, script_types, parent)
        self.script_path = script_path
        self.setWindowTitle("Metadata")
        # Initial validation
        self.update_validation()
        
        # Add tags display and manage button after software selection
        if self.script_path:
            self._add_tags_section()
    
    def _add_tags_section(self):
        """Add tags display and manage button to the dialog."""
        from ..metadata_manager import get_charon_config
        
        # Get current metadata
        metadata = get_charon_config(self.script_path)
        if not metadata:
            return
            
        tags = metadata.get('tags', [])
        
        # Find where to insert (after software scroll area, before script type)
        # Get the index of the scroll area
        scroll_area_index = None
        for i in range(self.main_layout.count()):
            widget = self.main_layout.itemAt(i).widget()
            if isinstance(widget, QtWidgets.QScrollArea):
                scroll_area_index = i
                break
                
        if scroll_area_index is None:
            return
            
        insert_index = scroll_area_index + 1
        
        # Add spacing
        self.main_layout.insertSpacing(insert_index, 10)
        insert_index += 1
        
        # Tags section
        tags_label = QtWidgets.QLabel("Tags:")
        self.main_layout.insertWidget(insert_index, tags_label)
        insert_index += 1
        
        # Tags display area with flow layout
        tags_widget = QtWidgets.QWidget()
        tags_layout = QtWidgets.QHBoxLayout(tags_widget)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(5)
        
        # Create tag badges
        if tags:
            for tag in sorted(tags):
                tag_label = create_tag_badge(tag)
                tags_layout.addWidget(tag_label)
        else:
            no_tags_label = QtWidgets.QLabel("No tags")
            no_tags_label.setStyleSheet("color: palette(mid);")
            tags_layout.addWidget(no_tags_label)
            
        tags_layout.addStretch()
        self.main_layout.insertWidget(insert_index, tags_widget)
        insert_index += 1
        
        # Manage Tags button
        self.manage_tags_btn = QtWidgets.QPushButton("Manage Tags")
        self.manage_tags_btn.clicked.connect(self._open_tag_manager)
        self.main_layout.insertWidget(insert_index, self.manage_tags_btn)
        insert_index += 1
        
        # Store the tags widget reference for updates
        self.tags_widget = tags_widget
        self.tags_layout = tags_layout
    
    def _open_tag_manager(self):
        """Open the tag manager dialog."""
        if not self.script_path:
            return
            
        # Find the main window parent to use its centralized tag manager
        main_window = self.parent()
        while main_window and not hasattr(main_window, 'open_tag_manager'):
            main_window = main_window.parent()
            
        if main_window and hasattr(main_window, 'open_tag_manager'):
            # Use the centralized method which handles folder paths and UI refresh correctly
            main_window.open_tag_manager(self.script_path)
            # After the tag manager closes, refresh our local tags display with a delay
            # to ensure file system writes are complete
            QtCore.QTimer.singleShot(150, self._refresh_tags)
        else:
            # Fallback if we can't find main window (shouldn't happen in normal use)
            folder_path = os.path.dirname(self.script_path)
            from .tag_manager_dialog import TagManagerDialog
            dialog = TagManagerDialog(self.script_path, folder_path, parent=self)
            dialog.resize(200, 350)
            # Use detailed signal for better performance
            def handle_tag_changes(added, removed, renamed):
                self._refresh_tags()
            dialog.detailed_tags_changed.connect(handle_tag_changes)
            exec_dialog(dialog)
    
    def _refresh_tags(self):
        """Refresh the tags display after changes."""
        if not hasattr(self, 'tags_widget') or not self.script_path:
            return
            
        from ..metadata_manager import get_charon_config
        
        # Get updated metadata
        metadata = get_charon_config(self.script_path)
        if not metadata:
            return
            
        tags = metadata.get('tags', [])
        
        # Clear existing tags
        while self.tags_layout.count() > 1:  # Keep the stretch
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        # Re-add tags
        if tags:
            for tag in sorted(tags):
                tag_label = create_tag_badge(tag)
                self.tags_layout.insertWidget(self.tags_layout.count() - 1, tag_label)
        else:
            no_tags_label = QtWidgets.QLabel("No tags")
            no_tags_label.setStyleSheet("color: palette(mid);")
            self.tags_layout.insertWidget(0, no_tags_label)

class CreateScriptDialog(BaseMetadataDialog):
    def __init__(self, script_types, software_list, current_host, parent=None):
        super(CreateScriptDialog, self).__init__(software_list, script_types, parent)
        self.setWindowTitle("Create New Workflow")
        
        # Store additional data
        self.script_types = script_types
        self.current_host = current_host
        
        # Add script name field at the top
        name_layout = QtWidgets.QHBoxLayout()
        name_label = QtWidgets.QLabel("Workflow Name:")
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("Enter workflow name")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_edit)
        
        # Insert name field at the top of the layout
        self.layout().insertLayout(0, name_layout)
        
        # Default to current host
        for software, checkbox in self.software_checkboxes.items():
            if software.lower() == current_host.lower():
                checkbox.setChecked(True)
                break
        
        # Connect name field to validation
        self.name_edit.textChanged.connect(self.update_validation)
        
        # Override validation to include script name (call after name_edit is created)
        self.update_validation()
        
        # Set focus to the name input field for immediate typing
        self.name_edit.setFocus()

    def update_validation(self):
        """Override to include workflow name validation"""
        script_name = self.name_edit.text().strip()
        selected_count = sum(1 for checkbox in self.software_checkboxes.values() if checkbox.isChecked())
        
        ok_button = self.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok)
        
        if not script_name:
            self.validation_label.setText("Please enter a workflow name.")
            self.validation_label.setVisible(True)
            ok_button.setEnabled(False)
        elif selected_count == 0:
            self.validation_label.setText("Please select at least one software.")
            self.validation_label.setVisible(True)
            ok_button.setEnabled(False)
        else:
            self.validation_label.setText(f"Selected: {selected_count} software")
            self.validation_label.setVisible(True)
            ok_button.setEnabled(True)

    def validate_and_accept(self):
        """Override to include workflow name validation"""
        script_name = self.name_edit.text().strip()
        selected_count = sum(1 for checkbox in self.software_checkboxes.values() if checkbox.isChecked())
        
        if script_name and selected_count > 0:
            self.accept()
        else:
            self.update_validation()

    def get_script_info(self):
        """Return the workflow name and type"""
        script_name = self.name_edit.text().strip()
        script_type = self.script_type_combo.currentText().lower()
        return script_name, script_type
        
    def get_script_extension(self):
        """Get the file extension for the selected script type"""
        script_type = self.script_type_combo.currentText().lower()
        if script_type in self.script_types and self.script_types[script_type]:
            return self.script_types[script_type][0]  # Get the first extension
        return ".py"  # Default to Python

class ReadmeDialog(QtWidgets.QDialog):
    def __init__(self, script_folder=None, parent=None):
        super(ReadmeDialog, self).__init__(parent)
        self.setWindowFlag(WindowContextHelpButtonHint, False)
        self.setWindowFlag(WindowCloseButtonHint, True)
        self.script_folder = script_folder
        self.readme_path = None  # Will be set in load_readme
        # Set a default title, will be updated in load_readme
        self.setWindowTitle("Readme")
        
        layout = QtWidgets.QVBoxLayout(self)

        # Add Edit button at the top
        edit_layout = QtWidgets.QHBoxLayout()
        edit_layout.addStretch()
        self.edit_btn = QtWidgets.QPushButton("Edit")
        self.edit_btn.clicked.connect(self.edit_readme)
        # Make sure edit button doesn't become default button
        self.edit_btn.setAutoDefault(False)
        self.edit_btn.setDefault(False)
        edit_layout.addWidget(self.edit_btn)
        layout.addLayout(edit_layout)

        self.text_browser = QtWidgets.QTextBrowser()
        # Enable loading of local resources
        self.text_browser.setOpenExternalLinks(True)
        self.text_browser.setOpenLinks(True)
        layout.addWidget(self.text_browser)

        # Remove the close button and bottom button layout

        self.load_readme(script_folder)
        
        # Remove focus from text browser to ensure dialog receives key events
        self.setFocusPolicy(StrongFocus)
        
        # Use a timer to set focus after dialog is shown
        QtCore.QTimer.singleShot(0, self._set_initial_focus)
    
    def _set_initial_focus(self):
        """Set initial focus after dialog is shown."""
        self.setFocus()
        self.activateWindow()

    def load_readme(self, script_folder):
        if script_folder:
            self.readme_path = os.path.join(script_folder, "readme.md")
            # Get the script name from the folder path
            script_name = os.path.basename(script_folder)
            self.setWindowTitle(f"Readme - {script_name}")
        else:
            # Load Charon's default readme from the project root.
            project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            self.readme_path = os.path.join(project_root, "readme.md")
            self.setWindowTitle("Readme - Charon")
            
        if os.path.exists(self.readme_path):
            try:
                with open(self.readme_path, "r", encoding="utf-8") as f:
                    content = f.read()
                # Define the base path for relative image paths
                base_path = os.path.dirname(self.readme_path)
                html_content = utilities.md_to_html(content, base_path=base_path)
                # Set base URL to the directory containing the readme file
                readme_dir = os.path.abspath(os.path.dirname(self.readme_path))
                base_url = QtCore.QUrl.fromLocalFile(readme_dir + os.sep)
                self.text_browser.document().setBaseUrl(base_url)
                self.text_browser.setHtml(html_content)
            except Exception as e:
                self.text_browser.setPlainText(f"Error loading readme: {str(e)}")
    
                
    def edit_readme(self):
        if self.readme_path and os.path.exists(self.readme_path):
            try:
                # Cross-platform file opening
                import platform
                import subprocess
                
                if platform.system() == "Windows":
                    os.startfile(self.readme_path)
                elif platform.system() == "Darwin":  # macOS
                    subprocess.run(["open", self.readme_path])
                else:  # Linux
                    subprocess.run(["xdg-open", self.readme_path])
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Error", f"Could not open file: {str(e)}")
    


class CharonMetadataDialog(QtWidgets.QDialog):
    """Dialog for editing metadata stored in `.charon.json` files."""

    def __init__(
        self,
        metadata: Dict[str, Any],
        workflow_path: Optional[str] = None,
        parent=None,
    ):
        super(CharonMetadataDialog, self).__init__(parent)
        self.setWindowFlag(WindowContextHelpButtonHint, False)
        self.setWindowFlag(WindowCloseButtonHint, True)
        self.setWindowTitle("Edit Workflow Metadata")
        self.setMinimumWidth(420)

        self._metadata = dict(metadata or {})
        raw_parameters = self._metadata.get("parameters") or []
        if isinstance(raw_parameters, list):
            parameters = [dict(item) for item in raw_parameters if isinstance(item, dict)]
        else:
            parameters = []
        self._metadata["parameters"] = parameters
        self._workflow_path = workflow_path
        self._discovery_thread: Optional[QtCore.QThread] = None
        self._discovery_worker: Optional[_ParameterDiscoveryWorker] = None
        self._scan_animation_timer: Optional[QtCore.QTimer] = None
        self._scan_animation_phase: int = 0
        self._scan_base_text: str = "Scanning workflow inputs"

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        workflow_file = self._metadata.get("workflow_file") or "workflow.json"
        workflow_label = QtWidgets.QLabel(f"Workflow JSON (read-only): {workflow_file}")
        workflow_label.setEnabled(False)
        layout.addWidget(workflow_label)

        layout.addWidget(QtWidgets.QLabel("Description:"))
        self.description_edit = QtWidgets.QTextEdit()
        self.description_edit.setPlaceholderText("Describe what this workflow does...")
        self.description_edit.setPlainText(self._metadata.get("description", ""))
        layout.addWidget(self.description_edit)

        self._build_input_mapping_section(layout)

        layout.addWidget(QtWidgets.QLabel("Dependencies (Git URLs):"))
        deps_container = QtWidgets.QWidget()
        deps_layout = QtWidgets.QVBoxLayout(deps_container)
        deps_layout.setContentsMargins(0, 0, 0, 0)
        deps_layout.setSpacing(4)

        self.deps_table = QtWidgets.QTableWidget(0, 1)
        self.deps_table.setHorizontalHeaderLabels(["Git URL"])
        header = self.deps_table.horizontalHeader()
        try:
            header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        except AttributeError:
            header.setStretchLastSection(True)
        self.deps_table.verticalHeader().setVisible(False)
        self.deps_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.deps_table.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        self.deps_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.AllEditTriggers)
        self.deps_table.setMaximumHeight(140)
        deps_layout.addWidget(self.deps_table)

        deps_buttons = QtWidgets.QHBoxLayout()
        self.add_dep_button = QtWidgets.QPushButton("Add")
        self.remove_dep_button = QtWidgets.QPushButton("Remove")
        deps_buttons.addWidget(self.add_dep_button)
        deps_buttons.addWidget(self.remove_dep_button)
        deps_buttons.addStretch()
        deps_layout.addLayout(deps_buttons)

        layout.addWidget(deps_container)

        self.add_dep_button.clicked.connect(self._add_dependency_row)
        self.remove_dep_button.clicked.connect(self._remove_selected_dependencies)

        for dep in self._metadata.get("dependencies", []) or []:
            self._add_dependency_row(dep)

        layout.addWidget(QtWidgets.QLabel("Tags (comma separated):"))
        self.tags_edit = QtWidgets.QLineEdit(", ".join(self._metadata.get("tags", [])))
        self.tags_edit.setPlaceholderText("e.g. comfy, FLUX, Nano-Banana")
        layout.addWidget(self.tags_edit)

        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        layout.addWidget(button_box)

        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

    def _build_input_mapping_section(self, layout: QtWidgets.QVBoxLayout) -> None:
        """Create and populate the workflow parameter preview list."""
        self.input_mapping_group = QtWidgets.QGroupBox("Select Parameters to Expose")
        self.input_mapping_group.setVisible(False)
        group_layout = QtWidgets.QVBoxLayout(self.input_mapping_group)
        group_layout.setContentsMargins(8, 8, 8, 8)
        group_layout.setSpacing(4)

        self.input_mapping_tree = QtWidgets.QTreeWidget()
        self.input_mapping_tree.setHeaderHidden(True)
        self.input_mapping_tree.setRootIsDecorated(True)
        self.input_mapping_tree.setAlternatingRowColors(True)
        group_layout.addWidget(self.input_mapping_tree)

        self.input_mapping_message = QtWidgets.QLabel()
        self.input_mapping_message.setWordWrap(True)
        group_layout.addWidget(self.input_mapping_message)

        layout.addWidget(self.input_mapping_group)
        self.input_mapping_tree.itemChanged.connect(self._on_parameter_item_changed)
        self._populate_input_mapping_preview()

    def _populate_input_mapping_preview(self) -> None:
        """Populate the preview tree with prompt widget candidates from the workflow."""
        if not self._workflow_path:
            self.input_mapping_group.setVisible(False)
            return

        self.input_mapping_group.setVisible(True)
        self.input_mapping_tree.clear()
        self.input_mapping_tree.setVisible(False)
        self.input_mapping_message.setVisible(True)

        base_title = "Select Parameters to Expose"
        self.input_mapping_group.setTitle(base_title)

        cached = _get_cached_parameters(self._workflow_path)
        if cached is not None:
            self._stop_scan_animation()
            system_debug("Metadata dialog loaded parameters from cache.")
            self._render_parameter_candidates(cached)
            return

        self._cancel_parameter_discovery()

        self.input_mapping_message.setText(self._scan_base_text)
        self._start_scan_animation()

        thread = QtCore.QThread(self)
        worker = _ParameterDiscoveryWorker(self._workflow_path)
        worker.moveToThread(thread)

        worker.finished.connect(self._on_parameter_discovery_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._clear_discovery_handles())

        thread.started.connect(worker.run)
        self._discovery_thread = thread
        self._discovery_worker = worker
        thread.start()

    def _cancel_parameter_discovery(self) -> None:
        if self._discovery_thread:
            try:
                self._discovery_thread.requestInterruption()
            except Exception:
                pass
            self._discovery_thread.quit()
            self._discovery_thread.wait(100)
        self._clear_discovery_handles()
        self._stop_scan_animation()

    def _clear_discovery_handles(self) -> None:
        self._discovery_thread = None
        self._discovery_worker = None

    def _start_scan_animation(self) -> None:
        if self._scan_animation_timer:
            return
        self._scan_animation_phase = 0
        timer = QtCore.QTimer(self)
        timer.setInterval(300)
        timer.timeout.connect(self._advance_scan_animation)
        timer.start()
        self._scan_animation_timer = timer

    def _advance_scan_animation(self) -> None:
        if not self._scan_animation_timer:
            return
        self._scan_animation_phase = (self._scan_animation_phase + 1) % 4
        dots = "." * self._scan_animation_phase
        self.input_mapping_message.setText(f"{self._scan_base_text}{dots}")

    def _stop_scan_animation(self) -> None:
        if self._scan_animation_timer:
            self._scan_animation_timer.stop()
            self._scan_animation_timer.deleteLater()
            self._scan_animation_timer = None
        self._scan_animation_phase = 0

    def _on_parameter_discovery_finished(self, candidates, error) -> None:
        self._stop_scan_animation()
        if error:
            self.input_mapping_message.setText(str(error))
            system_debug(f"Metadata dialog parameter discovery error: {error}")
            return

        try:
            candidates = tuple(candidates or ())
        except TypeError:
            candidates = tuple()

        if not candidates:
            self.input_mapping_message.setText(
                "No prompt widgets were detected in this workflow yet."
            )
            system_debug("Metadata dialog discovered 0 prompt candidates.")
            return

        system_debug(
            "Metadata dialog discovered prompt nodes: %s"
            % [(node.node_id, [attr.key for attr in node.attributes]) for node in candidates]
        )
        _store_cached_parameters(self._workflow_path, candidates)
        self._render_parameter_candidates(candidates)

    def _render_parameter_candidates(self, candidates) -> None:
        self._stop_scan_animation()
        base_title = "Select Parameters to Expose"

        total_attributes = sum(len(node.attributes) for node in candidates)
        if total_attributes:
            self.input_mapping_group.setTitle(f"{base_title} ({total_attributes})")
        else:
            self.input_mapping_group.setTitle(base_title)

        nodes_to_expand: List[QtWidgets.QTreeWidgetItem] = []

        for node in candidates:
            node_item = QtWidgets.QTreeWidgetItem(self.input_mapping_tree, [node.name])
            node_item.setFlags(QtCore.Qt.ItemIsEnabled)
            node_should_expand = False

            for attribute in node.attributes:
                attr_item = QtWidgets.QTreeWidgetItem(node_item, [attribute.label])
                flags = attr_item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsSelectable
                attr_item.setFlags(flags)
                if self._is_parameter_selected(node.node_id, attribute.key, attribute.aliases):
                    attr_item.setCheckState(0, QtCore.Qt.CheckState.Checked)
                    node_should_expand = True
                else:
                    attr_item.setCheckState(0, QtCore.Qt.CheckState.Unchecked)
                attr_item.setToolTip(0, attribute.preview or "No default assigned")
                attr_item.setData(
                    0,
                    QtCore.Qt.ItemDataRole.UserRole,
                    {
                        "node_id": node.node_id,
                        "attribute_key": attribute.key,
                        "node_name": node.name,
                        "group": node.name,
                        "label": attribute.label,
                        "preview": attribute.preview,
                        "value": attribute.value,
                        "value_type": attribute.value_type,
                        "aliases": attribute.aliases,
                        "node_default": attribute.node_default,
                    },
                )

            if node_should_expand:
                nodes_to_expand.append(node_item)

        self.input_mapping_tree.collapseAll()
        for item in nodes_to_expand:
            item.setExpanded(True)
        self.input_mapping_tree.setVisible(True)
        self.input_mapping_message.setVisible(False)

    def _is_parameter_selected(
        self,
        node_id: str,
        attribute_key: str,
        aliases: Tuple[str, ...] = tuple(),
    ) -> bool:
        for spec in self._metadata.get("parameters") or []:
            if (
                str(spec.get("node_id")) == str(node_id)
                and str(spec.get("attribute")) in {
                    str(attribute_key),
                    *[str(alias) for alias in aliases or ()],
                }
            ):
                return True
        return False


    def _on_parameter_item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        """Emit a console message whenever a user toggles an exposable parameter."""
        if item is None or item.parent() is None:
            return

        data = item.data(0, QtCore.Qt.ItemDataRole.UserRole) or {}
        key = data.get("attribute_key")
        node_id = data.get("node_id")
        state = item.checkState(0) == QtCore.Qt.CheckState.Checked

        system_debug(
            f"[Charon] Parameter toggled: node={node_id} key={key} state={'ON' if state else 'OFF'}"
        )

    def _collect_selected_parameters(self) -> List[Dict[str, Any]]:
        """Return parameter specs for all checked entries."""
        system_debug(
            f"[Charon] get_metadata group visible BEFORE: {self.input_mapping_group.isVisible()}"
        )
        if not self.input_mapping_group.isVisible():
            system_debug("[Charon] group hidden while saving; proceeding anyway")

        root = self.input_mapping_tree.invisibleRootItem()
        selected: List[Dict[str, Any]] = []

        for node_index in range(root.childCount()):
            node_item = root.child(node_index)
            for attr_index in range(node_item.childCount()):
                attr_item = node_item.child(attr_index)
                state = attr_item.checkState(0)
                data = attr_item.data(0, QtCore.Qt.ItemDataRole.UserRole) or {}
                system_debug(
                    f"[Charon] inspect node={data.get('node_id')} "
                    f"key={data.get('attribute_key')} state={state}"
                )
                if state != QtCore.Qt.CheckState.Checked:
                    continue
                resolved_default = _resolve_parameter_default(
                    data.get("value"),
                    data.get("value_type") or "",
                    data.get("node_default"),
                )
                spec = {
                    "node_id": str(data.get("node_id") or ""),
                    "node_name": data.get("node_name") or node_item.text(0),
                    "attribute": str(data.get("attribute_key") or ""),
                    "label": data.get("label") or attr_item.text(0),
                    "type": data.get("value_type") or "string",
                    "default": resolved_default,
                    "value": data.get("value"),
                    "group": data.get("group") or node_item.text(0),
                }
                selected.append(spec)
        system_debug(f"Metadata dialog collected parameters: {selected}")
        return selected

    def closeEvent(self, event):
        self._cancel_parameter_discovery()
        super(CharonMetadataDialog, self).closeEvent(event)

    def _add_dependency_row(self, dep: Dict[str, Any] = None):
        row = self.deps_table.rowCount()
        self.deps_table.insertRow(row)
        if isinstance(dep, dict):
            value = dep.get("repo") or dep.get("url") or ""
        else:
            value = dep or ""
        item = QtWidgets.QTableWidgetItem(value)
        self.deps_table.setItem(row, 0, item)
        self.deps_table.editItem(item)

    def _remove_selected_dependencies(self):
        rows = sorted({index.row() for index in self.deps_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.deps_table.removeRow(row)

    def get_metadata(self) -> Dict[str, Any]:
        dependencies: List[str] = []
        for row in range(self.deps_table.rowCount()):
            repo_item = self.deps_table.item(row, 0)
            repo = repo_item.text().strip() if repo_item else ""
            if repo:
                dependencies.append(repo)

        tags_raw = self.tags_edit.text()
        tags = [tag.strip() for tag in tags_raw.split(",") if tag.strip()] if tags_raw else []
        parameters = self._collect_selected_parameters()

        self._metadata["parameters"] = parameters

        return {
            "description": self.description_edit.toPlainText().strip(),
            "dependencies": dependencies,
            "tags": tags,
            "parameters": parameters,
        }


class HotkeyDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(HotkeyDialog, self).__init__(parent)
        self.setWindowFlag(WindowContextHelpButtonHint, False)
        self.setWindowFlag(WindowCloseButtonHint, True)
        self.setWindowTitle("Assign Hotkey")
        self.info_label = QtWidgets.QLabel("Press the key combination for the hotkey.\n(Press Esc to cancel)")
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.info_label)
        self.hotkey = None

    def keyPressEvent(self, event):
        # Cancel if Esc is pressed.
        if event.key() == Key_Escape:
            self.reject()
            return

        # Ignore events that are only modifier keys.
        if event.key() in (Key_Control, Key_Shift, Key_Alt):
            return

        # Get the key code
        key = event.key()
        modifiers = event.modifiers()
        
        # Handle shift+number keys specially to avoid getting symbols
        # When shift is pressed with a number, Qt returns the shifted symbol (e.g., # for 3)
        # We need to convert back to the number key
        if modifiers & ShiftModifier:
            # Map of shifted symbols to their number keys
            shift_number_map = {
                Key_Exclam: Key_1,      # ! → 1
                Key_At: Key_2,          # @ → 2
                Key_NumberSign: Key_3,  # # → 3
                Key_Dollar: Key_4,      # $ → 4
                Key_Percent: Key_5,     # % → 5
                Key_AsciiCircum: Key_6, # ^ → 6
                Key_Ampersand: Key_7,   # & → 7
                Key_Asterisk: Key_8,    # * → 8
                Key_ParenLeft: Key_9,   # ( → 9
                Key_ParenRight: Key_0,  # ) → 0
            }
            
            # If it's a shifted number symbol, convert back to the number
            if key in shift_number_map:
                key = shift_number_map[key]
        
        # Create the key sequence with the corrected key
        # Handle PySide6 enum differences
        if hasattr(modifiers, 'value'):
            # PySide6 - modifiers is an enum with a value attribute
            modifier_int = modifiers.value
        else:
            # PySide2 - modifiers is already an int
            modifier_int = int(modifiers)
            
        sequence = QtGui.QKeySequence(key | modifier_int)
        key_str = sequence.toString()
        if key_str:
            self.hotkey = key_str
            self.accept()






