from ..qt_compat import QtWidgets, QtCore, QtGui, Qt, UserRole, UniqueConnection, exec_dialog
from typing import Optional, Tuple
import os, sys, time, json, subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, Future

from .folder_panel import FolderPanel
from .script_panel import ScriptPanel
from .metadata_panel import MetadataPanel
from .execution_history_panel import ExecutionHistoryPanel
from .quick_search import QuickSearchDialog
from .tag_bar import TagBar
from .tiny_mode_widget import TinyModeWidget
from .resource_widget import ResourceWidget
from ..folder_loader import FolderListLoader
from .comfy_connection_widget import ComfyConnectionWidget
from .scene_nodes_panel import SceneNodesPanel as CharonBoardPanel
from ..model_transfer_manager import manager as transfer_manager

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
        UI_FOLDER_WORKFLOW_GAP = 14
        UI_BUTTON_WIDTH = 80
        UI_FOLDER_PANEL_RATIO = 0.25
        UI_CENTER_PANEL_RATIO = 0.50
        UI_HISTORY_PANEL_RATIO = 0.25
        UI_NAVIGATION_DELAY_MS = 50
    config = FallbackConfig()
from ..metadata_manager import clear_metadata_cache, get_charon_config, get_folder_tags
from ..workflow_model import GlobalIndexLoader
from ..settings import user_settings_db
from ..utilities import get_current_user_slug
from ..cache_manager import get_cache_manager
from ..execution.result import ExecutionStatus
from ..charon_logger import (
    system_info,
    system_debug,
    system_warning,
    system_error,
    log_user_action,
    log_user_action_detail,
)
from ..icon_manager import get_icon_manager
from ..paths import get_charon_temp_dir


# Centralized UI palette for quick tweaks
COLOR_MAIN_BG = "#212529"
COLOR_ACTION_BORDER = "#2c323c"
COLOR_ACTION_BG = "#37383D"
COLOR_ACTION_TEXT = "#e8eaef"
COLOR_ACTION_HOVER = "#404248"
COLOR_ACTION_PRESSED = "#2f3034"
COLOR_NEW_WORKFLOW_BG = "#84a8de"
COLOR_NEW_WORKFLOW_TEXT = "#3c5e78"
COLOR_NEW_WORKFLOW_HOVER = "#94b6e7"
COLOR_NEW_WORKFLOW_PRESSED = "#7393bf"


