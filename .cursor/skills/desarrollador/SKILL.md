# Skill: Estándares de Desarrollo y Entorno Agno

## 1. Framework y Dependencias
* [cite_start]**Core**: Utilizar exclusivamente el framework **Agno** para evitar código espagueti y vendor lock-in[cite: 4, 38, 103].
* [cite_start]**Gestión**: Usar `uv` o `venv` para aislamiento y fijar versiones: `agno==1.0.x`, `pydantic==2.x.x`[cite: 7, 41, 95].
* [cite_start]**Asincronía**: El código debe ser puramente asíncrono (`httpx`, `asyncpg`) para no bloquear el event loop de FastAPI[cite: 132, 135, 169].

## 2. Tipado con Pydantic
* [cite_start]**Lenguaje Universal**: Usar modelos Pydantic para tipar TODAS las herramientas (`@tool`) y generar JSON Schemas correctos[cite: 5, 35, 99].
* [cite_start]**Salidas Estructuradas**: Forzar respuestas del agente pasando el modelo Pydantic al parámetro `response_model`[cite: 12, 119, 171].
* [cite_start]**Inmutabilidad**: El estado interno del agente no debe usar diccionarios libres, sino modelos Pydantic inmutables[cite: 101, 102].

## 3. Configuración de Inferencia
* [cite_start]**Temperatura 0.0**: Obligatoria para llamadas a herramientas y generación de JSON para garantizar determinismo[cite: 19, 36, 78, 120].
* [cite_start]**Temperatura 0.7**: Permitida únicamente para agentes de generación creativa (ej. descripciones de vinos)[cite: 20, 37, 122].

## 4. Convenciones de Código
* [cite_start]**Herramientas**: Nombres en `snake_case` imperativo (ej. `procesar_cobro`)[cite: 39, 154].
* [cite_start]**Docstrings Cognitivos**: No explicar qué hace el código, sino **cuándo y por qué** el agente debe invocar esa función específica[cite: 40, 89, 155].
* [cite_start]**MCP (Model Context Protocol)**: Usar servidores MCP independientes para conectar la base de datos, asegurando tiempos de espera (timeouts) configurados[cite: 13, 125, 128].