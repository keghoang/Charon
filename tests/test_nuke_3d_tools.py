import os
import tempfile
import unittest

from charon.nuke_3d_tools import (
    create_camera_rig_nuke,
    extract_outer_group_block,
    generate_coverage_cameras_nuke,
    get_dag_center,
    load_nuke_group_template,
)


class _Node:
    def __init__(self, x, y):
        self._x = x
        self._y = y

    def xpos(self):
        return self._x

    def ypos(self):
        return self._y


class _NukeDag:
    def center(self):
        raise RuntimeError("not available")

    def allNodes(self, **_kwargs):
        return [_Node(10, 20), _Node(30, 60)]


class _PasteNuke:
    def __init__(self, error=None):
        self.error = error
        self.pasted_path = None

    def nodePaste(self, path):
        if self.error:
            raise self.error
        self.pasted_path = path


class _Knob:
    def __init__(self, name):
        self.name = name
        self.value = None

    def setValue(self, value):
        self.value = value


class _CreatedNode:
    def __init__(self, class_name):
        self.class_name = class_name
        self.name = ""
        self.knobs = {}
        self.selected = False

    def setName(self, name):
        self.name = name

    def setXYpos(self, _x, _y):
        pass

    def setInput(self, _index, _node):
        pass

    def begin(self):
        pass

    def end(self):
        pass

    def addKnob(self, knob):
        self.knobs[knob.name] = knob

    def setSelected(self, selected):
        self.selected = selected

    def __getitem__(self, name):
        return self.knobs.setdefault(name, _Knob(name))


class _CoverageNuke:
    def __init__(self):
        self.created = []

    def selectedNodes(self):
        return []

    def createNode(self, class_name):
        node = _CreatedNode(class_name)
        self.created.append(node)
        return node

    def Tab_Knob(self, name, _label):
        return _Knob(name)

    def Enumeration_Knob(self, name, _label, _values):
        return _Knob(name)

    def PyScript_Knob(self, name, _label, script):
        knob = _Knob(name)
        knob.value = script
        return knob


class Nuke3DToolTests(unittest.TestCase):
    def test_camera_rig_uses_packaged_template(self):
        nuke = _PasteNuke()
        errors = []

        create_camera_rig_nuke(
            report_error=lambda title, message: errors.append((title, message)),
            nuke_module=nuke,
        )

        self.assertTrue(nuke.pasted_path.endswith("charon_camera_rig.nk"))
        self.assertTrue(os.path.isfile(nuke.pasted_path))
        self.assertEqual(errors, [])

    def test_camera_rig_reports_missing_template(self):
        errors = []
        with tempfile.TemporaryDirectory() as tmp:
            create_camera_rig_nuke(
                report_error=lambda title, message: errors.append((title, message)),
                nuke_module=_PasteNuke(),
                resource_dir=tmp,
            )

        self.assertEqual(errors[0][0], "Error")
        self.assertIn("Camera rig template not found", errors[0][1])

    def test_coverage_group_creation_is_independent_of_main_window(self):
        nuke = _CoverageNuke()
        errors = []

        generate_coverage_cameras_nuke(
            "generate()",
            report_error=lambda title, message: errors.append((title, message)),
            nuke_module=nuke,
        )

        group = nuke.created[0]
        self.assertEqual(group.name, "Charon_Coverage_Rig")
        self.assertIn("charon_generate_cameras", group.knobs)
        self.assertTrue(group.selected)
        self.assertEqual(errors, [])

    def test_dag_center_falls_back_to_node_bounds(self):
        self.assertEqual(get_dag_center(_NukeDag()), (20, 40))

    def test_extracts_first_complete_group(self):
        content = "header\nGroup {\n name Test\n}\nend_group\ntrailer\n"

        result = extract_outer_group_block(content)

        self.assertEqual(result, "Group {\n name Test\n}\nend_group\n")

    def test_rejects_incomplete_template(self):
        with self.assertRaises(ValueError):
            extract_outer_group_block("Group {\n name Broken\n")

    def test_loads_group_from_template_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "template.nk")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("version 1\nGroup {\n name Tool\n}\nend_group\n")

            result = load_nuke_group_template(path)

        self.assertIn("name Tool", result)


if __name__ == "__main__":
    unittest.main()
