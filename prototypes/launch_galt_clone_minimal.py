import sys, os, runpy

repo = r"C:\\Users\\kien\\git\\Charon"
if repo not in sys.path:
    sys.path.insert(0, repo)

galt_main = os.path.join(repo, "prototypes", "galt_clone", "galt", "main.py")
runpy.run_path(galt_main, run_name="__main__")

