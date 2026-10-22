"""
Auto USD Material - Houdini 22

Crea materiales "Karma Material Builder" (MaterialX) a partir de una carpeta
de texturas y conecta cada mapa (albedo, roughness, metallic, AO, normal,
height, opacity, emissive) en su entrada del mtlxstandard_surface, con la
signature correcta (Color / Vector 3 / Float) y su espacio de color.

El normal map pasa por un mtlxnormalmap antes de llegar al surface.

Uso como shelf tool:
    import auto_usd_material
    auto_usd_material.run()

Dónde se crean los materiales:
  - Si hay un material builder seleccionado (o estás dentro de uno), se
    rellena ese builder.
  - Si hay seleccionada una red de materiales (/mat, un matnet o un Material
    Library), o estás dentro de una, se crean ahí.
  - Si no, se crean en /mat.
Si ya existe un builder vacío con el nombre del material, se reutiliza; si no
hay ninguno, se crea.

Asignación: si había objetos geo seleccionados en /obj, se les asigna el
material (parámetro Material del objeto). Con un solo material, va a todos;
con varios, cada objeto recibe el material cuyo nombre coincide con el suyo y
para los que no coinciden se pregunta cuál usar.

Informe de texturas: antes de crear nada se revisa la carpeta y se avisa de
  - error:   materiales sin albedo (o sin texturas reconocibles).
  - warning: sin normal, sin roughness/gloss, archivos no reconocidos, AO sin
             albedo, roughness y gloss a la vez, UDIM con tiles distintos
             entre canales y archivos que no existen en disco.
  - info:    normal DirectX, mask sin conectar y canales con varios archivos
             (se indica cuál se usa).
El informe se imprime en la consola de Houdini y se muestra en una ventana con
el detalle completo. Si hay errores o warnings se pregunta si crear igualmente;
si solo hay infos se continúa sin preguntar y el informe queda en los detalles
del mensaje final. Con WRITE_REPORT_FILE = True se guarda además como
texture_report.txt en la carpeta de texturas. Los canales que se comprueban se
cambian en REQUIRED_CHANNELS y RECOMMENDED_CHANNELS.
"""

import os
import re

import hou
import voptoolutils


TEXTURE_EXTS = (".exr", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".tga", ".hdr", ".tx", ".rat")

# Orden de preferencia si el mismo mapa existe en varios formatos.
EXT_PRIORITY = {ext: i for i, ext in enumerate(TEXTURE_EXTS)}

# canal -> palabras clave en el nombre del archivo.
# El orden importa: "basecolor" debe evaluarse antes que "color", etc.
MAP_KEYWORDS = [
    ("normal",       ("normalgl", "normal_gl", "normaldx", "normal_dx", "normal", "nrm", "nor", "nml")),
    ("albedo",       ("basecolor", "base_color", "albedo", "diffuse", "diff", "color", "col")),
    ("roughness",    ("roughness", "rough", "rgh")),
    ("gloss",        ("glossiness", "gloss")),
    ("metallic",     ("metallic", "metalness", "metal", "mtl")),
    ("occlusion",    ("ambientocclusion", "ambient_occlusion", "occlusion", "ao")),
    ("displacement", ("displacement", "height", "disp", "bump")),
    ("opacity",      ("opacity", "alpha", "transparency")),
    ("emissive",     ("emissive", "emission", "emit")),
    ("mask",         ("mask",)),
]

# Signatures del mtlximage: Color, Vector 3, Float.
COLOR = "color3"
VECTOR3 = "vector3"
FLOAT = "float"

SRGB = "srgb_texture"
RAW = "Raw"

