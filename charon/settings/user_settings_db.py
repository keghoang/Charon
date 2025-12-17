import os
import sqlite3
import datetime
import shutil
from typing import Optional

from .. import config
from ..preferences import get_preferences_root

_DB_PATH = None


def _host_allows_app_settings(host):
    host_key = normalize_host_key(host)
    return bool(config.SOFTWARE.get(host_key, {}).get("host_settings", False))


def normalize_host_key(host):
    """Normalize host names for namespaced settings keys."""
    if not host:
        return "standalone"
    host_key = str(host).strip().split()[0].lower()
    hosts = getattr(config, "APP_SETTING_HOSTS", ())
    if host_key not in hosts:
        return "standalone"
    return host_key


def normalize_path(path):
    """
    Normalize a path for consistent database comparisons.
    This ensures that paths with different separators are treated as the same.
    """
    if not path:
        return path
    return os.path.normpath(path)


def initialize(global_repo_path):
    """
    Initializes the database path using the provided global repository path.
    This must be called once at application startup before any other functions
    in this module are used.
    
    Note: The database is now stored locally in AppData for better performance.
    The global_repo_path parameter is kept for compatibility but no longer used.
    """
    global _DB_PATH
    
    # Use the same root as preferences, derived from GALT_PLUGIN_DIR or default
    db_base_folder = get_preferences_root(ensure_dir=True)
    db_folder = os.path.join(db_base_folder, "db") # Subfolder for DB files
    if not os.path.exists(db_folder):
        os.makedirs(db_folder, exist_ok=True)

    # Check if we need to migrate from old database
    old_db_path = os.path.join(db_folder, "hotkeys.db")
    new_db_path = os.path.join(db_folder, "settings.db")
    
    if os.path.exists(old_db_path) and not os.path.exists(new_db_path):
        # Migrate from old database
        _migrate_from_old_database(old_db_path, new_db_path)
    
    _DB_PATH = new_db_path

    # Create tables if they don't exist
    _create_tables_if_not_exist()

    # Ensure default application settings exist
    ensure_app_settings_defaults()
    
    # Normalize existing paths to fix inconsistencies
    normalize_database_paths()


