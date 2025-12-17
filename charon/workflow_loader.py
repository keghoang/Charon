import json
import os


def resolve_workflows_dir():
    candidates = []
    if "__file__" in globals():
        try:
            candidates.append(os.path.join(os.path.dirname(__file__), "..", "workflows"))
        except Exception:
            pass
    try:
        candidates.append(os.path.join(os.getcwd(), "workflows"))
    except Exception:
        pass
    candidates.append(r"D:\Coding\Nuke_ComfyUI\workflows")

    for candidate in candidates:
        path = os.path.abspath(candidate)
        if os.path.exists(path):
            return path
    return os.path.abspath(candidates[-1])


def list_workflows():
    directory = resolve_workflows_dir()
    workflows = []
    if os.path.exists(directory):
        for filename in sorted(os.listdir(directory)):
            if filename.endswith(".json"):
                display = filename[:-5].replace("_", " ").replace("-", " ").title()
                workflows.append((display, os.path.join(directory, filename)))
    return workflows


def load_workflow(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)
