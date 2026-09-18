# LoClip

**Búsqueda con IA para tu footage, 100 % local y offline, dentro de Premiere Pro.**

Escribe lo que buscas ("persona riendo en la cocina", "producto en primer plano", "atardecer con dron") y LoClip te muestra los momentos exactos de tus clips. También busca por lo que se **dice** (transcripción local en español e inglés), por **nombre de archivo o palabras clave**, por **imagen** (pega una captura) y por **parecido** a otro clip o al frame que tienes en el monitor de origen. Todo corre en tu máquina: tu material nunca sale de tu computadora.

> LoClip **solo lee** tus carpetas de footage. Nunca escribe, mueve, renombra ni borra nada ahí. El índice, las miniaturas y los modelos viven en su propia carpeta de datos.

## Funciones (v0.1)

- Búsqueda visual por texto (multilingüe, sin etiquetar nada)
- Búsqueda por voz: transcripción local con Whisper, editor de transcripción y exportación a .txt
- Búsqueda por nombre de archivo, ruta y palabras clave (tus propias etiquetas)
- Búsqueda híbrida: una sola caja mezcla los tres tipos de resultado
- Buscar con una imagen (subir o pegar del portapapeles)
- **Similar**: encontrar tomas parecidas a un momento
- **Match monitor** (en Premiere): tomas parecidas al frame del monitor de origen
- **Conceptos**: seleccionas ejemplos, le pones nombre, y luego buscas `#nombre`
- **Colecciones** (favoritos por cliente/proyecto)
- Fuentes múltiples: disco local, NAS/Vault (LucidLink), nube sincronizada; cada una con su interruptor, y con estado online/offline
- Inserción al timeline de Premiere con el tramo exacto (subclip), o abrir en el monitor de origen
- Interfaz en español e inglés (se ajusta sola al idioma de Premiere)
- Elige modelos según tu equipo: GPU NVIDIA, CPU o Apple Silicon

## Instalación

Requisitos: Windows 10/11 o macOS 13+, Premiere Pro 2022 o más nuevo, ~6 GB libres (modelos + PyTorch), internet solo para instalar.

**Windows**

1. Descarga o clona este repositorio (GitHub Desktop: *Code > Open with GitHub Desktop*).
2. Clic derecho en `installers\install.ps1` → **Ejecutar con PowerShell** (o en una terminal: `powershell -ExecutionPolicy Bypass -File installers\install.ps1`).
3. Abre Premiere → *Ventana > Extensiones > LoClip*.

**macOS**

1. Descarga o clona el repositorio.
2. En Terminal: `bash installers/install.sh`
3. Abre Premiere → *Window > Extensions > LoClip*.

La primera vez el instalador descarga PyTorch y los modelos (puede tardar 10–20 min). Después, todo es offline.

## Uso rápido

1. En el panel, **Fuentes → +** y agrega la carpeta de footage (por ejemplo `D:\Footage` o `/Volumes/Vault/Cliente`). Tipo *NAS / Vault* si es LucidLink.
2. LoClip empieza a analizar en segundo plano (barra inferior). Puedes buscar mientras tanto.
3. Escribe en la caja de búsqueda. Filtros: **Todo / Visual / Voz / Nombre**. `#concepto` busca un concepto tuyo.
4. En cada resultado: **Insertar** (al timeline, en el cabezal), **Abrir en origen**, **Similar**, **★** (colección), **…** (detalles y transcripción).
5. Selecciona varias tarjetas (casilla) para agregarlas a una colección, insertarlas todas o **enseñar un concepto**.

Consejos: "Solo disponibles ahora" oculta lo que está en fuentes desconectadas. Las palabras clave de un archivo se editan en *Detalles* y entran en la búsqueda por nombre. Con LucidLink, indexa por carpetas de proyecto: la primera pasada descarga a la caché de Lucid lo que analiza.

## Para equipos

Todos deben usar el **mismo modelo visual** (por defecto `base`) para que los índices sean compatibles. El índice es local por máquina en esta versión; compartir índices por carpeta está en el roadmap.

## Cómo funciona (en corto)

`engine/` es un servidor local en Python (FastAPI) que solo escucha en `127.0.0.1:47821`. Analiza los clips con **SigLIP 2** (imagen↔texto, multilingüe), transcribe con **faster-whisper**, y guarda todo en SQLite. `ui/` es la interfaz web que sirve ese servidor. `panel/` es un panel CEP de Premiere que muestra esa misma interfaz y habla con Premiere por ExtendScript (API interna, independiente del idioma). Más detalle en [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).

## Licencias

LoClip es MIT. Modelos y librerías usadas: SigLIP 2 (Apache 2.0), open_clip (MIT), faster-whisper / CTranslate2 (MIT), Whisper (MIT), PyTorch (BSD), FastAPI (MIT), ffmpeg (LGPL/GPL, binario externo). No contiene código de productos de terceros.

## Roadmap

Ver [`docs/ROADMAP.md`](docs/ROADMAP.md): caras y personas, hablantes (diarización), índices compartidos por carpeta, After Effects, servidor MCP para agentes, app de escritorio.
