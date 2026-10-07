from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
from pathlib import Path

from app.config import get_settings
from app.database import DATA_DIR, agora, conectar
from app.models import STATUS_REVISAR
from app.services.comparativo import comparar_campos, dumps_comparativo, encontrar_match
from app.services.manutencao import sha256_arquivo
from app.services.microsoft_graph import GraphAttachment, GraphMessage, GraphNotConfigured, MicrosoftGraphClient
from app.services.parsers.base import ParserGenerico, identificar_cnpjs_live
from app.services.pdf_parser import extrair_texto_pdf, parsear_texto
from app.services.telemiza_email_parser import ItemEmail, parsear_email_telemiza
from app.utils.formatadores import data_para_nome_arquivo, formatar_cnpj, formatar_valor, nome_exibicao_loja, normalizar_cnpj, sanitizar_nome_path


logger = logging.getLogger("telemiza")
ORIGINAIS = DATA_DIR / "caixa_compartilhada" / "originais"
PROCESSAMENTO = DATA_DIR / "caixa_compartilhada" / "processamento"


def graph_status() -> dict:
    settings = get_settings()
    if not settings.graph_configurado:
        return {
            "configurado": False,
            "mensagem": "Integracao Microsoft 365 aguardando configuracao",
            "shared_mailbox": "",
            "intervalo": settings.mail_sync_interval_seconds,
        }
    return {
        "configurado": True,
        "mensagem": "Integracao Microsoft 365 configurada",
        "shared_mailbox": settings.shared_mailbox,
        "intervalo": settings.mail_sync_interval_seconds,
    }


def _safe_filename(nome: str) -> str:
    return sanitizar_nome_path(nome, "anexo.pdf")


def _buscar_loja(conn, cnpj: str):
    cnpj_norm = normalizar_cnpj(cnpj)
    if not cnpj_norm:
        return None
    return conn.execute("SELECT * FROM lojas WHERE cnpj = ? AND ativo = 1", (cnpj_norm,)).fetchone()


def _ajustar_identidade_pdf(dados_pdf: dict, texto: str, nome_arquivo: str) -> dict:
    """Aplica a mesma regra do upload manual: CNPJ da loja LIVE! e operadora automaticos."""
    dados_pdf = dict(dados_pdf)
    dados_pdf["confianca"] = dict(dados_pdf.get("confianca") or {})
    dados_pdf["origem"] = dict(dados_pdf.get("origem") or {})
    cnpjs = list(dict.fromkeys(dados_pdf.get("cnpjs") or []))
    live = identificar_cnpjs_live(f"{texto}\n{nome_arquivo}")
    for cnpj in live:
        if cnpj not in cnpjs:
            cnpjs.insert(0, cnpj)
    dados_pdf["cnpjs"] = cnpjs
    if len(live) == 1:
        dados_pdf["cnpj"] = live[0]
        dados_pdf["cnpj_formatado"] = formatar_cnpj(live[0])
        dados_pdf["confianca"]["cnpj"] = 0.99
        dados_pdf["origem"]["cnpj"] = "Identificado automaticamente pelo prefixo CNPJ LIVE! 35.303.139"
    elif len(live) > 1:
        dados_pdf["cnpj"] = ""
        dados_pdf["cnpj_formatado"] = ""
        dados_pdf["confianca"]["cnpj"] = 0.45
        dados_pdf["origem"]["cnpj"] = "Mais de um CNPJ LIVE! encontrado no documento"
    elif not (dados_pdf.get("cnpj") or "").startswith("35303139"):
        dados_pdf["cnpj"] = ""
        dados_pdf["cnpj_formatado"] = ""
        dados_pdf["confianca"]["cnpj"] = 0.0
        dados_pdf["origem"]["cnpj"] = "Nenhum CNPJ com prefixo LIVE! 35.303.139 foi encontrado"
    detector = ParserGenerico()
    operadora_nome = detector.identificar_operadora(nome_arquivo)
    operadora_texto = detector.identificar_operadora(texto)
    if operadora_nome:
        dados_pdf["operadora"] = operadora_nome
        dados_pdf["origem"]["operadora"] = "Identificada automaticamente pelo nome do arquivo"
    elif operadora_texto:
        dados_pdf["operadora"] = operadora_texto
        dados_pdf["origem"]["operadora"] = "Identificada automaticamente pelo conteudo do PDF"
    elif not dados_pdf.get("operadora"):
        dados_pdf["operadora"] = ""
        dados_pdf["origem"]["operadora"] = "Operadora não identificada automaticamente"
    return dados_pdf


def _nome_sugerido(loja, dados_pdf: dict) -> str:
    loja_txt = nome_exibicao_loja(loja) if loja else "CNPJ NÃO CADASTRADO"
    partes = [
        loja_txt,
        dados_pdf.get("operadora") or "OPERADORA",
        data_para_nome_arquivo(dados_pdf.get("vencimento")) if dados_pdf.get("vencimento") else "SEM DATA",
        formatar_valor(dados_pdf.get("valor")) if dados_pdf.get("valor") else "SEM VALOR",
        dados_pdf.get("codigo_fatura") or "SEM CODIGO",
    ]
    return sanitizar_nome_path(" - ".join(partes) + ".pdf")


