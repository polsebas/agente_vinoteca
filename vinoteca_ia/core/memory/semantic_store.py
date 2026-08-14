"""Memoria semántica: perfil permanente del cliente (SQL).

Lee/escribe `clientes` y `cliente_preferencias`. Las preferencias con más
de 24 meses se consideran stale y no alimentan el perfil activo.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from schemas.customer_profile import (
    CustomerProfile,
    PerfilClienteTipo,
    PreferenciaRegistrada,
    SegmentoCliente,
)
from schemas.wine_catalog import Varietal
from storage.postgres import execute, fetch_all, fetchrow

STALE_TTL = timedelta(days=365 * 2)
_SEGMENTOS = {s.value for s in SegmentoCliente}
_PERFILES = {p.value for p in PerfilClienteTipo}
_CEPA_KEYS = {"cepa_favorita", "varietal_favorito", "cepas_favoritas"}
_RANGO_KEYS = {"rango_precio", "rango_precio_habitual", "presupuesto"}
_RESTRICCION_KEYS = {"alergia", "alergias", "restricciones_dietarias"}


def _enum(cls, raw: str | None, default):
    try:
        return cls(raw or default.value)
    except ValueError:
        return default


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class SemanticStore:
    """Perfil y preferencias permanentes. TTL de 24 meses sobre preferencias."""

    def is_stale(self, updated_at: datetime) -> bool:
        return datetime.now(UTC) - _aware(updated_at) > STALE_TTL

    async def get_profile(self, cliente_id: str) -> CustomerProfile | None:
        if not cliente_id:
            return None
        row = await fetchrow(
            """
            SELECT nombre, email, telefono, segmento, perfil_tipo
            FROM clientes
            WHERE id = $1
            """,
            cliente_id,
        )
        if row is None:
            return None

        prefs = await fetch_all(
            """
            SELECT clave, valor, fuente, updated_at
            FROM cliente_preferencias
            WHERE cliente_id = $1
            ORDER BY updated_at DESC
            """,
            cliente_id,
        )
        vigentes = [p for p in prefs if not self.is_stale(p["updated_at"])]
        historial = [
            PreferenciaRegistrada(
                tipo=p["clave"],
                valor=p["valor"],
                confianza=1.0,
                origen_turno=0,
                registrado_en=_aware(p["updated_at"]),
            )
            for p in vigentes
        ]
        stats = await fetchrow(
            """
            SELECT COUNT(*)::int AS total, MAX(created_at) AS ultima
            FROM pedidos
            WHERE cliente_id = $1
              AND estado IN ('pagada', 'aprobada')
            """,
            cliente_id,
        )
        return CustomerProfile(
            cliente_id=cliente_id,
            nombre=row["nombre"],
            segmento=_enum(SegmentoCliente, row["segmento"], SegmentoCliente.GENERAL),
            perfil_tipo=_enum(PerfilClienteTipo, row["perfil_tipo"], PerfilClienteTipo.GENERAL),
            cepas_favoritas=self._cepas(vigentes),
            restricciones_dietarias=self._restricciones(vigentes),
            rango_precio_habitual=self._rango(vigentes),
            fecha_ultima_compra=stats["ultima"] if stats else None,
            historial_preferencias=historial,
            total_compras=int(stats["total"]) if stats and stats["total"] else 0,
        )

    async def upsert_preference(
        self,
        cliente_id: str,
        tipo: str,
        valor: str,
        fuente: str = "conversacion",
    ) -> None:
        if not cliente_id or not tipo.strip() or not valor.strip():
            return
        exists = await fetchrow("SELECT id FROM clientes WHERE id = $1", cliente_id)
        if exists is None:
            await execute(
                """
                INSERT INTO clientes (id, segmento, perfil_tipo, created_at)
                VALUES ($1, 'general', 'general', NOW())
                """,
                cliente_id,
            )
        await execute(
            """
            INSERT INTO cliente_preferencias (cliente_id, clave, valor, fuente, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (cliente_id, clave)
            DO UPDATE SET valor = EXCLUDED.valor,
                          fuente = EXCLUDED.fuente,
                          updated_at = NOW()
            """,
            cliente_id,
            tipo.strip(),
            valor.strip(),
            fuente,
        )
        if tipo.strip() == "segmento" and valor.strip() in _SEGMENTOS:
            await execute(
                "UPDATE clientes SET segmento = $1 WHERE id = $2",
                valor.strip(),
                cliente_id,
            )
        if tipo.strip() == "perfil_tipo" and valor.strip() in _PERFILES:
            await execute(
                "UPDATE clientes SET perfil_tipo = $1 WHERE id = $2",
                valor.strip(),
                cliente_id,
            )

    async def upsert_profile(self, profile: CustomerProfile) -> None:
        await execute(
            """
            INSERT INTO clientes (id, nombre, segmento, perfil_tipo, created_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (id) DO UPDATE SET
                nombre = COALESCE(EXCLUDED.nombre, clientes.nombre),
                segmento = EXCLUDED.segmento,
                perfil_tipo = EXCLUDED.perfil_tipo
            """,
            profile.cliente_id,
            profile.nombre,
            profile.segmento.value,
            profile.perfil_tipo.value,
        )
        for cepa in profile.cepas_favoritas:
            await self.upsert_preference(
                profile.cliente_id,
                "cepa_favorita",
                cepa.value,
                fuente="perfil",
            )
        if profile.rango_precio_habitual:
            lo, hi = profile.rango_precio_habitual
            await self.upsert_preference(
                profile.cliente_id,
                "rango_precio",
                f"{lo}-{hi}",
                fuente="perfil",
            )
        for restriccion in profile.restricciones_dietarias:
            await self.upsert_preference(
                profile.cliente_id,
                "restricciones_dietarias",
                restriccion,
                fuente="perfil",
            )

    @staticmethod
    def _cepas(prefs: list) -> list[Varietal]:
        resultado: list[Varietal] = []
        vistos: set[str] = set()
        for p in prefs:
            if str(p["clave"]) not in _CEPA_KEYS:
                continue
            raw = str(p["valor"]).strip().lower()
            if raw in vistos:
                continue
            vistos.add(raw)
            try:
                resultado.append(Varietal(raw))
            except ValueError:
                resultado.append(Varietal.OTRO)
        return resultado

    @staticmethod
    def _restricciones(prefs: list) -> list[str]:
        return [str(p["valor"]) for p in prefs if str(p["clave"]) in _RESTRICCION_KEYS]

    @staticmethod
    def _rango(prefs: list) -> tuple[int, int] | None:
        for p in prefs:
            if str(p["clave"]) not in _RANGO_KEYS:
                continue
            nums = [int(n) for n in re.findall(r"\d+", str(p["valor"]))]
            if len(nums) >= 2:
                return nums[0], nums[1]
            if len(nums) == 1:
                return 0, nums[0]
        return None
