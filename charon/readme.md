# Charon - Simple Script Sharing Tool
Charon is an internal tool that helps you easily browse, run, and share simple scripts with your colleagues.
This tool is built and maintained by **AlexD**. Feedback and bug reports are welcome.

**Host Apps supported:** Maya, Nuke, Windows  
**Script types supported:** Python, mel  
**Python requirement:** 3.7 (for compatibility with our supported software)

## Getting Started

### Creating Scripts
Right-click in any folder (empty space) and select **"New Script"** to create a new script with metadata.

### Running Scripts
- **Browse Mode** (default): Double-click or press Ctrl+Enter to run
- **Command Mode** (F2): Single-click to instantly run scripts

### Organizing Scripts
- **Bookmark** frequently used scripts (right-click → Add Bookmark)
- **Assign Hotkeys** to scripts for quick access (right-click → Assign Hotkey)
- **Use Tags** to categorize and filter scripts

## Keyboard Shortcuts

### Navigation
| Hotkey       | Action                           |
|--------------|----------------------------------|
| Arrow Keys   | Navigate folders and scripts     |
| Backspace    | Go to parent folder              |
| Tab          | Focus folders panel              |
| Escape       | Clear selection / Close dialogs  |

### Quick Actions
| Hotkey       | Action                           |
|--------------|----------------------------------|
| F2           | Toggle Command Mode              |
| F4           | Toggle Quick Search              |
| Ctrl+Enter   | Run selected script              |
| Ctrl+R       | Refresh current folder           |
| Ctrl+O       | Open script folder in explorer   |
| Spacebar     | Open/Create readme               |
| Delete       | Remove bookmark (in Bookmarks)   |

### Global Hotkeys
| Hotkey       | Action                           |
|--------------|----------------------------------|
| (Custom)     | Run assigned scripts from anywhere |

## Features

### Command Mode
Press **F2** to toggle Command Mode - a streamlined interface for rapid script execution:
- Smaller, more compact window stays out of your way
- **F4** Quick Search finds and runs scripts immediately (no navigation needed)
- Single-click to run any script
- Yellow highlight indicates Command Mode is active

### Bookmarks
Bookmark your frequently used scripts for quick access:
- Right-click any script → **Add Bookmark** (or **Remove Bookmark**)
- A special **★ Bookmarks** folder appears when you have bookmarks
- Press Delete in the Bookmarks folder to remove selected bookmark

### Script Hotkeys
Assign global hotkeys to run scripts from anywhere:
- Right-click a script → **Assign Hotkey**
- Press your desired key combination
- Works even when Charon isn't focused
- Remove with right-click → **Remove Hotkey**

### Tags
Organize scripts with tags:
- Right-click → **Manage Tags** to add/remove tags
- Use the tag bar at the bottom to filter scripts
- Scripts can have multiple tags

### Right-Click Menu
Access all features through the context menu:
- **Open Folder** - Open in file explorer
- **Add/Remove Bookmark** - Quick access management
- **Assign/Remove Hotkey** - Global hotkey assignment
- **Create/Edit Metadata** - Configure script settings
- **Manage Tags** - Organize with tags
- **Open/Create Readme** - Documentation

## ⚠️ Important Warnings

### Threading and UI Scripts
- **UI/Widget scripts**: Always run on the **main thread** (set `"run_on_main": true` in metadata)
- **Background scripts**: Perfect for data processing, but **CANNOT** create Qt/PySide widgets
- **Maya users**: Qt widgets in background threads will freeze Maya - always use main thread for UI


## Markdown Rendering

Charon automatically detects `readme.md` files and supports limited Markdown:

### Headers
Use `#`, `##`, `###` for different header levels
```markdown
# Header 1
## Header 2
### Header 3
```

### Bullet Lists
Start lines with `-` for bullet points
```markdown
- Item 1
- Item 2
  - Nested item
```

### Images
Embed images:
```markdown
- Single image: `<img>screenshot.png</img>`
- Multiple images: `<img>first_image.png, second_image.png</img>`
```
<img>../charon_icon.png</img>

### Links
Add clickable links:
```markdown
<link>https://example.com, Click here</link>
```
<link>https://google.com, Click here</link>

### Code Blocks
Wrap code in triple backticks to ignore all other styling.
```python
print("Hello from Charon!")
```


🙂
