import json
import os

WORKFLOW_DIR = r"C:\Users\kien\git\Charon\extracted_workflows"

def load_json(filename):
    path = os.path.join(WORKFLOW_DIR, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_json(data, filename):
    path = os.path.join(WORKFLOW_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
    print(f"Saved {path}")

def fix_sdxl_txt2img():
    print("Fixing SDXL Text-to-Image...")
    workflow = load_json("sdxl_txt2img.json")
    # ... (Previous code remains same, skipping for brevity in this thought trace but will be in full file) ...
    # Re-implementing simplified version for context
    workflow["247"]["inputs"]["clip"] = ["6", 1]
    workflow["9"]["inputs"]["clip"] = ["247", 0]
    workflow["10"]["inputs"]["clip"] = ["247", 0]
    workflow["15"]["inputs"]["model"] = ["6", 0]
    workflow["15"]["inputs"]["positive"] = ["9", 0]
    workflow["15"]["inputs"]["negative"] = ["10", 0]
    workflow["15"]["inputs"]["latent_image"] = ["16", 0]
    workflow["19"]["inputs"]["samples"] = ["15", 0]
    workflow["19"]["inputs"]["vae"] = ["6", 2]
    workflow["25"]["inputs"]["images"] = ["19", 0]
    workflow["6"]["inputs"]["ckpt_name"] = "sd_xl_base_1.0.safetensors"
    for node_id in ["235", "236", "237", "239"]:
        if node_id in workflow:
            del workflow[node_id]
    save_json(workflow, "sdxl_txt2img_fixed.json")

def fix_sdxl_img2img():
    print("Fixing SDXL Image-to-Image...")
    workflow = load_json("sdxl_img2img.json")
    workflow["247"]["inputs"]["clip"] = ["38", 1]
    workflow["102"]["inputs"]["clip"] = ["247", 0]
    workflow["103"]["inputs"]["clip"] = ["247", 0]
    workflow["116"]["inputs"]["pixels"] = ["1", 0]
    workflow["105"]["inputs"]["latent_image"] = ["116", 0]
    workflow["105"]["inputs"]["model"] = ["38", 0]
    workflow["105"]["inputs"]["positive"] = ["102", 0]
    workflow["105"]["inputs"]["negative"] = ["103", 0]
    workflow["110"]["inputs"]["samples"] = ["105", 0]
    workflow["110"]["inputs"]["vae"] = ["38", 2]
    workflow["111"]["inputs"]["images"] = ["110", 0]
    workflow["38"]["inputs"]["ckpt_name"] = "sd_xl_base_1.0.safetensors"
    for node_id in ["12", "13", "117", "118", "224", "225", "226", "227", "228", "229", "235", "236", "237", "239"]:
        if node_id in workflow:
            del workflow[node_id]
    save_json(workflow, "sdxl_img2img_fixed.json")

def fix_flux_txt2img():
    print("Fixing Flux Text-to-Image...")
    workflow = load_json("flux_txt2img.json")
    workflow["10"]["inputs"]["vae_name"] = "ae.safetensors"
    workflow["11"]["inputs"]["clip_name1"] = "t5xxl_fp16.safetensors"
    workflow["11"]["inputs"]["clip_name2"] = "clip_l.safetensors"
    workflow["11"]["inputs"]["type"] = "flux"
    workflow["12"]["inputs"]["unet_name"] = "flux1-dev.safetensors"
    workflow["6"]["inputs"]["clip"] = ["11", 0]
    workflow["26"]["inputs"]["conditioning"] = ["6", 0]
    workflow["22"]["inputs"]["model"] = ["12", 0]
    workflow["22"]["inputs"]["conditioning"] = ["26", 0]
    workflow["17"]["inputs"]["model"] = ["12", 0]
    workflow["13"]["inputs"]["noise"] = ["25", 0]
    workflow["13"]["inputs"]["guider"] = ["22", 0]
    workflow["13"]["inputs"]["sampler"] = ["16", 0]
    workflow["13"]["inputs"]["sigmas"] = ["17", 0]
    workflow["13"]["inputs"]["latent_image"] = ["30", 0]
    workflow["8"]["inputs"]["samples"] = ["13", 0]
    workflow["8"]["inputs"]["vae"] = ["10", 0]
    workflow["32"]["inputs"]["images"] = ["8", 0]
    if "239" in workflow: del workflow["239"]
    if "51" in workflow: del workflow["51"]
    save_json(workflow, "flux_txt2img_fixed.json")

def fix_flux_img2img():
    print("Fixing Flux Image-to-Image...")
    workflow = load_json("flux_img2img.json")
    workflow["10"]["inputs"]["vae_name"] = "ae.safetensors"
    workflow["11"]["inputs"]["clip_name1"] = "t5xxl_fp16.safetensors"
    workflow["11"]["inputs"]["clip_name2"] = "clip_l.safetensors"
    workflow["11"]["inputs"]["type"] = "flux"
    workflow["12"]["inputs"]["unet_name"] = "flux1-dev.safetensors"
    workflow["6"]["inputs"]["clip"] = ["11", 0]
    if "1" in workflow and "44" in workflow:
        workflow["44"]["inputs"]["pixels"] = ["1", 0]
    # For basic img2img we use 116 (VAEEncode) not 44 (VAEEncodeForInpaint)
    # but the logic below in create_flux_sequential_inpaint handles the inpaint variant
    # Here we fix standard img2img:
    if "116" in workflow:
        workflow["116"]["inputs"]["pixels"] = ["1", 0]
        workflow["116"]["inputs"]["vae"] = ["10", 0]
        workflow["13"]["inputs"]["latent_image"] = ["116", 0]
    workflow["26"]["inputs"]["conditioning"] = ["6", 0]
    workflow["22"]["inputs"]["model"] = ["12", 0]
    workflow["22"]["inputs"]["conditioning"] = ["26", 0]
    workflow["17"]["inputs"]["model"] = ["12", 0]
    workflow["13"]["inputs"]["noise"] = ["25", 0]
    workflow["13"]["inputs"]["guider"] = ["22", 0]
    workflow["13"]["inputs"]["sampler"] = ["16", 0]
    workflow["13"]["inputs"]["sigmas"] = ["17", 0]
    workflow["8"]["inputs"]["samples"] = ["13", 0]
    workflow["8"]["inputs"]["vae"] = ["10", 0]
    workflow["32"]["inputs"]["images"] = ["8", 0]
    for node_id in ["42", "44", "45", "117", "224", "226", "227", "225", "50", "51", "239", "23", "43", "118"]:
        if node_id in workflow:
            del workflow[node_id]
    save_json(workflow, "flux_img2img_fixed.json")

def create_sdxl_sequential_inpaint():
    print("Creating SDXL Sequential Inpaint (2nd Iteration) with Depth ControlNet...")
    workflow = load_json("sdxl_img2img.json")

    # 1. Connect CLIP/Checkpoint
    workflow["247"]["inputs"]["clip"] = ["38", 1]
    workflow["102"]["inputs"]["clip"] = ["247", 0]
    workflow["103"]["inputs"]["clip"] = ["247", 0]
    workflow["38"]["inputs"]["ckpt_name"] = "sd_xl_base_1.0.safetensors"

    # 2. Mask Processing Chain
    workflow["25"]["inputs"]["image"] = ["12", 0]
    workflow["224"]["inputs"]["mask"] = ["25", 0]
    workflow["13"]["inputs"]["mask"] = ["224", 0]

    # 3. Input Image to VAEEncodeForInpaint
    workflow["13"]["inputs"]["pixels"] = ["1", 0]
    workflow["13"]["inputs"]["vae"] = ["38", 2]

    # --- ADD CONTROLNET (Depth) ---
    # Nodes: 500 (LoadImage), 501 (ControlNetLoader), 502 (ControlNetApplyAdvanced)
    
    workflow["500"] = {
        "class_type": "LoadImage",
        "_meta": {"title": "Load Depth Map"},
        "inputs": {"image": "depth_map.png", "upload": "image"}
    }
    
    workflow["501"] = {
        "class_type": "ControlNetLoader",
        "_meta": {"title": "Load Depth ControlNet"},
        "inputs": {"control_net_name": "controlnet_depth_sdxl.safetensors"}
    }
    
    workflow["502"] = {
        "class_type": "ControlNetApplyAdvanced",
        "_meta": {"title": "Apply Depth ControlNet"},
        "inputs": {
            "strength": 0.5,
            "start_percent": 0.0,
            "end_percent": 1.0,
            "positive": ["102", 0], # From Positive Prompt
            "negative": ["103", 0], # From Negative Prompt
            "control_net": ["501", 0],
            "image": ["500", 0],
            "vae": ["38", 2] # VAE from checkpoint
        }
    }

    # 4. Sampler Connections (Modified for ControlNet)
    workflow["105"]["inputs"]["latent_image"] = ["13", 0]
    workflow["105"]["inputs"]["model"] = ["38", 0]
    # Connect ControlNet output to Sampler
    workflow["105"]["inputs"]["positive"] = ["502", 0] # Output 0 is positive
    workflow["105"]["inputs"]["negative"] = ["502", 1] # Output 1 is negative

    # 5. Decode and Save
    workflow["110"]["inputs"]["samples"] = ["105", 0]
    workflow["110"]["inputs"]["vae"] = ["38", 2]
    workflow["111"]["inputs"]["images"] = ["110", 0]

    # Clean up
    for node_id in ["116", "117", "118", "23", "226", "227", "225", "228", "229", "235", "236", "237", "239"]:
        if node_id in workflow:
            del workflow[node_id]

    save_json(workflow, "sdxl_sequential_inpaint.json")

def create_flux_sequential_inpaint():
    print("Creating Flux Sequential Inpaint (2nd Iteration) with ControlNet...")
    workflow = load_json("flux_img2img.json")

    # 1. Configure Models
    workflow["10"]["inputs"]["vae_name"] = "ae.safetensors"
    workflow["11"]["inputs"]["clip_name1"] = "t5xxl_fp16.safetensors"
    workflow["11"]["inputs"]["clip_name2"] = "clip_l.safetensors"
    workflow["11"]["inputs"]["type"] = "flux"
    workflow["12"]["inputs"]["unet_name"] = "flux1-dev.safetensors"
    
    # 2. CLIP
    workflow["6"]["inputs"]["clip"] = ["11", 0]

    # --- ADD CONTROLNET ---
    # Nodes: 500 (LoadImage), 501 (ControlNetLoader), 502 (ControlNetApplyAdvanced)
    
    workflow["500"] = {
        "class_type": "LoadImage",
        "_meta": {"title": "Load Control Image"},
        "inputs": {"image": "control_img.png", "upload": "image"}
    }
    
    workflow["501"] = {
        "class_type": "ControlNetLoader",
        "_meta": {"title": "Load ControlNet"},
        "inputs": {"control_net_name": "flux_controlnet.safetensors"}
    }
    
    workflow["502"] = {
        "class_type": "ControlNetApplyAdvanced",
        "_meta": {"title": "Apply ControlNet"},
        "inputs": {
            "strength": 0.5,
            "start_percent": 0.0,
            "end_percent": 1.0,
            "positive": ["6", 0], # From Positive Prompt
            "negative": ["6", 0], # Flux often uses Pos for Neg in node inputs or handles it internally
            "control_net": ["501", 0],
            "image": ["500", 0],
            "vae": ["10", 0] # VAE Loader
        }
    }

    # 3. Guidance (Modified for ControlNet)
    # Connect ControlNet output to FluxGuidance
    workflow["26"]["inputs"]["conditioning"] = ["502", 0]

    workflow["22"]["inputs"]["model"] = ["12", 0]
    workflow["22"]["inputs"]["conditioning"] = ["26", 0]
    workflow["17"]["inputs"]["model"] = ["12", 0]

    # 4. Mask Processing Chain
    workflow["45"]["inputs"]["image"] = ["42", 0]
    workflow["224"]["inputs"]["mask"] = ["45", 0]
    workflow["44"]["inputs"]["mask"] = ["224", 0]

    # 5. Input Image to VAEEncodeForInpaint
    workflow["44"]["inputs"]["pixels"] = ["1", 0]
    workflow["44"]["inputs"]["vae"] = ["10", 0]

    # 6. Sampler Connections
    workflow["13"]["inputs"]["latent_image"] = ["44", 0]
    workflow["13"]["inputs"]["noise"] = ["25", 0]
    workflow["13"]["inputs"]["guider"] = ["22", 0]
    workflow["13"]["inputs"]["sampler"] = ["16", 0]
    workflow["13"]["inputs"]["sigmas"] = ["17", 0]

    # 7. Decode and Save
    workflow["8"]["inputs"]["samples"] = ["13", 0]
    workflow["8"]["inputs"]["vae"] = ["10", 0]
    workflow["32"]["inputs"]["images"] = ["8", 0]

    # Clean up unused
    for node_id in ["116", "117", "118", "43", "50", "51", "225", "226", "227", "239", "23"]:
        if node_id in workflow:
            del workflow[node_id]

    save_json(workflow, "flux_sequential_inpaint.json")

if __name__ == "__main__":
    fix_sdxl_txt2img()
    fix_sdxl_img2img()
    fix_flux_txt2img()
    fix_flux_img2img()
    create_sdxl_sequential_inpaint()
    create_flux_sequential_inpaint()