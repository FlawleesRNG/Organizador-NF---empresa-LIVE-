from __future__ import annotations

import json
from dataclasses import dataclass

from app.utils.formatadores import formatar_cnpj, formatar_data_br, formatar_valor


STATUS_CONFERE = "CONFERE"
STATUS_DIVERGENCIA = "DIVERGENCIA"
STATUS_REVISAR = "REVISAR"
STATUS_SEM_CORRESPONDENCIA = "SEM CORRESPONDENCIA"
STATUS_CNPJ_NAO_CADASTRADO = "CNPJ NAO CADASTRADO"
STATUS_ERRO_LEITURA = "ERRO DE LEITURA"


@dataclass
class MatchResultado:
    item_id: int | None
    status: str
    score: int


def _norm(valor) -> str:
    return str(valor or "").strip().upper()


def comparar_campos(item: dict | None, pdf: dict, loja_encontrada: bool, confianca_minima: float = 0.80) -> dict:
    linhas = []
    tem_divergencia = False
    campos = [
        ("CNPJ", "cnpj", formatar_cnpj),
        ("OPERADORA", "operadora", str),
        ("VENCIMENTO", "vencimento", formatar_data_br),
        ("CODIGO", "codigo_fatura", str),
    ]
    for label, key, formatter in campos:
        email_raw = item.get(key) if item else ""
        pdf_raw = pdf.get(key, "")
        if not email_raw:
            status = "INFORMATIVO"
        elif _norm(email_raw) == _norm(pdf_raw):
            status = "CONFERE"
        else:
            status = "DIVERGE"
            tem_divergencia = True
        linhas.append(
            {
                "campo": label,
                "email": formatter(email_raw) if email_raw else "NAO INFORMADO",
                "pdf": formatter(pdf_raw) if pdf_raw else "NAO IDENTIFICADO",
                "status": status,
            }
        )
    linhas.append(
        {
            "campo": "VALOR",
            "email": "NAO INFORMADO",
            "pdf": formatar_valor(pdf.get("valor")) if pdf.get("valor") else "NAO IDENTIFICADO",
            "status": "INFORMATIVO",
        }
    )

    if not item:
        geral = STATUS_SEM_CORRESPONDENCIA
    elif not loja_encontrada:
        geral = STATUS_CNPJ_NAO_CADASTRADO
    elif tem_divergencia:
        geral = STATUS_DIVERGENCIA
    elif any(float(pdf.get("confianca", {}).get(c, 0.0) or 0.0) < confianca_minima for c in ["cnpj", "valor", "vencimento", "codigo"]):
        geral = STATUS_REVISAR
    else:
        geral = STATUS_CONFERE
    return {"status": geral, "linhas": linhas}


def encontrar_match(itens: list[dict], pdf: dict) -> MatchResultado:
    scores = []
    for item in itens:
        score = 0
        if item.get("cnpj") and item.get("cnpj") == pdf.get("cnpj"):
            score += 50
        if item.get("codigo_fatura") and item.get("codigo_fatura") == pdf.get("codigo_fatura"):
            score += 35
        if item.get("operadora") and item.get("operadora") == pdf.get("operadora"):
            score += 10
        if item.get("vencimento") and item.get("vencimento") == pdf.get("vencimento"):
            score += 5
        if score:
            scores.append((score, item["id"]))
    if not scores:
        return MatchResultado(None, STATUS_SEM_CORRESPONDENCIA, 0)
    scores.sort(reverse=True)
    if len(scores) > 1 and scores[0][0] == scores[1][0]:
        return MatchResultado(None, STATUS_REVISAR, scores[0][0])
    return MatchResultado(scores[0][1], STATUS_CONFERE if scores[0][0] >= 50 else STATUS_REVISAR, scores[0][0])


def dumps_comparativo(valor: dict) -> str:
    return json.dumps(valor, ensure_ascii=False)
