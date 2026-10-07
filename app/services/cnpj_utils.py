from __future__ import annotations

import re

from app.utils.formatadores import formatar_cnpj, normalizar_cnpj, validar_cnpj


LIVE_CNPJ_PREFIX = "35303139"


def extrair_cnpjs(texto: str) -> list[str]:
    """Extrai CNPJs mesmo quando o PDF quebra pontuação/espaços.

    A função é propositalmente conservadora: coleta janelas de 14 dígitos em
    trechos que parecem CNPJ ou que começam pela raiz LIVE!, sem inferir nem
    corrigir dígitos.
    """
    texto = texto or ""
    vistos: set[str] = set()
    resultado: list[str] = []

    # Formatos usuais e variações com espaços/quebras entre os blocos.
    padrao = re.compile(
        r"(?<!\d)(\d{2})[\s./-]*(\d{3})[\s./-]*(\d{3})[\s./-]*(\d{4})[\s./-]*(\d{2})(?!\d)"
    )
    for match in padrao.finditer(texto):
        cnpj = "".join(match.groups())
        contexto = texto[max(0, match.start() - 40) : min(len(texto), match.end() + 40)]
        if (
            "cnpj" not in contexto.lower()
            and not cnpj.startswith(LIVE_CNPJ_PREFIX)
            and not any(sep in match.group(0) for sep in "./-")
        ):
            continue
        if cnpj not in vistos:
            vistos.add(cnpj)
            resultado.append(cnpj)

    # Fallback para sequências contínuas de 14 dígitos próximas de CNPJ ou LIVE!.
    for match in re.finditer(r"(?<!\d)\d{14}(?!\d)", texto):
        cnpj = normalizar_cnpj(match.group(0))
        contexto = texto[max(0, match.start() - 40) : min(len(texto), match.end() + 40)]
        if not cnpj:
            continue
        if "cnpj" not in contexto.lower() and not cnpj.startswith(LIVE_CNPJ_PREFIX):
            continue
        if cnpj not in vistos:
            vistos.add(cnpj)
            resultado.append(cnpj)

    return resultado


def identificar_cnpjs_live(texto: str) -> list[str]:
    return [cnpj for cnpj in extrair_cnpjs(texto) if cnpj.startswith(LIVE_CNPJ_PREFIX)]


def identificar_cnpj_live(texto: str) -> tuple[str, float, str]:
    live = identificar_cnpjs_live(texto)
    if len(live) == 1:
        cnpj = live[0]
        origem = "Identificado pelo prefixo CNPJ LIVE! 35.303.139"
        if validar_cnpj(cnpj):
            return cnpj, 0.99, origem
        return cnpj, 0.70, f"{origem}; dígitos verificadores inválidos"
    if len(live) > 1:
        return "", 0.45, "Mais de um CNPJ LIVE! encontrado no documento"
    return "", 0.0, "CNPJ da loja LIVE! não identificado no documento."


def motivo_cnpj_live_nao_cadastrado(cnpj: str) -> str:
    return f"CNPJ LIVE! identificado, porém não encontrado na base de lojas: {formatar_cnpj(cnpj)}"
