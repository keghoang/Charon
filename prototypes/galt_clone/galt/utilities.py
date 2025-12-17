import re, html, os
try:
    from galt import config
except ImportError:
    from . import config

def md_to_html(md_text, base_path=None):
    """
    Markdown to HTML converter with support for:
    - Tables
    - Code blocks with syntax highlighting
    - Headers (h1-h6)
    - Bold and italic text
    - Links (standard markdown format)
    - Images
    - Ordered and unordered lists
    - Blockquotes
    - Horizontal rules
    
    Args:
        md_text (str): The markdown text to convert.
        base_path (str, optional): The base directory for resolving relative paths, 
                                 like for images. Defaults to None.
    """
    import html
    import re
    from .qt_compat import QtWidgets, QtCore
    
    # Get Qt palette colors for theme inheritance
    app = QtWidgets.QApplication.instance()
    if app:
        palette = app.palette()
        text_color = palette.text().color().name()
        background_color = palette.window().color().name()
        base_color = palette.base().color().name()
        button_color = palette.button().color().name()
        link_color = palette.link().color().name()
        highlight_color = palette.highlight().color().name()
        light_color = palette.light().color().name()
        mid_color = palette.mid().color().name()
        dark_color = palette.dark().color().name()
    else:
        # Fallback colors if no Qt app
        text_color = "#333333"
        background_color = "#ffffff"
        base_color = "#ffffff"
        button_color = "#f0f0f0"
        link_color = "#0066cc"
        highlight_color = "#e0e0e0"
        light_color = "#f8f8f8"
        mid_color = "#cccccc"
        dark_color = "#666666"
    
    # Normalize common encoding issues
    md_text = md_text.replace("â€™", "'")
    md_text = md_text.replace("â€œ", '"')
    md_text = md_text.replace("â€", '"')
    
    lines = md_text.splitlines()
    html_lines = []
    
    # State tracking
    in_code_block = False
    code_block_lines = []
    in_table = False
    table_lines = []
    list_stack = []  # (indent_level, list_type)
    in_blockquote = False
    blockquote_lines = []
    
    def close_lists(target_indent):
        """Close lists down to target indent level"""
        while list_stack and list_stack[-1][0] >= target_indent:
            _, list_type = list_stack.pop()
            if list_type == "ul":
                html_lines.append("</ul>")
            else:
                html_lines.append("</ol>")
    
    def close_blockquote():
        """Close any open blockquote"""
        nonlocal in_blockquote, blockquote_lines
        if in_blockquote:
            html_lines.append("<blockquote>")
            html_lines.extend(blockquote_lines)
            html_lines.append("</blockquote>")
            in_blockquote = False
            blockquote_lines = []
    
    def process_inline(text):
        """Process inline markdown elements using a placeholder system to ensure correct escaping."""
        
        placeholders = {}
        
        # --- Step 1: Replace all HTML-generating patterns with placeholders ---
        
        # Custom <link> tags: <link>url, text</link>
        def save_link_custom(match):
            placeholder = f"||TAG{len(placeholders)}||"
            url = match.group(1).strip()
            display_text = html.escape(match.group(2).strip())
            placeholders[placeholder] = f'<a href="{url}" style="color:{link_color}; text-decoration:underline;">{display_text}</a>'
            return placeholder
        text = re.sub(r'<link>\s*([^,]+?)\s*,\s*(.*?)\s*</link>', save_link_custom, text)

        # Standard markdown images: ![alt](src)
        def save_img_md(match):
            placeholder = f"||TAG{len(placeholders)}||"
            alt = html.escape(match.group(1))
            src = match.group(2)  # Don't escape src
            placeholders[placeholder] = f'<img src="{src}" alt="{alt}" style="max-width:100%;">'
            return placeholder
        text = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', save_img_md, text)

        # Standard markdown links: [text](url)
        def save_link_md(match):
            placeholder = f"||TAG{len(placeholders)}||"
            display_text = html.escape(match.group(1))
            url = match.group(2)  # Don't escape url
            placeholders[placeholder] = f'<a href="{url}" style="color:{link_color}; text-decoration:underline;">{display_text}</a>'
            return placeholder
        text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', save_link_md, text)

        # Inline code: `code`
        def save_code(match):
            placeholder = f"||TAG{len(placeholders)}||"
            code_content = html.escape(match.group(1))
            placeholders[placeholder] = f'<code style="background-color:{light_color}; padding:2px 4px; border-radius:3px;">{code_content}</code>'
            return placeholder
        text = re.sub(r'`([^`]+)`', save_code, text)
        
        # --- Step 2: Escape the rest of the line ---
        text = html.escape(text)

        # --- Step 3: Process simple formatting on the now-safe text ---
        text = re.sub(r'\*\*\*(.+?)\*\*\*', r'<strong><em>\1</em></strong>', text)
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*', r'<em>\1</em>', text)
        text = re.sub(r'___(.+?)___', r'<strong><em>\1</em></strong>', text)
        text = re.sub(r'__(.+?)__', r'<strong>\1</strong>', text)
        text = re.sub(r'_(.+?)_', r'<em>\1</em>', text)

        # --- Step 4: Restore all placeholders ---
        for placeholder, html_content in placeholders.items():
            text = text.replace(placeholder, html_content)
        
        return text
    
    def process_custom_images(img_content, base_path):
        """Process custom <img> tags with comma-separated images or single image"""
        import os
        from .qt_compat import QtCore
        img_content = img_content.strip()

        # Check if it contains commas (multiple images)
        if ',' in img_content:
            imgs = [img.strip() for img in img_content.split(',')]
            # Create a flexible container for multiple images, left-aligned
            imgs_html = ''.join([
                f'<img src="{QtCore.QUrl.fromLocalFile(os.path.abspath(os.path.join(base_path, img))).toString()}" alt="Image" style="flex: 1 1 auto; max-width: 100%; height: auto; object-fit: contain;">'
                for img in imgs
            ])
            return f'<div style="display: flex; flex-wrap: wrap; gap: 10px; justify-content: flex-start; align-items: center;">{imgs_html}</div>'
        else:
            # Single image, left-aligned
            abs_path = os.path.abspath(os.path.join(base_path, img_content))
            return f'<div style="text-align: left;"><img src="{QtCore.QUrl.fromLocalFile(abs_path).toString()}" alt="Image" style="max-width:100%; max-height: 100%; object-fit: contain;"></div>'
    
    def render_table(table_lines):
        """Render a markdown table to HTML"""
        if len(table_lines) < 2:
            return ""
        
        html = [f'<table style="border-collapse:collapse; margin:10px 0;">']
        
        # Process header
        header_cells = [cell.strip() for cell in table_lines[0].split('|')[1:-1]]
        html.append('<thead>')
        html.append(f'<tr style="background-color:{button_color};">')
        for cell in header_cells:
            html.append(f'<th style="border:1px solid {mid_color}; padding:8px; text-align:left;">{process_inline(cell)}</th>')
        html.append('</tr>')
        html.append('</thead>')
        
        # Process body (skip separator line)
        if len(table_lines) > 2:
            html.append('<tbody>')
            for row in table_lines[2:]:
                cells = [cell.strip() for cell in row.split('|')[1:-1]]
                html.append('<tr>')
                for cell in cells:
                    html.append(f'<td style="border:1px solid {mid_color}; padding:8px;">{process_inline(cell)}</td>')
                html.append('</tr>')
            html.append('</tbody>')
        
        html.append('</table>')
        return '\n'.join(html)
    
    # Process lines
    for i, line in enumerate(lines):
        # Code blocks - handle first to prevent any processing inside them
        if line.strip().startswith('```'):
            if not in_code_block:
                in_code_block = True
                code_language = line.strip()[3:].strip()  # Get language from opening line
                code_block_lines = []
                continue
            else:
                # End code block
                in_code_block = False
                code_content = html.escape('\n'.join(code_block_lines))
                
                # Create a unified code block with styled language label
                if code_language:
                    lang_label = f'<div style="background-color:{button_color}; color:{dark_color}; font-size:0.8em; font-weight:bold; padding:4px 8px; border-radius:3px 3px 0 0; margin:-10px -10px 8px -10px; border-bottom:1px solid {mid_color}; text-transform:uppercase;">{code_language}</div>'
                else:
                    lang_label = ''
                
                html_lines.append(
                    f'<div style="background-color:{light_color}; border:1px solid {mid_color}; border-radius:4px; padding:10px; margin:10px 0; font-family:monospace; overflow:hidden;">'
                    f'{lang_label}'
                    f'<pre style="margin:0; white-space:pre-wrap; color:{text_color};">{code_content}</pre>'
                    f'</div>'
                )
                continue
        
        if in_code_block:
            code_block_lines.append(line)
            continue
        
        # Tables
        if '|' in line and not in_table:
            # Check if this looks like a table
            parts = line.split('|')
            if len(parts) >= 3 and parts[0].strip() == '' and parts[-1].strip() == '':
                in_table = True
                table_lines = [line]
                continue
        
        if in_table:
            if '|' in line:
                table_lines.append(line)
                continue
            else:
                # End of table
                html_lines.append(render_table(table_lines))
                in_table = False
                table_lines = []
                # Process current line normally
        
        # Headers
        header_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if header_match:
            close_lists(0)
            close_blockquote()
            level = len(header_match.group(1))
            text = process_inline(header_match.group(2))
            size = [32, 28, 24, 20, 18, 16][level-1]
            html_lines.append(f'<h{level} style="font-size:{size}px; margin:15px 0 10px 0;">{text}</h{level}>')
            continue
        
        # Horizontal rule
        if re.match(r'^[\-*_]{3,}$', line.strip()):
            close_lists(0)
            close_blockquote()
            html_lines.append(f'<hr style="border:none; border-top:1px solid {mid_color}; margin:20px 0;">')
            continue
        
        # Blockquotes
        blockquote_match = re.match(r'^>\s*(.*)$', line)
        if blockquote_match:
            close_lists(0)
            content = process_inline(blockquote_match.group(1))
            if not in_blockquote:
                in_blockquote = True
            blockquote_lines.append(f'<p style="margin:5px 0;">{content}</p>')
            continue
        elif in_blockquote and line.strip() == '':
            # Empty line might end blockquote
            continue
        elif in_blockquote:
            close_blockquote()
        
        # Lists
        # Unordered lists
        ul_match = re.match(r'^(\s*)[-*+]\s+(.+)$', line)
        if ul_match:
            close_blockquote()
            indent = len(ul_match.group(1))
            content = process_inline(ul_match.group(2))
            
            # Manage list stack
            while list_stack and list_stack[-1][0] > indent:
                close_lists(indent + 1)
            
            if not list_stack or list_stack[-1][0] < indent:
                html_lines.append('<ul style="margin:5px 0; padding-left:20px;">')
                list_stack.append((indent, 'ul'))
            
            html_lines.append(f'<li>{content}</li>')
            continue
        
        # Ordered lists
        ol_match = re.match(r'^(\s*)(\d+)\.\s+(.+)$', line)
        if ol_match:
            close_blockquote()
            indent = len(ol_match.group(1))
            content = process_inline(ol_match.group(3))
            
            # Manage list stack
            while list_stack and list_stack[-1][0] > indent:
                close_lists(indent + 1)
            
            if not list_stack or list_stack[-1][0] < indent or list_stack[-1][1] != 'ol':
                html_lines.append('<ol style="margin:5px 0; padding-left:20px;">')
                list_stack.append((indent, 'ol'))
            
            html_lines.append(f'<li>{content}</li>')
            continue
        
        # Empty line
        if not line.strip():
            close_lists(0)
            close_blockquote()
            html_lines.append('<br>')
            continue
        
        # Check if this is a standalone image tag (entire line is just an image)
        img_match = re.match(r'^\s*<img>\s*(.*?)\s*</img>\s*$', line)
        if img_match:
            close_lists(0)
            close_blockquote()
            img_content = img_match.group(1).strip()
            html_lines.append(process_custom_images(img_content, base_path))
            continue
        
        # Regular paragraph
        close_lists(0)
        close_blockquote()
        html_lines.append(f'<p style="margin:10px 0;">{process_inline(line)}</p>')
    
    # Close any remaining open elements
    close_lists(0)
    close_blockquote()
    if in_table and table_lines:
        html_lines.append(render_table(table_lines))
    
    # Add default styling using palette colors
    style = f"""<style>
    body {{ font-family: Arial, sans-serif; line-height: 1.6; color: {text_color}; }}
    a {{ color: {link_color}; text-decoration: underline; }}
    a:hover {{ color: {highlight_color}; }}
    code {{ font-family: 'Courier New', monospace; }}
    blockquote {{ border-left: 4px solid {mid_color}; margin: 10px 0; padding-left: 15px; color: {dark_color}; }}
    </style>
    """
    
    return style + '\n'.join(html_lines)


