import unittest

from charon.workflow_dependencies import collect_workflow_dependencies


class WorkflowDependencyTests(unittest.TestCase):
    def test_collects_nested_registry_and_aux_dependencies(self):
        workflow = {
            "nodes": [{"id": 1, "type": "Core", "properties": {"cnr_id": "comfy-core"}}],
            "definitions": {
                "subgraphs": [
                    {
                        "nodes": [
                            {
                                "id": 2,
                                "type": "Custom",
                                "properties": {
                                    "cnr_id": "comfyui-example",
                                    "aux_id": "studio/ComfyUI-Example",
                                },
                            }
                        ]
                    }
                ]
            },
        }

        self.assertEqual(
            [
                {
                    "name": "comfyui-example",
                    "repo": "https://github.com/studio/ComfyUI-Example",
                    "cnr_id": "comfyui-example",
                }
            ],
            collect_workflow_dependencies(workflow),
        )


if __name__ == "__main__":
    unittest.main()
