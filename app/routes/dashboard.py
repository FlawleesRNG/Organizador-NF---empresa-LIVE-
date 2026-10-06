from __future__ import annotations

from fastapi import APIRouter, Request

from app.database import conectar
from app.services.email_sync import graph_status


router = APIRouter()


def _carregar_processamentos(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT f.*, l.codigo_loja loja_codigo_cadastro, l.nome loja_nome_cadastro, l.uf loja_uf_cadastro
        FROM faturas f
        LEFT JOIN lojas l ON l.id = f.loja_id
        WHERE f.ativo_historico = 1
          AND f.email_message_id IS NOT NULL
        ORDER BY COALESCE(f.email_data, f.created_at) DESC
        LIMIT 30
        """
    ).fetchall()
    return [dict(row) for row in rows]


@router.get("/")
def index(request: Request):
    with conectar() as conn:
        dados = {
            "lojas": conn.execute("SELECT COUNT(*) total FROM lojas WHERE ativo = 1").fetchone()["total"],
            "faturas": conn.execute("SELECT COUNT(*) total FROM faturas").fetchone()["total"],
            "arquivadas": conn.execute("SELECT COUNT(*) total FROM faturas WHERE status = 'ARQUIVADA'").fetchone()["total"],
            "revisar": conn.execute("SELECT COUNT(*) total FROM faturas WHERE status = 'REVISAR' AND ativo_historico = 1").fetchone()["total"],
        }
        processamentos = _carregar_processamentos(conn)
    return request.app.state.templates.TemplateResponse(
        request,
        "index.html",
        {"dados": dados, "processamentos": processamentos, "graph": graph_status()},
    )


@router.get("/api/dashboard/processamentos")
def api_processamentos():
    with conectar() as conn:
        return {"graph": graph_status(), "processamentos": _carregar_processamentos(conn)}
