"""Nuke infrastructure for Charon's 3D helper tools."""

from __future__ import annotations

import os
import tempfile
from typing import Callable, Optional

from . import paths


ErrorReporter = Callable[[str, str], None]


def extract_outer_group_block(content: str) -> str:
    """Extract the first complete outer Nuke ``Group`` block."""
    lines = content.splitlines(keepends=True)
    start_line = None
    depth = 0
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("Group {"):
            if start_line is None:
                start_line = index
            depth += 1
        elif stripped.startswith("end_group") and start_line is not None:
            depth -= 1
            if depth == 0:
                return "".join(lines[start_line:index + 1])
    raise ValueError("No complete Group block found in template")


def load_nuke_group_template(template_path: str) -> str:
    with open(template_path, "r", encoding="utf-8") as handle:
        return extract_outer_group_block(handle.read())


def get_dag_center(nuke_module) -> tuple[int, int]:
    """Return the visible DAG center, falling back to the node bounding center."""
    try:
        center = nuke_module.center()
        if isinstance(center, (tuple, list)) and len(center) >= 2:
            return int(center[0]), int(center[1])
    except Exception:
        pass
    try:
        nodes = nuke_module.allNodes(recurseGroups=False)
        if nodes:
            min_x = min(node.xpos() for node in nodes)
            max_x = max(node.xpos() for node in nodes)
            min_y = min(node.ypos() for node in nodes)
            max_y = max(node.ypos() for node in nodes)
            return int((min_x + max_x) / 2), int((min_y + max_y) / 2)
    except Exception:
        pass
    return 0, 0


def create_camera_rig_nuke(
    *,
    report_error: ErrorReporter,
    nuke_module=None,
    resource_dir: Optional[str] = None,
) -> None:
    """Paste Charon's packaged camera rig into the active Nuke script."""
    if nuke_module is None:
        try:
            import nuke as nuke_module  # type: ignore
        except ImportError:
            return

    template_root = resource_dir or paths.RESOURCE_DIR
    template_path = os.path.join(
        template_root,
        "nuke_template",
        "charon_camera_rig.nk",
    )
    if not os.path.isfile(template_path):
        report_error("Error", f"Camera rig template not found: {template_path}")
        return

    try:
        nuke_module.nodePaste(template_path)
    except Exception as exc:
        report_error("Error", f"Failed to create camera rig: {exc}")


