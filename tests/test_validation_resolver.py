import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from charon.comfy_environment import ComfyEnvironment
from charon.validation_resolver import install_custom_nodes_via_playwright


class ValidationResolverTests(unittest.TestCase):
    def test_playwright_install_uses_runtime_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            comfy_dir = os.path.join(tmp, "ComfyUI")
            embedded_root = os.path.join(tmp, "python_embeded")
            os.makedirs(comfy_dir)
            os.makedirs(embedded_root)
            python_exe = os.path.join(embedded_root, "python.exe")
            open(python_exe, "wb").close()
            runtime = ComfyEnvironment(
                configured_path=tmp,
                base_url="http://render-node:9000",
                base_dir=tmp,
                comfy_dir=comfy_dir,
                models_dir=os.path.join(comfy_dir, "models"),
                python_exe=python_exe,
                embedded_root=embedded_root,
            )
            completed = SimpleNamespace(
                returncode=0,
                stdout='{"installed": [], "skipped": [], "failed": []}',
                stderr="",
            )

            with mock.patch(
                "charon.validation_resolver.resolve_comfy_runtime",
                return_value=runtime,
            ):
                with mock.patch(
                    "charon.validation_resolver.ComfyUIClient.test_connection",
                    return_value=True,
                ):
                    with mock.patch(
                        "charon.validation_resolver.subprocess.run",
                        return_value=completed,
                    ) as run:
                        result = install_custom_nodes_via_playwright(
                            tmp,
                            ["https://example.com/custom-node.git"],
                        )

            self.assertFalse(result.failed)
            self.assertEqual(run.call_args.args[0][-1], runtime.base_url)


if __name__ == "__main__":
    unittest.main()