# canal -> (entrada del mtlxstandard_surface, signature, espacio de color, nombre del nodo)
CHANNEL_SETUP = {
    "albedo":       ("base_color",         COLOR,   SRGB, "BaseColor_Texture"),
    "emissive":     ("emission_color",     COLOR,   SRGB, "Emissive_Texture"),
    "roughness":    ("specular_roughness", FLOAT,   RAW,  "Roughness_Texture"),
    "gloss":        ("specular_roughness", FLOAT,   RAW,  "Gloss_Texture"),
    "metallic":     ("metalness",          FLOAT,   RAW,  "Metallic_Texture"),
    "occlusion":    (None,                 FLOAT,   RAW,  "AO_Texture"),
    "opacity":      ("opacity",            COLOR,   RAW,  "Opacity_Texture"),
    "displacement": (None,                 FLOAT,   RAW,  "Height_Texture"),
    "normal":       (None,                 VECTOR3, RAW,  "Normal_Texture"),
    # El mask se crea pero no se conecta a ninguna entrada.
    "mask":         (None,                 FLOAT,   RAW,  "Mask_Texture"),
}

# Si es True, el AO se multiplica sobre el base color (standard_surface no
# tiene entrada de occlusion). Si es False, el nodo se crea sin conectar.
AO_MULTIPLY_BASECOLOR = True

# Canales que se comprueban en el informe. Gloss cuenta como roughness.
REQUIRED_CHANNELS = ("albedo", "normal")
RECOMMENDED_CHANNELS = ("roughness",)

# Nivel del aviso cuando falta un canal requerido; los que no aparecen aquí
# son "warning". Los recomendados que faltan siempre son "warning".
MISSING_REQUIRED_LEVEL = {"albedo": "error"}

# Canales equivalentes a efectos del informe.
CHANNEL_ALIASES = {"roughness": ("gloss",)}

# Si es True, el informe se guarda como texture_report.txt en la carpeta de
# texturas.
WRITE_REPORT_FILE = False
REPORT_FILENAME = "texture_report.txt"

UDIM_RE = re.compile(r"(?<!\d)(1\d{3})(?!\d)")


def _split_tokens(stem):
    return [t for t in re.split(r"[_\-. ]+", stem) if t]


def _classify(filename):
    """Devuelve (nombre_material, canal, es_directx, es_udim) o None."""
    stem, ext = os.path.splitext(filename)
    if ext.lower() not in TEXTURE_EXTS:
        return None

    tokens = _split_tokens(stem)
    lower = [t.lower() for t in tokens]
    is_udim = any(UDIM_RE.fullmatch(t) for t in tokens)

    # Busca el token de mapa empezando por el final: el nombre del material va
    # delante (p.ej. "Rock_Wall_BaseColor_1001.exr").
    for idx in range(len(lower) - 1, -1, -1):
        tok = lower[idx]
        nxt = lower[idx + 1] if idx + 1 < len(lower) else ""
        for channel, keys in MAP_KEYWORDS:
            pair = tok + "_" + nxt
            if tok in keys or pair in keys:
                is_dx = channel == "normal" and ("dx" in (tok, nxt) or tok.endswith("dx"))
                mat_tokens = [t for t in tokens[:idx] if not UDIM_RE.fullmatch(t)]
                mat_name = "_".join(mat_tokens) or "material"
                return mat_name, channel, is_dx, is_udim
    return None


def scan_folder(folder):
    """Agrupa las texturas por material: {material: {canal: info}}."""
    return scan_folder_detailed(folder)[0]


def scan_folder_detailed(folder):
    """Como scan_folder, pero devuelve también los archivos no reconocidos.

    Devuelve (materials, unrecognized):
      materials:    {material: {canal: info}}. Cada info lleva además
                    "candidates": todas las rutas encontradas para ese canal.
      unrecognized: nombres de archivo con extensión de textura que no se
                    han podido clasificar.
    No usa hou.
    """
    materials = {}
    unrecognized = []
    for filename in sorted(os.listdir(folder)):
        info = _classify(filename)
        if not info:
            if os.path.splitext(filename)[1].lower() in TEXTURE_EXTS:
                unrecognized.append(filename)
            continue
        mat_name, channel, is_dx, is_udim = info
        path = os.path.join(folder, filename).replace("\\", "/")
        if is_udim:
            path = UDIM_RE.sub("<UDIM>", path.rsplit("/", 1)[1])
            path = folder.replace("\\", "/").rstrip("/") + "/" + path

        ext = os.path.splitext(filename)[1].lower()
        candidate = {"path": path, "directx": is_dx, "ext": ext}
        current = materials.setdefault(mat_name, {}).get(channel)
        candidates = current["candidates"] if current else []
        if path not in candidates:
            candidates.append(path)
        if current is None or _better(candidate, current):
            materials[mat_name][channel] = candidate
        materials[mat_name][channel]["candidates"] = candidates
    return materials, unrecognized


