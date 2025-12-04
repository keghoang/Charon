from .qt_compat import QtCore, QtGui, Qt, UserRole, DisplayRole, Horizontal
from .utilities import apply_incompatible_opacity
import os


class FolderItem:
    """Simple folder item class to match ScriptItem pattern"""
    def __init__(self, name, path, is_special=False):
        self.name = name
        self.path = path
        self.is_special = is_special  # For Bookmarks folder
        self.is_compatible = True  # Default to optimistic True until checked
        

class FolderTableModel(QtCore.QAbstractTableModel):
    """Table model for displaying folders with a single column"""
    
    # Column indices
    COL_NAME = 0
    COLUMN_COUNT = 1
    
    # Custom roles
    FolderRole = UserRole + 1
    PathRole = UserRole + 2
    CompatibleRole = UserRole + 3
    
    def __init__(self, parent=None):
        super(FolderTableModel, self).__init__(parent)
        self.folders = []
        self.host = "Nuke"
        self.base_path = None
        
    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0
        return len(self.folders)
        
    def columnCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0
        return self.COLUMN_COUNT
        
    def data(self, index, role=DisplayRole):
        if not index.isValid() or index.row() >= len(self.folders):
            return None
            
        folder = self.folders[index.row()]
        
        if role == DisplayRole:
            return folder.name
            
        elif role == Qt.ForegroundRole:
            # Special folders get default color
            if folder.is_special:
                return None
                
            # Check compatibility using cached state
            if not folder.is_compatible:
                color = QtGui.QColor("#95a5a6")  # Default gray
                return QtGui.QBrush(apply_incompatible_opacity(color))
                
        elif role == Qt.FontRole:
            # Make special folders bold
            if folder.is_special:
                font = QtGui.QFont()
                font.setBold(True)
                return font
                
        # Custom roles
        elif role == self.FolderRole:
            return folder
        elif role == self.PathRole:
            return folder.path
        elif role == self.CompatibleRole:
            if folder.is_special:
                return True
            return folder.is_compatible
            
        return None
        
    def headerData(self, section, orientation, role=DisplayRole):
        """Provide header labels for columns"""
        if orientation == Horizontal and role == DisplayRole:
            return "Folders"
        return None
        
    def updateItems(self, folders):
        """Update the model with new folder items"""
        self.beginResetModel()
        self.folders = folders
        self.endResetModel()
        
    def update_compatibility(self, compatibility_map):
        """Update compatibility status for folders from a map"""
        if not compatibility_map:
            return
            
        changed = False
        for folder in self.folders:
            # Look up by original name (folder name)
            name = getattr(folder, 'original_name', folder.name)
            if name in compatibility_map:
                new_state = compatibility_map[name]
                if folder.is_compatible != new_state:
                    folder.is_compatible = new_state
                    changed = True
        
        if changed:
            self.sortItems()
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(len(self.folders) - 1, 0)
            )
        
    def clear(self):
        """Clear all folders"""
        self.beginResetModel()
        self.folders = []
        self.endResetModel()
        
    def sortItems(self):
        """Sort folders using cached properties to avoid I/O"""
        def sort_key(folder):
            is_current_user = getattr(folder, "is_current_user", False)
            # 1. Special folders (Bookmarks)
            if folder.is_special:
                priority = 0
            # 2. Current user's folder
            elif is_current_user:
                priority = 1
            # 3. Compatible folders
            elif folder.is_compatible:
                priority = 2
            # 4. Incompatible folders
            else:
                priority = 3
                
            # Secondary sort: alphabetical by original name or display name
            name = getattr(folder, 'original_name', folder.name).lower()
            return (priority, name)
            
        self.folders.sort(key=sort_key)
        self.layoutChanged.emit()
        
    def set_host(self, host):
        """Set the host software and refresh if needed"""
        if self.host != host:
            self.host = host
            if self.folders:
                self.sortItems()
                # Trigger visual refresh
                self.dataChanged.emit(
                    self.index(0, 0),
                    self.index(len(self.folders) - 1, 0)
                )
                
    def set_base_path(self, base_path):
        """Set the base path for compatibility checking"""
        self.base_path = base_path
        
    def get_folder_at_row(self, row):
        """Get folder at given row index"""
        if 0 <= row < len(self.folders):
            return self.folders[row]
        return None
    
    def add_folder(self, folder_item):
        """Add a single folder to the model and re-sort"""
        # Check if folder already exists
        for existing in self.folders:
            if existing.name == folder_item.name:
                return  # Already exists
        
        # Add the folder
        self.beginInsertRows(QtCore.QModelIndex(), len(self.folders), len(self.folders))
        self.folders.append(folder_item)
        self.endInsertRows()
        
        # Re-sort
        self.sortItems()
    
    def remove_folder_by_name(self, folder_name):
        """Remove a folder by name"""
        for i, folder in enumerate(self.folders):
            if hasattr(folder, 'original_name') and folder.original_name == folder_name:
                self.beginRemoveRows(QtCore.QModelIndex(), i, i)
                self.folders.pop(i)
                self.endRemoveRows()
                break
