from __future__ import annotations

import re
from pathlib import Path

import fitz

from app.services.parsers import selecionar_parser
from app.services.parsers.base import ParserGenerico
from app.services.operator_detector import detectar_operadora
from app.utils.formatadores import (
    OPERADORAS,
    normalizar_cnpj,
    normalizar_data,
    normalizar_operadora,
    normalizar_valor,
)


CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
DATA_RE = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b")
VALOR_RE = re.compile(r"(?:R\$\s*)?\d{1,3}(?:\.\d{3})*,\d{2}\b")
CODIGO_RE = re.compile(
    r"(?:codigo\s+(?:da\s+|do\s+)?(?:fatura|cliente)|cod\.\s*fatura|numero\s+da\s+fatura|n[ºo]\s+da\s+fatura|fatura\s+n[ºo])\s*[:\-]?\s*([A-Za-z0-9.\-\/]+)",
    re.IGNORECASE,
)


def extrair_texto_pdf(caminho_pdf: str | Path) -> str:
    texto = []
    with fitz.open(caminho_pdf) as doc:
        for pagina in doc:
            texto.append(pagina.get_text())
    return "\n".join(texto).strip()


def _candidatos_unicos(valores: list[str]) -> list[str]:
    vistos = set()
    resultado = []
    for valor in valores:
        if valor and valor not in vistos:
            vistos.add(valor)
            resultado.append(valor)
    return resultado


def _proximo_de_rotulo(texto: str, rotulos: list[str], regex: re.Pattern[str]) -> str:
    linhas = texto.splitlines()
    for idx, linha in enumerate(linhas):
        bloco = "\n".join(linhas[idx : idx + 3])
        if any(rotulo.lower() in linha.lower() for rotulo in rotulos):
            achado = regex.search(bloco)
            if achado:
                return achado.group(1) if achado.groups() else achado.group(0)
    achado = regex.search(texto)
    return (achado.group(1) if achado and achado.groups() else achado.group(0)) if achado else ""


def identificar_cnpjs(texto: str) -> list[str]:
    return _candidatos_unicos([normalizar_cnpj(item) for item in CNPJ_RE.findall(texto)])


def identificar_operadora(texto: str) -> str:
    detectada = detectar_operadora(texto)
    return detectada.operadora if detectada.segura else ""


def identificar_vencimento(texto: str) -> str:
    valor = _proximo_de_rotulo(
        texto,
        ["vencimento", "venc.", "data de vencimento", "data vencimento"],
        DATA_RE,
    )
    return normalizar_data(valor)


def identificar_valor(texto: str) -> str:
    valor = _proximo_de_rotulo(
        texto,
        ["total", "valor total", "valor a pagar", "total a pagar", "valor da fatura"],
        VALOR_RE,
    )
    return normalizar_valor(valor)


def identificar_codigo_fatura(texto: str) -> str:
    achado = CODIGO_RE.search(texto)
    return achado.group(1).strip()[:80] if achado else ""


def parsear_texto(texto: str) -> dict:
    operadora = identificar_operadora(texto)
    return selecionar_parser(operadora).parse(texto).as_dict()
