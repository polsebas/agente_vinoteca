"""Contract layer: todos los modelos Pydantic del sistema.

Nada en la aplicación debe usar dicts libres. Si un dato cruza una frontera
(tool → agent, agent → API, DB → agent), pasa tipado por uno de estos modelos.
"""
