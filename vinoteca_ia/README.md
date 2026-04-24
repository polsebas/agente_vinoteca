# Vinoteca IA (paquete)

El README completo del proyecto está en la raíz del repositorio:

**[→ README principal](../README.md)**

Desde esta carpeta (`vinoteca_ia/`) instalás dependencias, corrés tests y levantás la API:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose up -d
python scripts/ensure_database.py
uvicorn api.main:app --reload
```

Con `docker compose`, la primera vez que arranca el volumen Postgres ya se crean usuario, contraseña y base (`POSTGRES_DB` en `docker-compose.yml`). El script `ensure_database.py` sirve si usás otro Postgres o si la base del `DATABASE_URL` todavía no existe en el cluster.

**Agent UI (chat con AgentOS sin os.agno.com):** [doc Agno — AgentUI](https://docs.agno.com/other/agent-ui). `npx create-agent-ui@latest`, `npm run dev` en `localhost:3000`, y en el lateral la base de tu API (`http://127.0.0.1:8000` si usás el puerto del README raíz).