def _better(new, old):
    # Normal OpenGL antes que DirectX; después, formato preferido.
    if new["directx"] != old["directx"]:
        return not new["directx"]
    return EXT_PRIORITY[new["ext"]] < EXT_PRIORITY[old["ext"]]


# --- Informe de texturas (sin hou) -------------------------------------------

def _issue(level, material, message):
    return {"level": level, "material": material, "message": message}


def _has_channel(maps, channel):
    return channel in maps or any(a in maps for a in CHANNEL_ALIASES.get(channel, ()))


def _udim_tiles(path):
    """Tiles que existen en disco para una ruta con <UDIM>."""
    folder, name = path.rsplit("/", 1)
    pattern = re.compile(re.escape(name).replace(re.escape("<UDIM>"), r"(1\d{3})") + "$")
    try:
        files = os.listdir(folder)
    except OSError:
        return set()
    return {m.group(1) for m in map(pattern.match, files) if m}


def _path_exists(path):
    if "<UDIM>" in path:
        return bool(_udim_tiles(path))
    return os.path.isfile(path)


def _basename(path):
    return path.rsplit("/", 1)[-1]


def _check_material(name, maps):
    """Avisos de un material."""
    issues = []

    for channel in REQUIRED_CHANNELS:
        if not _has_channel(maps, channel):
            issues.append(_issue(MISSING_REQUIRED_LEVEL.get(channel, "warning"), name,
                                 "No tiene %s." % channel))
    for channel in RECOMMENDED_CHANNELS:
        if not _has_channel(maps, channel):
            aliases = CHANNEL_ALIASES.get(channel, ())
            label = " ni ".join((channel,) + aliases)
            issues.append(_issue("warning", name, "No tiene %s." % label))

    if "occlusion" in maps and "albedo" not in maps:
        issues.append(_issue("warning", name,
                             "Tiene occlusion pero no albedo: el AO no se aplicará."))
    if "roughness" in maps and "gloss" in maps:
        issues.append(_issue("warning", name,
                             "Tiene roughness y gloss a la vez: se usa roughness."))

    tiles = {c: _udim_tiles(i["path"]) for c, i in maps.items() if "<UDIM>" in i["path"]}
    if len({frozenset(t) for t in tiles.values()}) > 1:
        detail = "; ".join("%s: %s" % (c, ", ".join(sorted(t)) or "ninguno")
                           for c, t in sorted(tiles.items()))
        issues.append(_issue("warning", name,
                             "Los UDIM tienen tiles distintos entre canales (%s)." % detail))

    for channel, info in sorted(maps.items()):
        if not _path_exists(info["path"]):
            issues.append(_issue("warning", name, "El archivo de %s no existe en disco: %s"
                                 % (channel, _basename(info["path"]))))

    if maps.get("normal", {}).get("directx"):
        issues.append(_issue("info", name,
                             "Normal DirectX detectada: se convertirá a OpenGL."))
    if "mask" in maps:
        issues.append(_issue("info", name, "Mask creado pero sin conectar."))

    for channel, info in sorted(maps.items()):
        candidates = info.get("candidates", [])
        if len(candidates) > 1:
            others = [_basename(p) for p in candidates if p != info["path"]]
            issues.append(_issue("info", name, "%s aparece en %d archivos; se usa %s (descartados: %s)."
                                 % (channel, len(candidates), _basename(info["path"]),
                                    ", ".join(others))))
    return issues


