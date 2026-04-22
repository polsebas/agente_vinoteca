# Vinoteca IA (paquete)

El README completo del proyecto está en la raíz del repositorio:

**[→ README principal](../README.md)**

Desde esta carpeta (`vinoteca_ia/`) instalás dependencias, corrés tests y levantás la API:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose up -d
uvicorn api.main:app --reload
```
