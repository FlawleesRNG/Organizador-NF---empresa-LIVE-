from __future__ import annotations

import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from app.database import agora, conectar
from app.services.lojas_master import (
    STATUS_CNPJ_INVALIDO,
    STATUS_CNPJ_PENDENTE,
    STATUS_INATIVA,
    STATUS_OK,
    STATUS_UF_PENDENTE,
    aplicar_importacao,
    exportar_csv,
    gerar_preview,
    inferir_uf,
)
from app.utils.formatadores import (
    normalizar_cidade,
    normalizar_cnpj,
    normalizar_codigo_loja,
    normalizar_nome_loja,
    validar_cnpj,
)


router = APIRouter(prefix="/lojas", tags=["lojas"])


def _status_cadastro(cnpj: str, cnpj_original: str, uf: str, ativo: int) -> str:
    if not ativo:
        return STATUS_INATIVA
    if not (cnpj_original or "").strip():
        return STATUS_CNPJ_PENDENTE
    if not cnpj or not validar_cnpj(cnpj):
        return STATUS_CNPJ_INVALIDO
    if not uf:
        return STATUS_UF_PENDENTE
    return STATUS_OK


def _carregar_loja(loja_id: int):
    with conectar() as conn:
        return conn.execute("SELECT * FROM lojas WHERE id = ?", (loja_id,)).fetchone()


def _form_context(loja=None, erro: str = "") -> dict:
    return {"loja": loja, "erro": erro}


@router.get("")
def listar(request: Request, q: str = "", tipo: str = "", uf: str = "", status: str = "", msg: str = ""):
    sql = "SELECT * FROM lojas WHERE 1 = 1"
    params: list[str] = []
    if q:
        busca = f"%{q.strip()}%"
        sql += " AND (codigo_loja LIKE ? OR nome LIKE ? OR razao_social LIKE ? OR cnpj LIKE ? OR cidade LIKE ?)"
        params.extend([busca, busca, busca, busca, busca])
    if tipo:
        sql += " AND tipo_loja = ?"
        params.append(tipo)
    if uf:
        sql += " AND uf = ?"
        params.append(uf)
    if status:
        sql += " AND status_cadastro = ?"
        params.append(status)
    sql += " ORDER BY COALESCE(codigo_loja, ''), nome, uf"
    with conectar() as conn:
        lojas = conn.execute(sql, params).fetchall()
        tipos = conn.execute("SELECT DISTINCT tipo_loja FROM lojas WHERE tipo_loja IS NOT NULL AND tipo_loja != '' ORDER BY tipo_loja").fetchall()
        ufs = conn.execute("SELECT DISTINCT uf FROM lojas WHERE uf IS NOT NULL AND uf != '' ORDER BY uf").fetchall()
        statuses = conn.execute("SELECT DISTINCT status_cadastro FROM lojas WHERE status_cadastro IS NOT NULL AND status_cadastro != '' ORDER BY status_cadastro").fetchall()
    return request.app.state.templates.TemplateResponse(
        request,
        "lojas.html",
        {
            "lojas": lojas,
            "msg": msg,
            "filtro": {"q": q, "tipo": tipo, "uf": uf, "status": status},
            "tipos": tipos,
            "ufs": ufs,
            "statuses": statuses,
        },
    )


@router.get("/nova")
def nova(request: Request):
    return request.app.state.templates.TemplateResponse(request, "nova_loja.html", _form_context())