def build_report(materials, unrecognized, folder):
    """Lista de avisos {"level", "material", "message"} sobre una carpeta escaneada.

    level es "info", "warning" o "error"; material es None si el aviso no es
    de un material concreto. No usa hou.
    """
    report = []
    if not materials:
        report.append(_issue("error", None,
                             "No se han encontrado texturas reconocibles en: %s" % folder))
    if unrecognized:
        report.append(_issue("warning", None, "Archivos no reconocidos (%d): %s"
                             % (len(unrecognized), ", ".join(unrecognized))))
    for name in sorted(materials):
        report.extend(_check_material(name, materials[name]))
    return report


def count_levels(report):
    """{"error": n, "warning": n, "info": n}."""
    counts = {"error": 0, "warning": 0, "info": 0}
    for item in report:
        counts[item["level"]] += 1
    return counts


def report_summary(report):
    """Resumen de una línea con el número de avisos por nivel."""
    counts = count_levels(report)
    return "%d errores, %d warnings, %d infos" % (counts["error"], counts["warning"], counts["info"])


def format_report(report, folder):
    """Texto completo del informe, agrupado por material."""
    lines = ["Informe de texturas: %s" % folder, report_summary(report), ""]
    groups = {}
    for item in report:
        groups.setdefault(item["material"], []).append(item)
    for material in sorted(groups, key=lambda m: (m is not None, m or "")):
        lines.append("[%s]" % (material or "General"))
        for item in groups[material]:
            lines.append("  %-7s %s" % (item["level"].upper(), item["message"]))
        lines.append("")
    if not report:
        lines.append("Sin avisos.")
    return "\n".join(lines).rstrip() + "\n"


def _image_node(subnet, channel, info):
    _, signature, colorspace, node_name = CHANNEL_SETUP[channel]
    img = subnet.createNode("mtlximage", node_name)
    img.parm("signature").set(signature)
    img.parm("file").set(info["path"])
    img.parm("filecolorspace").set(colorspace)
    return img


def _flip_green(subnet, img):
    """DirectX -> OpenGL: g = 1 - g, con un multiply (1,-1,1) y un add (0,1,0)."""
    mult = subnet.createNode("mtlxmultiply", "Normal_DX_FlipG")
    mult.parm("signature").set(VECTOR3)
    mult.setInput(0, img)
    mult.parmTuple("in2_vector3").set((1, -1, 1))

    add = subnet.createNode("mtlxadd", "Normal_DX_OffsetG")
    add.parm("signature").set(VECTOR3)
    add.setInput(0, mult)
    add.parmTuple("in2_vector3").set((0, 1, 0))
    return add


def _children_of_type(node, type_name):
    return [c for c in node.children() if c.type().name().split("::")[0] == type_name]


def is_material_builder(node):
    """True si node es un material builder MaterialX (subnet con standard surface)."""
    return (node is not None
            and node.type().name() == "subnet"
            and node.type().category() == hou.vopNodeTypeCategory()
            and bool(_children_of_type(node, "mtlxstandard_surface")))


def _has_textures(builder):
    return bool(_children_of_type(builder, "mtlximage"))


def _create_builder(parent, name):
    builder = voptoolutils._setupMtlXBuilderSubnet(
        destination_node=parent, name=name,
        mask=voptoolutils.KARMAMTLX_TAB_MASK,
        folder_label="Karma Material Builder", render_context="kma")
    builder.moveToGoodPosition()
    return builder


def _get_or_create_builder(parent, name):
    """Reutiliza un builder vacío con ese nombre; si no existe, lo crea."""
    existing = parent.node(name)
    if is_material_builder(existing) and not _has_textures(existing):
        return existing
    return _create_builder(parent, name)


