import os
import getpass
import nuke

n = nuke.thisNode()

# CONFIG
asset = n['asset_name'].value()
sub = n['subname'].value()
aces = n['aces_mode'].value()

# UV size: U/V tile counts (1-based). If either value is 0, treat as legacy start/end.
uvs = n['uvsize'].value()
u_val = int(uvs[0])
v_val = int(uvs[1])

def iter_tiles():
    if u_val <= 0 or v_val <= 0:
        start_idx = max(0, u_val)
        end_idx = max(start_idx, v_val)
        for idx in range(start_idx, end_idx + 1):
            u = idx % 10
            v = idx // 10
            yield u, v
    else:
        u_count = max(1, u_val)
        v_count = max(1, v_val)
        for v in range(v_count):
            for u in range(u_count):
                yield u, v


def _format_from_node(node):
    if not node:
        return None
    try:
        fmt = node.format()
        if fmt:
            return fmt
    except Exception:
        pass
    try:
        width = int(node.width())
        height = int(node.height())
        if width > 0 and height > 0:
            return nuke.Format(width, height, 0, 0, width, height, 1, "bake_input")
    except Exception:
        pass
    return None


def _format_from_resolution(size):
    try:
        name = "bake_{0}".format(size)
        return nuke.Format(size, size, 0, 0, size, size, 1, name)
    except Exception:
        return None


def _apply_bake_resolution(root, node):
    if not root or not root.knob("format"):
        return None
    try:
        res = int(node["bake_resolution"].value())
    except Exception:
        return None
    name = "bake_{0}".format(res)
    fmt_string = "{0} {0} 0 0 {0} {0} 1 {1}".format(res, name)
    try:
        nuke.addFormat(fmt_string)
    except Exception:
        pass
    try:
        for f in nuke.formats():
            if f.name() == name:
                root["format"].setValue(f)
                return name
    except Exception:
        pass
    try:
        root["format"].setValue(name)
    except Exception:
        pass
    return name


def _ensure_anchor(node):
    k = None
    try:
        k = node.knob("charon_link_anchor")
    except Exception:
        k = None
    if not k:
        try:
            k = nuke.Double_Knob("charon_link_anchor", "Anchor")
            k.setFlag(nuke.NO_ANIMATION | nuke.INVISIBLE)
            node.addKnob(k)
        except Exception:
            k = None
    return k


def _ensure_contact_knob(node):
    k = None
    try:
        k = node.knob("charon_contact_sheet")
    except Exception:
        k = None
    if not k:
        try:
            k = nuke.String_Knob("charon_contact_sheet", "Contact Sheet", "")
            k.setFlag(nuke.NO_ANIMATION | nuke.INVISIBLE)
            node.addKnob(k)
        except Exception:
            k = None
    return k


def _build_contact_sheet(group, out_dir, tiles, cols, rows):
    if not tiles:
        return
    parent = group.parent() or nuke.root()
    try:
        parent.begin()
        existing_name = ""
        try:
            existing_name = group.knob("charon_contact_sheet").value()
        except Exception:
            existing_name = ""
        if existing_name:
            try:
                existing = nuke.toNode(existing_name)
                if existing:
                    nuke.delete(existing)
            except Exception:
                pass

        for node in list(nuke.allNodes()):
            try:
                node_name = node.name()
            except Exception:
                node_name = ""
            if node_name.startswith("TextureBake_CS_Read_"):
                nuke.delete(node)
                continue
            if node_name.startswith("TextureBake_CS_IVT_"):
                nuke.delete(node)
                continue
            if node_name.startswith("TextureBake_ContactSheet_"):
                nuke.delete(node)

        for node in nuke.selectedNodes():
            node.setSelected(False)

        safe_name = "".join(c if c.isalnum() else "_" for c in group.name())
        cs_group = nuke.createNode("Group", inpanel=False)
        cs_group.setName("Charon_ContactSheet_{0}".format(safe_name))
        try:
            cs_group["tile_color"].setValue(0xFFFF00FF)
        except Exception:
            pass
        try:
            cs_group["lock_connections"].setValue(True)
        except Exception:
            pass
        try:
            cs_group.setXYpos(group.xpos() + 200, group.ypos() + 100)
        except Exception:
            pass

        contact_knob = _ensure_contact_knob(group)
        if contact_knob:
            try:
                contact_knob.setValue(cs_group.name())
            except Exception:
                pass

        _ensure_anchor(group)
        anchor = _ensure_anchor(cs_group)
        if anchor:
            try:
                anchor.setExpression("{0}.charon_link_anchor".format(group.fullName()))
            except Exception:
                pass

        cs_group.begin()

        cols = max(1, int(cols))
        rows = max(1, int(rows))

        cs = nuke.createNode("ContactSheet")
        cs["width"].setValue(cols * 1024)
        cs["height"].setValue(rows * 1024)
        cs["rows"].setValue(rows)
        cs["columns"].setValue(cols)
        cs["roworder"].setValue("BottomTop")
        cs["gap"].setValue(10)
        cs["center"].setValue(True)

        for i, (u, v) in enumerate(tiles):
            udim = 1001 + u + (v * 10)
            fname = "{0}_{1}_{2}.png".format(asset, sub, udim)
            path = os.path.join(out_dir, fname).replace("\\", "/")
            r = nuke.createNode("Read")
            r.setName("TextureBake_CS_Read_{0}".format(i + 1))
            r["file"].setValue(path)
            r["on_error"].setValue("nearest frame")
            r.setXYpos(i * 150, -300)

            txt = nuke.createNode("Text2", inpanel=False)
            txt.setInput(0, r)
            try:
                txt["message"].setValue(os.path.basename(path))
                txt["box"].setValue([0, 0, 1000, 100])
                txt["yjustify"].setValue("bottom")
                txt["global_font_scale"].setValue(0.5)
                try:
                    txt["font"].setValue("Myanmar Text", "Regular")
                except Exception:
                    pass
            except Exception:
                pass
            txt.setXYpos(r.xpos(), r.ypos() + 150)

            cs.setInput(i, txt)
            r.setSelected(False)
            txt.setSelected(False)

        last_node = cs

        aces_enabled = False
        try:
            from charon import preferences
            aces_enabled = preferences.get_preference("aces_mode_enabled", False)
        except Exception:
            aces_enabled = False

        if aces_enabled:
            ivt_temp = None
            try:
                import uuid
                from charon.paths import get_charon_temp_dir
                from charon.processor import INVERSE_VIEW_TRANSFORM_GROUP
                ivt_temp = os.path.join(
                    get_charon_temp_dir(),
                    "ivt_cs_{0}.nk".format(str(uuid.uuid4())[:8]),
                ).replace("\\", "/")
                with open(ivt_temp, "w") as handle:
                    handle.write(INVERSE_VIEW_TRANSFORM_GROUP)

                for node in nuke.selectedNodes():
                    node.setSelected(False)
                cs.setSelected(True)

                nuke.nodePaste(ivt_temp)
                ivt_node = nuke.selectedNode()
                if ivt_node:
                    ivt_node.setInput(0, cs)
                    ivt_node.setXpos(cs.xpos())
                    ivt_node.setYpos(cs.ypos() + 200)
                    try:
                        ivt_node["tile_color"].setValue(0x0000FFFF)
                        ivt_node["gl_color"].setValue(0x0000FFFF)
                    except Exception:
                        pass
                    last_node = ivt_node
            except Exception:
                pass
            finally:
                if ivt_temp and os.path.exists(ivt_temp):
                    try:
                        os.remove(ivt_temp)
                    except Exception:
                        pass

        out = nuke.createNode("Output")
        out.setInput(0, last_node)
        out.setXYpos(last_node.xpos(), last_node.ypos() + 200)

        cs_group.end()
    finally:
        if group:
            group.begin()


