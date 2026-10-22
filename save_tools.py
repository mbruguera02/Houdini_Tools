"""
Save Tools - Houdini 22

Guardado incremental de escenas: <base>_v###.<ext>.

  - La base es el nombre del archivo actual sin el sufijo _v### final.
  - La extensión es la del archivo abierto; si la escena es nueva, la de la
    licencia (Education/Apprentice: .hipnc, Indie: .hiplc, Commercial: .hip).
  - La siguiente versión es la mayor que haya en la carpeta + 1, contando
    .hip, .hiplc y .hipnc. Nunca se sobrescribe un archivo.

Escena nueva (untitled): se pide la carpeta raíz y el nombre del proyecto, se
crean raíz/hip, geo, cache, render y tex, y se guarda en
raíz/hip/<nombre>_v001.<ext>.

Con SET_PROJECT_VARS = True se definen JOB (raíz del proyecto) y SHOT (base de
la escena, sin versión) con "set -g", que se guardan dentro del .hip. Así las
cachés pueden usar $JOB/cache/$SHOT/... en lugar de $HIPNAME, que cambia en
cada versión.

Notas: "Guardar versión + nota" pide un texto y añade la línea
"v003 | 2026-10-22 17:40 | texto" a <base>_notes.txt, junto al .hip.

Orden: con KEEP_LAST_N_IN_FOLDER = 10, tras guardar se mueven las versiones
más antiguas de esa base a la subcarpeta _old/, dejando las 10 más recientes.
Nunca se borra nada.

Atajo: MBL Save se lanza con Ctrl+Alt+Shift+S (SAVE_HOTKEY). Lo asigna
install_hotkey() en cada arranque, llamada desde
$HOUDINI_USER_PREF_DIR/python3.13libs/uiready.py.

Uso desde la Python Shell:
    import save_tools
    save_tools.save_version()                  # guarda la siguiente versión
    save_tools.save_version(note="blocking")   # y añade una nota
    save_tools.save_version_with_note()        # pide la nota en una ventana

    save_tools.parse_name("escena_v003.hipnc")
    # ('escena', 3, '.hipnc')
    save_tools.list_versions("C:/proyecto/hip", "escena")
    # [(1, WindowsPath('C:/proyecto/hip/escena_v001.hipnc')), ...]
    save_tools.next_version_path("C:/proyecto/hip", "escena", ".hipnc")
    # WindowsPath('C:/proyecto/hip/escena_v004.hipnc')
"""

import datetime
import os
import re
import shutil
from pathlib import Path

import hou


HIP_EXTS = (".hip", ".hiplc", ".hipnc")
VERSION_PADDING = 3
VERSION_RE = re.compile(r"^(?P<base>.*?)_v(?P<version>\d+)$", re.IGNORECASE)

# Extensión de las escenas nuevas según hou.licenseCategoryType.
LICENSE_EXTS = {
    "Commercial":   ".hip",
    "Indie":        ".hiplc",
    "Education":    ".hipnc",
    "Apprentice":   ".hipnc",
    "ApprenticeHD": ".hipnc",
}
DEFAULT_EXT = ".hipnc"

# Subcarpetas que se crean en la raíz de un proyecto nuevo.
PROJECT_SUBDIRS = ("hip", "geo", "cache", "render", "tex")
HIP_SUBDIR = "hip"

# Define JOB y SHOT dentro del .hip tras guardar.
SET_PROJECT_VARS = True

# Si es False, "Guardar versión + nota" guarda sin pedir nota.
ASK_NOTE = True
NOTES_SUFFIX = "_notes.txt"

# Versiones que se dejan en la carpeta; las demás van a _old/. None lo desactiva.
KEEP_LAST_N_IN_FOLDER = 10
OLD_SUBDIR = "_old"

# Atajo global de "MBL Save" (shelf tool save_version). Lo asigna
# install_hotkey() al arrancar Houdini, desde uiready.py.
SAVE_HOTKEY = "Ctrl+Alt+Shift+S"
SAVE_TOOL_NAME = "save_version"
HOTKEY_CONTEXT = "h"

INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*]')


# --- Funciones puras (sin hou) ------------------------------------------------

