# Arquitectura de LoClip

```
Premiere Pro ──(ExtendScript, API interna)── panel/ (CEP) ──iframe──▶ ui/  ──HTTP 127.0.0.1:47821──▶ engine/ (Python)
                                                                                                      ├─ SigLIP 2 (visual)
                                                                                                      ├─ faster-whisper (voz)
                                                                                                      ├─ ffmpeg (lectura de video)
                                                                                                      └─ SQLite + índice vectorial en RAM
```

## engine/ (Python 3.11+)

| Módulo | Qué hace |
|---|---|
| `config.py` | Rutas (carpeta de datos del usuario), ajustes, extensiones de medios, carpetas ignoradas |
| `hardware.py` | Detecta GPU/CPU/Mac y recomienda modelos |
| `db.py` | Esquema SQLite: fuentes, archivos, momentos (embedding), segmentos de voz (FTS5), colecciones, conceptos |
| `media.py` | Escaneo de carpetas, `ffprobe`, extracción de frames con `ffmpeg` (solo lectura), miniaturas |
| `embeddings.py` | Modelo visual SigLIP 2 vía open_clip: imágenes y texto → vectores |
| `transcribe.py` | faster-whisper |
| `indexer.py` | Hilo en segundo plano: escanea, analiza, agrupa frames en "momentos", transcribe |
| `search.py` | Índice vectorial en RAM (numpy), búsqueda visual, por nombre (FTS) y por voz (FTS) |
| `server.py` | API HTTP (FastAPI) + sirve `ui/` |

### Momentos
Se analiza 1 frame por segundo (ajustable). Frames consecutivos con similitud ≥ 0.90 se agrupan en un momento; el momento guarda el vector promedio, su rango de tiempo y una miniatura. Así un plano fijo de 40 s es un solo resultado y no 40.

### Búsqueda híbrida
Modo "Todo" ejecuta las tres búsquedas y las fusiona por rango recíproco (RRF). Un resultado que aparece en varias listas sube.

### Regla de solo lectura
Ningún módulo abre archivos de las fuentes para escritura. Miniaturas, WAV temporales y base de datos van a la carpeta de datos (`%LOCALAPPDATA%\LoClip` en Windows, `~/Library/Application Support/LoClip` en Mac).

## ui/
HTML/CSS/JS sin frameworks. Funciona en el navegador y dentro del panel. Cuando corre en Premiere (`?host=ppro`) manda acciones al panel con `postMessage` (`insert`, `openSource`, `sourceMonitor`).

## panel/ (CEP)
`index.html` muestra la UI en un iframe y arranca el motor si no está corriendo (`engine.json`, escrito por el instalador). `jsx/host.jsx` habla con Premiere usando solo la API de ExtendScript, que es la misma en todos los idiomas de Premiere.

## API (resumen)
`GET /api/search?q=&mode=all|visual|speech|name&k=&per_file=&available_only=` · `POST /api/search/image` · `GET /api/similar/{moment}` · `POST /api/match_frame` · `GET/POST/PATCH/DELETE /api/sources` · `GET /api/status` · `GET /api/files/{id}` · `GET /api/files/{id}/transcript` · `PUT /api/segments/{id}` · `/api/collections…` · `/api/concepts…` · `GET /api/system` · `PUT /api/settings`