def get_galt_config(script_path):
    from galt.metadata_manager import get_galt_config as get_config
    return get_config(script_path)

def create_default_galt_file(script_path, default_config=None):
    from galt.metadata_manager import create_default_galt_file as create_file
    return create_file(script_path, default_config=default_config)

def update_galt_config(script_path, config):
    from galt.metadata_manager import update_galt_config as update_config
    return update_config(script_path, config)

def format_script_display_name(script_name, software_list):
    if not software_list:
        return script_name
    return f"{script_name} ({', '.join(software_list)})"

def get_software_color(software):
    """Get color for software, using new unified config."""
    # Handle special cases
    if software in ["None", "No Metadata", "Default"]:
        return config.SOFTWARE_COLORS.get(software, "#95a5a6")
    
    # Check new unified structure
    software_lower = software.lower()
    if software_lower in config.SOFTWARE:
        return config.SOFTWARE[software_lower].get("color", "#95a5a6")
    
    # Fall back to old SOFTWARE_COLORS for compatibility
    software_cap = software.capitalize()
    return config.SOFTWARE_COLORS.get(software_cap, "#95a5a6")

def get_visible_software_list():
    """Get list of non-hidden software for display in dialogs."""
    visible_software = []
    for software_key, software_config in config.SOFTWARE.items():
        if not software_config.get("hidden", False):  # Default to visible if hidden not specified
            visible_software.append(software_key.capitalize())
    return visible_software