def build_material(parent, mat_name, maps, builder=None):
    """Conecta los mapas en un Karma Material Builder.

    Si no se pasa builder, se reutiliza uno vacío con el nombre del material
    dentro de parent o se crea uno nuevo.
    """
    safe_name = re.sub(r"[^A-Za-z0-9_]", "_", mat_name)
    subnet = builder or _get_or_create_builder(parent, safe_name)

    surface = _children_of_type(subnet, "mtlxstandard_surface")[0]
    surface.setName("Standard_Surface", unique_name=True)

    displacement = (_children_of_type(subnet, "mtlxdisplacement") or [None])[0]
    if displacement is None:
        displacement = subnet.createNode("mtlxdisplacement")
    displacement.setName("Displacement", unique_name=True)

    for props in _children_of_type(subnet, "kma_material_properties"):
        props.setName("Material_Properties", unique_name=True)

    channels = [c for c, _ in MAP_KEYWORDS if c in maps]
    if "gloss" in channels and "roughness" in channels:
        channels.remove("gloss")

    images = {c: _image_node(subnet, c, maps[c]) for c in channels}

    for channel, img in images.items():
        surf_input = CHANNEL_SETUP[channel][0]

        if channel == "normal":
            src = _flip_green(subnet, img) if maps[channel]["directx"] else img
            normalmap = subnet.createNode("mtlxnormalmap", "Normal_Map")
            normalmap.setNamedInput("in", src, 0)
            surface.setNamedInput("normal", normalmap, 0)

        elif channel == "gloss":
            invert = subnet.createNode("mtlxinvert", "Gloss_to_Roughness")
            invert.parm("signature").set("default")
            invert.setInput(0, img)
            surface.setNamedInput(surf_input, invert, 0)

        elif channel == "displacement":
            displacement.setNamedInput("displacement", img, 0)

        elif channel == "occlusion":
            if AO_MULTIPLY_BASECOLOR and "albedo" in images:
                mult = subnet.createNode("mtlxmultiply", "BaseColor_x_AO")
                mult.parm("signature").set("color3FA")
                mult.setInput(0, images["albedo"])
                mult.setInput(1, img)
                surface.setNamedInput("base_color", mult, 0)

        elif channel == "albedo" and "occlusion" in images and AO_MULTIPLY_BASECOLOR:
            continue  # se conecta a través del multiply del AO

        elif surf_input:
            surface.setNamedInput(surf_input, img, 0)

    subnet.layoutChildren()
    return subnet


def build_materials(folder, parent=None, builder=None):
    """Crea un material por cada grupo de texturas de folder.

    parent:  red de materiales donde crear los builders (por defecto /mat).
    builder: material builder ya existente; recibe el primer material.
    """
    materials = scan_folder(folder)
    if not materials:
        raise hou.Error("No se han encontrado texturas reconocibles en:\n" + folder)

    if builder is not None:
        parent = builder.parent()
    elif parent is None:
        parent = hou.node("/mat")

    created = []
    for name, maps in materials.items():
        created.append(build_material(parent, name, maps, builder))
        builder = None
    return created


def _is_material_network(node):
    """Red donde se pueden crear builders: /mat, un matnet o un Material Library."""
    return (node is not None
            and node.childTypeCategory() == hou.vopNodeTypeCategory()
            and not is_material_builder(node))


def _resolve_target():
    """Decide dónde crear los materiales según la selección y la red abierta.

    Devuelve (parent, builder).
    """
    for node in hou.selectedNodes():
        if is_material_builder(node):
            return None, node
        if _is_material_network(node):
            return node, None

    editor = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
    pwd = editor.pwd() if editor else None
    if is_material_builder(pwd):
        return None, pwd
    if _is_material_network(pwd):
        return pwd, None
    return hou.node("/mat"), None


def selected_objects():
    """Objetos geo de /obj seleccionados."""
    return [n for n in hou.selectedNodes()
            if n.type().category() == hou.objNodeTypeCategory()
            and n.type().name().split("::")[0] == "geo"
            and n.parm("shop_materialpath") is not None]


