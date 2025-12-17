import sys, runpy, importlib

# --- tweak me if needed -----------------------------------------------------
REPO_PATH = r"C:\\Users\\kien\\git\\Charon"
WORKFLOW_REPO = r"C:\\Users\\kien\\git\\Charon\\workflows"   # set to None to use Galt defaults
HOST = "nuke"                                           # "nuke", "maya", etc.
DEBUG = True                                            # turn off if you want quieter logs
# ----------------------------------------------------------------------------

if REPO_PATH not in sys.path:
    sys.path.insert(0, REPO_PATH)

importlib.invalidate_caches()
for name in list(sys.modules):
    if name.startswith("prototypes.galt_clone"):
        sys.modules.pop(name, None)

sys.argv = ["galt.main"]
if WORKFLOW_REPO:
    sys.argv += ["--repository", WORKFLOW_REPO]
if HOST:
    sys.argv += ["--host", HOST]
if DEBUG:
    sys.argv.append("--debug")

runpy.run_module("prototypes.galt_clone.galt.main", run_name="__main__", alter_sys=True)