def detect_host():
    """Return the current host application name.

    Charon is only deployed inside Nuke, so we skip dynamic host detection to
    avoid branching for other DCCs. We still attempt to import ``nuke`` so the
    call mirrors the production environment, but fall back to the same result
    if the module is unavailable (e.g., during local CLI development).
    """
    try:
        import nuke  # noqa: F401
    except Exception:
        pass
    return "Nuke"

def get_host_version(host=None):
    """Get the version of the current host application.
    
    Args:
        host (str, optional): The host to get version for. If None, detects current host.
        
    Returns:
        str: Version string with major.minor (e.g., "2022", "15.0") or None if version cannot be determined
    """
    if host is None:
        host = detect_host()
    
    host_lower = host.lower()
    
    if host_lower == "maya":
        try:
            import maya.cmds as cmds
            version = cmds.about(version=True)
            # Maya returns full version like "2022.3" - we want just major (no minor for Maya)
            return version.split('.')[0] if version else None
        except:
            return None
            
    elif host_lower == "nuke":
        try:
            import nuke
            # Nuke version is like "15.0v1"
            version = nuke.NUKE_VERSION_STRING
            # Extract major.minor part
            import re
            match = re.match(r'(\d+\.\d+)', version)
            return match.group(1) if match else None
        except:
            return None
            
    elif host_lower == "houdini":
        try:
            import hou
            version = hou.applicationVersionString()
            # Houdini returns something like "19.5.303" - want major.minor
            parts = version.split('.')
            return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else parts[0]
        except:
            return None
            
    elif host_lower == "blender":
        try:
            import bpy
            # Blender version tuple like (3, 6, 0)
            version = bpy.app.version
            if len(version) >= 2:
                return f"{version[0]}.{version[1]}"
            else:
                return str(version[0]) if version else None
        except:
            return None
    
    elif host_lower == "windows":
        try:
            import platform
            import sys
            
            # Windows 11 still reports as 10.x in platform.version()
            # We need to check the build number
            version_info = platform.version()
            if version_info:
                parts = version_info.split('.')
                if len(parts) >= 3:
                    build = int(parts[2])
                    # Windows 11 starts at build 22000
                    if build >= 22000:
                        return "11"
                    else:
                        return "10"
            
            # Fallback to platform.release() which might work
            release = platform.release()
            if release in ["10", "11"]:
                return release
                
            # Final fallback
            return "10"  # Assume Windows 10 if we can't detect
        except:
            return None
    
    return None