def upsert_mensagem(message: GraphMessage, itens: list[ItemEmail]) -> int:
    with conectar() as conn:
        row = conn.execute("SELECT id FROM mensagens_email WHERE message_id = ?", (message.id,)).fetchone()
        if row:
            mensagem_id = row["id"]
            conn.execute(
                "UPDATE mensagens_email SET remetente = ?, assunto = ?, data_recebimento = ?, status = ? WHERE id = ?",
                (message.sender, message.subject, message.received_at, "PROCESSANDO", mensagem_id),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO mensagens_email (message_id, remetente, assunto, data_recebimento, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (message.id, message.sender, message.subject, message.received_at, "PROCESSANDO", agora()),
            )
            mensagem_id = cur.lastrowid
        for item in itens:
            conn.execute(
                """
                INSERT INTO itens_email (
                    mensagem_id, row_index, razao_social, cnpj, cliente, unidade_email, operadora,
                    vencimento, referencia, codigo_fatura, tipo, servico, interface, acesso_banda,
                    liberacao, dados_originais, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mensagem_id, row_index) DO UPDATE SET
                    razao_social=excluded.razao_social, cnpj=excluded.cnpj, cliente=excluded.cliente,
                    unidade_email=excluded.unidade_email, operadora=excluded.operadora,
                    vencimento=excluded.vencimento, referencia=excluded.referencia,
                    codigo_fatura=excluded.codigo_fatura, tipo=excluded.tipo, servico=excluded.servico,
                    interface=excluded.interface, acesso_banda=excluded.acesso_banda,
                    liberacao=excluded.liberacao, dados_originais=excluded.dados_originais
                """,
                item.as_db_tuple(mensagem_id) + (agora(),),
            )
        return mensagem_id


def _itens_mensagem(conn, mensagem_id: int) -> list[dict]:
    return [dict(row) for row in conn.execute("SELECT * FROM itens_email WHERE mensagem_id = ?", (mensagem_id,))]


def processar_anexo(mensagem_id: int, message: GraphMessage, attachment: GraphAttachment) -> int:
    ORIGINAIS.mkdir(parents=True, exist_ok=True)
    nome = _safe_filename(attachment.name)
    destino = ORIGINAIS / f"{mensagem_id}_{_safe_filename(attachment.id)}_{nome}"
    destino.write_bytes(attachment.content_bytes)
    sha = sha256_arquivo(destino)
    with conectar() as conn:
        existente_anexo = conn.execute(
            "SELECT fatura_id FROM anexos_email WHERE mensagem_id = ? AND attachment_id = ?",
            (mensagem_id, attachment.id),
        ).fetchone()
        if existente_anexo and existente_anexo["fatura_id"]:
            return existente_anexo["fatura_id"]

        existente_pdf = conn.execute(
            "SELECT id FROM faturas WHERE sha256 = ? AND ativo_historico = 1",
            (sha,),
        ).fetchone()
        texto = extrair_texto_pdf(destino)
        dados_pdf = _ajustar_identidade_pdf(parsear_texto(texto), texto, attachment.name)
        loja = _buscar_loja(conn, dados_pdf.get("cnpj", ""))
        itens = _itens_mensagem(conn, mensagem_id)
        match = encontrar_match(itens, dados_pdf)
        item = next((item for item in itens if item["id"] == match.item_id), None)
        comparativo = comparar_campos(item, dados_pdf, loja_encontrada=bool(loja))
        nome_sugerido = _nome_sugerido(loja, dados_pdf)
        status = STATUS_REVISAR if comparativo["status"] != "CONFERE" else "PENDENTE"

        if existente_pdf:
            fatura_id = existente_pdf["id"]
            conn.execute(
                """
                UPDATE faturas SET email_message_id = ?, email_attachment_id = ?, email_remetente = ?,
                    email_assunto = ?, email_data = ?, item_email_id = ?, cnpj = ?, cnpj_fornecedor = ?,
                    loja_id = ?, nome_loja = ?, uf_loja = ?, operadora = ?, valor = ?, vencimento = ?,
                    codigo_fatura = ?, codigo_cliente = ?, numero_fatura = ?, texto_extraido = ?,
                    parser_utilizado = ?, confianca_cnpj = ?, confianca_valor = ?, confianca_vencimento = ?,
                    confianca_codigo = ?, origem_cnpj = ?, origem_valor = ?, origem_vencimento = ?,
                    origem_codigo = ?, outros_cnpjs = ?, nome_arquivo_sugerido = ?, comparativo_status = ?,
                    comparativo_json = ?, status = ?, motivo_revisao = ?
                WHERE id = ?
                """,
                _fatura_params(message, attachment, match.item_id, dados_pdf, loja, texto, nome_sugerido, comparativo, status)
                + (fatura_id,),
            )
        else:
            cur = conn.execute(
                """
                INSERT INTO faturas (
                    arquivo_original, arquivo_final, caminho_final, sha256, email_message_id, email_attachment_id,
                    email_remetente, email_assunto, email_data, item_email_id, cnpj, cnpj_fornecedor,
                    loja_id, nome_loja, uf_loja, operadora, valor, vencimento, codigo_fatura,
                    codigo_cliente, numero_fatura, texto_extraido,
                    parser_utilizado, confianca_cnpj, confianca_valor, confianca_vencimento, confianca_codigo,
                    origem_cnpj, origem_valor, origem_vencimento, origem_codigo, outros_cnpjs,
                    nome_arquivo_sugerido, comparativo_status, comparativo_json, status, motivo_revisao, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attachment.name,
                    nome,
                    str(destino),
                    sha,
                )
                + _fatura_params(message, attachment, match.item_id, dados_pdf, loja, texto, nome_sugerido, comparativo, status)
                + (agora(),),
            )
            fatura_id = cur.lastrowid
        conn.execute(
            """
            INSERT INTO anexos_email (mensagem_id, attachment_id, nome_original, sha256, caminho_original, fatura_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mensagem_id, attachment_id) DO UPDATE SET
                sha256=excluded.sha256, caminho_original=excluded.caminho_original, fatura_id=excluded.fatura_id
            """,
            (mensagem_id, attachment.id, attachment.name, sha, str(destino), fatura_id, agora()),
        )
        return fatura_id


def _fatura_params(message, attachment, item_id, dados_pdf, loja, texto, nome_sugerido, comparativo, status) -> tuple:
    return (
        message.id,
        attachment.id,
        message.sender,
        message.subject,
        message.received_at,
        item_id,
        dados_pdf.get("cnpj", ""),
        dados_pdf.get("cnpj_fornecedor", ""),
        loja["id"] if loja else None,
        loja["nome"] if loja else "",
        loja["uf"] if loja else "",
        dados_pdf.get("operadora", ""),
        float(dados_pdf["valor"]) if dados_pdf.get("valor") else None,
        dados_pdf.get("vencimento", ""),
        dados_pdf.get("codigo_fatura", ""),
        dados_pdf.get("codigo_cliente", ""),
        dados_pdf.get("numero_fatura", ""),
        texto[:200000],
        dados_pdf.get("parser_utilizado", "generico"),
        dados_pdf.get("confianca", {}).get("cnpj", 0.0),
        dados_pdf.get("confianca", {}).get("valor", 0.0),
        dados_pdf.get("confianca", {}).get("vencimento", 0.0),
        dados_pdf.get("confianca", {}).get("codigo", 0.0),
        dados_pdf.get("origem", {}).get("cnpj", ""),
        dados_pdf.get("origem", {}).get("valor", ""),
        dados_pdf.get("origem", {}).get("vencimento", ""),
        dados_pdf.get("origem", {}).get("codigo", ""),
        json.dumps(dados_pdf.get("outros_cnpjs", []), ensure_ascii=False),
        nome_sugerido,
        comparativo["status"],
        dumps_comparativo(comparativo),
        status,
        "" if comparativo["status"] == "CONFERE" else comparativo["status"],
    )


async def sincronizar_uma_vez() -> dict:
    settings = get_settings()
    if not settings.graph_configurado:
        return {"status": "AGUARDANDO_CONFIGURACAO", "mensagens": 0, "pdfs": 0}
    client = MicrosoftGraphClient(settings)
    mensagens = await client.listar_mensagens_telemiza()
    pdfs = 0
    logger.info("Sincronizacao iniciada: %s mensagens encontradas", len(mensagens))
    for message in mensagens:
        itens = parsear_email_telemiza(message.body_html)
        mensagem_id = upsert_mensagem(message, itens)
        if not message.has_attachments:
            continue
        for attachment in await client.listar_anexos_pdf(message.id):
            processar_anexo(mensagem_id, message, attachment)
            pdfs += 1
        with conectar() as conn:
            conn.execute(
                "UPDATE mensagens_email SET status = ?, processada_em = ? WHERE id = ?",
                ("PROCESSADA", agora(), mensagem_id),
            )
    logger.info("Sincronizacao concluida: %s PDFs processados", pdfs)
    return {"status": "OK", "mensagens": len(mensagens), "pdfs": pdfs}


async def loop_sincronizacao(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    while not stop_event.is_set():
        try:
            await sincronizar_uma_vez()
        except GraphNotConfigured:
            logger.info("Integracao Microsoft 365 aguardando configuracao")
        except Exception:
            logger.exception("Erro na sincronizacao da caixa compartilhada")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=settings.mail_sync_interval_seconds)
        except asyncio.TimeoutError:
            continue