@router.post("/nova")
def criar(
    request: Request,
    codigo_loja: str = Form(""),
    nome: str = Form(...),
    tipo_loja: str = Form(""),
    razao_social: str = Form(""),
    cnpj: str = Form(""),
    cidade: str = Form(""),
    uf: str = Form(""),
):
    codigo_norm = normalizar_codigo_loja(codigo_loja)
    cnpj_norm = normalizar_cnpj(cnpj) if cnpj.strip() else ""
    nome_norm = normalizar_nome_loja(nome)
    cidade_norm = normalizar_cidade(cidade)
    uf_norm, _ = inferir_uf(cidade_norm, uf)
    status = _status_cadastro(cnpj_norm, cnpj, uf_norm, 1)
    loja_form = {
        "codigo_loja": codigo_norm,
        "nome": nome_norm,
        "tipo_loja": tipo_loja,
        "razao_social": normalizar_nome_loja(razao_social),
        "cnpj": cnpj,
        "cidade": cidade_norm,
        "uf": uf_norm,
        "ativo": 1,
        "status_cadastro": status,
    }
    if not nome_norm:
        return request.app.state.templates.TemplateResponse(
            request,
            "nova_loja.html",
            _form_context(loja_form, "Informe o nome/unidade."),
            status_code=400,
        )
    if cnpj.strip() and status == STATUS_CNPJ_INVALIDO:
        return request.app.state.templates.TemplateResponse(
            request,
            "nova_loja.html",
            _form_context(loja_form, "CNPJ invalido. Corrija ou deixe em branco para marcar como pendente."),
            status_code=400,
        )
    try:
        with conectar() as conn:
            conn.execute(
                """
                INSERT INTO lojas (codigo_loja, cnpj, nome, tipo_loja, razao_social, cidade, uf, ativo, status_cadastro, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    codigo_norm or None,
                    cnpj_norm or None,
                    nome_norm,
                    tipo_loja.strip() or None,
                    normalizar_nome_loja(razao_social) or None,
                    cidade_norm or None,
                    uf_norm or "",
                    status,
                    agora(),
                    agora(),
                ),
            )
    except sqlite3.IntegrityError:
        return request.app.state.templates.TemplateResponse(
            request,
            "nova_loja.html",
            _form_context(loja_form, "Nao foi possivel cadastrar. Verifique se codigo ou CNPJ ja existem."),
            status_code=400,
        )
    return RedirectResponse("/lojas?msg=Loja cadastrada com sucesso", status_code=303)


@router.get("/{loja_id}/editar")
def editar(request: Request, loja_id: int):
    loja = _carregar_loja(loja_id)
    return request.app.state.templates.TemplateResponse(request, "editar_loja.html", _form_context(loja))


@router.post("/{loja_id}/editar")
def atualizar(
    request: Request,
    loja_id: int,
    codigo_loja: str = Form(""),
    nome: str = Form(...),
    tipo_loja: str = Form(""),
    razao_social: str = Form(""),
    cnpj: str = Form(""),
    cidade: str = Form(""),
    uf: str = Form(""),
    ativo: int = Form(0),
):
    codigo_norm = normalizar_codigo_loja(codigo_loja)
    cnpj_norm = normalizar_cnpj(cnpj) if cnpj.strip() else ""
    nome_norm = normalizar_nome_loja(nome)
    cidade_norm = normalizar_cidade(cidade)
    uf_norm, _ = inferir_uf(cidade_norm, uf)
    ativo_norm = 1 if ativo else 0
    status = _status_cadastro(cnpj_norm, cnpj, uf_norm, ativo_norm)
    loja_form = {
        "id": loja_id,
        "codigo_loja": codigo_norm,
        "nome": nome_norm,
        "tipo_loja": tipo_loja,
        "razao_social": normalizar_nome_loja(razao_social),
        "cnpj": cnpj,
        "cidade": cidade_norm,
        "uf": uf_norm,
        "ativo": ativo_norm,
        "status_cadastro": status,
    }
    if not nome_norm:
        return request.app.state.templates.TemplateResponse(
            request,
            "editar_loja.html",
            _form_context(loja_form, "Informe o nome/unidade."),
            status_code=400,
        )
    if cnpj.strip() and status == STATUS_CNPJ_INVALIDO:
        return request.app.state.templates.TemplateResponse(
            request,
            "editar_loja.html",
            _form_context(loja_form, "CNPJ invalido. Corrija ou deixe em branco para marcar como pendente."),
            status_code=400,
        )
    try:
        with conectar() as conn:
            conn.execute(
                """
                UPDATE lojas
                SET codigo_loja = ?, cnpj = ?, nome = ?, tipo_loja = ?, razao_social = ?, cidade = ?,
                    uf = ?, ativo = ?, status_cadastro = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    codigo_norm or None,
                    cnpj_norm or None,
                    nome_norm,
                    tipo_loja.strip() or None,
                    normalizar_nome_loja(razao_social) or None,
                    cidade_norm or None,
                    uf_norm or "",
                    ativo_norm,
                    status,
                    agora(),
                    loja_id,
                ),
            )
    except sqlite3.IntegrityError:
        return request.app.state.templates.TemplateResponse(
            request,
            "editar_loja.html",
            _form_context(loja_form, "Nao foi possivel salvar. Verifique se codigo ou CNPJ ja existem."),
            status_code=400,
        )
    return RedirectResponse("/lojas?msg=Loja atualizada", status_code=303)


@router.get("/importar")
def importar_form(request: Request, erro: str = "", msg: str = ""):
    return request.app.state.templates.TemplateResponse(
        request,
        "importar_lojas.html",
        {"erro": erro, "msg": msg},
    )


@router.post("/importar")
async def importar_preview(request: Request, arquivo: UploadFile = File(...)):
    conteudo = await arquivo.read()
    if not conteudo:
        return request.app.state.templates.TemplateResponse(
            request,
            "importar_lojas.html",
            {"erro": "Selecione um CSV para importar.", "msg": ""},
            status_code=400,
        )
    try:
        preview = gerar_preview(conteudo)
    except Exception:
        return request.app.state.templates.TemplateResponse(
            request,
            "importar_lojas.html",
            {"erro": "Nao foi possivel ler o CSV. Verifique o cabecalho e o separador.", "msg": ""},
            status_code=400,
        )
    return request.app.state.templates.TemplateResponse(request, "preview_importacao_lojas.html", preview)


@router.post("/importar/confirmar")
def importar_confirmar(payload: str = Form(...)):
    try:
        resultado = aplicar_importacao(payload)
    except Exception as exc:
        return RedirectResponse(f"/lojas/importar?erro={quote(str(exc))}", status_code=303)
    return RedirectResponse(
        f"/lojas?msg=Importacao concluida: {resultado['linhas']} linhas. Backup: {resultado['backup']}",
        status_code=303,
    )


@router.get("/exportar")
def exportar():
    csv_texto = exportar_csv()
    return Response(
        csv_texto,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=lojas.csv"},
    )


@router.post("/{loja_id}/alternar")
def alternar(loja_id: int):
    with conectar() as conn:
        loja = conn.execute("SELECT ativo FROM lojas WHERE id = ?", (loja_id,)).fetchone()
        if loja:
            conn.execute(
                "UPDATE lojas SET ativo = ?, updated_at = ? WHERE id = ?",
                (0 if loja["ativo"] else 1, agora(), loja_id),
            )
    return RedirectResponse("/lojas?msg=Loja atualizada", status_code=303)