def check_version_compatibility(host=None, version=None):
    """Check if the current host version is compatible with Galt.
    
    Version matching rules:
    - "15" matches any 15.x version (15.0, 15.1, etc.)
    - "15.0" matches only 15.0 specifically
    
    Args:
        host (str, optional): The host to check. If None, detects current host.
        version (str, optional): The version to check. If None, detects current version.
        
    Returns:
        tuple: (is_compatible, error_message)
            - is_compatible (bool): True if compatible, False otherwise
            - error_message (str): Error message if incompatible, None otherwise
    """
    if host is None:
        host = detect_host()
    
    if version is None:
        version = get_host_version(host)
    
    host_lower = host.lower()
    
    # Get supported versions from SOFTWARE dict
    software_config = config.SOFTWARE.get(host_lower)
    if software_config is None:
        return True, None
        
    supported_versions = software_config.get("compatible_versions", [])
    
    # If None, any version is supported
    if supported_versions is None:
        return True, None
    
    # If empty list, no versions are supported
    if supported_versions == []:
        return False, f"{host} is not supported by Galt"
    
    # If version couldn't be detected but we have requirements, that's a problem
    if version is None:
        return False, f"Could not detect {host} version"
    
    # Check version compatibility with partial matching
    for supported in supported_versions:
        # None in the list means any version is accepted
        if supported is None:
            return True, None
            
        # Exact match
        if version == supported:
            return True, None
        
        # Partial match: if supported has no dot, it matches any minor version
        if '.' not in supported:
            # Check if our version starts with this major version
            if version.startswith(supported + '.') or version == supported:
                return True, None
    
    # No match found
    # Format supported versions for display, handling None values
    formatted_versions = []
    for v in supported_versions:
        if v is None:
            formatted_versions.append("any")
        else:
            formatted_versions.append(v)
    
    error_msg = f"{host} version {version} is not supported. Supported versions: {', '.join(formatted_versions)}"
    return False, error_msg

