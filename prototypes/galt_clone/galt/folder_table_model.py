from .qt_compat import QtCore, QtGui, Qt, UserRole, DisplayRole, Horizontal
from .utilities import is_compatible_with_host, apply_incompatible_opacity, get_software_color_for_metadata
from .metadata_manager import is_folder_compatible_with_host
import os


class FolderItem:
    """Simple folder item class to match ScriptItem pattern"""
    def __init__(self, name, path, is_special=False):
        self.name = name
        self.path = path
        self.is_special = is_special  # For Bookmarks folder
        

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
        self.host = "None"
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
                
            # Check compatibility for regular folders
            is_compatible = True
            if self.base_path:
                folder_path = os.path.join(self.base_path, folder.name)
                is_compatible = is_folder_compatible_with_host(folder_path, self.host)
                
            if not is_compatible:
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
            if self.base_path:
                folder_path = os.path.join(self.base_path, folder.name)
                return is_folder_compatible_with_host(folder_path, self.host)
            return True
            
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
        
    def clear(self):
        """Clear all folders"""
        self.beginResetModel()
        self.folders = []
        self.endResetModel()
        
    def sortItems(self):
        """Sort folders using the centralized folder sorting logic"""
        from galt.utilities import create_folder_sort_key
        # For folders, we need to pass the original name for sorting
        self.folders.sort(key=lambda f: create_folder_sort_key(
            getattr(f, 'original_name', f.name),  # Use original name if available
            self.host, 
            self.base_path
        ))
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