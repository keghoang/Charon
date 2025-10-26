from ..qt_compat import QtWidgets, QtCore, QtGui, Qt, UserRole, UniqueConnection, WindowModal, exec_dialog
from typing import Optional, Tuple
import os, sys, time
from pathlib import Path

from .folder_panel import FolderPanel
from .script_panel import ScriptPanel
from .metadata_panel import MetadataPanel
from .execution_history_panel import ExecutionHistoryPanel
from .quick_search import QuickSearchDialog
from .tag_bar import TagBar
from .tiny_mode_widget import TinyModeWidget
from ..folder_loader import FolderListLoader
from .comfy_connection_widget import ComfyConnectionWidget
from .scene_nodes_panel import SceneNodesPanel as CharonBoardPanel

import threading

# Import config with fallback
try:
    from .. import config
except ImportError:
    # Fallback for CLI usage
    class FallbackConfig:
        WINDOW_WIDTH = 800
        UI_WINDOW_MARGINS = 4
        UI_ELEMENT_SPACING = 2
        UI_BUTTON_WIDTH = 80
        UI_FOLDER_PANEL_RATIO = 0.25
        UI_CENTER_PANEL_RATIO = 0.50
        UI_HISTORY_PANEL_RATIO = 0.25
        UI_NAVIGATION_DELAY_MS = 50
    config = FallbackConfig()
from ..metadata_manager import clear_metadata_cache, get_charon_config, get_folder_tags
from ..workflow_model import GlobalIndexLoader
from ..settings import user_settings_db
from ..utilities import is_compatible_with_host, get_current_user_slug
from ..cache_manager import get_cache_manager
from ..execution.result import ExecutionStatus
from ..charon_logger import system_info, system_debug, system_warning, system_error
from ..icon_manager import get_icon_manager
from ..paths import get_charon_temp_dir


BANNER_IMAGE_PATH = Path(__file__).resolve().parent.parent / "resources" / "banner.png"
BANNER_MAX_HEIGHT = 80

