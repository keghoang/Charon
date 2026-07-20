import unittest

from charon.processor_node_state import (
    LinkedOutputRepository,
    NodeMetadataWriter,
    apply_status_to_outputs,
    collect_linked_output_ids,
    deduplicate_node_id,
    ensure_charon_node_identity,
    ensure_link_anchor_value,
    normalize_node_id,
    normalize_script_hash,
    read_script_hash,
    refresh_linked_output_info,
    safe_knob_value,
    sync_anchored_output_nodes,
    update_linked_parent_ids,
    update_last_output_state,
)


class _Knob:
    def __init__(self, value=None, error=False):
        self._value = value
        self._error = error

    def value(self):
        if self._error:
            raise RuntimeError("unavailable")
        return self._value

    def setValue(self, value):
        self._value = value

    def expression(self):
        return self._value

    def setEnabled(self, enabled):
        self.enabled = enabled

    def clearAnimated(self):
        pass


class _Node:
    def __init__(
        self,
        knobs=None,
        metadata_value=None,
        metadata_values=None,
        name="Output",
        class_name="Read",
        x=0,
        y=0,
    ):
        self._knobs = knobs or {}
        self.metadata_value = metadata_value
        self.metadata_values = metadata_values or {}
        self._name = name
        self._class_name = class_name
        self._x = x
        self._y = y

    def knob(self, name):
        return self._knobs.get(name)

    def metadata(self, key):
        return self.metadata_values.get(key, self.metadata_value)

    def setMetaData(self, key, value):
        self.metadata_values[key] = value
        if key == "charon/parent_id":
            self.metadata_value = value

    def name(self):
        return self._name

    def fullName(self):
        return self._name

    def Class(self):
        return self._class_name

    def __getitem__(self, name):
        return self._knobs[name]

    def xpos(self):
        return self._x

    def ypos(self):
        return self._y


class _Nuke:
    def __init__(self, nodes_by_class):
        self.nodes_by_class = nodes_by_class

    def allNodes(self, class_name=None):
        if class_name is not None:
            return self.nodes_by_class.get(class_name, [])
        return [node for nodes in self.nodes_by_class.values() for node in nodes]

    def toNode(self, name):
        return next((node for node in self.allNodes() if node.name() == name), None)

    @staticmethod
    def executeInMainThread(callback):
        callback()


