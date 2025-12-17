import os
import uuid
import folder_paths

try:
    import trimesh
except ImportError as exc:
    raise ImportError("CHARON_GLB_to_OBJ requires the trimesh package. Install with `pip install -r requirements.txt`.") from exc

class CHARON_GLB_to_OBJ:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "glb_file": ("STRING", {"default": "", "multiline": False, "tooltip": "Path to input GLB file"}),
                "filename_prefix": ("STRING", {"default": "charon_converted", "tooltip": "Prefix for saved OBJ file"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("obj_file",)
    FUNCTION = "convert"
    OUTPUT_NODE = True
    CATEGORY = "CHARON/3D"

    def convert(self, glb_file, filename_prefix="charon_converted"):
        if not glb_file:
            raise ValueError("glb_file path is required")
        if not os.path.exists(glb_file):
            raise FileNotFoundError(f"Input file not found: {glb_file}")

        try:
            # Load mesh
            # force='mesh' might fail for scenes, so we try generic load first
            mesh = trimesh.load(glb_file, process=False)
            
            # Handle Scene objects (GLB often loads as Scene)
            if isinstance(mesh, trimesh.Scene):
                # Concatenate all geometries into a single mesh for OBJ export
                # This applies transforms in the scene to the geometry
                mesh = mesh.dump(concatenate=True)
            
            if not isinstance(mesh, trimesh.Trimesh):
                 raise ValueError(f"Could not extract a valid mesh from {glb_file}")

            # Prepare output path
            output_dir = folder_paths.get_output_directory()
            os.makedirs(output_dir, exist_ok=True)
            
            out_name = f"{filename_prefix}_{uuid.uuid4().hex[:8]}.obj"
            out_path = os.path.join(output_dir, out_name)
            
            # Export
            mesh.export(out_path)
            print(f"[CHARON_GLB_to_OBJ] Converted {glb_file} to {out_path}")
            
            # UI info
            file_info = {"filename": out_name, "subfolder": "", "type": "output"}
            
            return {
                "ui": {"files": [file_info]},
                "result": (str(out_path),),
            }
            
        except Exception as e:
            raise RuntimeError(f"Failed to convert GLB to OBJ: {e}")

NODE_CLASS_MAPPINGS = {
    "CHARON_GLB_to_OBJ": CHARON_GLB_to_OBJ,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CHARON_GLB_to_OBJ": "CHARON GLB to OBJ",
}
