"""Tools de pedidos: Two-Phase Commit obligatorio.

Fase 1 (preparación): verify_stock_exact → calculate_order → create_order.
Fase 2 (ejecución): send_payment_link. Todas las tools destructivas llevan
`requires_confirmation=True` para que el agente pause y espere aprobación
externa antes de ejecutarlas.
"""