def generate_final_prep_nuke(
    update_script: str,
    *,
    report_error: ErrorReporter,
    nuke_module=None,
    resource_dir: Optional[str] = None,
) -> None:
    """Paste and initialize the projection final-prep group in Nuke."""
    if nuke_module is None:
        try:
            import nuke as nuke_module  # type: ignore
        except ImportError:
            return
    nuke = nuke_module
    template_root = resource_dir or paths.RESOURCE_DIR
    template_path = os.path.join(
        template_root,
        "nuke_template",
        "projection_final_prep_6_cams.nk",
    )
    try:
        if not os.path.exists(template_path):
            report_error("Error", f"Template file not found: {template_path}")
            return
        script_content = load_nuke_group_template(template_path)
    except Exception as exc:
        report_error("Error", f"Failed to read template file: {exc}")
        return

    anchor_pos = get_dag_center(nuke)
    for node in nuke.allNodes():
        node.setSelected(False)

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".nk",
            delete=False,
        ) as handle:
            handle.write(script_content)
            temp_path = handle.name

        nuke.nodePaste(temp_path)
        final_prep_group = None
        for node in nuke.selectedNodes():
            if node.Class() == "Group":
                final_prep_group = node
                break
        if final_prep_group is None:
            try:
                selected = nuke.selectedNode()
                if selected and selected.Class() == "Group":
                    final_prep_group = selected
            except Exception:
                pass
        if final_prep_group is None:
            raise RuntimeError("Could not find pasted Group node.")

        final_prep_group.begin()
        try:
            existing_inputs = {
                node.name(): node
                for node in nuke.allNodes()
                if node.Class() == "Input"
            }
            coverage_rig = existing_inputs.get("coverage_rig") or nuke.createNode("Input")
            coverage_rig.setName("coverage_rig")
            coverage_rig["number"].setValue(2)
            coverage_rig.setXYpos(0, -200)

            geo_input = existing_inputs.get("geo") or nuke.createNode("Input")
            geo_input.setName("geo")
            geo_input["number"].setValue(3)
            geo_input.setXYpos(0, -120)

            coverage_input = existing_inputs.get("coverage_sheet") or nuke.createNode("Input")
            coverage_input.setName("coverage_sheet")
            coverage_input["number"].setValue(4)
            coverage_input.setXYpos(0, -40)
        finally:
            final_prep_group.end()

        if not final_prep_group.knob("charon_update_inputs"):
            update_knob = nuke.PyScript_Knob(
                "charon_update_inputs",
                "Update Inputs",
                update_script,
            )
            update_knob.setFlag(nuke.STARTLINE)
            final_prep_group.addKnob(update_knob)

        if not final_prep_group.knob("charon_rig_cam_count"):
            camera_count_knob = nuke.Int_Knob(
                "charon_rig_cam_count",
                "Projection Cameras Found",
            )
            try:
                camera_count_knob.setEnabled(False)
            except Exception:
                camera_count_knob.setFlag(nuke.DISABLED)
            final_prep_group.addKnob(camera_count_knob)

        final_prep_group.setXYpos(anchor_pos[0], anchor_pos[1])
    except Exception as exc:
        report_error("Error", f"Failed to generate Final Prep: {exc}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def generate_coverage_cameras_nuke(
    generate_script: str,
    *,
    report_error: ErrorReporter,
    nuke_module=None,
) -> None:
    """Create the coverage-camera group around the selected Nuke nodes."""
    if nuke_module is None:
        try:
            import nuke as nuke_module  # type: ignore
        except ImportError:
            return
    nuke = nuke_module
    selection = nuke.selectedNodes()
    initial_camera = None
    geometry_source = None
    target = None

    for node in selection:
        if not initial_camera and node.Class() in ("Camera3", "Camera2", "Camera"):
            initial_camera = node
        elif not target and node.Class() in ("Axis3", "Axis2", "Axis"):
            target = node
        elif not geometry_source and node.Class() not in (
            "Camera3",
            "Camera2",
            "Camera",
            "Axis3",
            "Axis2",
            "Axis",
        ):
            geometry_source = node

    if initial_camera and not target:
        camera_input = initial_camera.input(1)
        if camera_input and "Axis" in camera_input.Class():
            target = camera_input

    group = nuke.createNode("Group")
    group.setName("Charon_Coverage_Rig")
    if initial_camera:
        group.setXYpos(initial_camera.xpos() + 300, initial_camera.ypos())
        group.setInput(0, initial_camera)
    else:
        group.setXYpos(0, 0)
    if geometry_source:
        group.setInput(1, geometry_source)

    group.begin()
    try:
        camera_input = nuke.createNode("Input")
        camera_input.setName("init_cam")
        camera_input["number"].setValue(0)
        camera_input.setXYpos(0, 0)

        geometry_input = nuke.createNode("Input")
        geometry_input.setName("geo")
        geometry_input["number"].setValue(1)
        geometry_input.setXYpos(0, 100)
    finally:
        group.end()

    group.addKnob(nuke.Tab_Knob("charon_coverage_tab", "Coverage Cameras"))
    camera_count_knob = nuke.Enumeration_Knob(
        "charon_cam_count",
        "Number of Cameras",
        ["2", "4", "6", "8"],
    )
    camera_count_knob.setValue(3)
    group.addKnob(camera_count_knob)
    group.addKnob(
        nuke.PyScript_Knob(
            "charon_generate_cameras",
            "Generate Cameras",
            generate_script,
        )
    )
    if initial_camera and geometry_source and target:
        try:
            group["charon_generate_cameras"].execute()
        except Exception as exc:
            report_error("Error", f"Failed to generate cameras: {exc}")
    group.setSelected(True)


def generate_texture_bake_nuke(
    *,
    report_error: ErrorReporter,
    nuke_module=None,
    resource_dir: Optional[str] = None,
) -> None:
    """Paste and initialize the projection texture-bake group in Nuke."""
    if nuke_module is None:
        try:
            import nuke as nuke_module  # type: ignore
        except ImportError:
            return
    nuke = nuke_module
    template_root = resource_dir or paths.RESOURCE_DIR
    template_dir = os.path.normpath(os.path.join(template_root, "nuke_template"))
    template_path = os.path.join(template_dir, "projection_texture_bake.nk")

    try:
        if not os.path.exists(template_path):
            report_error("Error", f"Template not found: {template_path}")
            return
        script_content = load_nuke_group_template(template_path)
    except Exception as exc:
        report_error("Error", f"Failed to load template: {exc}")
        return

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".nk",
            delete=False,
        ) as handle:
            handle.write(script_content)
            temp_path = handle.name

        current_group = nuke.thisGroup()
        root = nuke.root()
        root.begin()
        nuke.nodePaste(temp_path)

        bake_group = None
        for node in nuke.selectedNodes():
            if node.Class() == "Group":
                bake_group = node
                break
        if bake_group is None:
            bake_group = nuke.toNode("Projection_Texture_Bake")
        if current_group and current_group is not root:
            current_group.begin()

        if bake_group and not bake_group.knob("charon_template_dir"):
            template_knob = nuke.String_Knob(
                "charon_template_dir",
                "Template Dir",
                template_dir,
            )
            template_knob.setFlag(nuke.NO_ANIMATION | nuke.INVISIBLE)
            bake_group.addKnob(template_knob)
        elif bake_group is None:
            report_error(
                "Error",
                "Failed to create Projection_Texture_Bake group. "
                "Please delete any pasted nodes and try again.",
            )
    except Exception as exc:
        report_error("Error", f"Failed to process bake group: {exc}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
