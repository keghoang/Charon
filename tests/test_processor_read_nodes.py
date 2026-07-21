import unittest

from charon.processor_read_nodes import (
    assign_read_file,
    batch_navigation_controls,
    ensure_placeholder_read_node,
    index_grouped_read_nodes,
    link_read_node,
    remove_linked_placeholder_nodes,
    set_output_label,
    unlink_read_node,
    update_read_info,
    update_read_label,
)


class _Knob:
    def __init__(self, name, value=""):
        self.name = name
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value

    def setFlag(self, _flag):
        pass

    def setExpression(self, expression):
        self.expression = expression

    def setEnabled(self, enabled):
        self.enabled = enabled

    def clearAnimated(self):
        self.expression = None


class _NativeFileKnob(_Knob):
    def fromUserText(self, value):
        self.from_user_text_value = value
        self._value = value


class _Node:
    def __init__(self, name="Read1"):
        self._name = name
        self.knobs = {
            "file": _Knob("file", "D:/results/output.png"),
            "label": _Knob("label"),
        }
        self.metadata_values = {"charon/output_label": "Preview"}
        self.control_panel_tabs = []

    def knob(self, name):
        return self.knobs.get(name)

    def addKnob(self, knob):
        self.knobs[knob.name] = knob

    def metadata(self, key):
        return self.metadata_values.get(key)

    def setMetaData(self, key, value):
        self.metadata_values[key] = value

    def name(self):
        return self._name

    def fullName(self):
        return self._name

    def __getitem__(self, name):
        return self.knobs[name]

    def setControlPanelTab(self, name):
        self.control_panel_tabs.append(name)


class _Nuke:
    NO_ANIMATION = 1
    INVISIBLE = 2

    @staticmethod
    def String_Knob(name, _label, value):
        return _Knob(name, value)

    @staticmethod
    def Double_Knob(name, _label):
        return _Knob(name, 0.0)

    @staticmethod
    def Tab_Knob(name, _label):
        return _Knob(name)

    @staticmethod
    def Text_Knob(name, _label, value):
        return _Knob(name, value)

    def __init__(self):
        self.deleted = []

    def delete(self, node):
        self.deleted.append(node)


