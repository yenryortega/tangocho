# 単語帳 · JLPT N1

App de tarjetas con repaso espaciado (tipo Anki) para preparar el JLPT N1: vocabulario, gramática y tips de examen de las clases diarias.

## Cómo funciona

- `content/day-NNN.json`: las tarjetas de cada clase. Es la fuente del contenido.
- Al arrancar, la app copia todos esos archivos a la base de datos (inserta o actualiza; nunca borra el progreso).
- Cada mañana la clase de japonés añade un `content/day-NNN.json` nuevo y hace push a `main`. Railway redespliega solo y las tarjetas aparecen en la app.
- El progreso de repaso (`reviews`) y los ajustes (`settings`) solo viven en la base de datos.

## Formato de una tarjeta

```json
{"id": "d003-v01", "type": "vocab", "order": 1,
 "front": "懸念", "reading": "けねん", "meaning": "preocupación",
 "example": "…", "exampleEs": "…",
 "examples": [{"jp": "…", "es": "…"}, {"jp": "…", "es": "…"}],
 "note": "opcional"}
```

`type`: `vocab`, `grammar` o `tip` (en los tips, `front` es la pregunta y `meaning` la respuesta). `order`: 1–19 vocabulario, 20–49 gramática, 50+ tips.

## Variables de entorno (Railway)

| Variable | Para qué |
|---|---|
| `DATABASE_URL` | La pone Railway al añadir PostgreSQL (referencia `${{Postgres.DATABASE_URL}}`) |
| `APP_PASSWORD` | Opcional. Si no existe, la primera visita pide crear una contraseña (se guarda con hash en la base de datos) |
| `SECRET_KEY` | Opcional. Si no existe, la app genera una y la guarda en la base de datos |

## En local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
APP_PASSWORD=test python app.py   # usa SQLite (local.db)
```