def parse_name(filename):
    """Separa un nombre de escena en (base, versión o None, extensión).

    parse_name("escena_v003.hipnc") -> ("escena", 3, ".hipnc")
    parse_name("escena.hip")        -> ("escena", None, ".hip")
    """
    path = Path(filename)
    match = VERSION_RE.match(path.stem)
    if match:
        return match.group("base"), int(match.group("version")), path.suffix
    return path.stem, None, path.suffix


def format_name(base, version, ext):
    """("escena", 3, ".hipnc") -> "escena_v003.hipnc"."""
    return "%s_v%0*d%s" % (base, VERSION_PADDING, version, ext)


def list_versions(folder, base):
    """Versiones de base en folder (todas las extensiones .hip*).

    Devuelve una lista ordenada de (versión, ruta).
    """
    folder = Path(folder)
    if not folder.is_dir():
        return []
    versions = []
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in HIP_EXTS:
            continue
        file_base, version, _ = parse_name(path.name)
        if version is not None and file_base == base:
            versions.append((version, path))
    return sorted(versions, key=lambda item: (item[0], item[1].name))


def next_version_path(folder, base, ext):
    """Ruta libre para la siguiente versión de base en folder."""
    folder = Path(folder)
    versions = list_versions(folder, base)
    version = versions[-1][0] + 1 if versions else 1
    path = folder / format_name(base, version, ext)
    while path.exists():
        version += 1
        path = folder / format_name(base, version, ext)
    return path


def ext_for_license(category_name):
    """Extensión de escena para el nombre de un hou.licenseCategoryType."""
    return LICENSE_EXTS.get(category_name, DEFAULT_EXT)


def sanitize_name(name):
    """Limpia un nombre de proyecto para usarlo como nombre de archivo."""
    return INVALID_CHARS_RE.sub("_", name).strip().strip(".")


def project_root_for(hip_folder):
    """Raíz del proyecto: la carpeta padre si el .hip está en .../hip/."""
    hip_folder = Path(hip_folder)
    if hip_folder.name.lower() == HIP_SUBDIR:
        return hip_folder.parent
    return hip_folder


def create_project_dirs(root):
    """Crea raíz/hip, geo, cache, render y tex. Devuelve la carpeta hip."""
    root = Path(root)
    for sub in PROJECT_SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root / HIP_SUBDIR


def notes_path(folder, base):
    return Path(folder) / (base + NOTES_SUFFIX)


def format_note_line(version, text, when=None):
    """"v003 | 2026-10-22 17:40 | texto"."""
    when = when or datetime.datetime.now()
    return "v%0*d | %s | %s" % (VERSION_PADDING, version, when.strftime("%Y-%m-%d %H:%M"),
                                " ".join(text.split()))


def append_note(folder, base, version, text, when=None):
    """Añade una línea al archivo de notas (UTF-8, se crea si no existe)."""
    path = notes_path(folder, base)
    with open(path, "a", encoding="utf-8") as f:
        f.write(format_note_line(version, text, when) + "\n")
    return path


def unique_destination(path):
    """Si path existe, añade _1, _2... antes de la extensión."""
    path = Path(path)
    candidate = path
    counter = 1
    while candidate.exists():
        candidate = path.with_name("%s_%d%s" % (path.stem, counter, path.suffix))
        counter += 1
    return candidate


def versions_to_archive(folder, base, keep):
    """Versiones de base que sobran si se dejan las keep más recientes."""
    if keep is None:
        return []
    versions = list_versions(folder, base)
    keep = max(int(keep), 1)
    return [path for _, path in versions[:-keep]]


def archive_old_versions(folder, base, keep):
    """Mueve a _old/ las versiones antiguas de base. Devuelve [(origen, destino)]."""
    moved = []
    for path in versions_to_archive(folder, base, keep):
        old_dir = Path(folder) / OLD_SUBDIR
        old_dir.mkdir(exist_ok=True)
        dest = unique_destination(old_dir / path.name)
        shutil.move(str(path), str(dest))
        moved.append((path, dest))
    return moved


def to_houdini_path(path):
    """Ruta con barras normales, como la espera Houdini."""
    return str(path).replace("\\", "/")


# --- Houdini ------------------------------------------------------------------

def _license_ext():
    return ext_for_license(hou.licenseCategory().name())


def _error(message, details=None):
    hou.ui.displayMessage(message, severity=hou.severityType.Error,
                          title="Guardar versión", details=details)