def _migrate_from_old_database(old_db_path, new_db_path):
    """Migrate data from the old user-based database to the new userless database."""
    from ..charon_logger import system_info, system_error
    
    try:
        system_info("Migrating settings database from old format...")
        
        # Connect to old database
        old_conn = sqlite3.connect(old_db_path)
        old_cursor = old_conn.cursor()
        
        # Create new database
        new_conn = sqlite3.connect(new_db_path)
        new_cursor = new_conn.cursor()
        
        # Create new tables without user column
        new_cursor.execute("""
        CREATE TABLE IF NOT EXISTS hotkeys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hotkey TEXT NOT NULL,
            script TEXT NOT NULL,
            software TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(hotkey, software)
        )
        """)

        new_cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            script_path TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(script_path)
        )
        """)

        new_cursor.execute("""
        CREATE TABLE IF NOT EXISTS local_keybind_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_name TEXT NOT NULL,
            key_sequence TEXT NOT NULL,
            enabled INTEGER DEFAULT 1,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(action_name)
        )
        """)

        new_cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)

# Migrate hotkeys (take the most recent entry for each hotkey/software combo)
        old_cursor.execute("""
            SELECT hotkey, script, software, MAX(timestamp) as latest_timestamp
            FROM hotkeys
            GROUP BY hotkey, software
        """)
        hotkeys = old_cursor.fetchall()
        for hotkey, script, software, timestamp in hotkeys:
            new_cursor.execute(
                "INSERT OR IGNORE INTO hotkeys (hotkey, script, software, timestamp) VALUES (?, ?, ?, ?)",
                (hotkey, script, software, timestamp)
            )
        
        # Migrate bookmarks (take the most recent entry for each script_path)
        old_cursor.execute("""
            SELECT script_path, MAX(timestamp) as latest_timestamp
            FROM bookmarks
            GROUP BY script_path
        """)
        bookmarks = old_cursor.fetchall()
        for script_path, timestamp in bookmarks:
            new_cursor.execute(
                "INSERT OR IGNORE INTO bookmarks (script_path, timestamp) VALUES (?, ?)",
                (script_path, timestamp)
            )
        
        # Migrate local keybind settings (take the most recent entry for each action)
        old_cursor.execute("""
            SELECT action_name, key_sequence, enabled, MAX(timestamp) as latest_timestamp
            FROM local_keybind_settings
            GROUP BY action_name
        """)
        keybinds = old_cursor.fetchall()
        for action_name, key_sequence, enabled, timestamp in keybinds:
            new_cursor.execute(
                "INSERT OR IGNORE INTO local_keybind_settings (action_name, key_sequence, enabled, timestamp) VALUES (?, ?, ?, ?)",
                (action_name, key_sequence, enabled, timestamp)
            )
        
        # Commit and close
        new_conn.commit()
        new_conn.close()
        old_conn.close()
        
        # Rename old database to backup
        backup_path = old_db_path + ".bak"
        shutil.move(old_db_path, backup_path)
        
        system_info("Successfully migrated settings database")
        
    except Exception as e:
        system_error(f"Error migrating database: {e}")
        # If migration fails, just use the new database
        if os.path.exists(new_db_path):
            os.remove(new_db_path)


def _get_db_path():
    """Gets the database path, ensuring it has been initialized."""
    if _DB_PATH is None:
        raise RuntimeError(
            "The user_settings_db module has not been initialized. "
            "Please call user_settings_db.initialize(global_repo_path) at startup."
        )
    return _DB_PATH

def get_storage_directory():
    """Return the directory containing the settings database."""
    return os.path.dirname(_get_db_path())


def get_connection():
    """Gets a new database connection with proper settings for network drives."""
    conn = sqlite3.connect(_get_db_path(), timeout=30.0)  # 30 second timeout
    # Note: WAL mode is persistent per database file, no need to set it every time
    # Just set busy timeout for better concurrency
    conn.execute("PRAGMA busy_timeout=30000")  # 30 seconds
    return conn


def _create_tables_if_not_exist():
    """Internal function to create database tables."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Set WAL mode once during initialization (it's persistent)
    cursor.execute("PRAGMA journal_mode=WAL")
    
    # Create hotkeys table without user column
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS hotkeys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotkey TEXT NOT NULL,
        script TEXT NOT NULL,
        software TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(hotkey, software)
    )
    """)

    # Create bookmarks table without user column
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bookmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        script_path TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(script_path)
    )
    """)
    
    # Create local keybind settings table without user column
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS local_keybind_settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action_name TEXT NOT NULL,
        key_sequence TEXT NOT NULL,
        enabled INTEGER DEFAULT 1,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(action_name)
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    conn.commit()
    conn.close()


def set_hotkey(hotkey, script, software):
    """
    Assign a hotkey to a script in the database.
    This will remove any existing hotkey assignments for:
    1. This specific hotkey for this software
    2. Any other hotkey assigned to this script
    """
    # Normalize the script path
    script = normalize_path(script)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # First, remove any existing assignment of this hotkey for this software
    cursor.execute(
        "DELETE FROM hotkeys WHERE hotkey = ? AND software = ?",
        (hotkey, software)
    )
    
    # Also, remove any other hotkeys assigned to this script
    cursor.execute(
        "DELETE FROM hotkeys WHERE script = ? AND software = ?",
        (script, software)
    )
    
    # Now add the new assignment
    cursor.execute(
        "INSERT INTO hotkeys (hotkey, script, software) VALUES (?, ?, ?)",
        (hotkey, script, software)
    )
    
    conn.commit()
    conn.close()


