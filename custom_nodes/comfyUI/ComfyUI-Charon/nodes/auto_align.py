import json
import os
import uuid

import numpy as np

try:
    import trimesh
except ImportError as exc:
    raise ImportError("CHARON_3D_Auto_Align requires the trimesh package. Install with `pip install -r requirements.txt`.") from exc

import folder_paths

# Hyperparameters (aligned with Blender/Maya versions)
ITERATION_RANSAC = 200
ITERATION_MEDIAN = 10
THRESHOLD = 5 * (np.pi / 180)
MAX_POLYS = 10000
MAX_POLYS_SUBSET = 100
SYMMETRY_PAIR_DIST = 0.03
SYMMETRY_BUCKET_SIZE = 0.1


def _normalize(arr: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-8
    return arr / norms


def _load_mesh(path: str) -> "trimesh.Trimesh":
    mesh = trimesh.load(path, force="mesh", process=False)
    if isinstance(mesh, trimesh.Scene):
        mesh = mesh.dump(concatenate=True)
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError(f"Unsupported mesh type from {path}")
    if mesh.vertices.size == 0 or mesh.faces.size == 0:
        raise ValueError(f"Mesh has no geometry: {path}")
    return mesh


def _save_mesh(mesh: "trimesh.Trimesh", input_path: str) -> str:
    base = os.path.splitext(os.path.basename(input_path))[0]
    out_dir = os.path.join(folder_paths.get_temp_directory(), "charon_auto_align")
    os.makedirs(out_dir, exist_ok=True)
    out_name = f"{base}_charon_aligned_{uuid.uuid4().hex[:8]}.obj"
    out_path = os.path.join(out_dir, out_name)
    mesh.export(out_path)
    return out_path


def get_symmetry_plane(normals: np.ndarray, positions: np.ndarray) -> np.ndarray:
    if normals.shape[0] > MAX_POLYS:
        idx = np.random.choice(normals.shape[0], MAX_POLYS, replace=False)
        normals = normals[idx]
        positions = positions[idx]

    if normals.shape[0] > MAX_POLYS_SUBSET:
        idx = np.random.choice(normals.shape[0], MAX_POLYS_SUBSET, replace=False)
        normals_subset = normals[idx]
        positions_subset = positions[idx]
    else:
        normals_subset = normals
        positions_subset = positions

    positions_1 = np.tile(positions, (normals_subset.shape[0], 1))
    positions_2 = np.repeat(positions_subset, normals.shape[0], axis=0)
    normals_1 = np.tile(normals, (normals_subset.shape[0], 1))
    normals_2 = np.repeat(normals_subset, normals.shape[0], axis=0)

    plane_normals = positions_1 - positions_2
    plane_normals_scale = np.linalg.norm(plane_normals, axis=1)
    plane_normals = plane_normals / (plane_normals_scale + 1e-6).reshape(-1, 1)
    normals_3 = normals_1 - 2 * plane_normals * np.sum(plane_normals * normals_1, axis=1).reshape(-1, 1)

    idx = np.nonzero(
        (np.linalg.norm(normals_2 - normals_3, axis=1) < SYMMETRY_PAIR_DIST) &
        (plane_normals_scale > 1e-6)
    )[0]
    plane_normals = plane_normals[idx]
    plane_centers = np.sum((positions_1 + positions_2)[idx] / 2 * plane_normals, axis=1)

    plane = np.concatenate((plane_normals, plane_centers.reshape(-1, 1)), axis=1)
    plane = np.concatenate((plane, -plane), axis=0)
    plane_centers_std = np.std(plane[:, 3])
    plane[:, 3] = plane[:, 3] / (plane_centers_std + 1e-6)

    plane_int = np.rint(plane / SYMMETRY_BUCKET_SIZE).astype(np.int64)
    plane_range = np.max(plane_int, axis=0) - np.min(plane_int, axis=0) + 1
    plane_int_hash = (
        plane_int[:, 0]
        + plane_int[:, 1] * plane_range[0]
        + plane_int[:, 2] * plane_range[0] * plane_range[1]
        + plane_int[:, 3] * plane_range[0] * plane_range[1] * plane_range[2]
    )
    value, count = np.unique(plane_int_hash, return_counts=True)
    origin = plane_int[(plane_int_hash == value[np.argmax(count)]).nonzero()[0][0]] * SYMMETRY_BUCKET_SIZE
    dist = np.linalg.norm(plane - origin.reshape(1, -1), axis=1)
    plane_res = np.median(plane[(dist < SYMMETRY_BUCKET_SIZE).nonzero()[0]], axis=0)
    plane_res[3] = plane_res[3] * (plane_centers_std + 1e-6)
    plane_res[:3] = plane_res[:3] / np.linalg.norm(plane_res[:3])
    return plane_res


def get_matrix(areas: np.ndarray, normals: np.ndarray, fixed_axis=None) -> np.ndarray:
    if areas.size > MAX_POLYS:
        idx = np.random.choice(areas.size, MAX_POLYS, p=areas / sum(areas), replace=False)
        areas = areas[idx]
        normals = normals[idx]

    first_indices = np.random.choice(areas.size, ITERATION_RANSAC, p=areas / sum(areas))

    best_model = np.identity(3)
    best_value = -1.0

    for index in first_indices:
        model = np.zeros((3, 3))
        model[0] = normals[index] if fixed_axis is None else fixed_axis
        next_indices = np.nonzero(np.abs(normals @ model[0]) < np.sin(THRESHOLD))[0]
        if next_indices.size > 0:
            next_areas = areas[next_indices]
            model[1] = normals[np.random.choice(next_indices, p=next_areas / sum(next_areas))]
        else:
            model[1] = np.zeros(3)
            model[1][(np.argmax(np.abs(model[0])) + 1) % 3] = 1

        model[1] = np.cross(model[0], model[1])
        model[1] = model[1] / np.linalg.norm(model[1])
        model[2] = np.cross(model[0], model[1])

        idx = np.max(np.abs(normals @ model.T), axis=1) > np.cos(THRESHOLD)
        value = np.sum(areas[idx])
        if best_value < value:
            best_value, best_model, best_indices = value, model, idx

    areas = areas[best_indices]
    normals = normals[best_indices]
    axis = np.vstack((best_model, -best_model))
    axis_indices = np.argmax(normals @ axis.T, axis=1)
    normals_per_axis = []
    areas_per_axis = []
    xyz_axis = np.array([[[1, 2], [2, 4], [4, 5], [5, 1]], [[3, 2], [2, 0], [0, 5], [5, 3]],
                         [[0, 1], [1, 3], [3, 4], [4, 0]]])
    for i in range(6):
        normals_per_axis.append(normals[axis_indices == i])
        areas_per_axis.append(areas[axis_indices == i])

    normals_area = []
    for i in range(3):
        normals_area.append(np.concatenate([areas_per_axis[a] for (a, _) in xyz_axis[i]]))

    for _ in range(ITERATION_MEDIAN):
        for i in range(3):
            if fixed_axis is not None and i != 0:
                continue

            normals_proj = np.concatenate([normals_per_axis[a] @ axis[b] for (a, b) in xyz_axis[i]])
            if normals_proj.size == 0:
                continue

            sort_indices = np.argsort(normals_proj)
            value = normals_proj[sort_indices]
            weight = normals_area[i][sort_indices]
            weight_cumsum = np.cumsum(weight)
            med_index = np.searchsorted(weight_cumsum, weight_cumsum[-1] / 2)

            c, s = np.cos(value[med_index]), np.sin(value[med_index])
            j, k = (i + 1) % 3, (i + 2) % 3

            transform = np.identity(3)
            transform[(j, j, k, k), (j, k, j, k)] = np.array([c, -s, s, c])
            best_model = transform.T @ best_model
            axis = np.vstack((best_model, -best_model))

    unit_rot = np.array([[0, 0, 1], [1, 0, 0], [0, 1, 0]])
    flip_rot = np.array([[1, 0, 0], [0, 0, 1], [0, 1, 0]])
    unit_diag = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]])

    best_model_opt = best_model
    best_trace = 0
    rot = np.identity(3)
    for _ in range(3):
        rot = unit_rot @ rot
        for j in range(4):
            model_opt = np.diag(unit_diag[j]) @ rot @ best_model
            trace = np.trace(model_opt)
            if trace > best_trace:
                best_trace, best_model_opt = trace, model_opt

            model_opt = -np.diag(unit_diag[j]) @ flip_rot @ rot @ best_model
            trace = np.trace(model_opt)
            if trace > best_trace:
                best_trace, best_model_opt = trace, model_opt

    return best_model_opt