def setup_script_paths(script_paths=None):
    """
    Setup sys.path with provided paths only. No fallback to config.
    Args:
        script_paths (list, optional): List of paths to add to sys.path
    Returns:
        str: The primary path to use as global_repo_path, or None if not provided
    """
    import sys
    
    # If paths provided, use them
    if script_paths:
        # Add all paths to sys.path
        for path in script_paths:
            if path and path not in sys.path:
                sys.path.insert(0, path)
                from .galt_logger import system_debug
                system_debug(f"Added to sys.path: {path}")
        
        # Use first path as base, append galt_global_repo if it exists
        base_path = script_paths[0]
        potential_global_repo = os.path.join(base_path, "galt_global_repo")
        if os.path.exists(potential_global_repo):
            return potential_global_repo
        else:
            return base_path
    
    # No paths provided, do not fallback to config
    return None

def reload_galt_modules():
    """Reload all galt modules for fresh imports"""
    import sys
    import importlib
    
    # Get all galt modules
    galt_modules = [module for module in list(sys.modules.keys()) if module.startswith("galt")]
    
    # Remove them from sys.modules
    for module in galt_modules:
        del sys.modules[module]
    
    from .galt_logger import system_debug
    system_debug(f"Reloaded {len(galt_modules)} galt modules")


# ===== NEW COMPATIBILITY AND STYLING UTILITIES =====

def is_compatible_with_host(metadata, host):
    """Centralized compatibility checking for scripts and folders.

    Charon only runs inside Nuke, so we now treat every workflow as compatible
    regardless of the legacy ``software`` tag. This keeps older metadata usable
    without forcing artists to edit stale fields.
    """
    return True


def apply_incompatible_opacity(color):
    """Centralized opacity application for incompatible items"""
    from galt import config
    color.setAlpha(int(255 * config.INCOMPATIBLE_OPACITY))
    return color


def get_software_color_for_metadata(metadata, host):
    """Centralized color selection for software-based items with metadata"""
    from galt import config
    from galt.metadata_manager import get_software_for_host
    
    if not metadata:
        return config.SOFTWARE_COLORS.get("No Metadata", "#7f8c8d")
    sw = get_software_for_host(metadata, host)
    return config.SOFTWARE_COLORS.get(sw, "#95a5a6")


def create_script_sort_key(script_item, host):
    """
    Create sort key for a script item.
    
    Priority order:
    1. Workflows with metadata (bookmarked first)
    2. Workflows without metadata or tagged with "none" (bookmarked first)
    
    Within each category, sort alphabetically by name.
    """
    name = script_item.name.lower()
    metadata = script_item.metadata
    is_bookmarked = getattr(script_item, 'is_bookmarked', False)
    
    if not metadata:
        # No metadata - treat as "none" software
        return (2, 0 if is_bookmarked else 1, name)
    
    # Preserve the legacy "none" grouping so folders lacking metadata still sort last
    from .metadata_manager import get_software_for_host
    software = (get_software_for_host(metadata, host) or "").lower()
    if software == "none":
        return (2, 0 if is_bookmarked else 1, name)
    
    # All other workflows are treated as compatible now that we only target Nuke
    return (1, 0 if is_bookmarked else 1, name)


