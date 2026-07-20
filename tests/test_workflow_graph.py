import unittest

from charon.workflow_graph import iter_workflow_nodes


class WorkflowGraphTests(unittest.TestCase):
    def test_iterates_nested_frontend_subgraph_nodes(self):
        workflow = {
            "nodes": [{"id": 1, "type": "TopNode"}],
            "definitions": {
                "subgraphs": [
                    {
                        "nodes": [{"id": 2, "type": "NestedNode"}],
                    }
                ]
            },
        }

        nodes = list(iter_workflow_nodes(workflow))

        self.assertEqual(["TopNode", "NestedNode"], [node["type"] for _, node in nodes])

    def test_iterates_api_prompt_nodes_without_metadata_dicts(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {}},
            "metadata": {"not": "a node"},
        }

        nodes = list(iter_workflow_nodes(workflow))

        self.assertEqual([("1", workflow["1"])], nodes)


if __name__ == "__main__":
    unittest.main()
