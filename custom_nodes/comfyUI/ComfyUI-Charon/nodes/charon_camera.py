import json
import uuid
import numpy as np
import folder_paths
import math


def _parse_da3_matrix(json_str, key, batch_index):
    """Parse a DA3 camera matrix (intrinsics or extrinsics) from JSON."""
    data = json.loads(json_str)
    if key not in data or not isinstance(data[key], list):
        raise ValueError(f"Missing '{key}' list in JSON")
    if batch_index >= len(data[key]):
        raise IndexError(f"Batch index {batch_index} out of range for {key}")
    img_key = f"image_{batch_index}"
    mat = data[key][batch_index].get(img_key)
    if mat is None:
        raise ValueError(f"No matrix for {img_key} in {key}")
    mat = np.array(mat, dtype=float)
    if mat.ndim == 3:
        mat = mat[0]
    if key == "extrinsics" and mat.shape == (3, 4):
        mat = np.vstack([mat, np.array([0, 0, 0, 1], dtype=float)])
    return mat


class CHARON_Camera_From_DA3:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "extrinsics_json": ("STRING", {"multiline": True, "tooltip": "DA3 extrinsics JSON output"}),
                "intrinsics_json": ("STRING", {"multiline": True, "tooltip": "DA3 intrinsics JSON output"}),
                "batch_index": ("INT", {"default": 0, "min": 0, "max": 999, "tooltip": "Which image index to extract"}),
                "image_width": ("INT", {"default": 1920, "min": 1, "tooltip": "Source image width in pixels"}),
                "image_height": ("INT", {"default": 1080, "min": 1, "tooltip": "Source image height in pixels"}),
                "sensor_width_mm": ("FLOAT", {"default": 36.0, "min": 1e-3, "tooltip": "Virtual sensor width (horizontal aperture) in mm"}),
            },
            "optional": {
                "transform_json": ("STRING", {"multiline": True, "default": "", "tooltip": "Optional transform JSON from CHARON_3D_Auto_Align (rotation/translation)"}),
                "save_nukecam": ("BOOLEAN", {"default": True, "tooltip": "Write a .nukecam text snippet to the output directory"}),
                "nukecam_prefix": ("STRING", {"default": "charon_camera", "tooltip": "Filename prefix for .nukecam export"}),
            }
        }

    RETURN_TYPES = (
        "STRING",  # nukecam_file
        "STRING",  # nukecam_text
    )
    RETURN_NAMES = (
        "nukecam_file",
        "nukecam_text",
    )
    FUNCTION = "extract"
    OUTPUT_NODE = True
    CATEGORY = "CHARON/3D"

    def extract(self, extrinsics_json, intrinsics_json, batch_index=0,
               transform_json="",
               image_width=1920, image_height=1080, sensor_width_mm=36.0,
               save_nukecam=True, nukecam_prefix="charon_camera"):
        try:
            extr = _parse_da3_matrix(extrinsics_json, "extrinsics", batch_index)
            intr = _parse_da3_matrix(intrinsics_json, "intrinsics", batch_index)
        except Exception as e:
            raise ValueError(f"Failed to parse DA3 camera data: {e}")

        # DA3 extrinsics are world-to-camera (w2c); invert to get camera-to-world (c2w)
        try:
            c2w_orig = np.linalg.inv(extr)
        except np.linalg.LinAlgError:
            raise ValueError("Extrinsics matrix is non-invertible")

        cam_pos = c2w_orig[:3, 3]
        fx, fy = float(intr[0, 0]), float(intr[1, 1])
        cx, cy = float(intr[0, 2]), float(intr[1, 2])

        haperture_mm = float(sensor_width_mm)
        vaperture_mm = haperture_mm * (float(image_height) / float(image_width))
        focal_mm = fx * haperture_mm / float(image_width)

        def rot_to_euler_xyz_deg(R):
            sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
            singular = sy < 1e-6
            if not singular:
                rx = math.degrees(math.atan2(R[2, 1], R[2, 2]))
                ry = math.degrees(math.atan2(-R[2, 0], sy))
                rz = math.degrees(math.atan2(R[1, 0], R[0, 0]))
            else:
                rx = math.degrees(math.atan2(-R[1, 2], R[1, 1]))
                ry = math.degrees(math.atan2(-R[2, 0], sy))
                rz = 0.0
            return rx, ry, rz

        def euler_xyz_deg_to_matrix(rx, ry, rz):
            rx_r = math.radians(rx)
            ry_r = math.radians(ry)
            rz_r = math.radians(rz)
            cx, sx = math.cos(rx_r), math.sin(rx_r)
            cy, sy = math.cos(ry_r), math.sin(ry_r)
            cz, sz = math.cos(rz_r), math.sin(rz_r)
            Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
            Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
            Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
            return Rz @ Ry @ Rx

        # Euler/translation additions (debug)
        orig_rx, orig_ry, orig_rz = rot_to_euler_xyz_deg(c2w_orig[:3, :3])
        align_rx = align_ry = align_rz = 0.0
        align_trans = np.zeros(3)
        if transform_json and transform_json.strip():
            try:
                tdata = json.loads(transform_json)
                align_rot = np.array(tdata.get("rotation"), dtype=float)
                align_rx, align_ry, align_rz = rot_to_euler_xyz_deg(align_rot)
                align_trans = np.array(tdata.get("translation"), dtype=float).reshape(3)
            except Exception:
                pass

        euler_add = (orig_rx + align_rx, orig_ry + align_ry, orig_rz + align_rz)
        trans_add = cam_pos + align_trans
        # Build aligned matrices from additive Euler/translation (single application)
        c2w_rot = euler_xyz_deg_to_matrix(*euler_add)
        c2w_aligned = np.eye(4, dtype=float)
        c2w_aligned[:3, :3] = c2w_rot
        c2w_aligned[:3, 3] = trans_add
        extr_aligned = np.linalg.inv(c2w_aligned)

        nukecam_snippet = (
            "set cut_paste_input [stack 0]\n"
            "version 16.0 v3\n"
            "push $cut_paste_input\n"
            "Camera3 {\n"
            f" translate {{{trans_add[0]} {trans_add[1]} {trans_add[2]}}}\n"
            f" rotate {{{euler_add[0]} {euler_add[1]} {euler_add[2]}}}\n"
            f" focal {focal_mm}\n"
            f" haperture {haperture_mm}\n"
            f" vaperture {vaperture_mm}\n"
            f" label \"CHARON from DA3\"\n"
            "}\n"
        )

        nukecam_path = ""
        ui_files = []
        if save_nukecam:
            from pathlib import Path
            out_dir = Path(folder_paths.get_output_directory())
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_prefix = nukecam_prefix or "charon_camera"
            nc_path = out_dir / f"{safe_prefix}_{uuid.uuid4().hex[:8]}.nukecam"
            try:
                nc_path.write_text(nukecam_snippet, encoding="utf-8")
                nukecam_path = str(nc_path)
                ui_files.append({"filename": nc_path.name, "subfolder": "", "type": "output"})
                print(f"[CHARON_Camera_From_DA3] Wrote Nuke cam to {nc_path}")
            except Exception as e:
                print(f"[CHARON_Camera_From_DA3] Failed to write Nuke cam file: {e}")

        return {
            "ui": {"files": ui_files} if ui_files else {},
            "result": (nukecam_path, nukecam_snippet),
        }


NODE_CLASS_MAPPINGS = {
    "CHARON_Camera_From_DA3": CHARON_Camera_From_DA3,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CHARON_Camera_From_DA3": "CHARON Camera From DA3",
}
