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
                "save_fbx": ("BOOLEAN", {"default": True, "tooltip": "Write a .fbx file (ASCII) of the camera to the output directory"}),
                "fbx_prefix": ("STRING", {"default": "charon_camera_fbx", "tooltip": "Filename prefix for .fbx export"}),
            }
        }

    RETURN_TYPES = (
        "STRING",  # nukecam_file
        "STRING",  # nukecam_text
        "STRING",  # fbx_file
    )
    RETURN_NAMES = (
        "nukecam_file",
        "nukecam_text",
        "fbx_file",
    )
    FUNCTION = "extract"
    OUTPUT_NODE = True
    CATEGORY = "CHARON/3D"

    def extract(self, extrinsics_json, intrinsics_json, batch_index=0,
               transform_json="",
               image_width=1920, image_height=1080, sensor_width_mm=36.0,
               save_nukecam=True, nukecam_prefix="charon_camera",
               save_fbx=True, fbx_prefix="charon_camera_fbx"):
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
        
        c2w_rot = euler_xyz_deg_to_matrix(*euler_add)
        c2w_aligned = np.eye(4, dtype=float)
        c2w_aligned[:3, :3] = c2w_rot
        c2w_aligned[:3, 3] = trans_add

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
        fbx_path = ""
        ui_files = []
        
        from pathlib import Path
        out_dir = Path(folder_paths.get_output_directory())
        out_dir.mkdir(parents=True, exist_ok=True)

        if save_nukecam:
            safe_prefix = nukecam_prefix or "charon_camera"
            nc_path = out_dir / f"{safe_prefix}_{uuid.uuid4().hex[:8]}.nukecam"
            try:
                nc_path.write_text(nukecam_snippet, encoding="utf-8")
                nukecam_path = str(nc_path)
                ui_files.append({"filename": nc_path.name, "subfolder": "", "type": "output"})
                print(f"[CHARON_Camera_From_DA3] Wrote Nuke cam to {nc_path}")
            except Exception as e:
                print(f"[CHARON_Camera_From_DA3] Failed to write Nuke cam file: {e}")

        if save_fbx:
            # Convert camera intrinsics to FBX format (inches)
            film_width_inch = haperture_mm / 25.4
            film_height_inch = vaperture_mm / 25.4
            
            # Use nukeCam translation and rotation directly - no conversion needed
            # Translation and rotation orders are the same between nukeCam and FBX
            
            # Generate random IDs
            id_model = uuid.uuid4().int & (1<<62)-1
            id_node_attr = uuid.uuid4().int & (1<<62)-1
            id_scene = uuid.uuid4().int & (1<<62)-1
            
            # Use safe values if fbx_prefix is empty
            s_fbx_prefix = fbx_prefix or "charon_camera_fbx"

            fbx_content = f"""
; FBX 7.7.0 project file
; Created by ComfyUI-Charon

FBXHeaderExtension:  {{
    FBXHeaderVersion: 1003
    FBXVersion: 7700
    CreationTimeStamp:  {{
        Version: 1000
        Year: 2025
        Month: 12
        Day: 16
        Hour: 12
        Minute: 0
        Second: 0
        Millisecond: 0
    }}
    Creator: "ComfyUI-Charon"
    SceneInfo: "SceneInfo::GlobalInfo", "UserData" {{
        Type: "UserData"
        Version: 100
        MetaData:  {{
            Version: 100
            Title: ""
            Subject: ""
            Author: ""
            Keywords: ""
            Revision: ""
            Comment: ""
        }}
        Properties70:  {{
            P: "DocumentUrl", "KString", "Url", "", "{s_fbx_prefix}.fbx"
            P: "SrcDocumentUrl", "KString", "Url", "", "{s_fbx_prefix}.fbx"
            P: "Original", "Compound", "", ""
            P: "Original|ApplicationVendor", "KString", "", "", "ComfyUI"
            P: "Original|ApplicationName", "KString", "", "", "Charon"
            P: "Original|ApplicationVersion", "KString", "", "", "1.0"
            P: "Original|DateTime_GMT", "DateTime", "", "", "16/12/2025 00:00:00.000"
            P: "Original|FileName", "KString", "", "", "{s_fbx_prefix}.fbx"
            P: "LastSaved", "Compound", "", ""
            P: "LastSaved|ApplicationVendor", "KString", "", "", "ComfyUI"
            P: "LastSaved|ApplicationName", "KString", "", "", "Charon"
            P: "LastSaved|ApplicationVersion", "KString", "", "", "1.0"
            P: "LastSaved|DateTime_GMT", "DateTime", "", "", "16/12/2025 00:00:00.000"
        }}
    }}
}}

GlobalSettings:  {{
    Version: 1000
    Properties70:  {{
        P: "UpAxis", "int", "Integer", "",1
        P: "UpAxisSign", "int", "Integer", "",1
        P: "FrontAxis", "int", "Integer", "",2
        P: "FrontAxisSign", "int", "Integer", "",1
        P: "CoordAxis", "int", "Integer", "",0
        P: "CoordAxisSign", "int", "Integer", "",1
        P: "OriginalUpAxis", "int", "Integer", "",1
        P: "OriginalUpAxisSign", "int", "Integer", "",1
        P: "UnitScaleFactor", "double", "Number", "",1.0
        P: "OriginalUnitScaleFactor", "double", "Number", "",1.0
        P: "AmbientColor", "ColorRGB", "Color", "",0,0,0
        P: "DefaultCamera", "KString", "", "", "Producer Perspective"
        P: "TimeMode", "enum", "", "",11
        P: "TimeProtocol", "enum", "", "",2
        P: "SnapOnFrameMode", "enum", "", "",0
        P: "TimeSpanStart", "KTime", "Time", "",0
        P: "TimeSpanStop", "KTime", "Time", "",46186158000
        P: "CustomFrameRate", "double", "Number", "",-1.0
        P: "TimeMarker", "Compound", "", ""
        P: "CurrentTimeMarker", "int", "Integer", "",-1
    }}
}}

Documents:  {{
    Count: 1
    Document: {id_scene}, "", "Scene" {{
        Properties70:  {{
            P: "SourceObject", "object", "", ""
            P: "ActiveAnimStackName", "KString", "", "", ""
        }}
        RootNode: 0
    }}
}}

References:  {{
}}

Definitions:  {{
    Version: 100
    Count: 3
    ObjectType: "GlobalSettings" {{
        Count: 1
    }}
    ObjectType: "NodeAttribute" {{
        Count: 1
        PropertyTemplate: "FbxCamera" {{
            Properties70:  {{
                P: "Color", "ColorRGB", "Color", "",0.8,0.8,0.8
                P: "Position", "Vector", "", "A",0,0,0
                P: "UpVector", "Vector", "", "A",0,1,0
                P: "InterestPosition", "Vector", "", "A",0,0,0
                P: "AspectWidth", "double", "Number", "",320
                P: "AspectHeight", "double", "Number", "",200
                P: "FilmWidth", "double", "Number", "",0.816
                P: "FilmHeight", "double", "Number", "",0.612
                P: "FilmAspectRatio", "double", "Number", "",1.33333333333333
                P: "ApertureMode", "enum", "", "",2
                P: "GateFit", "enum", "", "",0
                P: "FieldOfView", "FieldOfView", "", "A",25.1149997711182
                P: "FocalLength", "Number", "", "A",35
                P: "NearPlane", "double", "Number", "",10
                P: "FarPlane", "double", "Number", "",4000
            }}
        }}
    }}
    ObjectType: "Model" {{
        Count: 1
        PropertyTemplate: "FbxNode" {{
            Properties70:  {{
                P: "Lcl Translation", "Lcl Translation", "", "A",0,0,0
                P: "Lcl Rotation", "Lcl Rotation", "", "A",0,0,0
                P: "Lcl Scaling", "Lcl Scaling", "", "A",1,1,1
                P: "Visibility", "Visibility", "", "A",1
                P: "Visibility Inheritance", "Visibility Inheritance", "", "",1
            }}
        }}
    }}
}}

Objects:  {{
    NodeAttribute: {id_node_attr}, "NodeAttribute::charon_aligned_camera", "Camera" {{
        Properties70:  {{
            P: "FilmWidth", "double", "Number", "",{film_width_inch:.6f}
            P: "FilmHeight", "double", "Number", "",{film_height_inch:.6f}
            P: "FilmAspectRatio", "double", "Number", "",{haperture_mm/vaperture_mm:.6f}
            P: "ApertureMode", "enum", "", "",3
            P: "FocalLength", "Number", "", "A+",{focal_mm:.6f}
            P: "NearPlane", "double", "Number", "",0.100000001490116
            P: "FarPlane", "double", "Number", "",10000
            P: "FilmOffset", "Vector2D", "Vector2", "",0,0
        }}
        TypeFlags: "Camera"
        GeometryVersion: 124
        Position: 0,0,0
        Up: 0,1,0
        LookAt: 0,0,0
        ShowInfoOnMoving: 1
        ShowAudio: 0
        AudioColor: 0,1,0
        CameraOrthoZoom: 1
    }}
    Model: {id_model}, "Model::charon_aligned_camera", "Camera" {{
        Version: 232
        Properties70:  {{
            P: "RotationOrder", "enum", "", "",4
            P: "PostRotation", "Vector3D", "Vector", "",0,-90,0
            P: "RotationActive", "bool", "", "",1
            P: "ScalingMax", "Vector3D", "Vector", "",0,0,0
            P: "DefaultAttributeIndex", "int", "Integer", "",0
            P: "Lcl Translation", "Lcl Translation", "", "A+",{trans_add[0]:.6f},{trans_add[1]:.6f},{trans_add[2]:.6f}
            P: "Lcl Rotation", "Lcl Rotation", "", "A+",{euler_add[0]:.6f},{euler_add[1]:.6f},{euler_add[2]:.6f}
        }}
        Shading: Y
        Culling: "CullingOff"
    }}
}}

Connections:  {{
    
    ;Model::charon_aligned_camera, Model::RootNode
    C: "OO",{id_model},0
    
    ;NodeAttribute::charon_aligned_camera, Model::charon_aligned_camera
    C: "OO",{id_node_attr},{id_model}
}}
""".strip()

            f_path = out_dir / f"{s_fbx_prefix}_{uuid.uuid4().hex[:8]}.fbx"
            try:
                f_path.write_text(fbx_content, encoding="utf-8")
                fbx_path = str(f_path)
                ui_files.append({"filename": f_path.name, "subfolder": "", "type": "output"})
                print(f"[CHARON_Camera_From_DA3] Wrote FBX to {f_path}")
            except Exception as e:
                print(f"[CHARON_Camera_From_DA3] Failed to write FBX file: {e}")

        return {
            "ui": {"files": ui_files} if ui_files else {},
            "result": (nukecam_path, nukecam_snippet, fbx_path),
        }


NODE_CLASS_MAPPINGS = {
    "CHARON_Camera_From_DA3": CHARON_Camera_From_DA3,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CHARON_Camera_From_DA3": "CHARON Camera From DA3",
}
