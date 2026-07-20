import unittest

from charon.processor_prompt_cache import PromptCacheRepository, prompt_path_matches_hash


class _Knob:
    def __init__(self, value=""):
        self._value = value
        self.flags = None

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value

    def setFlag(self, flags):
        self.flags = flags


class _Node:
    def __init__(self, *, metadata_value=None, metadata_error=False):
        self.knobs = {"charon_prompt_path": _Knob("C:/cache/prompt.json")}
        self.metadata_value = metadata_value
        self.metadata_error = metadata_error

    def knob(self, name):
        return self.knobs.get(name)

    def addKnob(self, knob):
        self.knobs["charon_prompt_hash"] = knob

    def metadata(self, _key):
        if self.metadata_error:
            raise RuntimeError("metadata unavailable")
        return self.metadata_value


class _Nuke:
    NO_ANIMATION = 1
    INVISIBLE = 2

    @staticmethod
    def String_Knob(_name, _label, value):
        return _Knob(value)


def _repository(node, writes=None):
    writes = writes if writes is not None else []
    return PromptCacheRepository(
        node,
        _Nuke(),
        write_metadata=lambda key, value: writes.append((key, value)) or True,
        run_on_main_thread=lambda callback: callback(),
        log_debug=lambda _message: None,
    )


class PromptCacheRepositoryTests(unittest.TestCase):
    def test_path_hash_match_uses_filename_prefix(self):
        self.assertTrue(prompt_path_matches_hash("C:/cache/abcd1234_prompt.json", "abcd1234ffff"))
        self.assertFalse(prompt_path_matches_hash("C:/cache/prompt.json", "abcd1234ffff"))

    def test_load_uses_metadata_when_hash_knob_is_missing(self):
        node = _Node(metadata_value="workflow-hash")

        self.assertEqual(_repository(node).load(), ("C:/cache/prompt.json", "workflow-hash"))

    def test_load_retains_knob_hash_when_metadata_is_unavailable(self):
        node = _Node(metadata_error=True)
        node.knobs["charon_prompt_hash"] = _Knob("knob-hash")

        self.assertEqual(_repository(node).load()[1], "knob-hash")

    def test_store_normalizes_path_and_creates_hidden_hash_knob(self):
        node = _Node()
        writes = []

        _repository(node, writes).store("C:\\cache\\prompt.json", "workflow-hash")

        self.assertEqual(node.knob("charon_prompt_path").value(), "C:/cache/prompt.json")
        self.assertEqual(node.knob("charon_prompt_hash").value(), "workflow-hash")
        self.assertEqual(node.knob("charon_prompt_hash").flags, 3)
        self.assertEqual(writes, [("charon/prompt_hash", "workflow-hash")])


if __name__ == "__main__":
    unittest.main()