class CharonWindow(QtWidgets.QWidget):
    def __init__(self, global_path=None, local_path=None, host="None", parent=None, startup_mode="normal"):
        super(CharonWindow, self).__init__(parent)
        self._charon_is_charon_window = True
        try:
            self.setObjectName("CharonWindow")
        except Exception:
            pass

        # Initialize icon manager early (icons are loaded once globally)
        self.icon_manager = get_icon_manager()

        self._startup_mode_pending = (startup_mode or "normal").lower()
        self._banner_base_pixmap: Optional[QtGui.QPixmap] = None
        self._banner_target_height: int = 0

        resolved_global_path = global_path or config.WORKFLOW_REPOSITORY_ROOT
        self.global_path = resolved_global_path
        if not os.path.isdir(self.global_path):
            system_warning(f"Workflow repository is not accessible: {self.global_path}")
        # We don't use local_path at all anymore, but keep parameter for backwards compatibility
        self.local_path = None

        # Note: We no longer clear the entire cache when global_path is provided
        # The cache uses full paths as keys, so different repositories won't conflict
        # This significantly improves performance when switching between repositories

        # If no host is specified but we're in a panel, try to detect the host
        if host == "None" and not global_path:
            from charon.utilities import detect_host
            host = detect_host()
            system_debug(f"Auto-detected host in panel: {host}")

        self.host = host
        self.current_base = self.global_path  # Initialize current_base to avoid None errors
        self.comfy_client = None

        # Navigation context flag to prevent deselection during programmatic navigation
        self._is_navigating = False

        # When created directly by panel system, print paths for debugging
        if not global_path:
            system_debug(f"CharonWindow initialized with global_path: {self.global_path}")
            system_debug(f"Host: {self.host}")

            # Ensure directory exists
            if not os.path.exists(self.global_path):
                try:
                    os.makedirs(self.global_path)
                    system_info(f"Created directory: {self.global_path}")
                except Exception as e:
                    system_error(f"Error creating directory {self.global_path}: {str(e)}")

        # Initialize script execution engine
        from charon.execution.engine import ScriptExecutionEngine
        self.script_engine = ScriptExecutionEngine(host=self.host, parent=self)
        self.script_engine.execution_started.connect(self._on_script_started)
        self.script_engine.execution_completed.connect(self._on_script_completed)
        self.script_engine.execution_failed.connect(self._on_script_failed)
        self.script_engine.execution_cancelled.connect(self._on_script_cancelled)
        self.script_engine.progress_updated.connect(self._on_script_progress)
        self.script_engine.output_updated.connect(self._on_script_output)

        # Initialize folder loader before setup_ui
        self.folder_list_loader = FolderListLoader(self)
        self.folder_list_loader.folders_loaded.connect(self._on_folders_loaded)
        self.folder_list_loader.compatibility_loaded.connect(self._on_compatibility_loaded)

        # Setup UI
        self.setup_ui()

        # Clean up missing scripts
        self._cleanup_missing_script_hotkeys(show_dialog=True)

        # Clean up missing bookmarks
        missing_bookmarks = user_settings_db.cleanup_missing_bookmarks()
        if missing_bookmarks:
            bookmark_list = "\n".join(missing_bookmarks)
            QtWidgets.QMessageBox.information(
                self,
                "Removed Bookmarks",
                f"The following bookmarked workflows were not found and have been removed:\n\n{bookmark_list}"
            )

        # Register hotkeys
        self.register_hotkeys()

        # Set window properties
        self.setWindowTitle("Charon")
        self.resize(config.WINDOW_WIDTH, config.WINDOW_HEIGHT)

        # Remove any minimum size constraints to allow full resizing
        self.setMinimumSize(0, 0)
        self.setMinimumWidth(0)
        self.setMinimumHeight(0)

        # Set window icon
        # Icon is now in the root directory (two levels up from ui/)
        icon_path = os.path.join(os.path.dirname(__file__), "..", "..", "charon_icon.png")
        if os.path.exists(icon_path):
            icon = QtGui.QIcon(icon_path)
            self.setWindowIcon(icon)
            # On macOS, also set the application icon
            if sys.platform == "darwin":
                app = QtWidgets.QApplication.instance()
                if app:
                    app.setWindowIcon(icon)

        if self._startup_mode_pending:
            self.apply_startup_mode(self._startup_mode_pending)

    def apply_startup_mode(self, mode: Optional[str] = None):
        mode = (mode or "normal").lower()
        self._startup_mode_pending = mode
        if mode == "tiny" and hasattr(self, "enter_tiny_mode"):
            self.enter_tiny_mode()

    def mark_tiny_offset_dirty(self) -> None:
        """Ensure the next tiny-mode entry uses default offsets."""
        self._use_tiny_offset_defaults_once = True
        self.tiny_mode_geometry = None

    def _get_tiny_mode_default_offset(self) -> Tuple[int, int]:
        """Return configured default X/Y offsets for tiny mode."""
        manager = getattr(self, "keybind_manager", None)
        if manager is None:
            return 0, 0

        def _coerce(value):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                return 0

        raw_x = manager.get_app_setting("tiny_offset_x") if hasattr(manager, "get_app_setting") else None
        raw_y = manager.get_app_setting("tiny_offset_y") if hasattr(manager, "get_app_setting") else None
        return _coerce(raw_x), _coerce(raw_y)

    def get_current_tiny_mode_offset(self) -> Optional[Tuple[int, int]]:
        """Return the current tiny-mode offset relative to the default center."""
        if not getattr(self.keybind_manager, 'tiny_mode_active', False):
            return None

        handle = self.windowHandle() if hasattr(self, 'windowHandle') else None
        screen_geom = None
        if handle is not None:
            try:
                screen_obj = handle.screen()
                if screen_obj:
                    screen_geom = screen_obj.geometry()
            except Exception:
                screen_geom = None
        if screen_geom is None:
            if hasattr(QtWidgets.QApplication, 'primaryScreen'):
                primary = QtWidgets.QApplication.primaryScreen()
                screen_geom = primary.geometry() if primary else None
            else:
                primary = QtGui.QGuiApplication.primaryScreen()
                screen_geom = primary.geometry() if primary else None
        if screen_geom is None:
            return None

        base_x = (screen_geom.width() - self.width()) // 2
        base_y = (screen_geom.height() - self.height()) // 2
        current_pos = self.pos()
        offset_x = current_pos.x() - base_x
        offset_y = current_pos.y() - base_y
        return int(offset_x), int(offset_y)

    def refresh(self):
        """Refresh the UI completely - useful for panel instances"""
        # Update title to show current host
        self.setWindowTitle(f"Charon ({self.host})")
        
        # Make sure folder panel is refreshed
        self.refresh_folder_panel()
        
        # Register hotkeys again
        self.register_hotkeys()
    
    def _refresh_everything(self):
        """Refresh everything - folders and all caches."""
        # Clear all caches
        from ..metadata_manager import clear_metadata_cache
        clear_metadata_cache()
        
        # Clear the entire persistent cache for the current base
        from ..cache_manager import get_cache_manager
        cache_manager = get_cache_manager()
        
        # Clear the cached folder list for the current base
        if self.current_base:
            folder_list_cache_key = f"folders:{self.current_base}"
            if folder_list_cache_key in cache_manager.general_cache:
                del cache_manager.general_cache[folder_list_cache_key]
                system_debug(f"Cleared folder list cache for {self.current_base}")
        
        # Invalidate all folders in the current base
        if self.current_base and os.path.exists(self.current_base):
            try:
                with os.scandir(self.current_base) as entries:
                    for entry in entries:
                        if entry.is_dir():
                            cache_manager.invalidate_folder(entry.path)
            except Exception as e:
                system_error(f"Error clearing cache: {e}")
        
        # Store current selection
        current_folder = self.folder_panel.get_selected_folder()
        
        # Refresh the folder panel (this will reload all folders from disk)
        self.refresh_folder_panel()
        
        # Queue all folders for background prefetching
        if self.current_base and config.CACHE_PREFETCH_ALL_FOLDERS:
            cache_manager.queue_all_folders_prefetch(self.current_base, self.host)
            system_debug("Started background prefetching of all folders")
        
        # Restore selection if possible
        if current_folder:
            # Use a timer to restore selection after folder loading completes
            def restore_selection():
                self.folder_panel.select_folder(current_folder)
            QtCore.QTimer.singleShot(100, restore_selection)
    
    def _cleanup_missing_script_hotkeys(self, show_dialog=False):
        """
        Clean up hotkeys for scripts that no longer exist.
        
        Args:
            show_dialog: If True, print the list of removed scripts
        """
        system_debug(f"Cleaning up missing script hotkeys for host={self.host}, show_dialog={show_dialog}")
        missing_scripts = user_settings_db.cleanup_missing_scripts(self.host)
        system_debug(f"Found {len(missing_scripts)} missing scripts: {missing_scripts}")
        
        if missing_scripts:
            if show_dialog:
                # Print to console instead of showing dialog
                script_names = [os.path.basename(path) for path in missing_scripts]
                system_info(f"Removed hotkeys for missing scripts:\n  {', '.join(script_names)}")
            else:
                # On refresh, also show script names
                script_names = [os.path.basename(path) for path in missing_scripts]
                system_info(f"Removed hotkeys for {len(missing_scripts)} missing scripts: {', '.join(script_names)}")
        return missing_scripts

    def _list_active_charonops(self):
        try:
            import nuke  # type: ignore
        except ImportError:
            return []

        try:
            all_nodes = nuke.allNodes(recurse=True)
        except Exception:
            all_nodes = []

        active = []
        for node in all_nodes:
            try:
                status_knob = node.knob("charon_status")
            except Exception:
                status_knob = None
            if status_knob is None:
                continue
            try:
                status_value = status_knob.value()
            except Exception:
                status_value = ""
            normalized = str(status_value or "").strip().lower()
            if not normalized:
                continue
            if normalized in {"ready", "completed", "complete", "error", "failed"}:
                continue
            active.append(node)
        return active

    def closeEvent(self, event):
        """Clean up background threads and stream patches when window is closed."""
        active_nodes = self._list_active_charonops()
        if active_nodes:
            node_names = ", ".join(node.name() for node in active_nodes[:5])
            if len(active_nodes) > 5:
                node_names += "..."
            message = (
                "CharonOp processing is still running.\n\n"
                f"Active nodes: {node_names}\n\n"
                "Are you sure you want to close Charon?"
            )
            reply = QtWidgets.QMessageBox.question(
                self,
                "CharonOps Processing",
                message,
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if reply != QtWidgets.QMessageBox.Yes:
                event.ignore()
                return

        if hasattr(self, 'script_panel') and hasattr(self.script_panel, 'folder_loader'):
            self.script_panel.folder_loader.stop_loading()
        if hasattr(self, 'global_indexer'):
            self.global_indexer.stop_loading()
        if hasattr(self, 'folder_list_loader'):
            self.folder_list_loader.stop_loading()
        
        # Stop cache stats timer
        if hasattr(self, 'cache_stats_timer'):
            self.cache_stats_timer.stop()
        
        # Shutdown cache manager
        from ..cache_manager import shutdown_cache_manager
        shutdown_cache_manager()
        if hasattr(self, 'bookmark_loader'):
            self.bookmark_loader.stop_loading()
        
        # Clean up the execution engine to restore stdout/stderr
        if hasattr(self, 'execution_engine'):
            # Clean up the background executor to restore stdout/stderr
            if hasattr(self.execution_engine, 'background_executor'):
                self.execution_engine.background_executor.cleanup()
            
        super().closeEvent(event)

    def setup_ui(self):
        # Create stacked widget as the main container
        self.stacked_widget = QtWidgets.QStackedWidget(self)
        
        # Create normal mode widget
        self.normal_widget = QtWidgets.QWidget()
        self._setup_normal_ui(self.normal_widget)
        
        # Create tiny mode widget
        self.tiny_mode_widget = TinyModeWidget()
        
        # Add both to stacked widget
        self.stacked_widget.addWidget(self.normal_widget)
        self.stacked_widget.addWidget(self.tiny_mode_widget)
        
        # Main layout just contains the stacked widget
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.stacked_widget)
        
        # Start in normal mode
        self.stacked_widget.setCurrentWidget(self.normal_widget)
        
        # Setup shared components and initialization after UI is created
        self._setup_shared_components()

    def _on_comfy_client_changed(self, client):
        """Store the active ComfyUI client exposed by the connection widget."""
        self.comfy_client = client
        if client:
            system_debug("ComfyUI client updated for CharonWindow")
        else:
            system_debug("ComfyUI client cleared for CharonWindow")

    def _update_banner_pixmap(self):
        if not self.banner_label or self._banner_base_pixmap is None:
            return
        margin = getattr(config, "UI_WINDOW_MARGINS", 0)
        available_width = max(1, self.normal_widget.width() - (margin * 2))
        if available_width <= 0:
            return

        base = self._banner_base_pixmap
        target_height = self._banner_target_height or base.height()

        if available_width < base.width():
            pixmap = base.scaled(
                available_width,
                target_height,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            self.banner_label.setPixmap(pixmap)
            banner_height = pixmap.height()
        else:
            # Avoid expanding the pixmap beyond its native width so layouts can still shrink later
            self.banner_label.setPixmap(base)
            banner_height = base.height()
        self.banner_label.setFixedHeight(banner_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_banner_pixmap()

    def _setup_normal_ui(self, parent):
        """Setup the normal mode UI."""
        # Use a QVBoxLayout with minimal margins
        main_layout = QtWidgets.QVBoxLayout(parent)
        main_layout.setContentsMargins(config.UI_WINDOW_MARGINS, config.UI_WINDOW_MARGINS, 
                                      config.UI_WINDOW_MARGINS, config.UI_WINDOW_MARGINS)
        main_layout.setSpacing(config.UI_ELEMENT_SPACING)

        self.banner_label = None
        if BANNER_IMAGE_PATH.exists():
            banner_pixmap = QtGui.QPixmap(str(BANNER_IMAGE_PATH))
            if not banner_pixmap.isNull():
                if banner_pixmap.height() > BANNER_MAX_HEIGHT:
                    banner_pixmap = banner_pixmap.scaledToHeight(
                        BANNER_MAX_HEIGHT,
                        QtCore.Qt.TransformationMode.SmoothTransformation,
                    )
                self.banner_label = QtWidgets.QLabel()
                self.banner_label.setObjectName("CharonBanner")
                self.banner_label.setAlignment(Qt.AlignCenter)
                self.banner_label.setContentsMargins(0, 0, 0, 0)
                self.banner_label.setStyleSheet("background-color: #000;")
                self.banner_label.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
                self.banner_label.setMinimumSize(0, 0)
                self._banner_base_pixmap = banner_pixmap
                self._banner_target_height = banner_pixmap.height()
                self.banner_label.setFixedHeight(self._banner_target_height)
                self._update_banner_pixmap()
                main_layout.addWidget(self.banner_label)
                QtCore.QTimer.singleShot(0, self._update_banner_pixmap)

        # Add spacing before separator
        main_layout.addSpacing(config.UI_ELEMENT_SPACING)
        
        # Add horizontal separator
        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        separator.setStyleSheet("QFrame { color: palette(mid); }")
        main_layout.addWidget(separator)
        
        # Add spacing after separator
        main_layout.addSpacing(config.UI_ELEMENT_SPACING)
        
        # Main content layout
        content_layout = QtWidgets.QVBoxLayout()
        content_layout.setContentsMargins(4, 4, 4, 4)  # Small margins
        content_layout.setSpacing(2)  # Minimal spacing
        
        # Main horizontal splitter: folder panel, center panel, and history panel
        self.main_splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.main_splitter.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        
        # Center panel - horizontal layout for tag bar and script panel
        center_widget = QtWidgets.QWidget()
        center_widget.setMinimumWidth(0)  # Remove any minimum width
        center_layout = QtWidgets.QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(2)

        self.center_tab_widget = QtWidgets.QTabWidget(center_widget)
        self.center_tab_widget.setDocumentMode(True)
        self._install_tab_corner_controls()
        center_layout.addWidget(self.center_tab_widget)

        workflows_container = QtWidgets.QWidget()
        workflows_layout = QtWidgets.QHBoxLayout(workflows_container)
        workflows_layout.setContentsMargins(0, 5, 0, 0)
        workflows_layout.setSpacing(0)

        self.workflows_splitter = QtWidgets.QSplitter(Qt.Horizontal, workflows_container)
        self.workflows_splitter.setChildrenCollapsible(False)
        self.workflows_splitter.setHandleWidth(6)
        workflows_layout.addWidget(self.workflows_splitter)

        # Folder panel
        self.folder_panel = FolderPanel()
        self.folder_panel.set_host(self.host)
        self.folder_panel.set_base_path(self.global_path)
        self.folder_panel.folder_selected.connect(self.on_folder_selected)
        self.folder_panel.folder_deselected.connect(self.on_folder_deselected)
        self.folder_panel.open_folder_requested.connect(self.open_folder_from_context)
        self.folder_panel.create_script_requested.connect(self.on_create_script_in_folder)
        self.folder_panel.collapse_requested.connect(self._collapse_folders_panel)
        if hasattr(self.folder_panel, 'navigate_right'):
            self.folder_panel.navigate_right.connect(self._focus_first_script_via_keyboard)
        self.folder_panel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.workflows_splitter.addWidget(self.folder_panel)

        workflow_area = QtWidgets.QWidget()
        workflow_area_layout = QtWidgets.QHBoxLayout(workflow_area)
        workflow_area_layout.setContentsMargins(0, 0, 0, 0)
        workflow_area_layout.setSpacing(2)
        self.workflows_splitter.addWidget(workflow_area)

        # Create tag bar
        self.tag_bar = TagBar()
        self.tag_bar.tags_changed.connect(self.on_tags_changed)
        workflow_area_layout.addWidget(self.tag_bar)

        # Script panel
        self.script_panel = ScriptPanel()
        self.script_panel.set_host(self.host)
        self.script_panel.script_deselected.connect(self.on_script_deselected)
        self.script_panel.bookmark_requested.connect(self.on_bookmark_requested)
        self.script_panel.assign_hotkey_requested.connect(self.on_assign_hotkey_requested)
        
        # Get reference to the metadata panel now that it's inside script panel
        self.metadata_panel = self.script_panel.metadata_panel
        
        # Connect granular signals for efficient updates
        self.metadata_panel.entry_changed.connect(self._on_entry_changed)
        self.metadata_panel.tags_updated.connect(self._on_tags_updated)
        
        # Keep general signal for backward compatibility and complex changes
        self.metadata_panel.metadata_changed.connect(self.on_metadata_changed)
        # Note: We don't connect to refresh_current_folder because on_metadata_changed
        # already calls _perform_soft_refresh which properly preserves selection
        self.metadata_panel.script_created.connect(self._navigate_to_script)
        self.script_panel.create_metadata_requested.connect(self.on_create_metadata_requested)
        self.script_panel.edit_metadata_requested.connect(self.on_edit_metadata_requested)
        self.script_panel.manage_tags_requested.connect(self.on_manage_tags_requested)
        self.script_panel.script_view.openFolderRequested.connect(self.open_folder)
        self.script_panel.script_run.connect(self.execute_script) # Connect the run signal
        
        # Connect panel open requests
        self.script_panel.open_folders_panel_requested.connect(self._open_folders_panel)
        self.script_panel.open_history_panel_requested.connect(self._open_history_panel)
        
        # IMPORTANT: Connect to folder loader to update tags when scripts are loaded
        # This connection must be made AFTER script_panel is fully initialized
        # and must use Qt.UniqueConnection to avoid duplicate connections
        self.script_panel.folder_loader.scripts_loaded.connect(
            self._on_folder_scripts_loaded,
            UniqueConnection
        )
        # Keyboard navigation from script list back to folder list
        if hasattr(self.script_panel, 'navigate_left'):
            self.script_panel.navigate_left.connect(self._focus_folder_via_keyboard)
        # Set script panel to expand
        self.script_panel.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        workflow_area_layout.addWidget(self.script_panel, 1)  # Add stretch factor

        self.center_tab_widget.addTab(workflows_container, "Workflows")

        self.charon_board_panel = CharonBoardPanel()
        self.center_tab_widget.addTab(self.charon_board_panel, "CharonBoard")

        # Set center widget to expand vertically
        center_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.main_splitter.addWidget(center_widget)
        
        # Execution history panel (right)
        self.execution_history_panel = ExecutionHistoryPanel()
        # Set history panel to expand vertically
        self.execution_history_panel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Expanding)
        self.execution_history_panel.collapse_requested.connect(self._collapse_history_panel)
        self.main_splitter.addWidget(self.execution_history_panel)

        # Enable horizontal collapsible panels
        self.main_splitter.setCollapsible(0, False)  # Center panel - always visible
        self.main_splitter.setCollapsible(1, True)   # History panel (right) - collapsible
        
        # Remove minimum sizes to allow full flexibility
        self.folder_panel.setMinimumWidth(0)
        self.execution_history_panel.setMinimumWidth(0)
        
        # Make splitter handles more tactile (thicker and easier to grab)
        self.main_splitter.setHandleWidth(8)  # Default is usually 3-4px
        
        # Style the splitter handles - blend with theme, subtle press feedback
        # Get theme-appropriate colors from the current palette
        window_color = self.palette().color(self.palette().Window)
        selection_color = self.palette().color(self.palette().Highlight)
        
        # Create theme-aware stylesheet with press feedback
        self.main_splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {window_color.name()};
                border: none;
            }}
            QSplitter::handle:pressed {{
                background-color: {selection_color.name()};
            }}
        """)
        
        # Set the width ratio for center/history (history collapsed by default)
        total_width = config.WINDOW_WIDTH - 50  # Subtract some padding
        center_width = int(total_width * (config.UI_FOLDER_PANEL_RATIO + config.UI_CENTER_PANEL_RATIO))
        history_width = 0  # Start with history panel collapsed
        self.main_splitter.setSizes([center_width, history_width])

        # Configure splitter inside Workflows tab (folders + workflows)
        workflow_total = max(center_width, 600)
        folder_width = int(workflow_total * config.UI_FOLDER_PANEL_RATIO)
        workflow_content_width = max(workflow_total - folder_width, 400)
        self.workflows_splitter.setSizes([folder_width, workflow_content_width])
        
        # Connect to splitter movement to detect when panels are collapsed
        self.main_splitter.splitterMoved.connect(self._on_main_splitter_moved)
        self.workflows_splitter.splitterMoved.connect(self._on_workflows_splitter_moved)
        
        # Check initial state
        QtCore.QTimer.singleShot(0, lambda: self._on_main_splitter_moved(0, 0))
        QtCore.QTimer.singleShot(0, lambda: self._on_workflows_splitter_moved(0, 0))

        # Add the splitter to fill most of the space
        content_layout.addWidget(self.main_splitter, 1)  # Add with stretch factor = 1

        # Remove the old 'Run Script' button and its layout
        # The functionality is now handled by the RunButtonDelegate

        # Add content layout to main layout
        main_layout.addLayout(content_layout)

        # Add spacing to separate content from footer controls
        main_layout.addSpacing(config.UI_ELEMENT_SPACING)

        # Bottom footer with ComfyUI controls aligned to the right
        footer_layout = QtWidgets.QHBoxLayout()
        footer_layout.setContentsMargins(4, 0, 4, 4)

        self.project_label = QtWidgets.QLabel(parent)
        self.project_label.setObjectName("charonProjectLabel")
        self.project_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.project_label.setWordWrap(False)
        self.project_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self.project_label.setMinimumWidth(280)
        footer_layout.addWidget(self.project_label, 1)

        footer_layout.addStretch()
        self.comfy_connection_widget = ComfyConnectionWidget(parent)
        self.comfy_connection_widget.client_changed.connect(self._on_comfy_client_changed)
        footer_layout.addWidget(self.comfy_connection_widget)
        main_layout.addLayout(footer_layout)
        self._refresh_project_display()

        # Initialize and populate folders
        self.current_base = self.global_path
        self.refresh_folder_panel()
        
        # Auto-select Bookmarks folder on startup if user has bookmarks
        self._auto_select_bookmarks_on_startup()
    
    def _install_tab_corner_controls(self):
        """Attach Refresh and Settings buttons to the tab bar corner."""
        corner_container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(corner_container)
        layout.setContentsMargins(0, 2, 4, 2)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignVCenter)

        self.refresh_btn = QtWidgets.QPushButton("Refresh")
        self.refresh_btn.setToolTip("Refresh metadata and re-index quick search (Ctrl+R)")
        self.refresh_btn.setMaximumWidth(config.UI_BUTTON_WIDTH)
        self.refresh_btn.clicked.connect(self.on_refresh_clicked)
        layout.addWidget(self.refresh_btn)

        self.settings_btn = QtWidgets.QPushButton("Settings")
        self.settings_btn.setToolTip("Configure keybinds and preferences")
        self.settings_btn.setMaximumWidth(config.UI_BUTTON_WIDTH)
        self.settings_btn.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_btn)

        corner_container.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        self.center_tab_widget.setCornerWidget(corner_container, Qt.TopRightCorner)

        # Update cache stats on a timer so tooltip reflects current values
        self.cache_stats_timer = QtCore.QTimer()
        self.cache_stats_timer.timeout.connect(self.update_cache_stats)
        self.cache_stats_timer.start(5000)  # Update every 5 seconds
        QtCore.QTimer.singleShot(0, self.update_cache_stats)

    def _setup_shared_components(self):
        """Setup components shared between normal and command mode."""
        # Share the execution history model with tiny mode
        self.tiny_mode_widget.set_execution_history_model(
            self.execution_history_panel.history_model
        )
        
        # Share execution panel state so dialogs are tracked across both panels
        self.tiny_mode_widget.share_execution_panel_state(
            self.execution_history_panel
        )

        # Ensure project details stay updated after shared components load
        self._refresh_project_display()
        
        # Connect tiny mode signals
        self.tiny_mode_widget.exit_tiny_mode.connect(self.exit_tiny_mode)
        self.tiny_mode_widget.open_settings.connect(self.open_settings)
        
        # ---------- quick search (TAB) setup ----------
        self._script_index = []
        self._index_lock = threading.Lock()
        self._index_dirty = True  # Start with a dirty index

        self.global_indexer = GlobalIndexLoader(self)
        self.global_indexer.index_loaded.connect(self._on_index_loaded)
        self._start_async_indexing()
        
        # Initialize keybind manager
        from .keybinds import KeybindManager
        self.keybind_manager = KeybindManager(self, self.host)
        
        # Connect keybind manager signals
        self.keybind_manager.keybind_triggered.connect(self._on_keybind_triggered)
        
        # Register local keybind handlers
        self._setup_local_keybind_handlers()
        
        # Store original window geometry
        self.normal_mode_geometry = None
        self.tiny_mode_geometry = None
        self._use_tiny_offset_defaults_once = False

    # -------------------------------------------------
    # Keybind handling
    # -------------------------------------------------
    
    def _setup_local_keybind_handlers(self):
        """Set up handlers for local keybinds."""
        # Map action names to handler methods
        self.local_keybind_handlers = {
            'quick_search': self.open_quick_search,
            'run_script': self.run_script_from_shortcut,
            'refresh': self.on_refresh_clicked,
            'open_folder': self.open_folder,
            'settings': self.open_settings
        }

    def _refresh_project_display(self):
        """Update the footer label with project context derived from BUCK env vars."""
        label = getattr(self, "project_label", None)
        if label is None:
            return

        project_path = os.environ.get("BUCK_PROJECT_PATH", "").strip()
        if project_path:
            project_name = Path(project_path).name or project_path
            label.setText(f"Project: {project_name}")
            label.setToolTip(project_path)
            return

        work_root = os.environ.get("BUCK_WORK_ROOT", "").strip()
        if work_root:
            destination = os.path.join(work_root, "Work")
        else:
            destination = os.path.join(get_charon_temp_dir(), "results")
        destination = os.path.normpath(destination)
        label.setText(f"Project not Found, saving outputs to {destination}")
        label.setToolTip(destination)
    
    def _on_keybind_triggered(self, keybind_type: str, keybind_id: str):
        """Handle keybind trigger from keybind manager."""
        if keybind_type == 'local':
            # Handle tiny mode toggle
            if keybind_id == 'tiny_mode':
                # Toggle is already handled in keybind manager, we just need to switch UI
                if self.keybind_manager.tiny_mode_active:
                    self.enter_tiny_mode()
                else:
                    self.exit_tiny_mode()
                return
            
            # Handle other local keybinds
            handler = self.local_keybind_handlers.get(keybind_id)
            if handler:
                handler()
        elif keybind_type == 'global':
            # Handle global keybind (run script)
            self._run_script_by_path(keybind_id)
    
    def _run_script_by_path(self, script_path: str):
        """Run a script by its path (for global keybinds) - delegates to execute_script."""
        self.execute_script(script_path)
    
    # -------------------------------------------------
    # Command Mode
    # -------------------------------------------------
    
    def enter_tiny_mode(self):
        """Enter tiny mode UI."""
        # Update keybind manager state
        self.keybind_manager.set_tiny_mode(True)
        
        # Store current geometry
        self.normal_mode_geometry = self.saveGeometry()
        
        # Store current window flags
        self.normal_mode_flags = self.windowFlags()
        
        # Apply tiny mode window flags
        self._apply_tiny_mode_flags()
        
        # Set minimum size for tiny mode
        self.setMinimumSize(config.TINY_MODE_MIN_WIDTH, config.TINY_MODE_MIN_HEIGHT)
        
        # Load bookmarks for tiny mode
        from ..settings import user_settings_db
        bookmarks = user_settings_db.get_bookmarks()
        self.tiny_mode_widget.set_host(self.host)
        self.tiny_mode_widget.set_bookmarks(bookmarks)
        
        # Switch to tiny mode widget
        self.stacked_widget.setCurrentWidget(self.tiny_mode_widget)
        
        use_defaults = self._use_tiny_offset_defaults_once or not self.tiny_mode_geometry
        if not use_defaults and self.tiny_mode_geometry:
            # Restore previous tiny mode geometry
            self.restoreGeometry(self.tiny_mode_geometry)
        else:
            # Use configured defaults on first entry or after offset changes
            self._use_tiny_offset_defaults_once = False
            self.tiny_mode_geometry = None
            self.resize(config.TINY_MODE_WIDTH, config.TINY_MODE_HEIGHT)
            
            # Center on screen - PySide6 compatible
            screen_obj = None
            if hasattr(QtWidgets.QApplication, 'primaryScreen'):
                screen_obj = QtWidgets.QApplication.primaryScreen()
            if screen_obj is None:
                screen_obj = QtGui.QGuiApplication.primaryScreen()
            if screen_obj is not None:
                screen = screen_obj.geometry()
            else:
                screen = QtCore.QRect(0, 0, self.width(), self.height())
            x = (screen.width() - self.width()) // 2
            y = (screen.height() - self.height()) // 2
            offset_x, offset_y = self._get_tiny_mode_default_offset()
            self.move(x + offset_x, y + offset_y)
        
        # Update window title
        self.setWindowTitle("Charon - Tiny Mode")
    
    def exit_tiny_mode(self):
        """Exit tiny mode and return to normal UI."""
        # Update keybind manager state
        self.keybind_manager.set_tiny_mode(False)
        
        # Store tiny mode geometry
        self.tiny_mode_geometry = self.saveGeometry()
        
        # Restore normal window flags
        if hasattr(self, 'normal_mode_flags'):
            self.setWindowFlags(self.normal_mode_flags)
            self.show()  # Required after changing window flags
        
        # Restore normal minimum size
        self.setMinimumSize(0, 0)
        
        # Switch back to normal widget
        self.stacked_widget.setCurrentWidget(self.normal_widget)
        
        # Restore normal mode geometry
        if self.normal_mode_geometry:
            self.restoreGeometry(self.normal_mode_geometry)
        
        # Update window title
        self.setWindowTitle("Charon")
        
        # Focus the window after exiting command mode
        self.raise_()
        self.activateWindow()
        
        # Ensure keybind manager state is synced
        self.keybind_manager.tiny_mode_active = False
    
    def _apply_tiny_mode_flags(self):
        """Apply tiny mode specific window flags."""
        host_config = config.WINDOW_CONFIGS.get(self.host.lower(), config.DEFAULT_WINDOW_CONFIG)
        tiny_mode_flags = list(host_config.get("tiny_mode_flags", []))

        allow_on_top = True
        try:
            setting_value = self.keybind_manager.get_app_setting("always_on_top")
            if setting_value is None:
                setting_value = user_settings_db.get_app_setting_for_host("always_on_top", self.host)
            allow_on_top = (setting_value or "off").lower() == "on"
        except Exception as exc:
            system_warning(f"Failed to read always_on_top setting: {exc}")

        handle = self.windowHandle()
        if handle:
            for flag_str in tiny_mode_flags:
                attr_name = flag_str.replace("Qt.", "")
                if not hasattr(Qt, attr_name):
                    continue
                flag = getattr(Qt, attr_name)
                if attr_name == "WindowStaysOnTopHint":
                    handle.setFlag(flag, allow_on_top)
                else:
                    handle.setFlag(flag, True)
            handle.setFlag(Qt.WindowStaysOnTopHint, allow_on_top)
            handle.setFlags(handle.flags())
        else:
            for flag_str in tiny_mode_flags:
                attr_name = flag_str.replace("Qt.", "")
                if not hasattr(Qt, attr_name):
                    continue
                flag = getattr(Qt, attr_name)
                if attr_name == "WindowStaysOnTopHint":
                    self.setWindowFlag(flag, allow_on_top)
                else:
                    self.setWindowFlag(flag, True)
            self.setWindowFlag(Qt.WindowStaysOnTopHint, allow_on_top)
            if self.isVisible():
                self.show()

        if self.isVisible():
            self.raise_()
            self.activateWindow()
    
    # -------------------------------------------------
    # Keyboard navigation helper methods
    # -------------------------------------------------

    def _focus_first_script_via_keyboard(self):
        """Select first script in current folder and move focus to script list."""
        # If scripts already loaded, focus immediately
        if self.script_panel.focus_first_script():
            return

        # Only connect handler if scripts are actually loading
        if self.script_panel._loading:
            # Wait for loader to finish then focus
            def _on_loaded(scripts):
                self.script_panel.focus_first_script()
                try:
                    self.script_panel.folder_loader.scripts_loaded.disconnect(_on_loaded)
                except Exception:
                    pass

            self.script_panel.folder_loader.scripts_loaded.connect(_on_loaded)

    def _focus_folder_via_keyboard(self):
        """Deselect script list and return focus to folder list."""
        try:
            # Clear the visual selection
            self.script_panel.script_view.clearSelection()
            # Clear the current index to ensure get_selected_script() returns None
            self.script_panel.script_view.setCurrentIndex(QtCore.QModelIndex())
            # Reset the script panel's internal state
            self.script_panel.current_script = None
            # Call the script panel's deselection method to hide metadata panel
            self.script_panel.on_script_deselected()
        except Exception:
            pass
        self.on_script_deselected()
        self.folder_panel.folder_view.setFocus()



    def refresh_folder_panel(self):
        """Refresh the folder panel with the current base path (global path)."""
        if not self.current_base or not os.path.exists(self.current_base):
            system_warning(f"Current base path does not exist: {self.current_base}")
            return

        # The script panel will handle clearing the metadata panel
        
        # Clear script panel
        self.script_panel.clear_scripts()

        # Invalidate cached folder listing so new directories appear immediately
        cache_manager = get_cache_manager()
        cache_manager.invalidate_cached_data(f"folders:{self.current_base}")

        # Start async folder loading
        self.folder_list_loader.load_folders(
            self.current_base,
            host=self.host,
            check_compatibility=True  # Load compatibility in background
        )
    
    def _on_folders_loaded(self, folders):
        """Handle loaded folders from async loader."""
        user_slug = get_current_user_slug()
        user_dir_exists = False
        if user_slug and self.current_base and os.path.isdir(self.current_base):
            user_dir = os.path.join(self.current_base, user_slug)
            user_dir_exists = os.path.isdir(user_dir)

        display_folders = []

        try:
            from ..settings import user_settings_db
            bookmarks = user_settings_db.get_bookmarks()
            if bookmarks:
                display_folders.append("Bookmarks")
        except Exception as e:
            system_error(f"Error checking bookmarks: {str(e)}")

        normal_folders = {
            name for name in folders if name and (not user_slug or name.lower() != user_slug)
        }
        if user_slug and user_dir_exists:
            normal_folders.add(user_slug)

        display_folders.extend(sorted(normal_folders, key=str.lower))

        # Update folder panel
        self.folder_panel.update_folders(display_folders)

        # Prefer selecting the user's folder if nothing is selected yet
        if not self.folder_panel.get_selected_folder() and user_slug and user_dir_exists:
            if any(name.lower() == user_slug for name in display_folders):
                self.folder_panel.select_folder(user_slug)
                return

        # Check if we need to auto-select bookmarks on startup
        if hasattr(self, '_auto_select_bookmarks_pending') and self._auto_select_bookmarks_pending:
            self._auto_select_bookmarks_pending = False  # Clear the flag
            if not self.folder_panel.get_selected_folder():  # Only if nothing is selected yet
                # Now that folders are loaded, we can safely select Bookmarks
                self.folder_panel.select_folder("Bookmarks")

    def _on_compatibility_loaded(self, compatibility_map):
        """Handle compatibility data loaded in background."""
        # This arrives after folders are displayed, update visual state
        # The folder model will use this for coloring
        # For now, just trigger a refresh of the folder view
        if hasattr(self.folder_panel.folder_model, 'layoutChanged'):
            self.folder_panel.folder_model.layoutChanged.emit()

    def on_folder_selected(self, folder_name):
        if not folder_name:
            return
        
        # Skip deselection if we're navigating programmatically
        if not self._is_navigating:
            # Always clear current script selection and hide metadata panel when changing folders
            # This includes re-selecting the same folder
            if self.script_panel.current_script:
                self.script_panel.on_script_deselected()
        
        # Don't clear cache during normal folder switching - this was causing slowdown
        # Cache will be populated as needed when scripts are loaded
        
        # Store current folder
        self._last_selected_folder = folder_name
        
        # Clear tag filter when changing folders
        self.tag_bar.clear_selection()
        # Clear existing tags - they'll be repopulated when scripts load
        self.tag_bar.update_tags([])
        
        # Check if this is the special Bookmarks folder
        if folder_name == "Bookmarks":
            # Handle bookmarks folder
            # Clear current folder for bookmarks view
            self.current_folder = None
            
            # Load bookmarked scripts
            self.load_bookmarked_scripts()
            return
        
        folder_path = os.path.join(self.current_base, folder_name)
        
        # Track the current folder for efficient tag loading
        self.current_folder = folder_path
        
        if os.path.isdir(folder_path):
            # The script panel will handle clearing the metadata panel
            
            # NOTE: Don't clear cache during folder switching - this causes performance issues
            # The background loader will handle loading fresh data if needed
            # refresh_metadata("folder", folder_path=folder_path, clear_cache=True)
            
            # Load scripts in background thread for better responsiveness
            self.script_panel.load_scripts_for_folder(folder_path)

    def run_script_from_shortcut(self):
        """Wrapper to run script from shortcut, checking focus and button state."""
        # Only if the focused widget is part of our Charon widget
        focused_widget = QtWidgets.QApplication.focusWidget()
        if not focused_widget or not self.isAncestorOf(focused_widget):
            return

        # Get the currently selected script from the script panel
        selected_script = self.script_panel.get_selected_script()
        if selected_script:
            self.execute_script(selected_script.path)

    def execute_script(self, script_path):
        """Spawn or focus a CharonOp node for the given workflow."""
        if not script_path:
            return

        if hasattr(self.script_panel, 'flash_script_execution'):
            self.script_panel.flash_script_execution(script_path)

        if hasattr(self, 'script_panel') and self.script_panel:
            self.script_panel._handle_script_run_request(script_path)
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Unavailable",
                "Script panel is not ready; cannot spawn a CharonOp node."
            )

    def on_metadata_changed(self):
        """
        Handles all UI refresh logic when a script's metadata or hotkey changes.
        This is the authoritative refresh function.
        """
        # Mark quick-search index dirty and trigger a rebuild
        self._start_async_indexing()
        
        # Re-register all hotkeys from the database. This picks up any changes.
        self.register_hotkeys_silently()
        
        # Perform a soft refresh to update all UI elements, including folder visibility.
        self._perform_soft_refresh(refresh_folders=True)
    
    def _update_script_in_index(self, script_path: str):
        """Update a single script in the global index without rebuilding everything."""
        from ..charon_logger import system_debug
        
        # Check if we have an index
        with self._index_lock:
            if not hasattr(self, '_script_index') or self._script_index is None:
                # No index yet, trigger full rebuild
                self._start_async_indexing()
                return
            
            # Find and update the script in the index
            folder_name = os.path.basename(os.path.dirname(script_path))
            script_name = os.path.basename(script_path)
            display = f"{folder_name} > {script_name}"
            
            # Get fresh metadata
            from ..metadata_manager import get_charon_config
            metadata = get_charon_config(script_path)
            
            # Find existing entry
            updated = False
            for i, (old_display, old_path, old_metadata) in enumerate(self._script_index):
                if old_path == script_path:
                    # Update in place
                    self._script_index[i] = (display, script_path, metadata)
                    updated = True
                    system_debug(f"Updated script in quick search index: {script_path}")
                    break
            
            if not updated:
                # Script not in index, add it
                self._script_index.append((display, script_path, metadata))
                system_debug(f"Added script to quick search index: {script_path}")
    
    def _refresh_quick_search_index_for_folder(self, folder_path: str):
        """Refresh quick search index entries for all scripts in a folder."""
        from ..charon_logger import system_debug
        system_debug(f"Refreshing quick search index for folder: {folder_path}")
        
        # Get all scripts in the folder
        if hasattr(self.script_panel, 'script_model') and self.script_panel.script_model:
            for script in self.script_panel.script_model.scripts:
                self._update_script_in_index(script.path)
    
    def _is_tag_in_use(self, tag_name: str) -> bool:
        """Check if any script in the current folder still uses this tag."""
        from ..charon_logger import system_debug
        
        # First check the script model if available
        if hasattr(self.script_panel, 'script_model') and self.script_panel.script_model:
            for script in self.script_panel.script_model.scripts:
                if script.metadata and tag_name in script.metadata.get('tags', []):
                    system_debug(f"Tag '{tag_name}' still in use by {script.name}")
                    return True
        
        # Also check the cache for folder tags
        current_folder = self.folder_panel.get_selected_folder()
        if current_folder:
            # Try to get from cache first
            from ..metadata_manager import get_folder_tags
            from ..cache_manager import get_cache_manager
            
            cache_manager = get_cache_manager()
            
            # For special folders like Bookmarks, we need the actual folder path
            folder_path = None
            for row in range(self.folder_panel.folder_model.rowCount()):
                folder = self.folder_panel.folder_model.get_folder_at_row(row)
                if folder and hasattr(folder, 'name') and folder.name == current_folder:
                    folder_path = folder.path if hasattr(folder, 'path') else None
                    break
            
            if folder_path and os.path.exists(folder_path):
                # Check cache for folder tags
                cached_tags = cache_manager.get_cached_data('folder_tags', folder_path)
                if cached_tags and tag_name in cached_tags:
                    system_debug(f"Tag '{tag_name}' found in folder cache")
                    return True
        
        system_debug(f"Tag '{tag_name}' not in use, safe to remove")
        return False
    
    def _on_entry_changed(self, script_path: str, new_entry: str):
        """Handle entry file change for a single script."""
        from ..charon_logger import system_debug
        system_debug(f"Entry changed for {script_path}: {new_entry}")
        
        # Update the script in the model without full reload
        if hasattr(self.script_panel, 'script_model') and self.script_panel.script_model:
            updated = self.script_panel.script_model.update_single_script(script_path)
            if updated:
                # Invalidate just this script's validation cache
                from ..cache_manager import get_cache_manager
                cache_manager = get_cache_manager()
                cache_manager.invalidate_script_validation(script_path)
                
                # Update quick search index incrementally
                self._update_script_in_index(script_path)
                
                # Update metadata panel if it's showing this script
                if self.metadata_panel.script_folder == script_path:
                    self.metadata_panel.update_metadata(script_path)
                return
        
        # Fallback to full refresh if incremental update failed
        self.on_metadata_changed()
    
    def _on_tags_updated(self, script_path: str, added_tags: list, removed_tags: list):
        """Handle tag updates for a single script."""
        from ..charon_logger import system_debug
        system_debug(f"Tags updated for {script_path}: +{added_tags}, -{removed_tags}")
        
        # Update script in model
        if hasattr(self.script_panel, 'script_model') and self.script_panel.script_model:
            # Get current metadata to get all tags
            from ..metadata_manager import get_charon_config
            metadata = get_charon_config(script_path)
            if metadata:
                new_tags = metadata.get('tags', [])
                updated = self.script_panel.script_model.update_script_tags(script_path, new_tags)
                
                if updated:
                    # Update quick search index incrementally
                    self._update_script_in_index(script_path)
                    
                    # Update tag bar incrementally
                    for tag in added_tags:
                        self.tag_bar.add_tag(tag)
                    for tag in removed_tags:
                        # Only remove tag from bar if no scripts in folder use it
                        if not self._is_tag_in_use(tag):
                            self.tag_bar.remove_tag(tag)
                    return
        
        # Fallback to full refresh
        self.on_metadata_changed()

    def open_folder(self, path=None):
        """Open a folder. If no path provided, determine from current selection."""
        if path is None:
            # Ctrl+O logic - determine path from current selection
            folder_name = self.folder_panel.get_selected_folder()
            script_item = self.script_panel.get_selected_script()

            # Handle Bookmarks folder specially
            if folder_name == "Bookmarks":
                if script_item:
                    # For bookmarked scripts, open the script's actual folder
                    target_path = script_item.path
                else:
                    # If no script selected in bookmarks, open global path
                    target_path = self.global_path
            elif folder_name and script_item:
                target_path = os.path.join(self.global_path, folder_name, script_item.name)
            elif folder_name:
                target_path = os.path.join(self.global_path, folder_name)
            else:
                target_path = self.global_path
        else:
            # Context menu - use provided path directly
            target_path = path

        if not os.path.exists(target_path):
            target_path = self.global_path

        # Cross-platform file opening
        import platform
        import subprocess
        
        if platform.system() == "Windows":
            os.startfile(target_path)
        elif platform.system() == "Darwin":  # macOS
            subprocess.run(["open", target_path])
        else:  # Linux
            subprocess.run(["xdg-open", target_path])

    def register_hotkeys(self):
        """Register hotkeys and update UI"""
        try:
            # Use the new keybind manager to refresh all keybinds
            self.keybind_manager.refresh_keybinds()
            
            # Update UI if needed
            if (hasattr(self, 'metadata_panel') and 
                hasattr(self.metadata_panel, 'script_folder') and 
                self.metadata_panel.script_folder and 
                os.path.exists(self.metadata_panel.script_folder)):
                
                self.metadata_panel.update_metadata(self.metadata_panel.script_folder)
            
            # Process events to ensure UI updates
            QtWidgets.QApplication.processEvents()
            
        except Exception as e:
            # Log the error but don't show a popup
            system_error(f"Error in register_hotkeys: {str(e)}")

    def run_script_by_hotkey(self, script_folder):
        """Execute a script by hotkey - now delegates to _run_script_by_path."""
        # This method is kept for compatibility
        self._run_script_by_path(script_folder)

    def on_hotkey_changed(self, hotkey, script_path):
        """
        Handle a hotkey being changed. Use incremental update for better performance.
        """
        from ..charon_logger import system_debug
        system_debug(f"Hotkey changed for {script_path}: {hotkey}")
        
        # Update just this script in the model
        if hasattr(self.script_panel, 'script_model') and self.script_panel.script_model:
            updated = self.script_panel.script_model.update_single_script(script_path)
            if updated:
                # Update quick search index incrementally
                self._update_script_in_index(script_path)
                return
        
        # Fallback to full refresh if incremental update failed
        self.on_metadata_changed()

    def register_hotkeys_silently(self):
        """Register hotkeys without updating the UI - now delegates to keybind manager"""
        # This method is kept for compatibility but now uses the keybind manager
        self.keybind_manager.refresh_keybinds()

    def _perform_soft_refresh(self, refresh_folders=False):
        """
        Performs a soft refresh of the UI, preserving the user's selection.

        This is used after an action (like bookmarking or setting a hotkey)
        that requires the UI to update but should not disrupt the user's flow.

        Args:
            refresh_folders (bool): If True, the folder list will also be
                                    refreshed. This is needed when an action
                                    might add or remove the 'Bookmarks' or 'Hotkeys' folder.
        """
        # 1. Preserve State
        current_folder_name = self.folder_panel.get_selected_folder()
        selected_script = self.script_panel.get_selected_script()
        current_script_path = selected_script.path if selected_script else None

        # 2. Check if folder update is actually needed
        if refresh_folders:
            from ..settings import user_settings_db
            bookmarks = user_settings_db.get_bookmarks()
            has_bookmarks = len(bookmarks) > 0
            
            # Check if Bookmarks folder is currently visible
            bookmarks_folder_visible = False
            for i in range(self.folder_panel.folder_model.rowCount()):
                folder = self.folder_panel.folder_model.get_folder_at_row(i)
                if folder and hasattr(folder, 'original_name'):
                    if folder.original_name == "Bookmarks":
                        bookmarks_folder_visible = True
            
            # Only update folders if the visibility state actually changed
            if has_bookmarks != bookmarks_folder_visible:
                if has_bookmarks and not bookmarks_folder_visible:
                    # Need to add Bookmarks folder
                    from ..folder_table_model import FolderItem
                    bookmarks_item = FolderItem("★ Bookmarks", "Bookmarks", is_special=True)
                    bookmarks_item.original_name = "Bookmarks"
                    self.folder_panel.folder_model.add_folder(bookmarks_item)
                elif not has_bookmarks and bookmarks_folder_visible:
                    # Need to remove Bookmarks folder
                    self.folder_panel.folder_model.remove_folder_by_name("Bookmarks")
                
                # Re-select the current folder if it still exists
                if current_folder_name:
                    self.folder_panel.select_folder(current_folder_name)
            else:
                # No folder refresh needed
                refresh_folders = False

        # 4. Refresh Script List with targeted metadata refresh
        # Determine the correct way to reload scripts based on the selected folder
        if current_folder_name == "Bookmarks":
            self.load_bookmarked_scripts()
        elif current_folder_name:
            folder_path = os.path.join(self.current_base, current_folder_name)
            # Don't refresh metadata during soft refresh - this was causing slowdown
            # Just reload the scripts normally
            self.script_panel.load_scripts_for_folder(folder_path)
        
        # The rest of the logic (re-selecting the script) will be handled
        # by a connection to the script_panel's scripts_loaded signal.
        def _after_scripts_loaded(scripts):
            if current_script_path:
                if self.script_panel.select_script(current_script_path):
                    # Get the actual corrected path for the metadata update
                    selected_script = self.script_panel.get_selected_script()
                    if selected_script:
                        # Get corrected path using the script panel's method
                        corrected_path = self.script_panel._get_corrected_script_path(selected_script)
                        # Force metadata panel update to ensure it shows with new tags
                        self.script_panel.metadata_panel.update_metadata(corrected_path)
                        self.script_panel.metadata_panel.setVisible(True)

            # 6. Disconnect the temporary signal handler
            try:
                self.script_panel.folder_loader.scripts_loaded.disconnect(_after_scripts_loaded)
            except (TypeError, RuntimeError):
                pass # May have already been disconnected or was never connected
            try:
                if hasattr(self, 'bookmark_loader'):
                    self.bookmark_loader.scripts_loaded.disconnect(_after_scripts_loaded)
            except (TypeError, RuntimeError):
                pass

        # Connect the temporary handler to the correct loader
        # Use Qt.UniqueConnection to prevent duplicate connections
        if current_folder_name == "Bookmarks" and hasattr(self, 'bookmark_loader'):
            self.bookmark_loader.scripts_loaded.connect(_after_scripts_loaded, QtCore.Qt.UniqueConnection)
        elif current_folder_name == "Hotkeys" and hasattr(self, 'hotkey_loader'):
            self.hotkey_loader.scripts_loaded.connect(_after_scripts_loaded, QtCore.Qt.UniqueConnection)
        elif current_folder_name:
            self.script_panel.folder_loader.scripts_loaded.connect(_after_scripts_loaded, QtCore.Qt.UniqueConnection)


    def on_folder_deselected(self):
        # Handle the event when a folder is deselected
        self.script_panel.clear_scripts()

    def on_script_deselected(self):
        # Handle the event when a script is deselected
        # The script panel now handles metadata panel visibility
        pass
    
    def on_tags_changed(self, active_tags):
        """Handle tag filter changes."""
        # Update script panel filter
        self.script_panel.set_tag_filter(active_tags)
    
    def _update_tags_from_scripts(self, scripts):
        """Extract unique tags from loaded scripts and update tag bar."""
        # If we have a current folder, use the cached folder tags for better performance
        if hasattr(self, 'current_folder') and self.current_folder:
            unique_tags = get_folder_tags(self.current_folder)
        else:
            # Fallback to extracting from scripts (for bookmarks view)
            all_tags = []
            for script in scripts:
                if hasattr(script, 'metadata') and script.metadata:
                    tags = script.metadata.get('tags', [])
                    if isinstance(tags, list):
                        all_tags.extend(tags)
            unique_tags = sorted(set(all_tags))
        
        # Update tag bar with unique tags
        self.tag_bar.update_tags(unique_tags)
    
    def _force_update_tag_bar(self):
        """Force update the tag bar with fresh folder tags and refresh script metadata."""
        if hasattr(self, 'current_folder') and self.current_folder:
            # Get fresh tags from folder
            unique_tags = get_folder_tags(self.current_folder)
            self.tag_bar.update_tags(unique_tags)
            
            # Also update the in-memory script metadata for proper filtering
            self._refresh_script_metadata()
    
    def _refresh_script_metadata(self):
        """Refresh the metadata of all loaded scripts to ensure tag filtering works correctly."""
        # Get ALL scripts from the script panel (not just the filtered ones)
        if not hasattr(self.script_panel, '_all_scripts'):
            return
            
        # Refresh metadata for each script in the full list
        for script in self.script_panel._all_scripts:
            if script and script.path:
                # Get fresh metadata from disk
                fresh_metadata = get_charon_config(script.path)
                if fresh_metadata:
                    # Update the script's in-memory metadata
                    script.metadata = fresh_metadata
        
        # Re-apply tag filter to update the view
        if hasattr(self.script_panel, '_apply_tag_filter'):
            self.script_panel._apply_tag_filter()
    
    def _has_valid_entry_file(self, script_path):
        """Check if script has a valid entry file (uses cached validation)"""
        from ..metadata_manager import get_charon_config
        from ..script_validator import ScriptValidator
        
        # Load metadata
        metadata = get_charon_config(script_path)
        has_entry, _ = ScriptValidator.has_valid_entry(script_path, metadata)
        return has_entry
    
    def on_assign_hotkey_requested(self, script_path):
        """Handle hotkey assignment from the right-click menu."""
        if not script_path:
            return

        # Get current hotkey for this script
        current_hotkey = user_settings_db.get_hotkey_for_script(script_path, self.host)
        
        if current_hotkey:
            # If a hotkey exists, remove it
            self.keybind_manager.remove_global_keybind(script_path)
            self.on_hotkey_changed("", script_path) # Notify system of change
        else:
            # If no hotkey, open dialog to capture one
            from .dialogs import HotkeyDialog
            dialog = HotkeyDialog(self)
            dialog.resize(300, 100)
            dialog.setWindowModality(WindowModal)
            if exec_dialog(dialog) == QtWidgets.QDialog.Accepted:
                new_hotkey = dialog.hotkey
                dialog.deleteLater()
                # Use keybind manager to add the global keybind
                if self.keybind_manager.add_global_keybind(script_path, new_hotkey):
                    self.on_hotkey_changed(new_hotkey, script_path)
            else:
                dialog.deleteLater()

    def _process_new_hotkey(self, script_path, new_hotkey, current_sw):
        """Process a new hotkey assignment - now handled by keybind manager."""
        # This method is kept for compatibility but functionality moved to keybind_manager
        pass
    
    def _check_hotkey_conflicts(self, hotkey, script_path, current_sw):
        """Check if hotkey is already taken - now handled by keybind manager."""
        # This method is kept for compatibility but functionality moved to keybind_manager
        return False

    def on_bookmark_requested(self, script_path):
        """Handle bookmark request from right-click context menu"""
        from ..settings import user_settings_db
        
        # Normalize the path before storing/checking
        normalized_path = os.path.normpath(script_path)
        
        # Check if already bookmarked
        if user_settings_db.is_bookmarked(normalized_path):
            user_settings_db.remove_bookmark(normalized_path)
        else:
            user_settings_db.add_bookmark(normalized_path)
        
        # Invalidate the script panel's cached bookmarks
        self.script_panel.invalidate_user_data_cache()
        
        # Perform a soft refresh to update the UI without losing position.
        # We refresh folders here because a bookmark change can affect
        # whether the 'Bookmarks' folder is visible.
        self._perform_soft_refresh(refresh_folders=True)

    def _get_actual_script_path(self, script_path):
        """Get the actual script path based on current base, handling path mismatches."""
        # If the script path already starts with current base, return it as-is
        if self.current_base and script_path.startswith(self.current_base):
            return script_path
            
        # Always reconstruct the path based on current base to avoid cached paths
        
        # First, try to extract the relative structure from the script path
        # Look for common base paths that might be in the script path
        # Get possible base paths from config
        from .. import config
        possible_bases = list(config.REPOSITORY_SEARCH_PATHS)
        
        # Also check the current global path's parent directory
        if self.global_path:
            possible_bases.append(os.path.dirname(self.global_path))
        
        relative_path = None
        for base in possible_bases:
            if base and script_path.startswith(base):
                # Extract the relative path after the base
                relative_path = os.path.relpath(script_path, base)
                break
        
        # If we couldn't extract a relative path, try to get it from folder structure
        if not relative_path:
            # Get the folder structure (e.g., "user/script_name" from full path)
            parts = script_path.replace('\\', '/').split('/')
            # Find "charon_repo" or similar base indicator
            for i, part in enumerate(parts):
                if part in ["charon_repo", "Charon_repo", "galt_repo", "Galt_repo", "CODE"]:
                    if i + 1 < len(parts):
                        relative_path = '/'.join(parts[i+1:])
                        break
        
        # If we still don't have a relative path, use just the last two parts
        if not relative_path:
            parts = script_path.replace('\\', '/').split('/')
            if len(parts) >= 2:
                relative_path = '/'.join(parts[-2:])  # e.g., "user/script_name"
            else:
                relative_path = parts[-1]  # Just the script name
        
        # Now reconstruct with current base
        if self.current_base:
            reconstructed_path = os.path.join(self.current_base, relative_path.replace('/', os.sep))
            system_debug(f"Reconstructed path: {script_path} -> {reconstructed_path}")
            return reconstructed_path
        else:
            # Fallback to original if no current base
            return script_path

    def on_create_metadata_requested(self, script_path):
        """Handle create metadata request from right-click context menu"""
        # Get the actual path based on current base
        actual_script_path = self._get_actual_script_path(script_path)
        # Update the metadata panel to show the script and trigger create metadata
        self.metadata_panel.update_metadata(actual_script_path)
        self.metadata_panel.create_metadata()

    def on_edit_metadata_requested(self, script_path):
        """Handle edit metadata request from right-click context menu"""
        actual_script_path = self._get_actual_script_path(script_path)
        self.metadata_panel.update_metadata(actual_script_path)
        self.metadata_panel.edit_metadata()
    
    def open_tag_manager(self, script_path):
        """Open tag manager dialog with consistent behavior from any access point."""
        # Debug logging
        system_debug(f"Opening tag manager for script: {script_path}")
        system_debug(f"Current base path: {self.current_base}")
        system_debug(f"Global path: {self.global_path}")
        
        # Get current folder path
        current_folder = self.folder_panel.get_selected_folder()
        if not current_folder:
            return
        
        # Get the actual script path based on current base
        actual_script_path = self._get_actual_script_path(script_path)
        
        # Get folder path
        if current_folder == "Bookmarks":
            # For bookmarked scripts, use the parent folder of the script
            folder_path = os.path.dirname(actual_script_path)
        else:
            folder_path = os.path.join(self.current_base, current_folder)
        
        system_debug(f"Reconstructed script path from {script_path} to {actual_script_path}")
        system_debug(f"Using folder path for tag manager: {folder_path}")
        system_debug(f"Script path for tag manager: {actual_script_path}")
            
        # Open tag manager dialog
        from .tag_manager_dialog import TagManagerDialog
        dialog = TagManagerDialog(actual_script_path, folder_path, parent=self)
        dialog.resize(200, 350)
        
        # Instead of directly connecting to refresh, use a delayed refresh
        # to ensure file system writes are complete and caches can be properly invalidated
        def delayed_refresh():
            # Cache invalidation is already done in TagManagerDialog._invalidate_folder_caches()
            # No need to do it again here
            
            # For tag changes, we only need to update the affected scripts
            # The tag bar has already been updated incrementally above
            from ..charon_logger import system_debug
            system_debug("Performing targeted refresh after tag changes")
            
            # Update only the specific script that was edited without full reload
            if hasattr(self.script_panel, 'script_model') and self.script_panel.script_model:
                # Re-read the metadata for just this script
                from ..metadata_manager import get_charon_config
                fresh_metadata = get_charon_config(actual_script_path)
                if fresh_metadata:
                    # Update just this script's tags in the model
                    updated = self.script_panel.script_model.update_script_tags(
                        actual_script_path, 
                        fresh_metadata.get('tags', [])
                    )
                    
                    if updated:
                        system_debug(f"Successfully updated tags for {actual_script_path}")
                        # Update the quick search index for just this script
                        self._update_script_in_index(actual_script_path)
                        
                        # Refresh the metadata panel to show the new tags
                        if (self.metadata_panel.script_folder and 
                            os.path.normpath(self.metadata_panel.script_folder) == os.path.normpath(actual_script_path)):
                            system_debug("Refreshing metadata panel to show updated tags")
                            self.metadata_panel.update_metadata(actual_script_path)
                    else:
                        system_debug(f"Failed to find script in model: {actual_script_path}")
                        # Fall back to refresh_tags_from_disk if update failed
                        system_debug("Falling back to refresh_tags_from_disk")
                        self.script_panel.script_model.refresh_tags_from_disk()
                        self._refresh_quick_search_index_for_folder(folder_path)
        
        # Connect detailed signal for incremental updates
        def handle_detailed_tag_changes(added_tags, removed_tags, renamed_tags):
            """Handle detailed tag changes for incremental updates."""
            from ..charon_logger import system_debug
            system_debug(f"Detailed tag changes - Added: {added_tags}, Removed: {removed_tags}, Renamed: {renamed_tags}")
            
            # Update tag bar incrementally
            for tag in added_tags:
                self.tag_bar.add_tag(tag)
            for tag in removed_tags:
                # For removed tags, we know they've been deleted from the current script
                # The delayed_refresh will update the model and then we can check properly
                # For now, keep the tag in the bar - it will be removed after refresh if needed
                system_debug(f"Tag '{tag}' removed from script, will check folder usage after refresh")
            for old_tag, new_tag in renamed_tags:
                self.tag_bar.update_tag_name(old_tag, new_tag)
                
            # Check if any tags were globally deleted (removed from ALL scripts)
            # This happens when user uses "Delete Tag" button in tag manager
            # In this case, we need to refresh all scripts, not just the current one
            global_delete = False
            if removed_tags:
                # If a tag was removed and dialog has a folder path, it's likely a global delete
                # Check if the tag exists in any script metadata after the operation
                from ..metadata_manager import get_charon_config
                tag_still_exists = False
                for tag in removed_tags:
                    try:
                        with os.scandir(folder_path) as entries:
                            for entry in entries:
                                if entry.is_dir():
                                    metadata = get_charon_config(entry.path)
                                    if metadata and tag in metadata.get('tags', []):
                                        tag_still_exists = True
                                        break
                            if tag_still_exists:
                                break
                    except:
                        pass
                    
                    if not tag_still_exists:
                        # Tag was globally deleted
                        global_delete = True
                        system_debug(f"Tag '{tag}' was globally deleted from all scripts")
            
            # Do appropriate refresh based on whether it's a global delete
            if global_delete:
                # For global deletes, we need to refresh all scripts
                def delayed_refresh_all():
                    system_debug("Performing full refresh after global tag deletion")
                    if hasattr(self.script_panel, 'script_model') and self.script_panel.script_model:
                        self.script_panel.script_model.refresh_tags_from_disk()
                        # After refresh, remove tags that are no longer in use
                        for tag in removed_tags:
                            if not self._is_tag_in_use(tag):
                                system_debug(f"Removing tag '{tag}' from bar - no longer in use")
                                self.tag_bar.remove_tag(tag)
                QtCore.QTimer.singleShot(100, delayed_refresh_all)
            else:
                # For single script changes, use targeted refresh
                QtCore.QTimer.singleShot(100, delayed_refresh)
        
        dialog.detailed_tags_changed.connect(handle_detailed_tag_changes)
        exec_dialog(dialog)  # Just show the dialog, no need to check result
    
    def on_manage_tags_requested(self, script_path):
        """Handle manage tags request from right-click context menu"""
        self.open_tag_manager(script_path)
    
    def load_bookmarked_scripts(self):
        """Load bookmarked scripts using the BookmarkLoader"""
        # Create bookmark loader if it doesn't exist
        if not hasattr(self, 'bookmark_loader'):
            from ..workflow_model import BookmarkLoader
            self.bookmark_loader = BookmarkLoader(self)
            self.bookmark_loader.scripts_loaded.connect(
                self.on_bookmarked_scripts_loaded,
                UniqueConnection
            )
        
        # Note: We no longer clear the entire cache for bookmarks
        # The bookmark loader will get fresh metadata as needed
        
        # Load bookmarked scripts, filtered by current base path
        base_path = self.current_base or config.WORKFLOW_REPOSITORY_ROOT
        self.bookmark_loader.load_bookmarks(self.host, base_path=base_path)
    
    def on_bookmarked_scripts_loaded(self, scripts):
        """Handle when bookmarked scripts are loaded"""
        # Clear parent folder for bookmark view
        self.script_panel.parent_folder = None
        # Update the script panel with bookmarked scripts
        self.script_panel.on_scripts_loaded(scripts)
        # Update tags from loaded scripts
        self._update_tags_from_scripts(scripts)
    
    
    def _start_async_indexing(self):
        """Start the background process to build the global script index."""
        with self._index_lock:
            self._index_dirty = True
        self.global_indexer.load_index(self.global_path)

    def _on_index_loaded(self, new_index):
        """Callback for when the global index has finished building."""
        with self._index_lock:
            self._script_index = new_index
            self._index_dirty = False
        # Only print in debug mode
        if config.DEBUG_MODE:
            system_info("Global script index has been rebuilt.")

    def open_quick_search(self):
        """Open quick search popup or close it if already open"""
        # Check if a quick search dialog is already open
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QuickSearchDialog) and widget.isVisible():
                # Close the existing dialog
                widget.close()
                return
        
        # In command mode, quick search is always available (global hotkey)
        # In normal mode, only if focused widget is part of Charon
        if not self.keybind_manager.tiny_mode_active:
            focused_widget = QtWidgets.QApplication.focusWidget()
            if not focused_widget or not self.isAncestorOf(focused_widget):
                return

        with self._index_lock:
            index_copy = self._script_index[:]
        
        # Show dialog with command mode flag
        dlg = QuickSearchDialog(
            index_copy, 
            parent=self, 
            host=self.host,
            tiny_mode=self.keybind_manager.tiny_mode_active
        )
        
        # Position the dialog
        if self.keybind_manager.tiny_mode_active:
            # Tiny mode - center on screen
            cursor_pos = QtGui.QCursor.pos()
            screen = QtWidgets.QApplication.screenAt(cursor_pos)
            if not screen:
                screen = QtWidgets.QApplication.primaryScreen()
            
            screen_geometry = screen.geometry()
            dialog_pos = screen_geometry.center() - dlg.rect().center()
            dlg.move(dialog_pos)
        else:
            # Normal mode - center on Charon window
            dlg.ensurePolished()
            
            # Get Charon window's absolute screen position
            charon_global_pos = self.mapToGlobal(QtCore.QPoint(0, 0))
            charon_rect = self.geometry()
            
            # Calculate center position in absolute screen coordinates
            center_x = charon_global_pos.x() + (charon_rect.width() - dlg.width()) // 2
            center_y = charon_global_pos.y() + (charon_rect.height() - dlg.height()) // 2
            
            # Move dialog to calculated position
            dlg.move(center_x, center_y)
        
        # Connect appropriate signal based on mode
        if self.keybind_manager.tiny_mode_active:
            dlg.script_executed.connect(self.execute_script)
        else:
            from ..charon_logger import system_debug
            system_debug("Connecting script_chosen signal to _navigate_to_script")
            dlg.script_chosen.connect(self._navigate_to_script)
            
        dlg.show()  # Modal dialog that can be closed with the same hotkey

    def _navigate_to_script(self, script_path):
        """Navigate UI to given script folder and select the script"""
        from ..charon_logger import system_debug, system_error
        system_debug(f"=== QUICK SEARCH NAVIGATION START ===")
        system_debug(f"Script path received: {script_path}")
        
        # Set navigation flag to prevent deselection
        self._is_navigating = True
        
        # Normalize the path
        script_path = os.path.normpath(script_path)
        
        if not os.path.exists(script_path):
            system_error(f"Path does not exist: {script_path}")
            self._is_navigating = False  # Clear flag on error
            return
        
        # Quick search passes the script folder path
        if not os.path.isdir(script_path):
            system_error(f"Expected directory path but got file: {script_path}")
            self._is_navigating = False  # Clear flag on error
            return
            
        # The script path is like: base_path/folder_name/script_name/
        # We need to extract the folder_name, not the script_name
        script_name = os.path.basename(script_path)
        parent_path = os.path.dirname(script_path)
        folder_name = os.path.basename(parent_path)
        
        system_debug(f"Script path structure:")
        system_debug(f"  Full path: {script_path}")
        system_debug(f"  Script name: {script_name}")
        system_debug(f"  Parent path: {parent_path}")
        system_debug(f"  Folder name: {folder_name}")
        
        # Make sure the folder panel is visible
        if self.folder_panel.isHidden():
            system_debug("Folder panel is hidden, showing it")
            self._toggle_folders_panel()
        def _locate_folder(target_name):
            """Return (found, row_index) for the requested folder."""
            for row in range(self.folder_panel.folder_model.rowCount()):
                folder = self.folder_panel.folder_model.get_folder_at_row(row)
                if not folder:
                    continue

                if hasattr(folder, 'name'):
                    folder_display_name = folder.name
                elif hasattr(folder, 'original_name'):
                    folder_display_name = folder.original_name
                else:
                    folder_display_name = str(folder)

                folder_full_path = folder.path if hasattr(folder, 'path') else ""
                system_debug(f"Row {row}: name='{folder_display_name}', path='{folder_full_path}'")

                if folder_display_name == target_name:
                    return True, row

                if folder_full_path and os.path.normpath(folder_full_path) == parent_path:
                    return True, row

            return False, -1

        # Get the folder list and find our target
        folder_found, target_row = _locate_folder(folder_name)

        if not folder_found:
            system_error(f"Could not find folder '{folder_name}' in folder list")
            self._is_navigating = False  # Clear flag on error
            return
        
        # Select the folder directly
        index = self.folder_panel.folder_model.index(target_row, 0)
        self.folder_panel.folder_view.setCurrentIndex(index)
        
        # Store script path in a way that persists across callbacks
        target_script_path = script_path
        
        # Connect directly to the scripts_loaded signal for instant response
        def on_scripts_loaded(scripts):
            system_debug(f"Scripts loaded signal received, {len(scripts)} scripts")
            # Disconnect immediately
            try:
                self.script_panel.folder_loader.scripts_loaded.disconnect(on_scripts_loaded)
            except:
                pass
            
            # Select the specific script immediately
            system_debug(f"Selecting specific script: {target_script_path}")
            if not self.script_panel.select_script(target_script_path):
                system_debug("Could not find exact script, selecting first")
                self.script_panel.focus_first_script()
            
            # Defer clearing the navigation flag and ensure selection persists
            # This ensures selection happens after all pending model/view updates
            def finalize_navigation():
                # Re-select the script to ensure it stays selected
                system_debug(f"Finalizing navigation, ensuring script selection: {target_script_path}")
                self.script_panel.select_script(target_script_path)
                self._is_navigating = False
                system_debug("Navigation complete, cleared _is_navigating flag")
            
            QtCore.QTimer.singleShot(0, finalize_navigation)
        
        # Connect to the scripts loaded signal BEFORE triggering folder selection
        self.script_panel.folder_loader.scripts_loaded.connect(on_scripts_loaded)
        
        # Trigger the selection - this should emit folder_selected signal
        system_debug(f"Triggering folder selection for row {target_row}")
        self.folder_panel.on_folder_selected(index)
        
        # Keep a shorter fallback in case the signal doesn't fire
        QtCore.QTimer.singleShot(200, lambda: self._fallback_navigation(folder_name, script_path))
        
        system_debug(f"=== QUICK SEARCH NAVIGATION END ===")
    
    def _fallback_navigation(self, folder_name, script_path):
        """Fallback navigation if the normal flow didn't work"""
        from ..charon_logger import system_debug
        # Check if we're already in the right folder
        if self.folder_panel.get_selected_folder() == folder_name:
            system_debug(f"Fallback: Already in folder {folder_name}, selecting script")
            if self.script_panel.script_model.rowCount() > 0:
                # Always try to select the specific script
                system_debug(f"Fallback: Selecting specific script {script_path}")
                if not self.script_panel.select_script(script_path):
                    self.script_panel.focus_first_script()
                
                # Defer to ensure selection persists
                def finalize_fallback():
                    self.script_panel.select_script(script_path)
                    self._is_navigating = False
                    system_debug("Fallback complete, cleared _is_navigating flag")
                
                QtCore.QTimer.singleShot(0, finalize_fallback)
            else:
                # No scripts loaded yet, just clear flag
                self._is_navigating = False
        else:
            system_debug(f"Fallback: Folder still not selected, trying select_folder")
            if self.folder_panel.select_folder(folder_name):
                # Connect to scripts_loaded signal for immediate response
                def on_scripts_loaded_fallback(scripts):
                    try:
                        self.script_panel.folder_loader.scripts_loaded.disconnect(on_scripts_loaded_fallback)
                    except:
                        pass
                    if not self.script_panel.select_script(script_path):
                        self.script_panel.focus_first_script()
                    
                    # Defer to ensure selection persists
                    def finalize_fallback_loaded():
                        self.script_panel.select_script(script_path)
                        self._is_navigating = False
                        system_debug("Fallback scripts loaded, cleared _is_navigating flag")
                    
                    QtCore.QTimer.singleShot(0, finalize_fallback_loaded)
                
                self.script_panel.folder_loader.scripts_loaded.connect(on_scripts_loaded_fallback)

    def _navigate_after_refresh(self, script_path, folder_name):
        """Navigate to script after folder panel refresh"""
        from ..charon_logger import system_debug
        system_debug(f"_navigate_after_refresh - folder_name: {folder_name}, script_path: {script_path}")
        
        # Try to select the folder
        if self.folder_panel.select_folder(folder_name):
            system_debug(f"Successfully selected folder: {folder_name}")
            # Give UI time to process the folder selection and load scripts
            QtCore.QTimer.singleShot(100, lambda: self._try_select_script(script_path))
        else:
            system_debug(f"Failed to select folder: {folder_name}")
    
    def _try_select_script(self, script_path):
        """Try to select the script after ensuring it's loaded"""
        if self.script_panel.script_model.rowCount() > 0:
            self.script_panel.select_script(script_path)
        else:
            # Try one more time after a delay if scripts aren't loaded yet
            QtCore.QTimer.singleShot(200, lambda: self.script_panel.select_script(script_path))



    def update_cache_stats(self):
        """Update the refresh button tooltip with cache statistics."""
        try:
            from ..cache_manager import get_cache_manager
            cache_manager = get_cache_manager()
            stats = cache_manager.get_stats()
            
            tooltip = f"""Refresh metadata and re-index quick search (Ctrl+R)
            
Cache Stats:
- Folders cached: {stats['folder_cache_size']}
- Tags cached: {stats['tag_cache_size']}
- Hot folders: {stats['hot_folders']}
- Memory usage: ~{stats['estimated_memory_mb']:.1f} MB"""
            
            self.refresh_btn.setToolTip(tooltip)
        except Exception:
            # Don't break if cache manager not available
            pass

    def on_refresh_clicked(self):
        """Handle the refresh button click."""
        # Store current focus widget to restore it later
        current_focus = QtWidgets.QApplication.focusWidget()
        
        try:
            # Get current state
            current_folder = self.folder_panel.get_selected_folder()
            current_script = self.script_panel.get_selected_script()
            
            # Import cache manager
            from ..cache_manager import get_cache_manager
            cache_manager = get_cache_manager()
            
            # Simplified approach: Either refresh current folder or everything
            if current_script or current_folder:
                # Refresh current folder (whether script or folder is selected)
                folder_path = None
                if current_script:
                    # Get the folder containing the script
                    folder_path = os.path.dirname(current_script.path)
                else:
                    # Use the selected folder
                    folder_path = os.path.join(self.current_base, current_folder)
                
                # Clear LRU cache since we're doing a refresh anyway
                from ..metadata_manager import clear_metadata_cache
                clear_metadata_cache()
                
                # Clear the cached folder list to ensure we pick up new folders
                folder_list_cache_key = f"folders:{self.current_base}"
                if folder_list_cache_key in cache_manager.general_cache:
                    del cache_manager.general_cache[folder_list_cache_key]
                    system_debug(f"Cleared folder list cache for {self.current_base}")
                
                # Invalidate folder in persistent cache
                cache_manager.invalidate_folder(folder_path)
                
                # Refresh the folder panel to pick up any new folders
                stored_folder = current_folder
                self.refresh_folder_panel()
                
                # Restore selection and reload scripts after folder panel updates
                def restore_and_reload():
                    if stored_folder:
                        self.folder_panel.select_folder(stored_folder)
                    # Reload scripts for the folder
                    self.script_panel.load_scripts_for_folder(folder_path)
                    # Update metadata panel if a script is selected
                    if current_script:
                        self.metadata_panel.update_metadata(current_script.path)
                
                QtCore.QTimer.singleShot(100, restore_and_reload)
            else:
                # Nothing selected - refresh everything
                self._refresh_everything()
            
            # Clean up hotkeys for missing scripts (don't show dialog on refresh)
            self._cleanup_missing_script_hotkeys(show_dialog=False)
            
            # Refresh hotkeys
            self.register_hotkeys()
            
            # Re-index quick search
            self._start_async_indexing()

            # Update CharonBoard state as part of the unified refresh
            try:
                if hasattr(self, "charon_board_panel"):
                    self.charon_board_panel.refresh_nodes()
            except Exception as board_exc:
                system_warning(f"CharonBoard refresh failed: {board_exc}")

            # No pop-up message - refresh happens silently
            
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self, 
                "Refresh Error", 
                f"Error refreshing metadata: {str(e)}"
            )
        finally:
            # Restore focus to the previously focused widget
            # Use try/except to handle cases where the widget was deleted during refresh
            if current_focus:
                try:
                    if current_focus.isVisible() and current_focus.isEnabled():
                        current_focus.setFocus()
                except RuntimeError:
                    # Widget was deleted during refresh (e.g., tag buttons)
                    pass

    def open_settings(self):
        """Open the settings dialog"""
        from .keybinds import KeybindSettingsDialog
        dialog = KeybindSettingsDialog(self.keybind_manager, parent=self)
        dialog.resize(560, 420)
        exec_dialog(dialog)

    def on_create_script_in_folder(self, folder_name):
        """Handle create script request from folder context menu."""
        # First select the folder
        self.folder_panel.select_folder(folder_name)
        
        # Wait a bit for the folder to load, then trigger the create script dialog
        def trigger_create():
            if hasattr(self.script_panel, '_on_create_script_clicked'):
                self.script_panel._on_create_script_clicked()
        
        QtCore.QTimer.singleShot(100, trigger_create)
    
    def open_folder_from_context(self, folder_name):
        """Open the folder directly from the folder context menu."""
        if folder_name:
            folder_path = os.path.join(self.global_path, folder_name)
            self.open_folder(folder_path)
    
    # Script Engine Event Handlers
    def _on_script_started(self, execution_id, script_path):
        """Handle script execution start"""
        if hasattr(self, 'execution_history_panel'):
            from charon.execution.result import ExecutionResult, ExecutionStatus
            import time
            
            # Create a result for "running" state
            running_result = ExecutionResult(
                status=ExecutionStatus.RUNNING,
                start_time=time.time()
            )
            
            # Check if execution already exists (e.g., from queuing with PENDING status)
            if self.execution_history_panel.has_execution(execution_id):
                # Update existing execution from PENDING to RUNNING
                self.execution_history_panel.update_execution(execution_id, running_result)
            else:
                # Add new execution (for immediately started executions)
                self.execution_history_panel.add_execution(execution_id, script_path, running_result)
    
    def _on_script_completed(self, execution_id, result):
        """Handle script execution completion"""
        # Add to execution history
        if hasattr(self, 'execution_history_panel'):
            self.execution_history_panel.update_execution(execution_id, result)
    
    def _on_script_failed(self, execution_id, error_message):
        """Handle script execution failure"""
        # Store the execution ID and error message to show dialog after history is updated
        self._pending_error_dialog = (execution_id, error_message)
        # Use a timer to ensure the execution_completed signal is processed first
        QtCore.QTimer.singleShot(100, self._show_error_dialog)
    
    def _on_main_splitter_moved(self, pos, index):
        """Handle splitter movement for main splitter (center/history)."""
        sizes = self.main_splitter.sizes()
        history_panel_collapsed = len(sizes) > 1 and sizes[1] == 0
        self.script_panel.set_history_collapsed_indicator(history_panel_collapsed)

    def _on_workflows_splitter_moved(self, pos, index):
        """Handle splitter movement for folders/workflows splitter."""
        sizes = self.workflows_splitter.sizes()
        folders_panel_collapsed = bool(sizes) and sizes[0] == 0
        self.script_panel.set_folders_collapsed_indicator(folders_panel_collapsed)

    def _open_folders_panel(self):
        """Open the folders panel if it's collapsed."""
        sizes = self.workflows_splitter.sizes()
        if sizes and sizes[0] == 0:  # Folders panel is collapsed
            total_width = sum(sizes) if sum(sizes) > 0 else self.workflows_splitter.width()
            if total_width <= 0:
                total_width = 600
            folder_width = int(total_width * config.UI_FOLDER_PANEL_RATIO)
            workflow_width = max(total_width - folder_width, 200)
            self.workflows_splitter.setSizes([folder_width, workflow_width])
            self._on_workflows_splitter_moved(0, 0)
            
    def _collapse_folders_panel(self):
        """Collapse the folders panel."""
        sizes = self.workflows_splitter.sizes()
        if sizes and sizes[0] > 0:  # Folders panel is open
            workflow_width = sum(sizes) - sizes[0]
            self.workflows_splitter.setSizes([0, max(workflow_width, 200)])
            self._on_workflows_splitter_moved(0, 0)
    
    def _open_history_panel(self):
        """Open the history panel if it's collapsed."""
        sizes = self.main_splitter.sizes()
        if len(sizes) < 2 or sizes[1] == 0:  # History panel is collapsed
            total_width = sum(sizes) if sum(sizes) > 0 else self.main_splitter.width()
            if total_width <= 0:
                total_width = 800
            history_width = int(total_width * config.UI_HISTORY_PANEL_RATIO)
            center_width = max(total_width - history_width, 400)
            self.main_splitter.setSizes([center_width, history_width])
            self._on_main_splitter_moved(0, 0)
            
    def _collapse_history_panel(self):
        """Collapse the history panel."""
        sizes = self.main_splitter.sizes()
        if len(sizes) > 1 and sizes[1] > 0:  # History panel is open
            center_width = sizes[0] + sizes[1]
            self.main_splitter.setSizes([center_width, 0])
            self._on_main_splitter_moved(0, 0)
    
    def _show_error_dialog(self):
        """Show the error dialog after execution history has been updated"""
        if not hasattr(self, '_pending_error_dialog'):
            return
            
        execution_id, error_message = self._pending_error_dialog
        delattr(self, '_pending_error_dialog')
        
        # Get the updated history item
        history_item = None
        if hasattr(self, 'execution_history_panel'):
            for i in range(self.execution_history_panel.history_model.rowCount()):
                item = self.execution_history_panel.history_model.data(
                    self.execution_history_panel.history_model.index(i, 0),
                    UserRole
                )
                if item and item.execution_id == execution_id:
                    history_item = item
                    break
        
        if history_item:
            script_name = os.path.basename(history_item.script_path)
            msg_box = QtWidgets.QMessageBox(self)
            msg_box.setIcon(QtWidgets.QMessageBox.Critical)
            msg_box.setWindowTitle("Script Error")
            msg_box.setText(f"{script_name} failed")
            
            # Add custom buttons
            ok_button = msg_box.addButton("OK", QtWidgets.QMessageBox.AcceptRole)
            history_button = msg_box.addButton("History", QtWidgets.QMessageBox.ActionRole)
            
            # Set default button (Enter key)
            msg_box.setDefaultButton(ok_button)
            
            # Show the dialog
            exec_dialog(msg_box)
            
            # If user clicked "History", show the execution details
            if msg_box.clickedButton() == history_button:
                from charon.ui.execution_history_panel import ExecutionDetailsDialog
                # Get the updated history item with the failed result
                for i in range(self.execution_history_panel.history_model.rowCount()):
                    item = self.execution_history_panel.history_model.data(
                        self.execution_history_panel.history_model.index(i, 0),
                        UserRole
                    )
                    if item and item.execution_id == execution_id:
                        dialog = ExecutionDetailsDialog(item, self)
                        dialog.resize(600, 400)
                        exec_dialog(dialog)
                        break
    
    def _on_script_cancelled(self, execution_id):
        """Handle script execution cancellation"""
        QtWidgets.QMessageBox.information(
            self, 
            "Script Execution", 
            "Script execution was cancelled. Check the Execution History panel for details."
        )
    
    def _on_script_progress(self, execution_id, progress_message):
        """Handle script execution progress updates"""
        # Handle special signal for adding PENDING executions to history
        if progress_message.startswith("PENDING_EXECUTION:"):
            script_path = progress_message.replace("PENDING_EXECUTION:", "")
            if hasattr(self, 'execution_history_panel'):
                from charon.execution.result import ExecutionResult, ExecutionStatus
                import time
                
                # Create PENDING result for history
                pending_result = ExecutionResult(
                    status=ExecutionStatus.PENDING,
                    start_time=time.time(),
                    execution_mode="background"
                )
                
                # Add PENDING execution to history
                self.execution_history_panel.add_execution(execution_id, script_path, pending_result)
        # Other progress messages are shown in the execution history details
    
    def _on_script_output(self, execution_id, output_chunk):
        """Handle real-time script output updates"""
        # Update the execution history panel with live output
        if hasattr(self, 'execution_history_panel'):
            self.execution_history_panel.update_execution_output(execution_id, output_chunk)

    def _show_execution_details(self, script_path, result):
        """Show execution details dialog for a specific script execution"""
        # Find the execution in the history panel
        if hasattr(self, 'execution_history_panel'):
            history_model = self.execution_history_panel.history_model
            
            # Look for the most recent execution of this script
            for i in range(history_model.rowCount()):
                history_item = history_model.data(history_model.index(i, 0), QtCore.Qt.UserRole)
                if history_item and history_item.script_path == script_path:
                    # Found the execution, show its details
                    from charon.ui.execution_history_panel import ExecutionDetailsDialog
                    dialog = ExecutionDetailsDialog(history_item, self)
                    dialog.resize(600, 400)
                    exec_dialog(dialog)
                    return
            
            # If not found in history, create a new item
            from charon.ui.execution_history_panel import ExecutionHistoryItem, ExecutionDetailsDialog
            history_item = ExecutionHistoryItem(script_path, result)
            dialog = ExecutionDetailsDialog(history_item, self)
            dialog.resize(600, 400)
            exec_dialog(dialog)
        else:
            # Fallback if history panel doesn't exist
            from charon.ui.execution_history_panel import ExecutionHistoryItem, ExecutionDetailsDialog
            history_item = ExecutionHistoryItem(script_path, result)
            dialog = ExecutionDetailsDialog(history_item, self)
            dialog.resize(600, 400)
            exec_dialog(dialog)
            
    def _prefetch_user_data(self):
        """Prefetch hotkeys and bookmarks from database at startup."""
        try:
            from ..settings import user_settings_db
            # These queries will be slow the first time but cached after
            system_debug("Prefetching user data (hotkeys and bookmarks)")
            
            # Prefetch all hotkeys for current host
            all_hotkeys = user_settings_db.get_all_hotkeys(self.host or "None")
            system_debug(f"Prefetched {len(all_hotkeys)} hotkeys")
            
            # Prefetch all bookmarks
            all_bookmarks = user_settings_db.get_bookmarks()
            system_debug(f"Prefetched {len(all_bookmarks)} bookmarks")
            
            # Store in script panel's cache so it doesn't need to query again
            if hasattr(self.script_panel, '_refresh_user_data_cache'):
                self.script_panel._cached_hotkeys = all_hotkeys
                self.script_panel._cached_bookmarks = set(all_bookmarks)
                
        except Exception as e:
            system_error(f"Error prefetching user data: {e}")
    
    def _auto_select_bookmarks_on_startup(self):
        """Auto-select Bookmarks folder on startup if user has bookmarks"""
        # Start background prefetching on launch
        if self.current_base and config.CACHE_PREFETCH_ALL_FOLDERS:
            from ..cache_manager import get_cache_manager
            cache_manager = get_cache_manager()
            cache_manager.queue_all_folders_prefetch(self.current_base, self.host)
            system_debug("Started background prefetching of all folders")
        
        # Prefetch hotkeys and bookmarks at startup
        self._prefetch_user_data()
        
        # Check if user has bookmarks and set a flag
        try:
            from ..settings import user_settings_db
            bookmarks = user_settings_db.get_bookmarks()
            if bookmarks:
                # Set a flag to auto-select bookmarks when folders are loaded
                self._auto_select_bookmarks_pending = True
            else:
                self._auto_select_bookmarks_pending = False
        except Exception as e:
            system_error(f"Error checking bookmarks for auto-selection: {str(e)}")
            self._auto_select_bookmarks_pending = False
    
    def _on_folder_scripts_loaded(self, scripts):
        """Handle when scripts are loaded for a folder to update tags."""
        # Update tags from the loaded scripts
        self._update_tags_from_scripts(scripts)
    
    def run_script_by_path(self, script_path):
        """Run a script by its full path without UI interaction."""
        # Delegate to the main execute_script method which handles validation and flash
        self.execute_script(script_path)