def align_mesh(mesh: "trimesh.Trimesh", symmetry: bool, ground_snap: bool):
    areas = mesh.area_faces
    normals = _normalize(mesh.face_normals)
    vertex_normals = _normalize(mesh.vertex_normals)
    positions = mesh.vertices

    if symmetry:
        plane = get_symmetry_plane(vertex_normals, positions)
        rotation = get_matrix(areas, normals, fixed_axis=plane[:3])
    else:
        rotation = get_matrix(areas, normals)

    rot_matrix = np.eye(4)
    rot_matrix[:3, :3] = rotation
    mesh = mesh.copy()
    mesh.apply_transform(rot_matrix)

    translation = np.zeros(3)
    if ground_snap:
        min_y = float(mesh.vertices[:, 1].min())
        if abs(min_y) > 1e-8:
            translation = np.array([0.0, -min_y, 0.0])
            trans_matrix = np.eye(4)
            trans_matrix[:3, 3] = translation
            mesh.apply_transform(trans_matrix)

    return mesh, rotation, translation


class CHARON_3D_Auto_Align:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mesh_path": ("STRING", {"default": "", "multiline": False, "tooltip": "Path to mesh file (.obj/.ply/.glb etc.)"}),
                "symmetry": ("BOOLEAN", {"default": False, "tooltip": "Try to detect symmetry plane before alignment"}),
                "ground_snap": ("BOOLEAN", {"default": True, "tooltip": "Lift mesh so lowest point sits on Y=0"}),
                "filename_prefix": ("STRING", {"default": "charon_mesh", "tooltip": "Prefix for saved aligned mesh in ComfyUI output directory"}),
                "save_transform_json": ("BOOLEAN", {"default": False, "tooltip": "Also write transform JSON to output directory for debugging"}),
            }
        }

    RETURN_TYPES = ("FILE", "STRING")
    RETURN_NAMES = ("aligned_mesh_file", "transform_json")
    FUNCTION = "execute"
    CATEGORY = "CHARON/3D"

    def execute(self, mesh_path: str, symmetry: bool = False, ground_snap: bool = True,
               filename_prefix: str = "charon_mesh", save_transform_json: bool = False):
        if not mesh_path:
            raise ValueError("mesh_path is required")
        if not os.path.exists(mesh_path):
            raise FileNotFoundError(f"Mesh not found: {mesh_path}")

        mesh = _load_mesh(mesh_path)
        aligned_mesh, rotation, translation = align_mesh(mesh, symmetry=symmetry, ground_snap=ground_snap)
        # Save to ComfyUI output directory with user prefix
        output_dir = folder_paths.get_output_directory()
        os.makedirs(output_dir, exist_ok=True)
        # Always force .obj output
        ext = ".obj"
        out_name = f"{filename_prefix}_{uuid.uuid4().hex[:8]}{ext}"
        out_path = os.path.join(output_dir, out_name)
        aligned_mesh.export(out_path)
        print(f"[CHARON_3D_Auto_Align] Saved mesh to: {out_path}")

        transform = {"rotation": rotation.tolist(), "translation": translation.tolist()}

        if save_transform_json:
            t_name = f"{filename_prefix}_{uuid.uuid4().hex[:8]}_transform.json"
            t_path = os.path.join(output_dir, t_name)
            # Compute Euler (XYZ) for debug/reference only
            try:
                sy = (rotation[0, 0] ** 2 + rotation[1, 0] ** 2) ** 0.5
                singular = sy < 1e-6
                if not singular:
                    rot_x = float(np.degrees(np.arctan2(rotation[2, 1], rotation[2, 2])))
                    rot_y = float(np.degrees(np.arctan2(-rotation[2, 0], sy)))
                    rot_z = float(np.degrees(np.arctan2(rotation[1, 0], rotation[0, 0])))
                else:
                    rot_x = float(np.degrees(np.arctan2(-rotation[1, 2], rotation[1, 1])))
                    rot_y = float(np.degrees(np.arctan2(-rotation[2, 0], sy)))
                    rot_z = 0.0
                transform["euler_xyz_deg"] = [rot_x, rot_y, rot_z]
            except Exception:
                transform["euler_xyz_deg"] = None

            with open(t_path, "w", encoding="utf-8") as f:
                json.dump(transform, f, indent=2)
            print(f"[CHARON_3D_Auto_Align] Wrote transform JSON to {t_path}")

        file_info = {"filename": os.path.basename(out_path), "subfolder": "", "type": "output"}
        return {
            "ui": {"meshes": [file_info]},
            "result": (str(out_path), json.dumps(transform)),
        }


NODE_CLASS_MAPPINGS = {
    "CHARON_3D_Auto_Align": CHARON_3D_Auto_Align,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CHARON_3D_Auto_Align": "CHARON 3D Auto Align",
}
