import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request


logger = logging.getLogger(__name__)


class ComfyUIClient:
    """Client for interacting with ComfyUI API."""

    def __init__(self, base_url="http://127.0.0.1:8188", timeout=300):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def test_connection(self):
        try:
            request = urllib.request.Request(f"{self.base_url}/system_stats")
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.getcode() == 200
        except Exception as exc:
            logger.error("Connection test failed: %s", exc)
            return False

    def get_system_stats(self):
        try:
            request = urllib.request.Request(f"{self.base_url}/system_stats")
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.getcode() == 200:
                    return json.loads(response.read().decode("utf-8"))
            return None
        except Exception as exc:
            logger.error("Failed to get system stats: %s", exc)
            return None

    def upload_image(self, image_path):
        try:
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Image file not found: {image_path}")

            filename = os.path.basename(image_path)
            logger.info("Uploading image: %s (%s bytes)", filename, os.path.getsize(image_path))

            with open(image_path, "rb") as handle:
                image_data = handle.read()

            boundary = "----WebKitFormBoundary" + time.strftime("%Y%m%d%H%M%S")
            body = []
            body.append(f"--{boundary}".encode())
            body.append(f'Content-Disposition: form-data; name="image"; filename="{filename}"'.encode())
            body.append(b"Content-Type: image/png")
            body.append(b"")
            body.append(image_data)

            body.append(f"--{boundary}".encode())
            body.append(b'Content-Disposition: form-data; name="overwrite"')
            body.append(b"")
            body.append(b"true")

            body.append(f"--{boundary}--".encode())
            body_data = b"\r\n".join(body)

            request = urllib.request.Request(
                f"{self.base_url}/upload/image",
                data=body_data,
                headers={
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                    "Content-Length": str(len(body_data)),
                },
            )

            with urllib.request.urlopen(request, timeout=30) as response:
                if response.getcode() == 200:
                    reply = json.loads(response.read().decode("utf-8"))
                    return reply.get("name") or reply.get("filename")
            return None
        except Exception as exc:
            logger.error("Failed to upload image: %s", exc)
            return None

    def submit_workflow(self, workflow):
        try:
            data = json.dumps({"prompt": workflow}).encode("utf-8")
            request = urllib.request.Request(
                f"{self.base_url}/prompt",
                data=data,
                headers={"Content-Type": "application/json"},
            )

            with urllib.request.urlopen(request, timeout=30) as response:
                if response.getcode() == 200:
                    reply = json.loads(response.read().decode("utf-8"))
                    return reply.get("prompt_id") or reply.get("id")
            return None
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode()
            except Exception:
                detail = str(exc)
            logger.error("HTTP error submitting workflow: %s", detail)
            return None
        except Exception as exc:
            logger.error("Failed to submit workflow: %s", exc)
            return None

    def get_history(self, prompt_id):
        try:
            request = urllib.request.Request(f"{self.base_url}/history/{prompt_id}")
            with urllib.request.urlopen(request, timeout=10) as response:
                if response.getcode() == 200:
                    return json.loads(response.read().decode("utf-8"))
            return None
        except Exception as exc:
            logger.error("Failed to get history: %s", exc)
            return None

    def get_queue_status(self):
        """Get current queue status and progress info."""
        try:
            request = urllib.request.Request(f"{self.base_url}/queue")
            with urllib.request.urlopen(request, timeout=5) as response:
                if response.getcode() == 200:
                    return json.loads(response.read().decode("utf-8"))
            return None
        except Exception as exc:
            logger.error("Failed to get queue status: %s", exc)
            return None

    def get_progress_for_prompt(self, prompt_id):
        """Get progress percentage for a specific prompt ID."""
        queue_data = self.get_queue_status()
        if not queue_data:
            return 0.0
        
        # Check running queue for current progress
        running = queue_data.get("queue_running", [])
        for item in running:
            if len(item) >= 2 and item[1] == prompt_id:
                # If it's running, assume 50% progress (could enhance with more detailed progress)
                return 0.5
        
        # Check pending queue
        pending = queue_data.get("queue_pending", [])
        for item in pending:
            if len(item) >= 2 and item[1] == prompt_id:
                return 0.0  # Still pending
        
        # If not in queues, check history for completion
        history = self.get_history(prompt_id)
        if history and prompt_id in history:
            status = history[prompt_id].get("status", {}).get("status_str")
            if status == "success":
                return 1.0
            elif status == "error":
                return -1.0  # Use negative to indicate error
        
        return 0.0

    def wait_for_completion(self, prompt_id, check_interval=1.0):
        start = time.time()
        while time.time() - start < self.timeout:
            try:
                history = self.get_history(prompt_id)
                if history and prompt_id in history:
                    info = history[prompt_id]
                    status = info.get("status", {}).get("status_str")
                    if status == "success":
                        outputs = info.get("outputs", {})
                        if outputs:
                            return True, outputs
                    elif status == "error":
                        error = info.get("status", {}).get("status_message", "Unknown error")
                        logger.error("Workflow failed: %s", error)
                        return False, None
                time.sleep(check_interval)
            except Exception as exc:
                logger.error("Error checking completion: %s", exc)
                time.sleep(check_interval)
        logger.error("Workflow timed out")
        return False, None

    def download_image(self, filename, output_path):
        return self.download_file(filename, output_path)

    def download_file(self, filename, output_path, subfolder: str = "", file_type: str = "output"):
        try:
            params = urllib.parse.urlencode(
                {
                    "filename": filename,
                    "subfolder": subfolder or "",
                    "type": file_type or "output",
                }
            )
            request = urllib.request.Request(f"{self.base_url}/view?{params}")
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.getcode() == 200:
                    with open(output_path, "wb") as handle:
                        handle.write(response.read())
                    return True
                logger.error("Failed to download file: %s", response.getcode())
                return False
        except Exception as exc:
            logger.error("Failed to download file: %s", exc)
            return False

    def process_workflow_with_image(self, workflow, image_path, output_dir=None):
        upload_name = self.upload_image(image_path)
        if not upload_name:
            return False, None

        workflow_copy = workflow.copy()
        for node_id, node_data in workflow_copy.items():
            if node_data.get("class_type") == "LoadImage":
                node_data.setdefault("inputs", {})
                node_data["inputs"]["image"] = upload_name
                break

        prompt_id = self.submit_workflow(workflow_copy)
        if not prompt_id:
            return False, None

        success, outputs = self.wait_for_completion(prompt_id)
        if not success:
            return False, None

        output_filename = None
        for node_id, node_data in workflow_copy.items():
            if node_data.get("class_type") == "SaveImage":
                if outputs and node_id in outputs:
                    images = outputs[node_id].get("images", [])
                    if images:
                        output_filename = images[0].get("filename")
                        break

        if not output_filename:
            logger.error("No output image found in workflow results")
            return False, None

        if output_dir is None:
            output_dir = os.path.dirname(image_path)
        os.makedirs(output_dir, exist_ok=True)
        target_path = os.path.join(output_dir, f"comfyui_output_{int(time.time())}.png")

        if self.download_image(output_filename, target_path):
            return True, target_path
        return False, None