def get_script_for_hotkey(hotkey, software):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT script FROM hotkeys WHERE hotkey = ? AND software = ?", 
        (hotkey, software)
    )
    row = cursor.fetchone()
    conn.close()
    # Return normalized path for consistency
    return normalize_path(row[0]) if row else None


def get_hotkey_for_script(script, software=None):
    """
    Returns the hotkey assigned to the given script,
    or None if no hotkey is assigned.
    
    If software is provided, only hotkeys for that specific software are returned.
    """
    # Normalize the script path
    script = normalize_path(script)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    if software:
        cursor.execute(
            "SELECT hotkey FROM hotkeys WHERE script = ? AND software = ?", 
            (script, software)
        )
    else:
        cursor.execute(
            "SELECT hotkey FROM hotkeys WHERE script = ?", 
            (script,)
        )
    
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def get_all_hotkeys(software):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT hotkey, script FROM hotkeys WHERE software = ?", 
        (software,)
    )
    hotkeys = cursor.fetchall()
    conn.close()
    # Normalize all script paths in the returned dictionary
    return {hotkey: normalize_path(script) for hotkey, script in hotkeys}


def remove_hotkey_for_script_software(script_path, software):
    """
    Removes a hotkey assignment for a specific script and software.
    """
    # Normalize the script path
    script_path = normalize_path(script_path)
    
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM hotkeys WHERE script = ? AND software = ?",
        (script_path, software)
    )
    conn.commit()
    conn.close()


def cleanup_missing_scripts(software):
    """
    Remove hotkey assignments for scripts that no longer exist.
    Returns a list of removed script paths.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get all scripts for this software
    cursor.execute(
        "SELECT script FROM hotkeys WHERE software = ?", 
        (software,)
    )
    scripts = [row[0] for row in cursor.fetchall()]
    
    # Check which scripts don't exist anymore
    missing_scripts = []
    for script_path in scripts:
        if not os.path.exists(script_path):
            missing_scripts.append(script_path)
            cursor.execute(
                "DELETE FROM hotkeys WHERE software = ? AND script = ?",
                (software, script_path)
            )
    
    conn.commit()
    conn.close()
    return missing_scripts


def add_bookmark(script_path):
    """
    Add a bookmark for a script.
    Returns True if successful, False if bookmark already exists.
    """
    # Normalize the script path
    script_path = normalize_path(script_path)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get current timestamp in ISO format
    timestamp = datetime.datetime.now().isoformat()
    
    try:
        cursor.execute(
            "INSERT INTO bookmarks (script_path, timestamp) VALUES (?, ?)",
            (script_path, timestamp)
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        # Bookmark already exists
        conn.close()
        return False


def remove_bookmark(script_path):
    """
    Remove a bookmark for a script.
    Returns True if bookmark was removed, False if it didn't exist.
    """
    # Normalize the script path
    script_path = normalize_path(script_path)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "DELETE FROM bookmarks WHERE script_path = ?",
        (script_path,)
    )
    
    rows_affected = cursor.rowcount
    conn.commit()
    conn.close()
    
    return rows_affected > 0


def get_bookmarks():
    """
    Get all bookmarks.
    Returns a list of script paths ordered by timestamp (newest first).
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT script_path FROM bookmarks ORDER BY timestamp DESC"
    )
    bookmarks = [normalize_path(row[0]) for row in cursor.fetchall()]
    
    conn.close()
    return bookmarks


def is_bookmarked(script_path):
    """
    Check if a script is bookmarked.
    Returns True if bookmarked, False otherwise.
    """
    # Normalize the script path
    script_path = normalize_path(script_path)
    
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT 1 FROM bookmarks WHERE script_path = ?",
        (script_path,)
    )
    result = cursor.fetchone()
    
    conn.close()
    return result is not None