class CharonWindow(QtWidgets.QWidget):
    WINDOW_TITLE_BASE = "Charon - Nuke/ComfyUI Integration"
    
    gpu_info_ready = QtCore.Signal(str)

    def __init__(self, global_path=None, local_path=None, host="Nuke", parent=None, startup_mode="normal"):
        super(CharonWindow, self).__init__(parent)
        self._charon_is_charon_window = True
        self.gpu_info_ready.connect(self._update_gpu_label)
        try:
            self.setObjectName("CharonWindow")
        except Exception:
            pass

        # Initialize icon manager early (icons are loaded once globally)
        self.icon_manager = get_icon_manager()

        self._startup_mode_pending = (startup_mode or "normal").lower()
        self._banner_base_pixmap: Optional[QtGui.QPixmap] = None
        self._banner_target_height: int = 0

        self._footer_comfy_layout: Optional[QtWidgets.QHBoxLayout] = None
        self._comfy_widget_in_tiny_mode: bool = False
        self._refresh_in_progress: bool = False
        self._last_refresh_time: float = 0.0
        self._folder_probe_executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix="FolderCompat"
        )
        self._folder_probe_generation: int = 0
        self._pending_folder_selection: Optional[str] = None

        resolved_global_path = global_path or config.WORKFLOW_REPOSITORY_ROOT
        self.global_path = resolved_global_path
        if not os.path.isdir(self.global_path):
            system_warning(f"Workflow repository is not accessible: {self.global_path}")
        # We don't use local_path at all anymore, but keep parameter for backwards compatibility
        self.local_path = None

        # Note: We no longer clear the entire cache when global_path is provided
        # The cache uses full paths as keys, so different repositories won't conflict
        # This significantly improves performance when switching between repositories

        # Charon only targets Nuke; legacy host detection removed
        self.host = host or "Nuke"
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

        # Setup UI
        self.setup_ui()
        self._apply_main_background()

        # Clean up missing bookmarks in background
        self._folder_probe_executor.submit(self._async_bookmark_cleanup)

        # Set window properties
        self.setWindowTitle(self.WINDOW_TITLE_BASE)
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

    def _async_bookmark_cleanup(self):
        """Run bookmark cleanup in background thread."""
        try:
            from ..settings import user_settings_db
            missing = user_settings_db.cleanup_missing_bookmarks()
            if missing:
                # Dispatch UI update to main thread
                QtCore.QMetaObject.invokeMethod(
                    self,
                    lambda: self._show_bookmark_cleanup_dialog(missing),
                    QtCore.Qt.QueuedConnection
                )
        except Exception as e:
            system_warning(f"Bookmark cleanup failed: {e}")

    def _show_bookmark_cleanup_dialog(self, missing):
        """Show the bookmark cleanup dialog on main thread."""
        bookmark_list = "\n".join(missing)
        QtWidgets.QMessageBox.information(
            self,
            "Removed Bookmarks",
            f"The following bookmarked workflows were not found and have been removed:\n\n{bookmark_list}"
        )

    def _debug_user_action(self, message: str) -> None:
        """Emit a concise debug line for user-triggered UI actions."""
        try:
            system_debug(f"[UserAction] {message}")
        except Exception:
            pass
        try:
            log_user_action(message)
            log_user_action_detail("ui_action", message=message)
        except Exception:
            pass

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
        self.setWindowTitle(self.WINDOW_TITLE_BASE)
        
        # Make sure folder panel is refreshed
        self._pending_folder_selection = self.folder_panel.get_selected_folder()
        self.refresh_folder_panel()
        if hasattr(self, "keybind_manager"):
            self.keybind_manager.refresh_keybinds()
    
    def _refresh_everything(self):
        """Refresh everything - folders and all caches."""
        self._debug_user_action("Full refresh requested (folders + caches)")
        # Clear all caches
        from ..metadata_manager import clear_metadata_cache
        clear_metadata_cache()
        self._debug_user_action("Cleared in-memory metadata cache")
        
        # Clear the entire persistent cache for the current base
        from ..cache_manager import get_cache_manager
        cache_manager = get_cache_manager()
        
        # Clear the cached folder list for the current base
        if self.current_base:
            folder_list_cache_key = f"folders:{self.current_base}"
            cache_manager.invalidate_cached_data(folder_list_cache_key)
            system_debug(f"Cleared folder list cache for {self.current_base}")
            cache_manager.invalidate_base_path(self.current_base)
            self._debug_user_action(
                f"Invalidated caches for base path {self.current_base}"
            )
        
        # Store current selection
        current_folder = self.folder_panel.get_selected_folder()
        self._debug_user_action(
            f"Stored current folder before refresh: {current_folder or 'None'}"
        )
        self._pending_folder_selection = current_folder
        
        # Refresh the folder panel (this will reload all folders from disk)
        self.refresh_folder_panel()
        
        # Queue all folders for background prefetching
        if self.current_base and config.CACHE_PREFETCH_ALL_FOLDERS:
            cache_manager.queue_all_folders_prefetch(self.current_base, self.host)
            system_debug("Started background prefetching of all folders")
            self._debug_user_action("Queued background prefetch for all folders")
        
        # Restore selection if possible
        if current_folder:
            # Use a timer to restore selection after folder loading completes
            def restore_selection():
                self.folder_panel.select_folder(current_folder)
            QtCore.QTimer.singleShot(100, restore_selection)
            self._debug_user_action(
                f"Scheduled folder re-selection after refresh: {current_folder}"
            )
    
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
        try:
            self._folder_probe_executor.shutdown(wait=False)
        except Exception:
            pass
        
        # Clean up the execution engine to restore stdout/stderr
        if hasattr(self, 'execution_engine'):
            # Clean up the background executor to restore stdout/stderr
            if hasattr(self.execution_engine, 'background_executor'):
                self.execution_engine.background_executor.cleanup()
        # Stop any active transfers (downloads/copies)
        try:
            transfer_manager.shutdown()
        except Exception:
            pass
        
        if hasattr(self, 'resource_widget'):
            try:
                self.resource_widget.close()
            except Exception:
                pass

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
        main_layout.setSpacing(0)
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

    def _on_3d_mode_toggled(self, checked):
        if hasattr(self, 'script_panel'):
            self.script_panel.set_3d_mode(checked)
        if hasattr(self, 'create_camera_button'):
            self.create_camera_button.setVisible(checked)
        if hasattr(self, 'generate_cameras_button'):
            self.generate_cameras_button.setVisible(checked)
        if hasattr(self, 'final_prep_button'):
            self.final_prep_button.setVisible(checked)

            
        from .. import preferences
        preferences.set_preference("3d_mode_enabled", checked)



    def _on_create_camera_clicked(self):
        """Create a camera framing the selected geometry."""
        host = str(self.host).lower()
        if host == "nuke":
            self._create_camera_nuke()
        else:
            QtWidgets.QMessageBox.information(
                self, 
                "Not Supported", 
                f"Camera creation is not yet implemented for {self.host}."
            )

    def _create_camera_nuke(self):
        try:
            import nuke
            import tempfile
            import os
        except ImportError:
            return

        # Nuke script snippet
        rig_script = r"""
set cut_paste_input [stack 0]
version 16.0 v3
Axis3 {
 inputs 0
 translate {0 143.3999939 0}
 name Charon_CamTarget_1
 selected true
 xpos 897
 ypos 389
}
push 0
Camera3 {
 inputs 2
 translate {0 145 120}
 focal 100
 name Charon_InitCam_1
 selected true
 xpos 1275
 ypos 349
}
set N1ad78f00 [stack 0]
push $N1ad78f00
push $cut_paste_input
Group {
 inputs 3
 name Charon_InitCam_render
 selected true
 xpos 1054
 ypos 545
}
 Input {
  inputs 0
  name cam
  xpos 200
  ypos 312
  number 1
 }
 Input {
  inputs 0
  name object
  xpos 339
  ypos 202
 }
push 0
add_layer {P P.red P.green P.blue P.alpha P.X P.Y P.Z P.x P.y P.z}
add_layer {N N.red N.green N.blue}
 ScanlineRender {
  inputs 3
  conservative_shader_sampling false
  motion_vectors_type distance
  output_shader_vectors true
  P_channel {P.red P.green P.blue}
  N_channel N
  name ScanlineRender1
  xpos 339
  ypos 312
 }
 Dot {
  name Dot10
  xpos 373
  ypos 389
 }
set N4e077400 [stack 0]
 Dot {
  name Dot17
  xpos 275
  ypos 389
 }
set N4e077000 [stack 0]
 Dot {
  name Dot15
  xpos 165
  ypos 389
 }
 Group {
  name NormalsRotate1
  onCreate "\nn=nuke.thisNode()\nn\['mblack'].setFlag(0x0000000000000004)\nn\['mgain'].setFlag(0x0000000000000004)\nn\['mgamma'].setFlag(0x0000000000000004)\n"
  tile_color 0xff00ff
  xpos 131
  ypos 495
  addUserKnob {20 User}
  addUserKnob {41 in l "Normals in" t "Select the layer containing the \nnormals" T Shuffle1.in}
  addUserKnob {41 pick l "Pick Plane" T Plane.pick}
  addUserKnob {22 planereset l Reset -STARTLINE T "nuke.thisNode().knob(\"pick\").setValue(0,0)\nnuke.thisNode().knob(\"pick\").setValue(0,1)\nnuke.thisNode().knob(\"pick\").setValue(1,2)"}
  addUserKnob {26 ""}
  addUserKnob {26 divider_2 l "" +STARTLINE T " "}
  addUserKnob {26 manual l "<b>Manual Rotation</b>" -STARTLINE T "  "}
  addUserKnob {22 rotreset l Reset -STARTLINE T "nuke.thisNode().knob(\"yoffset\").setValue(0)\nnuke.thisNode().knob(\"xzrot\").setValue(0)"}
  addUserKnob {7 yoffset l Horizontal t "Rotate around the world Y axis" R -180 180}
  yoffset {{"degrees(atan2(Charon_InitCam_1.world_matrix.2, Charon_InitCam_1.world_matrix.10))"}}
  addUserKnob {7 xzrot l Vertical t "Rotates around the rotated X axis" R -180 180}
  addUserKnob {26 ""}
  addUserKnob {26 matte l "@b;Matte Output" T "      "}
  addUserKnob {6 inv l "Invert    " t "This happens before the matte \ntweaks" -STARTLINE}
  addUserKnob {6 amask l "Mask by Alpha    " -STARTLINE}
  addUserKnob {6 unpre l Unpremult -STARTLINE}
  addUserKnob {7 exp l Exponent t "Exponential falloff" R 1 10}
  exp 2
  addUserKnob {22 expreset l Reset -STARTLINE T "nuke.thisNode().knob(\"exp\").setValue(2)"}
  addUserKnob {7 mblack l Black R -1 1}
  addUserKnob {22 mblackreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mblack\").setValue(0)"}
  addUserKnob {7 mgain l White R 0 4}
  mgain 1
  addUserKnob {22 mgainreset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgain\").setValue(1)"}
  addUserKnob {7 mgamma l Gamma R 0 4}
  mgamma 1
  addUserKnob {22 mgammareset l Reset -STARTLINE T "nuke.thisNode().knob(\"mgamma\").setValue(1)"}
  addUserKnob {26 ""}
  addUserKnob {26 "" l mask T ""}
  addUserKnob {41 maskChannelInput l "" -STARTLINE T Merge1.maskChannelInput}
  addUserKnob {41 inject -STARTLINE T Merge1.inject}
  addUserKnob {41 invert_mask l invert -STARTLINE T Merge1.invert_mask}
  addUserKnob {41 fringe -STARTLINE T Merge1.fringe}
  addUserKnob {41 mix T Merge1.mix}
  addUserKnob {20 info l Info}
  addUserKnob {26 infotext l "" +STARTLINE T "W_SuperNormal generates a surface angle based matte using normals.\n\n1. Select the layer containing normals in the dropdown menu.\n2. Enable color picker and pick the point where you want the matte to be white.\n  (I look at the alpha output, hold ctrl+alt and \"glide\" over the surfaces.)\n3. You can also manually rotate the matte. When you colorpick a new point,\n  it is recommended that you reset the manual rotation values to 0.\n"}
  addUserKnob {20 v2_1_group l "v2.1 - Feb 2019" n 1}
  v2_1_group 0
  addUserKnob {26 v2_1_text l "" +STARTLINE T "  -Manual rotation working as originally envisioned: It is more intuitive \n   and faster to reach any desired angle with horizontal(Y) and vertical\n   rotation than with separate XYZ rotations.\n  -General cleanup & refinements.\n"}
  addUserKnob {20 endGroup n -1}
  addUserKnob {20 v2group l "v2.0 - 2018" n 1}
  v2group 0
  addUserKnob {26 v2text l "" +STARTLINE T "  -Adopted a different method for rotating normals shown to me by Daniel Pelc\n  -Simpler math for converting normals into a matte with the help of Erwan Leroy\n"}
  addUserKnob {20 endGroup_1 l endGroup n -1}
  addUserKnob {26 v1_1_text l "" +STARTLINE T "    v1.1 - 2016"}
  addUserKnob {26 ""}
  addUserKnob {26 spacer_1 l "" +STARTLINE T "     "}
  addUserKnob {26 copyright l "&#169;  Wes Heo" -STARTLINE T " "}
 }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.yoffset} 0}
   name Axis10
   label H
   xpos -173
   ypos -163
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {{parent.xzrot} {-degrees(parent.Plane.picked.g)} 0}
   name Axis2
   label V
   xpos -171
   ypos -62
  }
  Axis2 {
   inputs 0
   rot_order YXZ
   rotate {0 {-parent.Axis2.rotate.y} 0}
   name Axis5
   label V
   xpos -170
   ypos 34
  }
  Input {
   inputs 0
   name Inputmask
   xpos 132
   ypos 544
   number 1
  }
  Input {
   inputs 0
   name N
   xpos 0
   ypos -425
  }
  Shuffle {
   in N
   alpha red2
   out rgb
   name Shuffle1
   xpos 0
   ypos -347
  }
set N715dc500 [stack 0]
  Dot {
   name Dot1
   xpos 315
   ypos 289
  }
push $N715dc500
  Unpremult {
   name Unpremult1
   xpos 0
   ypos -286
   disable {{!parent.unpre}}
  }
  NoOp {
   name Plane
   xpos 0
   ypos -218
   addUserKnob {20 User}
   addUserKnob {18 pick l "User Picked Plane" R -1 1}
   pick {0 0 1}
   addUserKnob {6 pick_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
   addUserKnob {20 calc l "Internal Conversions"}
   addUserKnob {18 picked}
   picked {0 {"(atan2(pick.r, pick.b))"} 0}
   addUserKnob {6 picked_panelDropped l "panel dropped state" -STARTLINE +HIDDEN}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis10.world_matrix.0} {parent.Axis10.world_matrix.1} {parent.Axis10.world_matrix.2}}
        {{parent.Axis10.world_matrix.4} {parent.Axis10.world_matrix.5} {parent.Axis10.world_matrix.6}}
        {{parent.Axis10.world_matrix.8} {parent.Axis10.world_matrix.9} {parent.Axis10.world_matrix.10}}
   }
   name ColorMatrix2
   xpos 0
   ypos -148
   disable {{parent.yoffset==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis2.world_matrix.0} {parent.Axis2.world_matrix.1} {parent.Axis2.world_matrix.2}}
        {{parent.Axis2.world_matrix.4} {parent.Axis2.world_matrix.5} {parent.Axis2.world_matrix.6}}
        {{parent.Axis2.world_matrix.8} {parent.Axis2.world_matrix.9} {parent.Axis2.world_matrix.10}}
   }
   name ColorMatrix3
   xpos 0
   ypos -42
   disable {{parent.xzrot==0}}
  }
  ColorMatrix {
   matrix {
    
        {{parent.Axis5.world_matrix.0} {parent.Axis5.world_matrix.1} {parent.Axis5.world_matrix.2}}
        {{parent.Axis5.world_matrix.4} {parent.Axis5.world_matrix.5} {parent.Axis5.world_matrix.6}}
        {{parent.Axis5.world_matrix.8} {parent.Axis5.world_matrix.9} {parent.Axis5.world_matrix.10}}
   }
   name ColorMatrix5
   xpos 0
   ypos 54
   disable {{parent.xzrot==0}}
  }
  Expression {
   temp_name0 nx
   temp_expr0 parent.Plane.pick.r
   temp_name1 ny
   temp_expr1 parent.Plane.pick.g
   temp_name2 nz
   temp_expr2 parent.Plane.pick.b
   channel0 {rgba.red -rgba.green -rgba.blue -rgba.alpha}
   expr0 r*nx
   channel1 {-rgba.red rgba.green -rgba.blue none}
   expr1 g*ny
   channel2 {-rgba.red -rgba.green rgba.blue none}
   expr2 b*nz
   channel3 {none none none -rgba.alpha}
   name Expression1
   xpos 0
   ypos 121
   cached true
  }
  Expression {
   expr3 clamp(r+g+b)
   name Expression3
   xpos 0
   ypos 187
  }
  Invert {
   channels alpha
   name Invert1
   xpos 0
   ypos 249
   disable {{!parent.inv}}
  }
  Expression {
   expr3 pow(a,max(1,parent.exp))
   name Expression4
   xpos 0
   ypos 317
  }
  Grade {
   channels alpha
   blackpoint {{-parent.mblack}}
   white {{parent.mgain}}
   gamma {{max(0.001,parent.mgamma)}}
   white_clamp true
   name Grade1
   xpos 0
   ypos 369
  }
  ChannelMerge {
   inputs 2
   operation multiply
   name ChannelMerge1
   xpos 0
   ypos 444
   disable {{!parent.amask}}
  }
push 0
  Merge2 {
   inputs 2+1
   operation copy
   also_merge all
   name Merge1
   label "\[ expr \{ \[value mix] == 1 ? \" \" : \[concat Mix: \[value mix]] \}]"
   xpos 0
   ypos 544
  }
  Output {
   name Output1
   xpos 0
   ypos 623
  }
 end_group
push $N4e077000
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  fromInput2 {
   {0}
   B
  }
  mappings "4 rgba.alpha 0 3 rgba.alpha 0 3 rgba.alpha 0 3 rgba.blue 0 2 rgba.alpha 0 3 rgba.green 0 1 rgba.alpha 0 3 rgba.red 0 0"
  name Shuffle9
  xpos 241
  ypos 431
 }
 Grade {
  channels rgba
  white 0.18
  name Grade3
  xpos 241
  ypos 462
 }
 Grade {
  inputs 1+1
  white 4
  name Grade2
  xpos 241
  ypos 495
 }
add_layer {facingratio facingratio.red facingratio.green facingratio.blue none}
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  in1 rgb
  out1 facingratio
  fromInput2 {
   {0}
   B
  }
  mappings "3 rgba.red 0 0 facingratio.red 0 0 rgba.green 0 1 facingratio.green 0 1 rgba.blue 0 2 facingratio.blue 0 2"
  name Shuffle15
  xpos 241
  ypos 533
 }
 Dot {
  name Dot19
  xpos 275
  ypos 616
 }
push $N4e077400
 Constant {
  inputs 0
  channels rgb
  color {0.36 0.36 0.36 1}
  name BG_Constant
  xpos 501
  ypos 430
 }
 Merge2 {
  inputs 2
  name Merge2
  xpos 339
  ypos 454
 }
add_layer {wireframe wireframe.red wireframe.green wireframe.blue}
 Shuffle2 {
  fromInput1 {
   {0}
   B
  }
  out1 wireframe
  fromInput2 {
   {0}
   B
  }
  mappings "3 rgba.red 0 0 wireframe.red 0 0 rgba.green 0 1 wireframe.green 0 1 rgba.blue 0 2 wireframe.blue 0 2"
  name Shuffle14
  xpos 339
  ypos 535
 }
 Shuffle2 {
  inputs 2
  fromInput1 {
   {0}
   B
   A
  }
  in1 wireframe
  out1 wireframe
  fromInput2 {
   {1}
   B
   A
  }
  in2 facingratio
  out2 facingratio
  mappings "6 wireframe.red 0 0 wireframe.red 0 0 wireframe.green 0 1 wireframe.green 0 1 wireframe.blue 0 2 wireframe.blue 0 2 facingratio.red 1 0 facingratio.red 1 0 facingratio.green 1 1 facingratio.green 1 1 facingratio.blue 1 2 facingratio.blue 1 2"
  name Shuffle16
  xpos 339
  ypos 613
 }
 Output {
  name Output1
  xpos 339
  ypos 753
 }
end_group
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.nk', delete=False) as f:
            f.write(rig_script)
            temp_path = f.name
        
        try:
            nuke.nodePaste(temp_path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to create camera rig: {str(e)}")
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass


    def _on_generate_cameras_clicked(self):
        host = str(self.host).lower()
        if host == "nuke":
            self._generate_coverage_cameras_nuke()
        else:
            QtWidgets.QMessageBox.information(
                self, "Not Supported", 
                f"Camera generation is not yet implemented for {self.host}."
            )

    def _generate_coverage_cameras_nuke(self):
        try:
            import nuke
            import math
        except ImportError:
            return

        # 1. Find Context from Selection
        selection = nuke.selectedNodes()
        init_cam = None
        target = None
        
        for node in selection:
            if node.Class() in ("Camera3", "Camera2", "Camera"):
                init_cam = node
            elif node.Class() in ("Axis3", "Axis2", "Axis"):
                target = node
        
        if init_cam and not target:
            inp = init_cam.input(1)
            if inp and "Axis" in inp.Class():
                target = inp
        
        if not init_cam or not target:
            QtWidgets.QMessageBox.warning(self, "Selection Required", 
                "Please select the Initial Camera and its Target Axis.\n"
                "(Or select just the Camera if the Target is connected to Input 1)")
            return

        # Find connected geometry source
        geo_source = None
        
        # 1. Try to find a ScanlineRender connected to the camera (Global search)
        # We search recursively to find it even if it's inside a Group
        for node in nuke.allNodes("ScanlineRender", recurseGroups=True):
            if node.input(2) == init_cam:
                geo_source = node.input(1)
                break
        
        # 2. If not found, check immediate dependents of the camera (e.g. if camera is plugged into a Group)
        if not geo_source:
            deps = init_cam.dependent()
            for dep in deps:
                if dep.Class() == "Group":
                    # Check inputs of the group to find something that looks like geometry (not the camera itself)
                    # We assume the camera is one input. The geometry should be another.
                    for i in range(dep.inputs()):
                        inp = dep.input(i)
                        if inp and inp != init_cam and inp != target:
                            # Verify it's not another camera or axis just in case
                            if inp.Class() not in ("Camera3", "Camera2", "Camera", "Axis3", "Axis2", "Axis"):
                                geo_source = inp
                                break
                if geo_source:
                    break

        if not geo_source:
             # Try to find a geo node in selection if available
             for n in selection:
                 if n not in (init_cam, target):
                     geo_source = n
                     break
        
        if not geo_source:
             QtWidgets.QMessageBox.warning(self, "Missing Geometry", 
                 "Could not identify geometry source. \n"
                 "Please ensure the initial ScanlineRender is connected to the camera, or select the geometry node as well.")
             return

        # 2. Gather Params
        pivot = target['translate'].value()
        start_pos = init_cam['translate'].value()
        # focal = init_cam['focal'].value() # No longer needed if we clone
        
        # Calculate radius vector relative to pivot
        rx = start_pos[0] - pivot[0]
        ry = start_pos[1] - pivot[1]
        rz = start_pos[2] - pivot[2]
        radius = math.sqrt(rx*rx + ry*ry + rz*rz)

        # Clone Init Cam to Clipboard
        # Save current selection
        original_selection = nuke.selectedNodes()
        # Select only init_cam
        for n in nuke.allNodes(): n.setSelected(False)
        init_cam.setSelected(True)
        nuke.nodeCopy("%clipboard%")
        init_cam.setSelected(False)
        # Restore selection? Not strictly necessary as we'll select the group.

        # 3. Create Group
        group = nuke.createNode("Group")
        group.setName("Charon_Coverage_Rig")
        group.setXYpos(init_cam.xpos() + 300, init_cam.ypos())
        
        # Connect Group Input to Geo Source
        group.setInput(0, geo_source)
        
        group.begin()
        
        input_geo = nuke.createNode("Input")
        input_geo.setName("geo")
        
        # Texture Setup (White Base + Grey Wireframe)
        tex_const = nuke.createNode("Constant")
        tex_const.setName("BaseGray")
        tex_const['color'].setValue([1, 1, 1, 1])
        tex_const.setXYpos(input_geo.xpos() + 150, input_geo.ypos())
        
        tex_wire = nuke.createNode("Wireframe")
        tex_wire.setInput(0, tex_const)
        tex_wire['operation'].setValue("over")
        tex_wire['line_width'].setValue(0.12)
        tex_wire['line_color'].setValue([0.36, 0.36, 0.36, 1])
        tex_wire.setXYpos(tex_const.xpos(), tex_const.ypos() + 100)
        
        apply_mat = nuke.createNode("ApplyMaterial")
        apply_mat.setInput(0, input_geo)
        apply_mat.setInput(1, tex_wire)
        apply_mat.setXYpos(input_geo.xpos(), input_geo.ypos() + 200)
        
        # Internal Target
        int_target = nuke.createNode("Axis3")
        int_target.setName("Target")
        int_target['translate'].setValue(pivot)
        int_target.setXYpos(0, 0)
        
        # Create 8 Cameras and Render setups (45 degree increments)
        cam_configs = [
            ("Init",   0),
            ("45",     45),
            ("90",     90),
            ("135",    135),
            ("180",    180),
            ("225",    225),
            ("270",    270),
            ("315",    315)
        ]
        
        render_outputs = []
        
        for i, (name, yaw) in enumerate(cam_configs):
            grid_x = i % 4
            grid_y = i // 4
            x_pos = (grid_x + grid_y * 4) * 200 
            
            # Paste Camera (Clone)
            nuke.nodePaste("%clipboard%")
            cam = nuke.selectedNode()
            cam.setName(f"Cam{name}")
            cam.setInput(1, int_target) # Reconnect LookAt to internal target
            
            # Explicitly reset rotation knobs to zero for clean LookAt behavior
            cam['rotate'].setValue([0, 0, 0])
            
            # Position
            rad_yaw = math.radians(yaw)
            nx = rx * math.cos(rad_yaw) - rz * math.sin(rad_yaw)
            nz = rx * math.sin(rad_yaw) + rz * math.cos(rad_yaw)
            cam['translate'].setValue([pivot[0] + nx, pivot[1] + ry, pivot[2] + nz])
            
            cam.setXYpos(x_pos, 200)
            
            # Render Setup
            scanline = nuke.createNode("ScanlineRender")
            scanline.setInput(1, apply_mat)
            scanline.setInput(2, cam)
            scanline.setXYpos(x_pos, 400)
            
            # Background
            bg = nuke.createNode("Constant")
            bg.setName("BG_Constant")
            bg['channels'].setValue("rgb")
            bg['color'].setValue([0.36, 0.36, 0.36, 1])
            bg.setXYpos(x_pos + 100, 400)
            
            merge = nuke.createNode("Merge2")
            merge.setInput(1, scanline)
            merge.setInput(0, bg)
            merge.setXYpos(x_pos, 500)
            
            render_outputs.append(merge)
            
        # Contact Sheet
        contact = nuke.createNode("ContactSheet")
        
        # Fixed resolution and layout as specified by user
        contact_width = 4096
        contact_height = 2048
        rows = 2
        columns = 4
        gap = 10 # This gap is for internal calculation, Nuke uses 'row_gap' and 'col_gap' knobs

        contact['width'].setValue(contact_width)
        contact['height'].setValue(contact_height)
        contact['rows'].setValue(rows)
        contact['columns'].setValue(columns)
        contact['roworder'].setValue("TopBottom")
        contact['gap'].setValue(gap)
        
        for i, node in enumerate(render_outputs):
            contact.setInput(i, node)
            
        contact.setXYpos(300, 700)
        
        output = nuke.createNode("Output")
        output.setInput(0, contact)
        output.setXYpos(300, 800)
        
        group.end()
        group.setSelected(True)

    def _on_final_prep_clicked(self):
        host = str(self.host).lower()
        if host == "nuke":
            self._generate_final_prep_nuke()
        else:
            QtWidgets.QMessageBox.information(
                self, "Not Supported", 
                f"Final Prep is not yet implemented for {self.host}."
            )

    def _generate_final_prep_nuke(self):
        try:
            import nuke
            import tempfile
        except ImportError:
            return

        # 1. Validate Selection
        selection = nuke.selectedNodes()
        if not selection or len(selection) != 1:
            QtWidgets.QMessageBox.warning(self, "Selection Required", "Please select the Charon Coverage Rig group.")
            return
        
        rig_group = selection[0]
        if rig_group.Class() != "Group":
            QtWidgets.QMessageBox.warning(self, "Invalid Selection", "Selected node must be a Group (Charon Coverage Rig).")
            return

        # 2. Extract Camera and Target Data
        cam_names = ["CamInit", "Cam45", "Cam90", "Cam135", "Cam180", "Cam225", "Cam270", "Cam315"]
        cam_data = {}
        target_data = None
        
        with rig_group:
            for name in cam_names:
                cam = nuke.toNode(name)
                if cam:
                    cam_data[name] = cam['translate'].value()
            
            # Extract Target Data
            tgt = nuke.toNode("Target")
            if tgt:
                target_data = tgt['translate'].value()

        # 3. Find Geometry Source
        geo_source = None
        # Check 'geo' input of the rig group
        for i in range(rig_group.inputs()):
            inp_node = rig_group.input(i)
            # We assume the rig has an input named 'geo' connected to input 0 or similar
            if i == 0:
                geo_source = inp_node
        
        if not geo_source:
             QtWidgets.QMessageBox.warning(self, "Missing Geometry", 
                 "Could not identify geometry source connected to the rig.")
             return

        # 4. Read Template from File
        try:
            # Construct path relative to this file
            current_dir = os.path.dirname(os.path.abspath(__file__))
            template_path = os.path.join(current_dir, "..", "resources", "nuke_template", "projection_final_prep.nk")
            template_path = os.path.normpath(template_path)
            
            if not os.path.exists(template_path):
                 QtWidgets.QMessageBox.warning(self, "Error", f"Template file not found: {template_path}")
                 return
                 
            with open(template_path, 'r') as f:
                content = f.read()
                
            # Extract the Group block
            # We look for the first "Group {" at the start of a line
            start_idx = content.find("\nGroup {")
            if start_idx == -1:
                # Try finding it at the very start of the file
                if content.startswith("Group {"):
                    start_idx = 0
                else:
                     QtWidgets.QMessageBox.warning(self, "Error", "Could not find Group definition in template file.")
                     return
            else:
                start_idx += 1 # Skip the newline
            
            script_content = content[start_idx:]
            
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to read template file: {str(e)}")
            return

        # 5. Paste Script via Temp File
        # Deselect everything to paste cleanly
        for n in nuke.allNodes(): n.setSelected(False)
        
        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.nk', delete=False) as f:
                f.write(script_content)
                temp_path = f.name
            
            nuke.nodePaste(temp_path)
            final_prep_group = None
            for n in nuke.selectedNodes():
                if n.Class() == "Group":
                    final_prep_group = n
                    break
            
            if not final_prep_group:
                try:
                    sel = nuke.selectedNode()
                    if sel and sel.Class() == "Group":
                        final_prep_group = sel
                except: pass
            
            if not final_prep_group:
                raise RuntimeError("Could not find pasted Group node.")
            
            # 6. Apply Camera and Target Data
            final_prep_group.begin()
            try:
                for name, translate_val in cam_data.items():
                    cam = nuke.toNode(name)
                    if cam:
                        cam['translate'].setValue(translate_val)
                    else:
                        print(f"Warning: Could not find camera '{name}' in pasted group to update.")
                
                # Apply Target Data
                if target_data:
                    tgt_pasted = nuke.toNode("Target")
                    if tgt_pasted:
                        tgt_pasted['translate'].setValue(target_data)
                    else:
                        print("Warning: Could not find 'Target' in pasted group to update.")
            finally:
                final_prep_group.end()
            
            # 7. Connect Geometry
            final_prep_group.setInput(0, geo_source)
            
            # Position near the rig
            final_prep_group.setXYpos(rig_group.xpos() + 200, rig_group.ypos() + 200)
            
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", f"Failed to generate Final Prep: {str(e)}")
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass

    def _setup_normal_ui(self, parent):
        """Setup the normal mode UI."""
        # Use a QVBoxLayout with minimal margins
        main_layout = QtWidgets.QVBoxLayout(parent)
        main_layout.setContentsMargins(
            config.UI_WINDOW_MARGINS,
            config.UI_WINDOW_MARGINS,
            config.UI_WINDOW_MARGINS,
            config.UI_WINDOW_MARGINS,
        )
        main_layout.setSpacing(config.UI_ELEMENT_SPACING + 4)

        base_margin = 10
        folder_workflow_gap = getattr(config, "UI_FOLDER_WORKFLOW_GAP", 70)

        # Main content layout
        content_layout = QtWidgets.QVBoxLayout()
        content_layout.setContentsMargins(base_margin, 4, base_margin, 4)
        content_layout.setSpacing(6)

        # Primary actions row (New Workflow, Refresh, Settings) beneath header
        self.actions_container = QtWidgets.QWidget()
        self.actions_layout = QtWidgets.QHBoxLayout(self.actions_container)
        self.actions_layout.setContentsMargins(0, 0, 0, 0)
        self.actions_layout.setSpacing(8)
        content_layout.addSpacing(10)
        content_layout.addWidget(self.actions_container)
        
        # Info row (Project Label + GPU Label + 3D Mode)
        info_container = QtWidgets.QWidget()
        info_layout = QtWidgets.QHBoxLayout(info_container)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(8) # Standard spacing
        
        # Left side: Labels stacked vertically
        labels_container = QtWidgets.QWidget()
        labels_layout = QtWidgets.QVBoxLayout(labels_container)
        labels_layout.setContentsMargins(0, 0, 0, 0)
        labels_layout.setSpacing(2)
        
        self.project_label = QtWidgets.QLabel(self.normal_widget)
        self.project_label.setObjectName("charonProjectLabel")
        self.project_label.setStyleSheet("color: #7f848e; font-size: 11px;")
        labels_layout.addWidget(self.project_label)
        
        self.gpu_label = QtWidgets.QLabel(self.normal_widget)
        self.gpu_label.setObjectName("charonGpuLabel")
        self.gpu_label.setStyleSheet("color: #7f848e; font-size: 11px;")
        labels_layout.addWidget(self.gpu_label)
        
        info_layout.addWidget(labels_container)
        
        info_layout.addStretch()

        # 3D Texturing Buttons
        self.create_camera_button = QtWidgets.QPushButton("🎥", info_container)
        self.create_camera_button.setToolTip("Create Initial Camera Rig")
        self.create_camera_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.create_camera_button.setFixedSize(28, 24)
        btn_style = """
            QPushButton {
                border: 1px solid #2c323c;
                border-radius: 4px;
                background-color: #37383D;
                color: #e8eaef;
                font-size: 14px;
                padding-bottom: 2px;
            }
            QPushButton:hover { background-color: #404248; }
            QPushButton:pressed { background-color: #2f3034; }
        """
        self.create_camera_button.setStyleSheet(btn_style)
        self.create_camera_button.clicked.connect(self._on_create_camera_clicked)
        self.create_camera_button.setVisible(False)
        info_layout.addWidget(self.create_camera_button)

        self.generate_cameras_button = QtWidgets.QPushButton("⭐", info_container)
        self.generate_cameras_button.setToolTip("Generate Coverage Cameras")
        self.generate_cameras_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.generate_cameras_button.setFixedSize(28, 24)
        self.generate_cameras_button.setStyleSheet(btn_style)
        self.generate_cameras_button.clicked.connect(self._on_generate_cameras_clicked)
        self.generate_cameras_button.setVisible(False)
        info_layout.addWidget(self.generate_cameras_button)

        self.final_prep_button = QtWidgets.QPushButton("✨", info_container)
        self.final_prep_button.setToolTip("Final Prep")
        self.final_prep_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.final_prep_button.setFixedSize(28, 24)
        self.final_prep_button.setStyleSheet(btn_style)
        self.final_prep_button.clicked.connect(self._on_final_prep_clicked)
        self.final_prep_button.setVisible(False)
        info_layout.addWidget(self.final_prep_button)
        
        # Right side: 3D Mode Toggle
        self.mode_3d_button = QtWidgets.QPushButton("3D Mode", info_container)
        self.mode_3d_button.setCheckable(True)
        self.mode_3d_button.setFixedHeight(24)
        self.mode_3d_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_3d_button.setStyleSheet("""
            QPushButton {
                padding: 0px 12px;
                border: 1px solid #2c323c;
                border-radius: 4px;
                background-color: #37383D;
                color: #e8eaef;
            }
            QPushButton:hover { background-color: #404248; }
            QPushButton:checked {
                background-color: #339af0;
                color: white;
                border: 1px solid #1c7ed6;
            }
        """)
        self.mode_3d_button.setToolTip("Toggle 3D Texturing workflows")
        self.mode_3d_button.toggled.connect(self._on_3d_mode_toggled)
        
        from .. import preferences
        initial_3d_state = preferences.get_preference("3d_mode_enabled", False)
        self.mode_3d_button.setChecked(initial_3d_state)
        
        info_layout.addWidget(self.mode_3d_button)
        
        # ACEScg Toggle Button
        self._aces_off_style = """
            QPushButton {
                padding: 0px 8px;
                border: 1px solid #2c323c;
                border-radius: 4px;
                background-color: #37383D;
                color: #e8eaef;
            }
            QPushButton:hover { background-color: #404248; }
            QPushButton:pressed { background-color: #2f3034; }
        """
        self._aces_on_style = """
            QPushButton {
                padding: 0px 8px;
                border: 1px solid #1c7ed6;
                border-radius: 4px;
                background-color: #339af0;
                color: white;
                font-weight: normal;
            }
            QPushButton:hover { background-color: #4dabf7; }
        """
        
        self.aces_toggle_button = QtWidgets.QPushButton("ACES Off", info_container)
        self.aces_toggle_button.setCheckable(True)
        self.aces_toggle_button.setFixedHeight(24)
        self.aces_toggle_button.setFixedWidth(80)
        self.aces_toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.aces_toggle_button.setStyleSheet(self._aces_off_style)
        self.aces_toggle_button.setToolTip("Toggle ACEScg color space handling for ComfyUI integration")
        self.aces_toggle_button.toggled.connect(self._on_aces_toggle_changed)
        
        from .. import preferences
        initial_aces_state = preferences.get_preference("aces_mode_enabled", False)
        self.aces_toggle_button.setChecked(initial_aces_state)
        if initial_aces_state:
             self.aces_toggle_button.setText("ACES On")
             self.aces_toggle_button.setStyleSheet(self._aces_on_style)

        info_layout.addWidget(self.aces_toggle_button)
        

        
        content_layout.addWidget(info_container)
        
        content_layout.addSpacing(10)
        
        # Main horizontal splitter: folder panel, center panel, and history panel
        self.main_splitter = QtWidgets.QSplitter(Qt.Horizontal)
        self.main_splitter.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.main_splitter.setHandleWidth(0)
        
        # Center panel - horizontal layout for tag bar and script panel
        center_widget = QtWidgets.QWidget()
        center_widget.setMinimumWidth(0)  # Remove any minimum width
        center_layout = QtWidgets.QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(2)

        self.center_tab_widget = QtWidgets.QTabWidget(center_widget)
        self.center_tab_widget.setObjectName("CenterTabWidget")
        self.center_tab_widget.setDocumentMode(True)
        self.center_tab_widget.setTabPosition(QtWidgets.QTabWidget.West)
        self._install_tab_corner_controls()
        center_layout.addWidget(self.center_tab_widget)

        workflows_container = QtWidgets.QWidget()
        workflows_layout = QtWidgets.QHBoxLayout(workflows_container)
        workflows_layout.setContentsMargins(0, 0, 0, 0)
        workflows_layout.setSpacing(10)

        self.workflows_splitter = QtWidgets.QSplitter(Qt.Horizontal, workflows_container)
        self.workflows_splitter.setChildrenCollapsible(False)
        self.workflows_splitter.setHandleWidth(folder_workflow_gap)
        self.workflows_splitter.setStyleSheet(
            f"QSplitter::handle {{ background: {COLOR_MAIN_BG}; }}"
        )
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
        workflow_area_layout.setSpacing(10)
        self.workflows_splitter.addWidget(workflow_area)

        # Create tag bar
        self.tag_bar = TagBar()
        self.tag_bar.setVisible(False)
        self.tag_bar.setFixedWidth(0)
        self.tag_bar.tags_changed.connect(self.on_tags_changed)
        workflow_area_layout.addWidget(self.tag_bar)

        # Script panel
        self.script_panel = ScriptPanel()
        self.script_panel.set_host(self.host)
        
        # Ensure ScriptPanel reflects the initial 3D mode state
        if hasattr(self, 'mode_3d_button'):
            self.script_panel.set_3d_mode(self.mode_3d_button.isChecked())
            
        self.script_panel.script_deselected.connect(self.on_script_deselected)
        self.script_panel.bookmark_requested.connect(self.on_bookmark_requested)

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

        # Attach shared header actions to the row beneath the title
        self._populate_actions_row()

        self.center_tab_widget.addTab(workflows_container, "Workflows")

        self.charon_board_panel = CharonBoardPanel()
        self.center_tab_widget.addTab(self.charon_board_panel, "CharonBoard")

        # Set center widget to expand vertically
        center_widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        self.main_splitter.addWidget(center_widget)
        
        # Execution history panel (right) - keep hidden to match requested layout
        self.execution_history_panel = ExecutionHistoryPanel()
        self.execution_history_panel.setVisible(False)
        self.execution_history_panel.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored)
        self.main_splitter.addWidget(self.execution_history_panel)

        # Disable history resizing
        self.main_splitter.setCollapsible(0, False)  # Center panel - always visible
        self.main_splitter.setCollapsible(1, True)   # History panel - hidden/collapsible
        
        # Remove minimum sizes to allow full flexibility
        self.folder_panel.setMinimumWidth(0)
        self.execution_history_panel.setMinimumWidth(0)
        
        # Hide the history splitter handle to remove resize affordance
        window_color = self.palette().color(self.palette().Window)
        self.main_splitter.setHandleWidth(0)
        self.main_splitter.setStyleSheet(f"QSplitter::handle {{ background-color: {window_color.name()}; border: none; width: 0px; padding: 0px; margin: 0px; }}")
        
        # Set the width ratio for center/history (history hidden by default)
        total_width = config.WINDOW_WIDTH - 50  # Subtract some padding
        center_width = int(total_width * (config.UI_FOLDER_PANEL_RATIO + config.UI_CENTER_PANEL_RATIO))
        history_width = 0  # History panel removed from view
        self.main_splitter.setSizes([center_width, history_width])

        # Configure splitter inside Workflows tab (folders + workflows)
        workflow_total = max(center_width, 600)
        folder_width = int(workflow_total * config.UI_FOLDER_PANEL_RATIO)
        workflow_content_width = max(workflow_total - folder_width, 400)
        self.workflows_splitter.setSizes([folder_width, workflow_content_width])
        handle = self.workflows_splitter.handle(1)
        if handle is not None:
            handle.setEnabled(False)
            handle.setStyleSheet(
                f"background: {COLOR_MAIN_BG}; width: {folder_workflow_gap}px; "
                "margin: 0px; padding: 0px; border: none;"
            )

        # Configure splitter inside Workflows tab (folders + workflows)
        workflow_total = max(center_width, 600)
        folder_width = int(workflow_total * config.UI_FOLDER_PANEL_RATIO)
        workflow_content_width = max(workflow_total - folder_width, 400)
        self.workflows_splitter.setSizes([folder_width, workflow_content_width])
        handle = self.workflows_splitter.handle(1)
        if handle is not None:
            handle.setEnabled(False)
            handle.setStyleSheet(
                f"background: {COLOR_MAIN_BG}; width: {folder_workflow_gap}px; "
                "margin: 0px; padding: 0px; border: none;"
            )

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

        # Bottom footer with ComfyUI controls aligned to the right
        footer_container = QtWidgets.QWidget(parent)
        footer_layout = QtWidgets.QGridLayout(footer_container)
        # Left margin reduced to 1 (was 4) to move tracker left by 3px
        footer_layout.setContentsMargins(1, 0, 4, 4)
        footer_layout.setSpacing(4)
        footer_layout.setVerticalSpacing(0) # Reduce vertical spacing since it's just one row effectively

        # Row 0 Left: Resource Widget
        self.resource_widget = ResourceWidget(parent)
        # Add slight left margin to resource widget to align bars with text above
        self.resource_widget.setContentsMargins(0, 0, 0, 0)
        footer_layout.addWidget(self.resource_widget, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)

        # Row 0 Right: Comfy Connection
        self.comfy_connection_widget = ComfyConnectionWidget(parent)
        self.comfy_connection_widget.client_changed.connect(self._on_comfy_client_changed)
        self.comfy_connection_widget.connection_status_changed.connect(
            self.script_panel.update_comfy_connection_status
        )
        self.script_panel.update_comfy_connection_status(
            self.comfy_connection_widget.is_connected()
        )
        footer_layout.addWidget(self.comfy_connection_widget, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
        
        # Spacer Column (Row 0, Col 1)
        footer_layout.setColumnStretch(1, 1)
        
        # Set the main footer layout reference to our grid layout
        self._footer_comfy_layout = footer_layout
        
        # Add container to main layout
        main_layout.addWidget(footer_container)

        self._refresh_project_display()
        self._refresh_gpu_display()

        # Initialize and populate folders
        self.current_base = self.global_path
        self.refresh_folder_panel()
        
        # Auto-select Bookmarks folder on startup if user has bookmarks
        self._auto_select_bookmarks_on_startup()
    
    def _install_tab_corner_controls(self):
        """Attach Refresh and Settings buttons to the tab bar corner."""
        self.center_tab_widget.setCornerWidget(None, Qt.TopRightCorner)

    def _populate_actions_row(self):
        """Place shared actions under the header to match reference layout."""
        if getattr(self, "_actions_populated", False):
            return
        if not hasattr(self, "actions_layout") or not hasattr(self, "actions_container"):
            return
        if not hasattr(self, "script_panel"):
            return

        # Add extra height so padded labels stay centered and un-clipped
        button_height = max(28, getattr(config, "UI_PANEL_HEADER_HEIGHT", 32) + 4)
        action_style = f"""
            QPushButton {{
                padding: 0px 16px;
                margin: 0px;
                border: 1px solid {COLOR_ACTION_BORDER};
                border-radius: 4px;
                background-color: {COLOR_ACTION_BG};
                color: {COLOR_ACTION_TEXT};
                font-weight: normal;
            }}
            QPushButton:hover {{
                background-color: {COLOR_ACTION_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {COLOR_ACTION_PRESSED};
            }}
        """

        def _make_symbol_icon(symbol: str, scale: float = 1.1):
            base_size = self.font().pointSizeF()
            if base_size <= 0:
                base_size = float(self.font().pointSize() or 10)
            icon_px = max(12, int(round(base_size * scale)))
            font = QtGui.QFont(self.font())
            font.setPointSize(icon_px)
            metrics = QtGui.QFontMetrics(font)
            canvas_size = max(icon_px + 2, int(icon_px * 1.05))
            pixmap = QtGui.QPixmap(canvas_size, canvas_size)
            pixmap.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(pixmap)
            painter.setFont(font)
            palette = self.palette()
            role = getattr(QtGui.QPalette, "ButtonText", QtGui.QPalette.ColorRole.ButtonText)
            try:
                color = palette.color(role)
            except Exception:
                try:
                    color = palette.color(QtGui.QPalette.ColorRole.ButtonText)
                except Exception:
                    color = QtGui.QColor("white")
            painter.setPen(color)
            painter.drawText(pixmap.rect(), Qt.AlignCenter, symbol)
            painter.end()
            return QtGui.QIcon(pixmap), canvas_size

        # Reparent the shared New Workflow button so it sits under the header
        new_workflow_btn = self.script_panel.new_script_button
        new_workflow_btn.setParent(self.actions_container)
        new_workflow_btn.setFixedHeight(button_height)
        new_workflow_btn.setObjectName("NewWorkflowButton")
        self.actions_layout.addWidget(new_workflow_btn)

        self.actions_layout.addStretch()

        refresh_icon, refresh_box = _make_symbol_icon("↻")
        self.header_refresh_button = QtWidgets.QPushButton("Refresh", self.actions_container)
        self.header_refresh_button.setIcon(refresh_icon)
        refresh_icon_px = max(12, int(button_height * 0.6))
        self.header_refresh_button.setIconSize(QtCore.QSize(refresh_icon_px, refresh_icon_px))
        self.header_refresh_button.setFixedHeight(button_height)
        self.header_refresh_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_refresh_button.setStyleSheet(action_style)
        self.header_refresh_button.setToolTip("Refresh metadata and re-index quick search (Ctrl+R)")
        self.header_refresh_button.clicked.connect(self.on_refresh_clicked)
        self.actions_layout.addWidget(self.header_refresh_button)

        settings_icon, settings_box = _make_symbol_icon("⏣")
        self.header_settings_button = QtWidgets.QPushButton("Settings", self.actions_container)
        self.header_settings_button.setIcon(settings_icon)
        settings_icon_px = max(12, int(button_height * 0.6))
        self.header_settings_button.setIconSize(QtCore.QSize(settings_icon_px, settings_icon_px))
        self.header_settings_button.setFixedHeight(button_height)
        self.header_settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_settings_button.setStyleSheet(action_style)
        self.header_settings_button.setToolTip("Configure keybinds and preferences")
        self.header_settings_button.clicked.connect(self.open_settings)
        width_refresh = self.header_refresh_button.sizeHint().width()
        width_settings = self.header_settings_button.sizeHint().width()
        target_width = max(width_refresh, width_settings, refresh_icon_px + 20, settings_icon_px + 20)
        self.header_refresh_button.setFixedWidth(target_width)
        self.header_settings_button.setFixedWidth(target_width)
        self.actions_layout.addWidget(self.header_settings_button)

        # Apply consistent styling to the reused button
        new_workflow_style = f"""
QPushButton#NewWorkflowButton {{
    background-color: {COLOR_NEW_WORKFLOW_BG};
    color: {COLOR_NEW_WORKFLOW_TEXT};
    padding: 8px 16px;
    margin: 0px;
    border: 1px solid palette(mid);
    border-radius: 4px;
    font-weight: normal;
    text-shadow: none;
    box-shadow: none;
}}
QPushButton#NewWorkflowButton:hover {{
    background-color: {COLOR_NEW_WORKFLOW_HOVER};
}}
QPushButton#NewWorkflowButton:pressed {{
    background-color: {COLOR_NEW_WORKFLOW_PRESSED};
}}
"""
        new_workflow_btn.setStyleSheet(new_workflow_style)
        new_workflow_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._realign_actions_to_tabs()
        self._actions_populated = True

    def _realign_actions_to_tabs(self):
        """Align the actions row with the start of the content (after vertical tabs)."""
        try:
            tab_bar = self.center_tab_widget.tabBar()
            tab_width = tab_bar.sizeHint().width() if tab_bar is not None else 0
        except Exception:
            tab_width = 0
        left_margin = max(0, tab_width)
        if hasattr(self, "actions_layout"):
            self.actions_layout.setContentsMargins(left_margin, 0, 0, 0)
        
        # Also align the project label which is below the actions
        if hasattr(self, "project_label"):
            self.project_label.setContentsMargins(left_margin, 0, 0, 0)
            
        # Also align the gpu label which is below the project label
        if hasattr(self, "gpu_label"):
            self.gpu_label.setContentsMargins(left_margin, 0, 0, 0)

    def _apply_main_background(self):
        """Apply the primary background color across the window surfaces."""
        bg_color = QtGui.QColor(COLOR_MAIN_BG)
        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, bg_color)
        palette.setColor(QtGui.QPalette.Base, bg_color)
        self.setAutoFillBackground(True)
        self.setPalette(palette)
        # Ensure main containers inherit the background
        if hasattr(self, "normal_widget"):
            self.normal_widget.setAutoFillBackground(True)
            self.normal_widget.setPalette(palette)
        if hasattr(self, "stacked_widget"):
            self.stacked_widget.setAutoFillBackground(True)
            self.stacked_widget.setPalette(palette)

    def _setup_shared_components(self):
        """Setup components shared between normal and command mode."""
        # Ensure project details stay updated after shared components load
        self._refresh_project_display()
        self._refresh_gpu_display()
        
        # Connect tiny mode signals
        self.tiny_mode_widget.exit_tiny_mode.connect(self.exit_tiny_mode)
        self.tiny_mode_widget.open_settings.connect(self.open_settings)
        self.tiny_mode_widget.open_charon_board.connect(
            self._open_charon_board_from_tiny_mode
        )
        
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
    # Hardware detection
    # -------------------------------------------------

    @staticmethod
    def _round_gb(value, scale: float) -> Optional[int]:
        try:
            return int(round(float(value) / scale))
        except Exception:
            return None

    @staticmethod
    def _is_supported_gpu(name: str) -> bool:
        """
        Check if the GPU is a supported GeForce RTX 30xx/40xx/50xx card.
        Ignores A2000, 20xx series, and non-GeForce cards.
        """
        if not name:
            return False
        
        name_clean = name.strip()
        if "GeForce RTX" not in name_clean:
            return False
            
        import re
        # Match 30xx, 40xx, 50xx
        return bool(re.search(r"\b(30|40|50)\d{2}\b", name_clean))

    def _detect_nvidia_gpus(self) -> list[str]:
        """Use nvidia-smi for accurate VRAM reporting when available."""
        cmd = [
            "nvidia-smi",
            "--query-gpu=name,memory.total",
            "--format=csv,noheader,nounits",
        ]
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except Exception as exc:
            system_debug(f"GPU detection via nvidia-smi failed: {exc}")
            return []

        entries: list[str] = []
        for line in result.stdout.splitlines():
            parts = [part.strip() for part in line.split(",") if part.strip()]
            if len(parts) < 2:
                continue
            name, mem_mib = parts[0], parts[1]
            
            if not self._is_supported_gpu(name):
                continue
                
            mem_gb = self._round_gb(mem_mib, 1024)
            if mem_gb:
                entries.append(f"{name} ({mem_gb} GB)")
            else:
                entries.append(name)
        return entries

    def _detect_wmi_gpus(self) -> list[str]:
        """Fallback GPU detection for Windows using WMI (may under-report VRAM)."""
        if sys.platform != "win32":
            return []
        cmd = (
            "Get-CimInstance Win32_VideoController | "
            "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"
        )
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
        except Exception as exc:
            system_debug(f"GPU detection via WMI failed: {exc}")
            return []

        try:
            payload = json.loads(result.stdout)
        except Exception:
            return []

        records = payload if isinstance(payload, list) else [payload]
        entries: list[str] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            name = str(record.get("Name") or "").strip()
            
            if not self._is_supported_gpu(name):
                continue
                
            raw_ram = record.get("AdapterRAM")
            mem_gb = None
            if isinstance(raw_ram, (int, float)):
                mem_gb = self._round_gb(raw_ram, 1024 ** 3)
            if name and mem_gb:
                entries.append(f"{name} ({mem_gb} GB)")
            elif name:
                entries.append(name)
        return entries

    def _detect_gpu_summary(self) -> str:
        """Return a concise GPU summary string for the footer."""
        entries = self._detect_nvidia_gpus()
        if not entries:
            entries = self._detect_wmi_gpus()
        if not entries:
            return "GPU: Unknown"
        summary = "; ".join(entries)
        return f"GPU: {summary}"

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
            # Prefix added back per user request
            label.setText(f"Project: {project_name}")
            label.setToolTip(project_path)
            return

        work_root = os.environ.get("BUCK_WORK_ROOT", "").strip()
        if work_root:
            destination = os.path.join(work_root, "Work")
        else:
            destination = os.path.join(get_charon_temp_dir(), "results")
        destination = os.path.normpath(destination)
        label.setText(f"Project: Unknown")
        label.setToolTip(f"Project not found, saving to {destination}")

    def _update_gpu_label(self, summary: str):
        self._gpu_summary = summary
        label = getattr(self, "gpu_label", None)
        if label:
            label.setText(f"GPU: {summary}")
            label.setToolTip(summary)

    def _refresh_gpu_display(self):
        """Update the footer with detected GPU/VRAM summary (async)."""
        if getattr(self, "_gpu_summary", None):
            self._update_gpu_label(self._gpu_summary)
            return

        label = getattr(self, "gpu_label", None)
        if label:
            label.setText("GPU: Detecting...")
        
        def run_check():
            try:
                entries = self._detect_nvidia_gpus()
                if not entries:
                    entries = self._detect_wmi_gpus()
                summary = "; ".join(entries) if entries else "Unknown GPU"
            except Exception as exc:
                system_debug(f"GPU detection failed: {exc}")
                summary = "Unknown GPU"
            
            self.gpu_info_ready.emit(summary)

        # Use dedicated thread to avoid thread pool starvation
        thread = threading.Thread(target=run_check)
        thread.daemon = True
        thread.start()
    
    def _on_keybind_triggered(self, action: str):
        """Handle keybind trigger from keybind manager."""
        # Handle tiny mode toggle
        if action == 'tiny_mode':
            if self.keybind_manager.tiny_mode_active:
                self.enter_tiny_mode()
            else:
                self.exit_tiny_mode()
            return

        handler = self.local_keybind_handlers.get(action)
        if handler:
            handler()

    def _on_aces_toggle_changed(self, checked: bool) -> None:
        """Save the ACEScg toggle state to preferences."""
        from .. import preferences
        preferences.set_preference("aces_mode_enabled", checked)
        system_debug(f"ACEScg mode toggled: {checked}")
        
        if hasattr(self, 'aces_toggle_button'):
            if checked:
                self.aces_toggle_button.setText("ACES On")
                if hasattr(self, '_aces_on_style'):
                    self.aces_toggle_button.setStyleSheet(self._aces_on_style)
            else:
                self.aces_toggle_button.setText("ACES Off")
                if hasattr(self, '_aces_off_style'):
                    self.aces_toggle_button.setStyleSheet(self._aces_off_style)
    
    def _run_script_by_path(self, script_path: str):
        """Run a script by its path - delegates to execute_script."""
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
        
        self.tiny_mode_widget.set_host(self.host)
        cached_nodes = None
        try:
            if hasattr(self, "charon_board_panel"):
                self.charon_board_panel.refresh_nodes()
                cached_nodes = (getattr(self.charon_board_panel, "_node_cache", {}) or {}).values()
        except Exception as exc:
            system_warning(f"Failed to refresh tiny mode nodes: {exc}")
        self._move_comfy_footer_to_tiny_mode()

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

        # Prime tiny mode after geometry is settled so initial layout uses the final width
        if cached_nodes:
            try:
                self.tiny_mode_widget.prime_from_nodes(cached_nodes)
            except Exception as exc:
                system_warning(f"Failed to prime tiny mode nodes: {exc}")

        # Switch to tiny mode widget after geometry is settled to avoid a visible resize jump
        self.stacked_widget.setCurrentWidget(self.tiny_mode_widget)
        
        # Update window title
        self.setWindowTitle(f"{self.WINDOW_TITLE_BASE} (Tiny Mode)")
    
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
        self._restore_comfy_footer_to_normal()

        # Restore normal mode geometry
        if self.normal_mode_geometry:
            self.restoreGeometry(self.normal_mode_geometry)
        
        # Update window title
        self.setWindowTitle(self.WINDOW_TITLE_BASE)
        
        # Focus the window after exiting command mode
        self.raise_()
        self.activateWindow()
        
        # Ensure keybind manager state is synced
        self.keybind_manager.tiny_mode_active = False

    def _open_charon_board_from_tiny_mode(self):
        """Exit tiny mode (if active) and focus the CharonBoard tab."""
        try:
            tiny_active = getattr(self.keybind_manager, "tiny_mode_active", False)
        except Exception:
            tiny_active = False

        if tiny_active:
            self.exit_tiny_mode()
        else:
            # Ensure the main widget is visible even if already in normal mode
            if getattr(self, "stacked_widget", None):
                self.stacked_widget.setCurrentWidget(self.normal_widget)

        index = -1
        try:
            index = self.center_tab_widget.indexOf(self.charon_board_panel)
        except Exception:
            index = -1

        if index != -1:
            self.center_tab_widget.setCurrentIndex(index)

        self.raise_()
        self.activateWindow()

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

    def _move_comfy_footer_to_tiny_mode(self) -> None:
        """Reparent the shared ComfyUI footer into the tiny mode layout."""
        if self._comfy_widget_in_tiny_mode:
            return
        widget = getattr(self, "comfy_connection_widget", None)
        if widget is None:
            return
        layout = self._footer_comfy_layout
        if layout is not None:
            try:
                layout.removeWidget(widget)
            except Exception:
                pass
        widget.setParent(None)
        self.tiny_mode_widget.attach_comfy_footer(widget)
        self._comfy_widget_in_tiny_mode = True

    def _restore_comfy_footer_to_normal(self) -> None:
        """Return the shared ComfyUI footer to the normal window layout."""
        if not self._comfy_widget_in_tiny_mode:
            return
        widget = self.tiny_mode_widget.detach_comfy_footer()
        if widget is None:
            self._comfy_widget_in_tiny_mode = False
            return
        layout = self._footer_comfy_layout
        if layout is not None:
            # Handle QGridLayout specifically to ensure correct placement
            if isinstance(layout, QtWidgets.QGridLayout):
                layout.addWidget(widget, 0, 2, Qt.AlignRight | Qt.AlignVCenter)
            else:
                layout.addWidget(widget)
            
            # Ensure correct parenting to the layout's container
            if layout.parentWidget():
                widget.setParent(layout.parentWidget())

        widget.setVisible(True)
        self._comfy_widget_in_tiny_mode = False
    
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
            self._debug_user_action("Refresh folders aborted (base path missing)")
            return

        self._debug_user_action(
            f"Refreshing folder panel (base={self.current_base}, host={self.host})"
        )

        # The script panel will handle clearing the metadata panel
        
        # Clear script panel
        self.script_panel.clear_scripts()

        # Invalidate cached folder listing so new directories appear immediately
        cache_manager = get_cache_manager()
        cache_manager.invalidate_cached_data(f"folders:{self.current_base}")
        self._debug_user_action("Invalidated cached folder listing for current base")

        # Start async folder loading
        self.folder_list_loader.load_folders(
            self.current_base,
            host=self.host,
        )
        self._debug_user_action("Started async folder load")
    
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
            name
            for name in folders
            if name
            and name != "Bookmarks"
            and (not user_slug or name.lower() != user_slug)
        }
        if user_slug and user_dir_exists:
            display_folders.append(user_slug)

        display_folders.extend(sorted(normal_folders, key=str.lower))

        # Update folder panel
        self.folder_panel.update_folders(display_folders)

        # Always apply folder compatibility check to update colors
        self._apply_folder_compatibility_async(display_folders)

        # Prefer restoring a pending selection (e.g., during refresh) to avoid flicker
        preferred = self._pending_folder_selection
        self._pending_folder_selection = None
        if preferred and preferred in display_folders:
            self.folder_panel.select_folder(preferred)
            return

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

    def _apply_folder_compatibility_async(self, folder_names):
        """Apply compatibility colors without blocking the UI thread."""
        if not self.current_base or not os.path.isdir(self.current_base):
            return

        cache_manager = get_cache_manager()
        compatibility = {}
        pending = []

        for folder_name in folder_names:
            if folder_name == "Bookmarks":
                continue

            folder_path = os.path.join(self.current_base, folder_name)
            cache_key = f"folder_nonempty_v2:{folder_path}"
            cached = cache_manager.get_cached_data(cache_key, max_age_seconds=600)
            if cached is not None:
                compatibility[folder_name] = bool(cached)
            else:
                pending.append((folder_name, folder_path, cache_key))

        if compatibility:
            self.folder_panel.apply_compatibility(compatibility)

        if not pending:
            return

        self._folder_probe_generation += 1
        generation = self._folder_probe_generation

        future: Future = self._folder_probe_executor.submit(
            self._probe_folder_compatibility, pending
        )
        future.add_done_callback(
            lambda f: self._on_folder_compatibility_ready(generation, f)
        )

    def _probe_folder_compatibility(self, pending):
        """Background task to check which folders have visible content."""
        cache_manager = get_cache_manager()
        results = {}
        for folder_name, folder_path, cache_key in pending:
            has_items = self._folder_has_visible_items(folder_path)
            cache_manager.cache_data(cache_key, has_items, ttl_seconds=600)
            results[folder_name] = has_items
        return results

    def _on_folder_compatibility_ready(self, generation, future: Future):
        """Apply compatibility results on the main thread, discarding stale runs."""
        if generation != self._folder_probe_generation:
            return

        try:
            results = future.result()
        except Exception as exc:
            system_error(f"Folder compatibility probe failed: {exc}")
            return

        if not results:
            return

        # Check if generation is still current before applying
        if generation != self._folder_probe_generation:
            return
        
        # Call directly - we're already on the main thread via the callback
        self.folder_panel.apply_compatibility(results)

    def on_refresh_clicked(self):
        """Handle public refresh request."""
        self._refresh_everything()

    def _folder_has_visible_items(self, folder_path):
        """Check if a folder contains any visible subfolders or JSON files."""
        try:
            if not os.path.exists(folder_path):
                return False
            # Use listdir for robustness on network shares
            for item in os.listdir(folder_path):
                if item.startswith('.'):
                    continue
                full_path = os.path.join(folder_path, item)
                if os.path.isdir(full_path):
                    return True
                if item.lower().endswith('.json'):
                    return True
            return False
        except Exception as exc:
            system_error(f"Error scanning folder contents for {folder_path}: {exc}")
            return False

    def on_folder_selected(self, folder_name):
        if not folder_name:
            return
        self._debug_user_action(
            f"Folder selected: {folder_name} (base={self.current_base})"
        )
        
        # Skip deselection if we're navigating programmatically
        if not self._is_navigating:
            # Always clear current script selection and hide metadata panel when changing folders
            # This includes re-selecting the same folder
            if self.script_panel.current_script:
                self._debug_user_action("Clearing current script selection for new folder")
                self.script_panel.on_script_deselected()
        
        # Don't clear cache during normal folder switching - this was causing slowdown
        # Cache will be populated as needed when scripts are loaded
        
        # Store current folder
        self._last_selected_folder = folder_name
        
        # Clear tag filter when changing folders
        self.tag_bar.clear_selection()
        # Clear existing tags - they'll be repopulated when scripts load
        self.tag_bar.update_tags([])
        self._debug_user_action("Cleared tag filters and tag list for new folder")
        
        # Check if this is the special Bookmarks folder
        if folder_name == "Bookmarks":
            # Handle bookmarks folder
            # Clear current folder for bookmarks view
            self.current_folder = None
            
            # Load bookmarked scripts
            self.load_bookmarked_scripts()
            self._debug_user_action("Loaded bookmarked workflows")
            return
        
        folder_path = os.path.join(self.current_base, folder_name)
        
        # Track the current folder for efficient tag loading
        self.current_folder = folder_path
        self._debug_user_action(f"Set current folder path: {folder_path}")
        
        if os.path.isdir(folder_path):
            # The script panel will handle clearing the metadata panel
            
            # NOTE: Don't clear cache during folder switching - this causes performance issues
            # The background loader will handle loading fresh data if needed
            # refresh_metadata("folder", folder_path=folder_path, clear_cache=True)
            
            # Load scripts in background thread for better responsiveness
            self.script_panel.load_scripts_for_folder(folder_path)
            self._debug_user_action(f"Loading scripts for folder: {folder_path}")
        else:
            self._debug_user_action(f"Folder path missing on selection: {folder_path}")

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
        Handles all UI refresh logic when a script's metadata changes.
        This is the authoritative refresh function.
        """
        # Mark quick-search index dirty and trigger a rebuild
        self._start_async_indexing()

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

    def _perform_soft_refresh(self, refresh_folders=False):
        """
        Performs a soft refresh of the UI, preserving the user's selection.

        This is used after an action (like bookmarking)
        that requires the UI to update but should not disrupt the user's flow.

        Args:
            refresh_folders (bool): If True, the folder list will also be
                                    refreshed. This is needed when an action
                                    might add or remove the 'Bookmarks' folder.
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
        # Prepare script panel for bookmark load so results are not dropped
        if hasattr(self, "script_panel"):
            self.script_panel.begin_bookmark_load()
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
        
        # In tiny mode, quick search is always available
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

    def _set_refresh_enabled(self, enabled: bool):
        """Enable/disable refresh triggers to prevent overlapping work."""
        try:
            if hasattr(self, "header_refresh_button"):
                self.header_refresh_button.setEnabled(enabled)
        except Exception:
            pass

    def on_refresh_clicked(self):
        """Handle the refresh button click."""
        # Throttle repeated clicks to avoid overlapping work in background threads
        now = time.monotonic()
        if self._refresh_in_progress:
            self._debug_user_action("Refresh ignored (already in progress)")
            system_debug("Refresh already in progress; ignoring additional trigger")
            return
        if now - getattr(self, "_last_refresh_time", 0.0) < 0.35:
            self._debug_user_action("Refresh ignored (throttled)")
            system_debug("Refresh ignored due to rapid re-trigger")
            return

        self._refresh_in_progress = True
        self._last_refresh_time = now
        self._set_refresh_enabled(False)
        # Store current focus widget to restore it later
        current_focus = QtWidgets.QApplication.focusWidget()

        try:
            # Get current state
            current_folder = self.folder_panel.get_selected_folder()
            is_bookmarks = current_folder == "Bookmarks"
            current_script = self.script_panel.get_selected_script()
            current_script_path = getattr(current_script, "path", None) if current_script else None
            self._debug_user_action(
                f"Refresh started (folder={current_folder or 'None'}, "
                f"script={current_script_path or 'None'})"
            )
            
            # Import cache manager
            from ..cache_manager import get_cache_manager
            cache_manager = get_cache_manager()

            # Simplified approach: Either refresh current folder or everything
            if current_script or current_folder:
                # Refresh current folder (whether script or folder is selected)
                folder_path = None
                if current_script:
                    folder_path = os.path.dirname(current_script.path)
                elif current_folder and not is_bookmarks:
                    folder_path = os.path.join(self.current_base, current_folder)
                self._debug_user_action(f"Refreshing current folder: {folder_path or 'Bookmarks'}")
                self._pending_folder_selection = current_folder
                
                # Clear LRU cache since we're doing a refresh anyway
                from ..metadata_manager import clear_metadata_cache
                clear_metadata_cache()
                self._debug_user_action("Cleared metadata cache before folder refresh")
                
                # Clear the cached folder list to ensure we pick up new folders
                folder_list_cache_key = f"folders:{self.current_base}"
                cache_manager.invalidate_cached_data(folder_list_cache_key)
                system_debug(f"Cleared folder list cache for {self.current_base}")
                self._debug_user_action(
                    f"Invalidated folder list cache for base {self.current_base}"
                )
                
                # Invalidate folder in persistent cache (skip special Bookmarks pseudo-folder)
                if folder_path:
                    cache_manager.invalidate_folder(folder_path)
                    self._debug_user_action(f"Invalidated cached folder data: {folder_path}")
                
                # Refresh the folder panel to pick up any new folders/bookmark visibility
                stored_folder = current_folder
                self.refresh_folder_panel()
                self._debug_user_action("Triggered folder panel refresh (current folder)")
                
                # Restore selection and reload scripts after folder panel updates
                def restore_and_reload():
                    if stored_folder:
                        self.folder_panel.select_folder(stored_folder)
                        self._debug_user_action(
                            f"Re-selected folder after refresh: {stored_folder}"
                        )
                    # Reload scripts for the folder or bookmarks
                    if stored_folder == "Bookmarks":
                        self.load_bookmarked_scripts()
                        self._debug_user_action("Reloaded bookmarked workflows after refresh")
                    else:
                        self.script_panel.load_scripts_for_folder(folder_path)
                        self._debug_user_action(
                            f"Reloaded scripts for folder: {folder_path}"
                        )
                    # Update metadata panel if a script is selected
                    if current_script:
                        self.metadata_panel.update_metadata(current_script.path)
                        self._debug_user_action(
                            f"Updated metadata for script: {current_script.path}"
                        )
                
                QtCore.QTimer.singleShot(100, restore_and_reload)
            else:
                # Nothing selected - refresh everything
                self._debug_user_action("No selection; triggering full refresh")
                self._refresh_everything()
            
            # Re-index quick search
            self._start_async_indexing()
            self._debug_user_action("Started async quick-search reindex")

            # Update CharonBoard state as part of the unified refresh
            try:
                if hasattr(self, "charon_board_panel"):
                    self.charon_board_panel.refresh_nodes()
                    self._debug_user_action("Refreshed CharonBoard nodes")
            except Exception as board_exc:
                system_warning(f"CharonBoard refresh failed: {board_exc}")
            
            # Restart resource monitor to ensure it's healthy
            if hasattr(self, "resource_widget"):
                try:
                    self.resource_widget.restart_monitor()
                    self._debug_user_action("Restarted resource monitor")
                except Exception as exc:
                    system_warning(f"Failed to restart resource monitor: {exc}")

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
            self._refresh_in_progress = False
            self._set_refresh_enabled(True)
            self._debug_user_action("Refresh finished")

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
        """History panel disabled in current layout."""
        return
            
    def _collapse_history_panel(self):
        """History panel disabled in current layout."""
        return
    
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
        """Prefetch bookmarks from database at startup."""
        try:
            from ..settings import user_settings_db
            # These queries will be slow the first time but cached after
            system_debug("Prefetching user bookmarks")

            all_bookmarks = user_settings_db.get_bookmarks()
            system_debug(f"Prefetched {len(all_bookmarks)} bookmarks")

            # Store in script panel's cache so it doesn't need to query again
            if hasattr(self.script_panel, '_refresh_user_data_cache'):
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
        
        # Prefetch bookmarks at startup
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
