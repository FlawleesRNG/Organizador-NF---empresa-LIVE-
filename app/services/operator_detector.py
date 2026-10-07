from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.utils.formatadores import OPERADORA_ALIASES, normalizar_operadora


@dataclass(frozen=True)
class OperadoraDetectada:
    operadora: str
    confianca: float
    nivel: str
    regra: str
    alias: str = ""
    razao_social_detectada: str = ""

    @property
    def segura(self) -> bool:
        return self.confianca >= 0.80


def _sem_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto or "")
    return "".join(ch for ch in normalizado if not unicodedata.combining(ch))


def _normalizar_busca(texto: str) -> str:
    return _sem_acentos(texto).upper()


def _nivel(score: float) -> str:
    if score >= 0.90:
        return "ALTA"
    if score >= 0.80:
        return "MEDIA"
    if score > 0:
        return "BAIXA"
    return "NAO_IDENTIFICADA"


def _candidatos(texto: str, origem: str, peso: float) -> list[OperadoraDetectada]:
    texto_norm = _normalizar_busca(texto)
    candidatos: list[OperadoraDetectada] = []
    for canonica, aliases in OPERADORA_ALIASES.items():
        for alias in aliases:
            alias_norm = _normalizar_busca(alias)
            if not alias_norm or len(alias_norm) < 3:
                continue
            if re.search(rf"(?<![A-Z0-9]){re.escape(alias_norm)}(?![A-Z0-9])", texto_norm):
                score = min(0.99, peso + min(len(alias_norm) / 100, 0.08))
                candidatos.append(
                    OperadoraDetectada(
                        operadora=normalizar_operadora(canonica),
                        confianca=score,
                        nivel=_nivel(score),
                        regra=f"Alias confiavel encontrado no {origem}",
                        alias=alias,
                        razao_social_detectada=alias,
                    )
                )
    return candidatos


def detectar_operadora(texto: str, nome_arquivo: str = "") -> OperadoraDetectada:
    """Detecta operadora sem depender de palavra genérica como 'telecom'.

    Conteúdo do PDF tem prioridade sobre nome do arquivo. O nome do arquivo só
    desempata quando o conteúdo não identifica nada com segurança ou quando os
    dois sinais apontam para a mesma operadora/alias.
    """
    candidatos = _candidatos(texto, "conteudo do PDF", 0.90)
    candidatos += _candidatos(nome_arquivo, "nome do arquivo", 0.78)
    if not candidatos:
        return OperadoraDetectada("", 0.0, "NAO_IDENTIFICADA", "Operadora não identificada com segurança")

    por_operadora: dict[str, OperadoraDetectada] = {}
    for candidato in candidatos:
        existente = por_operadora.get(candidato.operadora)
        if not existente or candidato.confianca > existente.confianca:
            por_operadora[candidato.operadora] = candidato

    ordenados = sorted(por_operadora.values(), key=lambda item: item.confianca, reverse=True)
    melhor = ordenados[0]
    # Casos atuais da base: alguns documentos comerciais BLUE trazem VOZIO como
    # razão social no PDF. Só consolidamos em BLUE quando há sinal explícito de
    # BLUE no nome do arquivo e VOZIO no conteúdo; VOZIO isolado continua VOZIO.
    if melhor.operadora == "VOZIO" and any(c.operadora == "BLUE" for c in candidatos):
        blue = next(c for c in candidatos if c.operadora == "BLUE")
        return OperadoraDetectada(
            "BLUE",
            min(0.92, max(melhor.confianca, blue.confianca) + 0.01),
            "ALTA",
            "Alias comercial BLUE com razao social VOZIO detectada",
            alias="BLUE/VOZIO",
            razao_social_detectada=melhor.razao_social_detectada,
        )
    if len(ordenados) > 1 and melhor.confianca - ordenados[1].confianca < 0.08:
        return OperadoraDetectada(
            "",
            0.45,
            "BAIXA",
            f"Operadora ambigua: {melhor.operadora} e {ordenados[1].operadora}",
        )
    return melhor
