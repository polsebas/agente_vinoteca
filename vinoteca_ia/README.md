# Vinoteca IA (paquete)

README completo: **[../README.md](../README.md)**  
Guías: **[../docs/](../docs/)**

```bash
cd vinoteca_ia
uv sync
cp .env.example .env
docker compose up -d
uv run python storage/migrations.py
uv run python scripts/seed_catalog.py
uv run uvicorn api.main:app --host 127.0.0.1 --port 8001 --reload
```

`ensure_database.py` solo hace falta si usás un Postgres que no creó `vinoteca_db`.

Agent UI: [docs Agno](https://docs.agno.com/other/agent-ui) → endpoint `http://127.0.0.1:8001`.