def cleanup_missing_bookmarks():
    """
    Remove bookmarks for scripts that no longer exist.
    Returns a list of removed script paths.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Get all bookmarks
    cursor.execute("SELECT script_path FROM bookmarks")
    bookmarks = [row[0] for row in cursor.fetchall()]
    
    # Check which scripts don't exist anymore
    missing_bookmarks = []
    for script_path in bookmarks:
        if not os.path.exists(script_path):
            missing_bookmarks.append(script_path)
            cursor.execute(
                "DELETE FROM bookmarks WHERE script_path = ?",
                (script_path,)
            )
    
    conn.commit()
    conn.close()
    return missing_bookmarks


# Local keybind customization functions

def set_local_keybind(action_name, key_sequence, enabled=True):
    """
    Set a custom local keybind.
    
    Args:
        action_name: Action name (e.g., 'run_script')
        key_sequence: Key sequence (e.g., 'Ctrl+Return')
        enabled: Whether the keybind is enabled
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT OR REPLACE INTO local_keybind_settings 
        (action_name, key_sequence, enabled)
        VALUES (?, ?, ?)
    """, (action_name, key_sequence, int(enabled)))
    
    conn.commit()
    conn.close()


def get_local_keybind(action_name):
    """
    Get a custom local keybind setting.
    
    Returns:
        Tuple of (key_sequence, enabled) or None if not customized
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT key_sequence, enabled FROM local_keybind_settings WHERE action_name = ?",
        (action_name,)
    )
    result = cursor.fetchone()
    
    conn.close()
    
    if result:
        return (result[0], bool(result[1]))
    return None


