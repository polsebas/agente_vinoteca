# Skill: Arquitectura Cognitiva y Estrategia de Agentes

## 1. Ciclo de Ejecución (Bucle PRAO)
* [cite_start]**Obligatorio**: Todo agente debe operar bajo el flujo Perceive → Reason → Act → Observe[cite: 29, 55, 218].
* [cite_start]**Estado**: El código debe ser estrictamente stateless; el orquestador gestiona la persistencia del historial[cite: 30, 56, 112].
* [cite_start]**Control de Pasos**: Implementar un límite duro de iteraciones (`max_steps`) para evitar bucles infinitos y consumo de tokens[cite: 172, 231].

## 2. Separación de Datos (Probabilístico vs. Determinista)
* [cite_start]**Fuente de Verdad (SQL)**: Precios, stock y datos transaccionales se consultan ÚNICAMENTE vía SQL (mcp-postgres/sqlite)[cite: 15, 31, 249].
* [cite_start]**Prohibición**: Queda terminantemente prohibido usar búsquedas vectoriales (RAG) para recuperar precios o disponibilidad para evitar alucinaciones[cite: 16, 61, 250].
* [cite_start]**Uso de Vectores**: RAG Vectorial se reserva exclusivamente para conocimiento cualitativo: notas de cata, historia de bodegas y maridajes[cite: 17, 58, 252].

## 3. Seguridad y Human-in-the-Loop (HitL)
* [cite_start]**Acciones Críticas**: Cobros, reembolsos o eliminación de registros requieren obligatoriamente el patrón de dos fases[cite: 22, 72, 285]:
    1. [cite_start]**Fase Preparación**: Crear un registro "Pendiente de Aprobación" y pausar el bucle PRAO[cite: 23, 139, 298].
    2. [cite_start]**Fase Ejecución**: Solo se procede tras una señal externa en el endpoint `/aprobar`[cite: 24, 73, 301].
* [cite_start]**Idempotencia**: Inyectar `idempotency_keys` en cada paso lógico para prevenir cobros dobles por fallos de red[cite: 21, 56, 276].

## 4. Topología de Agentes
* [cite_start]**Router**: Clasifica la intención y deriva al especialista mediante `transfer_task`[cite: 57, 114, 330].
* [cite_start]**Especialistas**: El agente Sommelier (Cata), Pedidos (Transacción) e Inventario (Stock) tienen límites de herramientas estrictos[cite: 58, 59, 60].