# PATH RESOLUTION
project_path = os.environ.get("BUCK_PROJECT_PATH")
user = getpass.getuser()

if not project_path:
    ref = n.node("Read11")
    if ref:
        path = ref["file"].value().replace("\\", "/")
        if "/Production/" in path:
            project_path = path.split("/Production/")[0]

if not project_path:
    nuke.message("Could not determine BUCK_PROJECT_PATH.")
else:
    out_dir = os.path.join(
        project_path,
        "Production",
        "MAYA",
        "sourceimages",
        "work.{0}".format(user),
        "_CHARON",
        asset,
        sub,
    )
    out_dir_norm = os.path.normpath(out_dir)
    out_dir_display = out_dir_norm.replace("\\", "/")

    if not os.path.exists(out_dir_norm):
        try:
            os.makedirs(out_dir_norm)
        except Exception:
            pass

    with nuke.root():
        root = nuke.root()
        original_format = None
        try:
            if root.knob("format"):
                original_format = root["format"].value()
        except Exception:
            original_format = None

        _apply_bake_resolution(root, n)

        input_node = n
        aces_node = None

        if aces:
            aces_node = nuke.createNode("OCIODisplay", inpanel=False)
            aces_node.setInput(0, n)
            aces_node["colorspace"].setValue("scene_linear")
            aces_node["display"].setValue("sRGB Display")
            aces_node["view"].setValue("ACES 1.0 SDR-video")
            input_node = aces_node

        w = nuke.createNode("Write", inpanel=False)
        w.setInput(0, input_node)
        w["file_type"].setValue("png")
        w["channels"].setValue("rgba")

        if aces:
            w["raw"].setValue(True)

        w_exr = nuke.createNode("Write", inpanel=False)
        w_exr.setInput(0, input_node)
        w_exr["file_type"].setValue("exr")
        w_exr["channels"].setValue("rgba")

        try:
            for u, v in iter_tiles():
                udim = 1001 + u + (v * 10)

                n["UVcoord"].setValue([u, v])

                fname = "{0}_{1}_{2}.png".format(asset, sub, udim)
                w["file"].setValue(out_dir_display + "/" + fname)

                fname_exr = "{0}_{1}_{2}.exr".format(asset, sub, udim)
                w_exr["file"].setValue(out_dir_display + "/" + fname_exr)

                nuke.execute(w, nuke.frame(), nuke.frame())
                nuke.execute(w_exr, nuke.frame(), nuke.frame())

            tiles = list(iter_tiles())
            if u_val > 0 and v_val > 0:
                cols = max(1, u_val)
                rows = max(1, v_val)
            else:
                cols = 1
                rows = 1
                if tiles:
                    min_u = min(t[0] for t in tiles)
                    max_u = max(t[0] for t in tiles)
                    min_v = min(t[1] for t in tiles)
                    max_v = max(t[1] for t in tiles)
                    cols = max_u - min_u + 1
                    rows = max_v - min_v + 1
            _build_contact_sheet(n, out_dir_norm, tiles, cols, rows)
            nuke.message("Bake Complete!\\nSaved to: " + out_dir_display)
        except Exception as exc:
            nuke.message("Error during bake: " + str(exc))
        finally:
            nuke.delete(w)
            nuke.delete(w_exr)
            if aces_node:
                nuke.delete(aces_node)
            n["UVcoord"].setValue([0, 0])
            if original_format and root.knob("format"):
                try:
                    if hasattr(original_format, "name"):
                        root["format"].setValue(original_format.name())
                    else:
                        root["format"].setValue(original_format)
                except Exception:
                    pass