def get_all_local_keybinds():
    """Get all custom local keybind settings."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT action_name, key_sequence, enabled FROM local_keybind_settings"
    )
    
    keybinds = {}
    for row in cursor.fetchall():
        keybinds[row[0]] = {
            'key_sequence': row[1],
            'enabled': bool(row[2])
        }
    
    conn.close()
    return keybinds


def reset_local_keybind(action_name):
    """Reset a local keybind to default."""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "DELETE FROM local_keybind_settings WHERE action_name = ?",
        (action_name,)
    )
    
    conn.commit()
    conn.close()


def get_or_create_local_keybinds():
    """
    Get local keybinds, creating defaults if they don't exist.
    Also adds any new default keybinds that are missing.
    
    Returns:
        dict: Dictionary of action_name -> {'key_sequence': str, 'enabled': bool}
    """
    # Import here to avoid circular imports
    from ..config import DEFAULT_LOCAL_KEYBINDS
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Migration: Handle command_mode to tiny_mode transition
    # First check if command_mode exists
    cursor.execute(
        "SELECT key_sequence, enabled FROM local_keybind_settings WHERE action_name = 'command_mode'"
    )
    command_mode_row = cursor.fetchone()
    
    if command_mode_row:
        # Command mode exists, need to migrate
        # First delete any existing tiny_mode entry
        cursor.execute(
            "DELETE FROM local_keybind_settings WHERE action_name = 'tiny_mode'"
        )
        # Now rename command_mode to tiny_mode
        cursor.execute(
            "UPDATE local_keybind_settings SET action_name = 'tiny_mode' WHERE action_name = 'command_mode'"
        )
        conn.commit()
    
    # Get existing keybinds
    cursor.execute(
        "SELECT action_name, key_sequence, enabled FROM local_keybind_settings"
    )
    
    keybinds = {}
    existing_actions = set()
    for row in cursor.fetchall():
        action_name = row[0]
        keybinds[action_name] = {
            'key_sequence': row[1],
            'enabled': bool(row[2])
        }
        existing_actions.add(action_name)

    # Migration: update tiny_mode default keybind from F2 to F3 when unchanged by user.
    tiny_entry = keybinds.get("tiny_mode")
    if tiny_entry:
        seq_normalized = (tiny_entry.get("key_sequence") or "").strip().upper()
        if seq_normalized == "F2":
            cursor.execute(
                "UPDATE local_keybind_settings SET key_sequence = ? WHERE action_name = 'tiny_mode'",
                ("F3",),
            )
            tiny_entry["key_sequence"] = "F3"
    
    # Check for any missing default keybinds and add them
    for action, default_config in DEFAULT_LOCAL_KEYBINDS.items():
        if action not in existing_actions:
            # Add the missing default keybind
            cursor.execute("""
                INSERT INTO local_keybind_settings 
                (action_name, key_sequence, enabled)
                VALUES (?, ?, ?)
            """, (action, default_config['key_sequence'], int(default_config['enabled'])))
            # Add to our return dictionary
            keybinds[action] = {
                'key_sequence': default_config['key_sequence'],
                'enabled': default_config['enabled']
            }
    
    conn.commit()
    conn.close()
    
    return keybinds





def _migrate_legacy_app_settings(cursor):
    """Backfill host-scoped keys from legacy app_settings rows."""
    definitions = getattr(config, "APP_SETTING_DEFINITIONS", {})
    hosts = getattr(config, "APP_SETTING_HOSTS", ())
    if not definitions or not hosts:
        return
    for base_key, meta in definitions.items():
        legacy_key = base_key
        cursor.execute("SELECT value FROM app_settings WHERE key = ?", (legacy_key,))
        row = cursor.fetchone()
        if not row:
            continue
        value = row[0]
        slug = meta.get("slug", base_key)
        for host in hosts:
            namespaced_key = f"{slug}-{host}"
            cursor.execute("INSERT OR IGNORE INTO app_settings (key, value, timestamp) VALUES (?, ?, CURRENT_TIMESTAMP)", (namespaced_key, value))
        cursor.execute("DELETE FROM app_settings WHERE key = ?", (legacy_key,))

def ensure_app_settings_defaults():
    """Ensure default application settings exist in the database."""
    defaults = getattr(config, "DEFAULT_APP_SETTINGS", None)
    if not defaults:
        return
    conn = get_connection()
    cursor = conn.cursor()
    try:
        _migrate_legacy_app_settings(cursor)
        for key, default_value in defaults.items():
            cursor.execute(
                "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)",
                (key, default_value),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()




def get_app_settings():
    """Return all persisted application settings as a dict."""
    ensure_app_settings_defaults()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM app_settings")
    results = {key: value for key, value in cursor.fetchall()}
    conn.close()
    for key, default_value in config.DEFAULT_APP_SETTINGS.items():
        results.setdefault(key, default_value)
    return results


def get_app_setting(key: str, default: Optional[str] = None) -> str:
    """Fetch a single application setting with fallback to defaults."""
    values = get_app_settings()
    if default is None:
        default = config.DEFAULT_APP_SETTINGS.get(key)
    return values.get(key, default)


def set_app_setting(key: str, value: str) -> None:
    """Persist an application setting."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO app_settings (key, value, timestamp)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, timestamp = CURRENT_TIMESTAMP
        """,
        (key, value),
    )
    conn.commit()
    conn.close()



def get_app_settings_for_host(host):
    """Return app settings for the given host using base setting keys."""
    definitions = getattr(config, "APP_SETTING_DEFINITIONS", {})
    if not definitions:
        return {}
    host_key = normalize_host_key(host)
    if not _host_allows_app_settings(host):
        results = {}
        for base_key, meta in definitions.items():
            slug = meta.get("slug", base_key)
            namespaced_key = f"{slug}-{host_key}"
            results[base_key] = config.DEFAULT_APP_SETTINGS.get(namespaced_key, meta.get("default"))
        return results
    values = get_app_settings()
    results = {}
    for base_key, meta in definitions.items():
        slug = meta.get("slug", base_key)
        namespaced_key = f"{slug}-{host_key}"
        default = config.DEFAULT_APP_SETTINGS.get(namespaced_key, meta.get("default"))
        results[base_key] = values.get(namespaced_key, default)
    return results


def get_app_setting_for_host(base_key: str, host, default: Optional[str] = None) -> str:
    """Fetch a setting for a specific host, falling back to defaults."""
    definitions = getattr(config, "APP_SETTING_DEFINITIONS", {})
    meta = definitions.get(base_key)
    host_key = normalize_host_key(host)
    if not _host_allows_app_settings(host):
        if meta and default is None:
            default = meta.get("default")
        return config.DEFAULT_APP_SETTINGS.get(f"{config.APP_SETTING_SLUGS.get(base_key, base_key)}-{host_key}", default)
    if meta:
        slug = meta.get("slug", base_key)
        namespaced_key = f"{slug}-{host_key}"
        if default is None:
            default = config.DEFAULT_APP_SETTINGS.get(namespaced_key, meta.get("default"))
        return get_app_setting(namespaced_key, default)
    return get_app_setting(base_key, default)


def set_app_setting_for_host(base_key: str, host, value: str) -> None:
    """Persist a host-specific application setting."""
    definitions = getattr(config, "APP_SETTING_DEFINITIONS", {})
    meta = definitions.get(base_key)
    if not _host_allows_app_settings(host) or not meta:
        return
    slug = meta.get("slug", base_key)
    host_key = normalize_host_key(host)
    namespaced_key = f"{slug}-{host_key}"
    set_app_setting(namespaced_key, value)

def reset_app_settings_for_host(host) -> None:
    """Reset all host-scoped settings to defaults for the given host."""
    definitions = getattr(config, "APP_SETTING_DEFINITIONS", {})
    if not definitions:
        return
    if not _host_allows_app_settings(host):
        return
    host_key = normalize_host_key(host)
    for base_key, meta in definitions.items():
        slug = meta.get("slug", base_key)
        default_value = config.DEFAULT_APP_SETTINGS.get(f"{slug}-{host_key}", meta.get("default"))
        if default_value is None:
            default_value = meta.get("default", "")
        set_app_setting_for_host(base_key, host, default_value)

def normalize_database_paths():
    """
    Normalize all paths in the database to use consistent format.
    This fixes issues with paths stored with different separators.
    """
    import os
    from ..charon_logger import system_info, system_error
    
    conn = get_connection()
    cursor = conn.cursor()
    
    try:
        # Normalize hotkeys paths
        cursor.execute("SELECT id, script FROM hotkeys")
        hotkeys = cursor.fetchall()
        
        normalized_count = 0
        for hk_id, script_path in hotkeys:
            normalized = os.path.normpath(script_path)
            if normalized != script_path:
                cursor.execute("UPDATE hotkeys SET script = ? WHERE id = ?", (normalized, hk_id))
                normalized_count += 1
        
        # Normalize bookmarks paths
        cursor.execute("SELECT id, script_path FROM bookmarks")
        bookmarks = cursor.fetchall()
        
        for bm_id, script_path in bookmarks:
            normalized = os.path.normpath(script_path)
            if normalized != script_path:
                cursor.execute("UPDATE bookmarks SET script_path = ? WHERE id = ?", (normalized, bm_id))
                normalized_count += 1
        
        if normalized_count > 0:
            conn.commit()
            system_info(f"Normalized {normalized_count} paths in database")
        
        # Clean up duplicates after normalization
        # For hotkeys: keep the most recent for each hotkey/software combo
        cursor.execute("""
            DELETE FROM hotkeys
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM hotkeys
                GROUP BY hotkey, script, software
            )
        """)
        
        # For bookmarks: keep the most recent for each script path
        cursor.execute("""
            DELETE FROM bookmarks  
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM bookmarks
                GROUP BY script_path
            )
        """)
        
        conn.commit()
        
    except Exception as e:
        system_error(f"Error normalizing database paths: {e}")
        conn.rollback()
    finally:
        conn.close()