class ProcessorReadNodeTests(unittest.TestCase):
    def test_assigns_read_file_through_nuke_native_parser(self):
        node = _Node()
        node.knobs["file"] = _NativeFileKnob("file")

        assign_read_file(node, r"D:\results\output.mp4")

        self.assertEqual(node["file"].value(), "D:/results/output.mp4")
        self.assertEqual(node["file"].from_user_text_value, "D:/results/output.mp4")

    def test_assign_read_file_falls_back_for_test_or_legacy_knobs(self):
        node = _Node()

        assign_read_file(node, r"D:\results\output.mp4")

        self.assertEqual(node["file"].value(), "D:/results/output.mp4")

    def test_batch_navigation_compatibility_hook_is_non_blocking(self):
        self.assertEqual(batch_navigation_controls(_Node()), (None, None, None))

    def test_placeholder_refresh_does_not_replace_rendered_output(self):
        source = _Node("CharonOp1")
        existing = _Node("Read1")
        existing["file"].setValue("D:/results/rendered.png")
        marked = []
        messages = []

        ensure_placeholder_read_node(
            _Nuke(),
            source,
            parent_id="parent-1",
            workflow_display_name="Workflow",
            placeholder_path="D:/resources/placeholder.png",
            find_linked_read=lambda: existing,
            mark_read=marked.append,
            sanitize_name=lambda value, _default: value,
            log_debug=lambda *args: messages.append(args),
        )

        self.assertEqual(existing["file"].value(), "D:/results/rendered.png")
        self.assertEqual(marked, [existing])
        self.assertIn("already has rendered output", messages[0][0])

    def test_unlinks_read_and_clears_source_references(self):
        source = _Node("CharonOp1")
        source.knobs.update(
            {
                "charon_read_node": _Knob("charon_read_node", "Read1"),
                "charon_read_node_id": _Knob("charon_read_node_id", "read-1"),
                "charon_last_output": _Knob("charon_last_output", "result.png"),
                "charon_recreate_read": _Knob("charon_recreate_read"),
            }
        )
        read = _Node("Read1")
        read.knobs.update(
            {
                "charon_parent_id": _Knob("charon_parent_id", "parent-1"),
                "charon_read_id": _Knob("charon_read_id", "read-1"),
                "charon_link_anchor": _Knob("charon_link_anchor", 0.5),
            }
        )
        read.metadata_values.update(
            {"charon/parent_id": "parent-1", "charon/read_id": "read-1"}
        )
        saved = []

        unlink_read_node(
            source,
            read,
            current_state="Ready",
            write_metadata=lambda *_args: None,
            update_info=lambda *_args: None,
            update_label=lambda *_args: None,
            apply_status=lambda *_args: None,
            refresh_linked_info=lambda: None,
            load_status_payload=lambda: {"read_node_id": "read-1"},
            save_status_payload=saved.append,
        )

        self.assertEqual(read.metadata("charon/parent_id"), "")
        self.assertEqual(read.knob("charon_parent_id").value(), "")
        self.assertEqual(read.knob("charon_link_anchor").value(), 0.0)
        self.assertEqual(source.knob("charon_read_node").value(), "")
        self.assertTrue(source.knob("charon_recreate_read").enabled)
        self.assertEqual(saved[0]["read_node_id"], "")

    def test_links_read_identity_anchor_and_status_payload(self):
        source = _Node("CharonOp1")
        source.knobs.update(
            {
                "charon_read_node": _Knob("charon_read_node"),
                "charon_read_node_id": _Knob("charon_read_node_id"),
                "charon_recreate_read": _Knob("charon_recreate_read"),
            }
        )
        read = _Node("Read1")
        writes = []
        saved = []

        read_id = link_read_node(
            _Nuke(),
            source,
            read,
            parent_id="parent-1",
            link_anchor_value=0.5,
            current_state="Processing",
            write_metadata=lambda key, value: writes.append((key, value)),
            read_id_resolver=lambda _node: "read-1",
            update_info=lambda *_args: None,
            update_label=lambda *_args: None,
            apply_status=lambda *_args: None,
            refresh_linked_info=lambda: None,
            load_status_payload=lambda: {},
            save_status_payload=saved.append,
        )

        self.assertEqual(read_id, "read-1")
        self.assertEqual(read.metadata("charon/parent_id"), "parent-1")
        self.assertEqual(read.knob("charon_parent_id").value(), "parent-1")
        self.assertEqual(read.knob("charon_read_id").value(), "read-1")
        self.assertEqual(source.knob("charon_read_node").value(), "Read1")
        self.assertTrue(source.knob("charon_recreate_read").enabled)
        self.assertEqual(saved[0]["read_node_id"], "read-1")

    def test_link_identity_survives_presentation_callback_failures(self):
        source = _Node("CharonOp1")
        source.knobs.update(
            {
                "charon_read_node": _Knob("charon_read_node"),
                "charon_read_node_id": _Knob("charon_read_node_id"),
                "charon_recreate_read": _Knob("charon_recreate_read"),
            }
        )
        read = _Node("Read1")

        def fail(*_args):
            raise RuntimeError("optional presentation failed")

        read_id = link_read_node(
            _Nuke(),
            source,
            read,
            parent_id="parent-1",
            link_anchor_value=0.5,
            current_state="Completed",
            write_metadata=fail,
            read_id_resolver=lambda _node: "read-1",
            update_info=fail,
            update_label=fail,
            apply_status=fail,
            refresh_linked_info=fail,
            load_status_payload=lambda: {},
            save_status_payload=lambda _payload: None,
        )

        self.assertEqual(read_id, "read-1")
        self.assertEqual(read.knob("charon_parent_id").value(), "parent-1")
        self.assertEqual(read.knob("charon_read_id").value(), "read-1")
        self.assertEqual(
            read.knob("charon_link_anchor").expression,
            "CharonOp1.charon_link_anchor",
        )
        self.assertEqual(source.knob("charon_read_node").value(), "Read1")
        self.assertEqual(source.knob("charon_read_node_id").value(), "read-1")

    def test_updates_label_with_output_file_and_identity(self):
        node = _Node()

        update_read_label(node, parent_id="parent-1", read_id="read-1")

        label = node["label"].value()
        self.assertIn("Output: Preview", label)
        self.assertIn("File: output.png", label)
        self.assertIn("Charon Parent: parent-1", label)
        self.assertIn("Read ID: read-1", label)

    def test_explicit_empty_label_clears_existing_label(self):
        node = _Node()
        node["label"].setValue("old")

        update_read_label(node, parent_id="", read_id="", label_text="")

        self.assertEqual(node["label"].value(), "")

    def test_creates_and_populates_info_controls(self):
        node = _Node()

        update_read_info(
            _Nuke(),
            node,
            parent_id="parent-1",
            read_id="read-1",
            state="Processing",
            color_hex="#123abc",
        )

        info = node.knob("charon_info_text").value()
        self.assertIn("Parent ID: parent-1", info)
        self.assertIn("Read Node ID: read-1", info)
        self.assertIn("Status: Processing", info)
        self.assertIn("Color: #123ABC", info)
        self.assertEqual(node.control_panel_tabs, ["Read"])

        update_read_info(
            _Nuke(),
            node,
            parent_id="parent-1",
            read_id="read-1",
            state="Completed",
            color_hex="#123abc",
        )

        self.assertEqual(node.control_panel_tabs, ["Read"])

    def test_indexes_only_linked_reads_with_output_labels(self):
        first = _Node("Read1")
        first.metadata_values.update(
            {"charon/parent_id": "PARENT-1", "charon/output_label": " Preview "}
        )
        duplicate = _Node("Read2")
        duplicate.metadata_values.update(
            {"charon/parent_id": "parent-1", "charon/output_label": "preview"}
        )
        unrelated = _Node("Read3")
        unrelated.metadata_values.update(
            {"charon/parent_id": "parent-2", "charon/output_label": "Other"}
        )

        indexed = index_grouped_read_nodes(
            [first, duplicate, unrelated],
            parent_id="parent-1",
            parent_id_resolver=lambda node: node.metadata("charon/parent_id"),
            normalize_id=lambda value: str(value or "").lower(),
        )

        self.assertEqual(indexed, {"preview": first})

    def test_persists_output_label_in_metadata_and_hidden_knob(self):
        node = _Node()

        set_output_label(_Nuke(), node, "Depth")

        self.assertEqual(node.metadata("charon/output_label"), "Depth")
        self.assertEqual(node.knob("charon_output_label").value(), "Depth")

    def test_removes_only_matching_linked_placeholder_reads(self):
        placeholder = _Node("Placeholder")
        placeholder["file"].setValue("D:\\resources\\placeholder.png")
        placeholder.metadata_values["charon/parent_id"] = "parent-1"
        rendered = _Node("Rendered")
        rendered.metadata_values["charon/parent_id"] = "parent-1"
        unrelated = _Node("Unrelated")
        unrelated["file"].setValue("D:/resources/placeholder.png")
        unrelated.metadata_values["charon/parent_id"] = "parent-2"
        nuke = _Nuke()
        unlinked = []

        removed = remove_linked_placeholder_nodes(
            nuke,
            [placeholder, rendered, unrelated],
            parent_id="PARENT-1",
            placeholder_path="D:/resources/placeholder.png",
            parent_id_resolver=lambda node: node.metadata("charon/parent_id"),
            normalize_id=lambda value: str(value or "").lower(),
            unlink_node=unlinked.append,
            log_debug=lambda *_args: None,
        )

        self.assertEqual(removed, 1)
        self.assertEqual(unlinked, [placeholder])
        self.assertEqual(nuke.deleted, [placeholder])


if __name__ == "__main__":
    unittest.main()