class ProcessorNodeStateTests(unittest.TestCase):
    def test_applies_status_to_source_and_linked_reads(self):
        source = _Node(
            {
                "tile_color": _Knob(0),
                "gl_color": _Knob([]),
                "charon_last_output": _Knob("result.png"),
                "charon_recreate_read": _Knob(""),
            },
            class_name="Group",
        )
        linked = _Node(
            {
                "tile_color": _Knob(0),
                "gl_color": _Knob([]),
                "charon_parent_id": _Knob("parent-1"),
                "charon_read_id": _Knob("read-1"),
            },
            class_name="Read",
        )
        nuke = _Nuke({"Read": [linked], "ReadGeo2": [], "Group": [source]})
        repository = LinkedOutputRepository(nuke, source, "parent-1")
        info_calls = []

        apply_status_to_outputs(
            nuke,
            source,
            "Processing",
            repository,
            tile_color=123,
            gl_color=(0.1, 0.2, 0.3, 1.0),
            ensure_read_info=lambda *args: info_calls.append(args),
        )

        self.assertEqual(source["tile_color"].value(), 123)
        self.assertEqual(linked["tile_color"].value(), 123)
        self.assertEqual(linked["gl_color"].value(), [0.1, 0.2, 0.3, 1.0])
        self.assertTrue(source.knob("charon_recreate_read").enabled)
        self.assertEqual(info_calls[0][1:], ("read-1", "Processing"))

    def test_linked_output_repository_prefers_stored_read_id(self):
        source = _Node({"charon_read_node_id": _Knob("read-two")}, class_name="Group")
        parent_match = _Node(
            metadata_values={"charon/parent_id": "parent-1", "charon/read_id": "read-one"},
            name="ParentMatch",
        )
        stored_match = _Node(
            metadata_values={"charon/parent_id": "other", "charon/read_id": "read-two"},
            name="StoredMatch",
        )
        repository = LinkedOutputRepository(
            _Nuke({"Read": [parent_match, stored_match], "ReadGeo2": []}),
            source,
            "parent-1",
        )

        self.assertIs(repository.find_linked(), stored_match)
        self.assertEqual(repository.collect_targets(), [parent_match])

    def test_linked_output_repository_falls_back_to_parent(self):
        source = _Node(class_name="Group")
        linked = _Node(metadata_values={"charon/parent_id": "parent-1"})
        repository = LinkedOutputRepository(
            _Nuke({"Read": [linked], "ReadGeo2": []}),
            source,
            "parent-1",
        )

        self.assertIs(repository.find_linked(), linked)

    def test_update_last_output_persists_value_and_recreate_state(self):
        output_knob = _Knob("")
        recreate_knob = _Knob("")
        node = _Node(
            {
                "charon_last_output": output_knob,
                "charon_recreate_read": recreate_knob,
            }
        )
        writes = []

        update_last_output_state(
            node,
            "result.png",
            write_metadata=lambda key, value: writes.append((key, value)) or True,
        )

        self.assertEqual(output_knob.value(), "result.png")
        self.assertTrue(recreate_knob.enabled)
        self.assertEqual(writes, [("charon/last_output", "result.png")])

    def test_metadata_writer_supports_node_setter(self):
        node = _Node()
        writer = NodeMetadataWriter(node)

        self.assertTrue(writer("charon/state", "Ready"))
        self.assertEqual(node.metadata("charon/state"), "Ready")

    def test_metadata_writer_reports_only_first_failure(self):
        warnings = []

        class FailingNode:
            @staticmethod
            def setMetaData(_key, _value):
                raise RuntimeError("read only")

        writer = NodeMetadataWriter(FailingNode(), log_warning=warnings.append)
        writer("first", "value")
        writer("second", "value")

        self.assertEqual(len(warnings), 1)
        self.assertIn("first", warnings[0])

    def test_ensure_link_anchor_derives_and_persists_stable_value(self):
        node = _Node({"charon_link_anchor": _Knob(0)}, class_name="Group")
        writes = []

        value = ensure_link_anchor_value(
            node,
            "a",
            write_metadata=lambda key, stored: writes.append((key, stored)) or True,
        )

        self.assertEqual(value, 0.625)
        self.assertEqual(node.knob("charon_link_anchor").value(), 0.625)
        self.assertEqual(writes, [("charon/link_anchor", 0.625)])

    def test_refresh_linked_output_info_sets_display_text(self):
        source = _Node({"charon_read_id_info": _Knob("")}, class_name="Group")
        linked = _Node(
            metadata_values={"charon/parent_id": "parent-1", "charon/read_id": "read-one"}
        )
        nuke = _Nuke({"Group": [source], "Read": [linked]})

        identifiers = refresh_linked_output_info(nuke, source, "parent-1")

        self.assertEqual(identifiers, ["read-one"])
        self.assertEqual(source.knob("charon_read_id_info").value(), "read-one")

    def test_ensure_identity_migrates_when_script_hash_changes(self):
        node = _Node(
            {
                "charon_node_id": _Knob("old-parent"),
                "charon_script_hash": _Knob("old-script"),
            },
            name="Current",
            class_name="Group",
        )
        linked = _Node(
            {"charon_parent_id": _Knob("old-parent")},
            name="Linked",
        )
        nuke = _Nuke({"Group": [node], "Read": [linked], "ReadGeo2": []})
        writes = []

        def update_identity(target, node_id, script_hash):
            if node_id:
                target.knob("charon_node_id").setValue(node_id)
            target.knob("charon_script_hash").setValue(script_hash)

        result = ensure_charon_node_identity(
            nuke,
            node,
            write_metadata=lambda key, value: writes.append((key, value)) or True,
            generate_id=lambda _hash: "new-parent",
            reset_node_state=lambda _node: "reset-parent",
            update_identity=update_identity,
            script_hash_resolver=lambda _nuke: "new-script",
        )

        self.assertEqual(result, "new-parent")
        self.assertEqual(linked.knob("charon_parent_id").value(), "new-parent")
        self.assertEqual(writes[-1], ("charon/node_id", "new-parent"))

    def test_deduplicate_keeps_current_node_when_neither_has_outputs(self):
        current = _Node({"charon_node_id": _Knob("shared-id")}, name="Current", class_name="Group")
        duplicate = _Node({"charon_node_id": _Knob("shared-id")}, name="Duplicate", class_name="Group")
        nuke = _Nuke({"Group": [current, duplicate], "Read": [], "ReadGeo2": []})
        reset_nodes = []

        def reset(node):
            reset_nodes.append(node)
            node.knob("charon_node_id").setValue("replacement")
            return "replacement"

        result = deduplicate_node_id(
            nuke,
            current,
            "shared-id",
            reset_node_state=reset,
        )

        self.assertEqual(result, "shared-id")
        self.assertEqual(reset_nodes, [duplicate])

    def test_deduplicate_keeps_only_node_with_existing_outputs(self):
        current = _Node({"charon_node_id": _Knob("shared-id")}, name="Current", class_name="Group")
        keeper = _Node(
            {
                "charon_node_id": _Knob("shared-id"),
                "charon_last_output": _Knob("result.png"),
            },
            name="Keeper",
            class_name="Group",
        )
        nuke = _Nuke({"Group": [current, keeper], "Read": [], "ReadGeo2": []})

        def reset(node):
            node.knob("charon_node_id").setValue("replacement")
            return "replacement"

        result = deduplicate_node_id(
            nuke,
            current,
            "shared-id",
            reset_node_state=reset,
        )

        self.assertEqual(result, "replacement")
        self.assertEqual(keeper.knob("charon_node_id").value(), "shared-id")

    def test_syncs_anchor_parent_and_contact_sheet_reference(self):
        source = _Node(
            {"charon_contact_sheet": _Knob("")},
            name="CharonOp1",
            class_name="Group",
        )
        contact_sheet = _Node(
            {
                "charon_link_anchor": _Knob("CharonOp1.charon_link_anchor"),
                "charon_parent_id": _Knob("old"),
                "charon_read_id": _Knob("sheet-id"),
            },
            name="ContactSheet1",
            class_name="Group",
        )
        nuke = _Nuke({"Group": [source, contact_sheet]})

        sync_anchored_output_nodes(nuke, source, "parent-1")

        self.assertEqual(contact_sheet.metadata_value, "parent-1")
        self.assertEqual(contact_sheet.knob("charon_parent_id").value(), "parent-1")
        self.assertEqual(source.knob("charon_contact_sheet").value(), "ContactSheet1")

    def test_collects_linked_ids_using_metadata_knob_and_name_fallbacks(self):
        metadata_id = _Node(
            metadata_values={"charon/parent_id": "parent-1", "charon/read_id": "read-one"},
        )
        knob_id = _Node(
            {
                "charon_parent_id": _Knob("parent-1"),
                "charon_read_node_id": _Knob("read-two"),
            }
        )
        name_id = _Node(metadata_values={"charon/parent_id": "parent-1"}, name="ReadThree")
        unrelated = _Node(metadata_values={"charon/parent_id": "other"}, name="Ignored")
        nuke = _Nuke({"Read": [metadata_id, knob_id, name_id, unrelated]})

        identifiers = collect_linked_output_ids(nuke, "parent-1")

        self.assertEqual(identifiers, ["read-one", "read-two", "readthree"])

    def test_updates_parent_ids_across_output_node_classes(self):
        read = _Node({"charon_parent_id": _Knob("old-parent")})
        group = _Node(metadata_value="old-parent")
        unrelated = _Node(metadata_value="another-parent")
        nuke = _Nuke({"Read": [read, unrelated], "ReadGeo2": [], "Group": [group]})

        update_linked_parent_ids(nuke, "old-parent", "new-parent")

        self.assertEqual(read.knob("charon_parent_id").value(), "new-parent")
        self.assertEqual(read.metadata_value, "new-parent")
        self.assertEqual(group.metadata_value, "new-parent")
        self.assertEqual(unrelated.metadata_value, "another-parent")

    def test_normalizes_and_limits_node_id(self):
        self.assertEqual(normalize_node_id("  ABCDEF123  ", max_length=6), "abcdef")
        self.assertEqual(normalize_node_id(None), "")

    def test_safe_knob_value_handles_missing_and_failing_knobs(self):
        node = _Node({"good": _Knob("value"), "bad": _Knob(error=True)})

        self.assertEqual(safe_knob_value(node, "good"), "value")
        self.assertIsNone(safe_knob_value(node, "missing"))
        self.assertIsNone(safe_knob_value(node, "bad"))

    def test_script_hash_prefers_knob_then_metadata(self):
        with_knob = _Node(
            {"charon_script_hash": _Knob(" KNOB-HASH ")},
            metadata_value="metadata-hash",
        )
        metadata_only = _Node(metadata_value=" METADATA-HASH ")

        self.assertEqual(read_script_hash(with_knob), "knob-hash")
        self.assertEqual(read_script_hash(metadata_only), "metadata-hash")
        self.assertEqual(normalize_script_hash(" HASH "), "hash")


if __name__ == "__main__":
    unittest.main()
