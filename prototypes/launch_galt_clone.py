import sys, importlib, os, runpy

repo = r"C:\\Users\\kien\\git\\Charon"
clone_module = "prototypes.galt_clone"

if repo not in sys.path:
    sys.path.insert(0, repo)

# Clear any stale Galt clone modules
importlib.invalidate_caches()
for name in list(sys.modules):
    root = name.split(".", 1)[0]
    if root in {"prototypes"} and name.startswith(clone_module):
        sys.modules.pop(name, None)

# Execute the clone's main launcher
galt_main = os.path.join(repo, "prototypes", "galt_clone", "galt", "main.py")
runpy.run_path(galt_main, run_name="__main__")