def _ask_new_scene_path():
    """Pide raíz y nombre de proyecto, crea las carpetas y devuelve la ruta v001."""
    root = hou.ui.selectFile(title="Carpeta raíz del proyecto",
                             file_type=hou.fileType.Directory)
    if not root:
        return None
    root = Path(hou.text.expandString(root))

    choice, name = hou.ui.readInput("Nombre del proyecto:", buttons=("Aceptar", "Cancelar"),
                                    close_choice=1, title="Guardar versión")
    name = sanitize_name(name)
    if choice != 0 or not name:
        return None

    base = parse_name(name + _license_ext())[0]
    try:
        hip_dir = create_project_dirs(root)
    except OSError as e:
        _error("No se han podido crear las carpetas del proyecto en:\n%s" % root, str(e))
        return None
    return next_version_path(hip_dir, base, _license_ext())


def _next_path_for_current_scene():
    current = Path(hou.hipFile.name())
    base, _, ext = parse_name(current.name)
    if ext.lower() not in HIP_EXTS:
        ext = _license_ext()
    return next_version_path(current.parent, base, ext)


def _same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _save_to(path):
    """Guarda la escena en path y comprueba que Houdini apunta a ella."""
    try:
        hou.hipFile.save(file_name=to_houdini_path(path))
    except hou.OperationFailed as e:
        _error("No se ha podido guardar la escena en:\n%s" % path, str(e))
        return False
    if not _same_file(hou.hipFile.name(), path):
        _error("La escena no apunta a la nueva versión tras guardar.",
               "Esperado: %s\nActual: %s" % (path, hou.hipFile.name()))
        return False
    return True


def _hscript_quote(value):
    return "'%s'" % value.replace("'", "\\'")


def _set_project_vars(root, shot):
    """Define JOB y SHOT con set -g (se guardan dentro del .hip)."""
    for name, value in (("JOB", to_houdini_path(root)), ("SHOT", shot)):
        hou.hscript("set -g %s = %s" % (name, _hscript_quote(value)))
    hou.hscript("varchange")


def save_version(note=None):
    """Guarda la siguiente versión de la escena. Devuelve la ruta o None.

    note: texto opcional que se añade a <base>_notes.txt.
    """
    if hou.hipFile.isNewFile():
        path = _ask_new_scene_path()
    else:
        path = _next_path_for_current_scene()
    if path is None:
        return None

    if not _save_to(path):
        return None

    base, version, _ = parse_name(path.name)
    if SET_PROJECT_VARS:
        _set_project_vars(project_root_for(path.parent), base)
        # Segundo guardado en la misma ruta para que JOB y SHOT queden en el .hip.
        if not _save_to(path):
            return None

    if note:
        append_note(path.parent, base, version, note)

    moved = archive_old_versions(path.parent, base, KEEP_LAST_N_IN_FOLDER)
    message = "Guardado: %s" % path.name
    if moved:
        message += "  (%d versiones movidas a %s/)" % (len(moved), OLD_SUBDIR)
    hou.ui.setStatusMessage(message, severity=hou.severityType.Message)
    print(message)
    return path


def install_hotkey():
    """Asigna SAVE_HOTKEY al shelf tool de MBL Save en el contexto global.

    Solo dura la sesión actual: se llama en cada arranque desde uiready.py.
    Devuelve True si Houdini acepta la asignación.
    """
    symbol = "%s.tool:%s" % (HOTKEY_CONTEXT, SAVE_TOOL_NAME)
    hou.hotkeys.addCommandBinding(HOTKEY_CONTEXT, symbol)
    ok = hou.hotkeys.addAssignment(HOTKEY_CONTEXT, symbol, SAVE_HOTKEY)
    if not ok:
        print("MBL Save: no se ha podido asignar %s a %s" % (SAVE_HOTKEY, symbol))
    return ok


def save_version_with_note():
    """Pide una nota y guarda la siguiente versión con ella."""
    if not ASK_NOTE:
        return save_version()
    choice, text = hou.ui.readInput("Nota para esta versión:", buttons=("Guardar", "Cancelar"),
                                    close_choice=1, title="Guardar versión + nota")
    if choice != 0:
        return None
    return save_version(note=text.strip() or None)