def create_folder_sort_key(folder_name, host, base_path=None):
    """
    Create sort key for a folder.
    
    Priority order:
    1. Special folders (Bookmarks)
    2. Folders containing workflows
    3. Empty or unreadable folders
    
    Within each category, sort alphabetically.
    """
    folder_lower = folder_name.lower()
    
    # Special folders always first
    if folder_name == "Bookmarks":
        return (0, folder_lower)
    
    # Check compatibility if base path provided
    if base_path:
        folder_path = os.path.join(base_path, folder_name)
        from .metadata_manager import is_folder_compatible_with_host
        
        if is_folder_compatible_with_host(folder_path, host):
            return (1, folder_lower)
        else:
            return (3, folder_lower)
    
    # Default to compatible if no base path
    return (1, folder_lower)


def create_sort_key(item, host, base_path=None):
    """
    Create a sort key for items based on compatibility with the current host.
    
    Args:
        item: Either a ScriptItem object or a folder name string
        host: Current host software
        base_path: Base path for folder compatibility checking (only for folders)
    
    Returns:
        tuple: Sort key with priority (lower = higher priority)
    """
    # Handle ScriptItem objects (scripts)
    if hasattr(item, 'metadata'):
        return create_script_sort_key(item, host)
    else:
        # This is a folder name string
        return create_folder_sort_key(item, host, base_path)

def load_scripts_for_folder(folder_path, host="None"):
    """Load scripts from a folder and return ScriptItem objects."""
    from galt.script_model import ScriptItem
    from galt.metadata_manager import get_galt_config
    
    items = []
    if os.path.exists(folder_path):
        for script in os.listdir(folder_path):
            script_path = os.path.join(folder_path, script)
            if os.path.isdir(script_path):
                metadata = get_galt_config(script_path)
                items.append(ScriptItem(script, script_path, metadata, host))
    return items


def detect_script_type_from_extension(entry_file: str) -> str:
    """
    Detect script type from file extension.
    
    Args:
        entry_file: Path to the entry file
        
    Returns:
        str: Script type ("python", "mel", etc.)
        
    Raises:
        ValueError: If extension is not recognized
    """
    ext = os.path.splitext(entry_file)[1].lower()
    
    for script_type, extensions in config.SCRIPT_TYPES.items():
        if ext in extensions:
            return script_type
    
    # If we get here, the extension is not recognized
    raise ValueError(f"Unrecognized script type for extension '{ext}'. "
                    f"Supported extensions: {', '.join([ext for exts in config.SCRIPT_TYPES.values() for ext in exts])}")


def get_metadata_with_fallbacks(script_path: str, current_host: str) -> dict:
    """
    Load metadata with robust fallbacks for all fields.
    
    Args:
        script_path: Path to the script directory
        current_host: Current host environment name
        
    Returns:
        dict: Complete metadata with all required fields
    """
    # Start with default metadata
    metadata = config.DEFAULT_METADATA.copy()
    
    # Try to load existing metadata
    file_metadata = get_galt_config(script_path) or {}
    
    # Apply fallbacks for missing or empty fields
    
    # Software fallback: use current host if empty
    if not file_metadata.get("software"):
        metadata["software"] = [current_host]
    else:
        metadata["software"] = file_metadata["software"]
    
    # Handle other fields with fallbacks
    metadata["entry"] = file_metadata.get("entry", metadata["entry"])
    metadata["script_type"] = file_metadata.get("script_type", metadata["script_type"])
    metadata["run_on_main"] = file_metadata.get("run_on_main", metadata["run_on_main"])
    
    # Handle backward compatibility: intercept_prints -> mirror_prints
    if "mirror_prints" in file_metadata:
        metadata["mirror_prints"] = file_metadata["mirror_prints"]
    elif "intercept_prints" in file_metadata:
        metadata["mirror_prints"] = file_metadata["intercept_prints"]
    # else use default from config.DEFAULT_METADATA
    
    # Remove deprecated fields
    metadata.pop("display", None)
    metadata.pop("intercept_prints", None)
    
    return metadata
