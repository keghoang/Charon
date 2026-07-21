import unittest

from charon.workflow_pipeline import validate_converted_workflow


class WorkflowPipelineValidationTests(unittest.TestCase):
    def test_accepts_conversion_with_matching_source_ids_and_types(self):
        source = {
            "nodes": [
                {"id": "320:301", "type": "PrimitiveInt"},
                {"id": 75, "type": "SaveVideo"},
            ]
        }
        converted = {
            "320:301": {"class_type": "PrimitiveInt", "inputs": {"value": 10}},
            "75": {"class_type": "SaveVideo", "inputs": {}},
        }

        validate_converted_workflow(source, converted)

    def test_rejects_unrelated_browser_export(self):
        source = {
            "nodes": [
                {"id": "320:301", "type": "PrimitiveInt"},
                {"id": 75, "type": "SaveVideo"},
            ]
        }
        unrelated = {
            "9": {"class_type": "SaveImage", "inputs": {}},
            "62": {"class_type": "CLIPLoader", "inputs": {}},
        }

        with self.assertRaisesRegex(RuntimeError, "does not match.*unknown node IDs 9, 62"):
            validate_converted_workflow(source, unrelated)

    def test_rejects_source_node_type_substitution(self):
        source = {"nodes": [{"id": 75, "type": "SaveVideo"}]}
        converted = {"75": {"class_type": "SaveImage", "inputs": {}}}

        with self.assertRaisesRegex(RuntimeError, "node type mismatches"):
            validate_converted_workflow(source, converted)


if __name__ == "__main__":
    unittest.main()
