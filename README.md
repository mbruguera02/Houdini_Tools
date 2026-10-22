# MBL Tools para Houdini 22

Tres herramientas para Houdini 22 (Windows). Una vez instaladas, aparecen en la shelf
**Houdini Tools** y en el menú **Tab** escribiendo **MBL**.

| Herramienta | Para qué sirve |
|---|---|
| **MBL Material** | Crea materiales a partir de una carpeta de texturas |
| **MBL Save** | Guarda una versión nueva de la escena (`Ctrl+Alt+Shift+S`) |
| **MBL Save + Note** | Igual que MBL Save, pero te deja escribir una nota |

---

## Instalación

1. **Copia la carpeta** `Houdini Tools` donde quieras guardarla (por ejemplo, en el
   Escritorio). No la muevas después: Houdini la busca en esa ruta.

2. **Abre la carpeta de preferencias de Houdini:** `Documentos\houdini22.0`.
   Si no existe, abre Houdini 22 una vez y ciérralo.

3. **Copia estos dos archivos** de `Houdini Tools\houdini_prefs` a esa carpeta:

   | Archivo | Va a |
   |---|---|
   | `toolbar\houdini_tools.shelf` | `Documentos\houdini22.0\toolbar\` |
   | `python3.13libs\uiready.py` | `Documentos\houdini22.0\python3.13libs\` (créala si no existe) |

   Si ya tienes un `uiready.py` ahí, no lo reemplaces: pega el contenido del nuevo al final
   del tuyo.

4. **Cambia la ruta** si tu carpeta no está en `C:\Users\Marc Bruguera\Desktop\Houdini Tools`.
   Abre con el Bloc de notas los dos archivos que acabas de copiar y sustituye esa ruta por la
   tuya en todos los sitios donde aparezca:
   - `houdini_tools.shelf`: aparece 6 veces. En las líneas `icon="…"` la ruta va con barras
     normales (`C:/Users/...`).
   - `uiready.py`: aparece 1 vez.

5. **Reinicia Houdini.**

6. **Si no ves la shelf:** haz clic en el **+** a la derecha de las pestañas de shelf →
   *Shelves* → marca **Houdini Tools**. También puedes usar las herramientas desde el **Tab**
   escribiendo **MBL**, en `/obj`, dentro de un geo, en `/mat` o en `/stage`.

---

## MBL Material

Crea un **Karma Material Builder** por cada material que encuentre en una carpeta de
texturas, con cada mapa conectado en su sitio y con el espacio de color correcto.

### Cómo usarlo

1. (Opcional) En `/obj`, **selecciona los objetos** a los que quieras ponerles el material.
2. Lanza **MBL Material** y **elige la carpeta** de texturas.
3. Lee el **informe**. Si avisa de algún problema, elige *Crear igualmente* o *Cancelar*.
4. Los materiales aparecen en **`/mat`** y, si tenías objetos seleccionados, quedan asignados.

### Qué necesitas saber

**Nombra bien las texturas.** El nombre del material va primero y el tipo de mapa al final:

```
Roca_BaseColor.png    Roca_Roughness.png    Roca_Normal.png    Roca_AO.png
```

Eso crea un material llamado **Roca**. Si en la carpeta hay texturas de varios materiales,
crea uno por cada nombre.

**Palabras que reconoce** (da igual mayúsculas o minúsculas):

| Mapa | Escribe en el nombre | Dónde se conecta |
|---|---|---|
| Color | `BaseColor`, `Albedo`, `Diffuse`, `Color` | Color base |
| Roughness | `Roughness`, `Rough` | Roughness |
| Gloss | `Gloss`, `Glossiness` | Roughness (invertido) |
| Metálico | `Metallic`, `Metalness`, `Metal` | Metalness |
| AO | `AO`, `Occlusion` | Se multiplica sobre el color |
| Normal | `Normal`, `Nrm`, `Normal_GL`, `Normal_DX` | Normal (pasa por un Normal Map) |
| Altura | `Height`, `Displacement`, `Disp` | Displacement |
| Opacidad | `Opacity`, `Alpha` | Opacity |
| Emisión | `Emissive`, `Emission` | Emission |
| Máscara | `Mask` | **No se conecta**: queda suelta para que la uses tú |

- **UDIMs:** funcionan solos (`Roca_BaseColor.1001.exr`, `.1002`…).
- **Normal DirectX:** si solo tienes la versión DX, se convierte sola. Si tienes GL y DX, usa
  la GL.
- **Mismo mapa en varios formatos:** usa el de mejor calidad (EXR > TIF > PNG > JPG).
- **Asignación:** si seleccionas varios objetos y se crean varios materiales, cada objeto
  recibe el material con su mismo nombre (`roca_geo` → `Roca`). Si alguno no coincide, te
  pregunta cuál ponerle.
- **Volver a lanzarlo** sobre la misma carpeta crea materiales nuevos (`Roca1`); no
  sobrescribe los que ya tienes.
- **Para elegir otro sitio que no sea `/mat`:** selecciona antes otra red de materiales o
  un material builder vacío.

**El informe** te avisa antes de crear nada:

- **Error:** un material sin color base.
- **Avisos:** falta el normal o el roughness, hay texturas que no ha reconocido (te dice
  cuáles), los UDIM no tienen los mismos tiles en todos los mapas, o hay un archivo que no
  existe.
- **Información:** el normal es DirectX, hay una máscara sin conectar, o un mapa estaba
  repetido y te dice cuál ha usado.

Si una textura sale como "no reconocida", renómbrala con una de las palabras de la tabla.

---

## MBL Save y MBL Save + Note

Guardan la escena como **versión nueva**, sin sobrescribir nunca la anterior:

```
escena_v001.hipnc → escena_v002.hipnc → escena_v003.hipnc …
```

### Cómo usarlo

- **MBL Save:** pulsa `Ctrl+Alt+Shift+S` o lánzalo desde la shelf o el Tab.
- **MBL Save + Note:** te pide una nota antes de guardar (por ejemplo, "cambio de luces"). Si
  cancelas, no guarda.

### Qué necesitas saber

**Escena nueva (sin guardar todavía):** te pide una **carpeta** y un **nombre de proyecto**, y
crea esta estructura:

```
MiProyecto/
├── hip/      ← aquí van las escenas: MiProyecto_v001.hipnc
├── geo/
├── cache/
├── render/
└── tex/
```

- **Número de versión:** siempre usa el siguiente al más alto que haya en la carpeta. Si
  tienes `v001`, `v002` y `v010`, la siguiente es `v011`.
- **Formato:** mantiene el formato de la escena abierta. Con licencia Education es `.hipnc`.
- **Variables `$JOB` y `$SHOT`:** quedan guardadas dentro de la escena.
  - `$JOB` es la carpeta del proyecto.
  - `$SHOT` es el nombre de la escena sin versión (`escena`).
  - **Úsalas en las rutas de caché** (`$JOB/cache/$SHOT/...`) en lugar de `$HIPNAME`, que
    cambia con cada versión y te haría perder las cachés.
- **Notas:** se guardan en `escena_notes.txt`, junto a la escena:
  ```
  v003 | 2026-10-22 17:40 | cambio de luces
  ```
- **Versiones antiguas:** cuando hay más de 10, las más viejas se mueven a la subcarpeta
  `hip/_old/`. **Nunca se borra nada.**
- **Si falla el guardado** (disco lleno, carpeta protegida…), te avisa con un mensaje y no toca
  nada más.
- **El atajo `Ctrl+Alt+Shift+S` no funciona:** haz clic derecho en **MBL Save** en la shelf →
  *Edit Tool* → pestaña *Hotkeys* y asígnalo a mano.

---

## Ajustes opcionales

Si quieres cambiar algún comportamiento, abre el archivo con el Bloc de notas y cambia el
valor al principio del archivo. Los cambios se aplican la próxima vez que uses la herramienta.

| Archivo | Ajuste | Por defecto | Qué hace |
|---|---|---|---|
| `auto_usd_material.py` | `AO_MULTIPLY_BASECOLOR` | `True` | `False` deja el AO creado pero sin conectar |
| `auto_usd_material.py` | `WRITE_REPORT_FILE` | `False` | `True` guarda el informe como `texture_report.txt` |
| `save_tools.py` | `KEEP_LAST_N_IN_FOLDER` | `10` | Versiones que se quedan fuera de `_old/` (`None` = no mover nada) |
| `save_tools.py` | `SAVE_HOTKEY` | `"Ctrl+Alt+Shift+S"` | Atajo de MBL Save (reinicia Houdini tras cambiarlo) |
| `save_tools.py` | `SET_PROJECT_VARS` | `True` | `False` no crea `$JOB` ni `$SHOT` |