def _normalize(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def match_material(obj, materials):
    """Material cuyo nombre coincide con el del objeto, o None."""
    obj_name = _normalize(obj.name())
    for mat in materials:
        if _normalize(mat.name()) == obj_name:
            return mat
    for mat in materials:
        mat_name = _normalize(mat.name())
        if mat_name and (mat_name in obj_name or obj_name in mat_name):
            return mat
    return None


def assign_materials(objects, materials, fallback=None):
    """Asigna materiales a objetos de /obj. Devuelve [(objeto, material)].

    fallback(objetos_sin_match, materials) -> material para los que no
    coinciden por nombre (o None para dejarlos sin asignar).
    """
    # Los materiales de un Material Library de Solaris no se pueden asignar
    # desde /obj.
    materials = [m for m in materials
                 if m.parent().type().category() != hou.lopNodeTypeCategory()]
    if not objects or not materials:
        return []

    if len(materials) == 1:
        pairs = [(obj, materials[0]) for obj in objects]
    else:
        pairs = [(obj, match_material(obj, materials)) for obj in objects]
        unmatched = [obj for obj, mat in pairs if mat is None]
        if unmatched and fallback:
            chosen = fallback(unmatched, materials)
            pairs = [(obj, mat or chosen) for obj, mat in pairs]

    assigned = []
    for obj, mat in pairs:
        if mat is not None:
            obj.parm("shop_materialpath").set(mat.path())
            assigned.append((obj, mat))
    return assigned


def _ask_material(objects, materials):
    names = ", ".join(o.name() for o in objects)
    picked = hou.ui.selectFromList(
        [m.name() for m in materials], exclusive=True,
        title="Asignar material",
        message="Estos objetos no coinciden con ningún material:\n%s\n\n"
                "Elige cuál asignarles (Cancelar = no asignar)." % names)
    return materials[picked[0]] if picked else None


def _write_report_file(folder, text):
    path = os.path.join(folder, REPORT_FILENAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print("Informe guardado en: " + path)
    except OSError as e:
        print("No se ha podido guardar el informe: %s" % e)


def _review_report(folder):
    """Escanea, muestra el informe y pregunta si continuar.

    Devuelve (continuar, texto_del_informe).
    """
    materials, unrecognized = scan_folder_detailed(folder)
    report = build_report(materials, unrecognized, folder)
    text = format_report(report, folder)
    print(text)
    if WRITE_REPORT_FILE:
        _write_report_file(folder, text)

    counts = count_levels(report)
    if not materials:
        hou.ui.displayMessage("No se han encontrado texturas reconocibles.",
                              severity=hou.severityType.Error,
                              title="Informe de texturas", details=text)
        return False, text
    if not counts["error"] and not counts["warning"]:
        return True, text

    severity = hou.severityType.Error if counts["error"] else hou.severityType.Warning
    choice = hou.ui.displayMessage(
        "Informe de texturas: " + report_summary(report) + "\n\n"
        "Mira los detalles antes de continuar.",
        buttons=("Crear igualmente", "Cancelar"), default_choice=0, close_choice=1,
        severity=severity, title="Informe de texturas",
        details=text, details_label="Detalle del informe")
    return choice == 0, text


def run():
    """Punto de entrada para el shelf tool."""
    objects = selected_objects()

    folder = hou.ui.selectFile(title="Carpeta de texturas",
                               file_type=hou.fileType.Directory)
    if not folder:
        return
    folder = hou.text.expandString(folder)

    proceed, report_text = _review_report(folder)
    if not proceed:
        return

    parent, builder = _resolve_target()
    created = build_materials(folder, parent, builder)
    assigned = assign_materials(objects, created, fallback=_ask_material)

    lines = []
    for subnet in created:
        maps = [c.name() for c in subnet.children() if c.type().name() == "mtlximage"]
        lines.append("%s: %s" % (subnet.name(), ", ".join(maps)))
    message = "Materiales creados:\n\n" + "\n".join(lines)
    if assigned:
        message += "\n\nAsignados:\n\n" + "\n".join(
            "%s -> %s" % (obj.name(), mat.path()) for obj, mat in assigned)
    hou.ui.displayMessage(message, details=report_text,
                          details_label="Informe de texturas")
    for i, subnet in enumerate(created):
        subnet.setSelected(True, clear_all_selected=(i == 0))
