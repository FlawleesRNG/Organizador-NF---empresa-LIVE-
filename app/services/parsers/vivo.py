from __future__ import annotations

import re

from app.services.parsers.base import CNPJ_RE, ParserGenerico, identificar_cnpjs_live, limpar_linhas, sem_acentos
from app.utils.formatadores import formatar_cnpj, normalizar_cnpj, normalizar_valor, validar_cnpj


class ParserVivo(ParserGenerico):
    nome = "vivo"

    def escolher_cnpj(self, texto: str) -> tuple[str, float, str]:
        live = identificar_cnpjs_live(texto)
        if len(live) == 1:
            return live[0], 0.99, "Identificado pelo prefixo CNPJ LIVE! 35.303.139"
        if len(live) > 1:
            return "", 0.45, "Mais de um CNPJ LIVE! encontrado no documento"
        candidatos = []
        linhas = limpar_linhas(texto)
        for idx, linha in enumerate(linhas):
            for match in CNPJ_RE.finditer(linha):
                cnpj = normalizar_cnpj(match.group(0))
                contexto = sem_acentos(" ".join(linhas[max(0, idx - 3) : idx + 3])).lower()
                score = 0.45
                origem = "Encontrado por padrao de CNPJ"
                if "razao social" in contexto or "cpf/cnpj" in contexto or "nome do cliente" in contexto:
                    score = 0.97
                    origem = "Encontrado no bloco de cliente/CPF-CNPJ"
                if "telefonica brasil" in contexto or "cnpj matriz" in contexto or "cnpj emitente" in contexto or "empresa prestadora" in contexto:
                    score -= 0.35
                    origem = "Encontrado em area da prestadora/emitente"
                if not validar_cnpj(cnpj):
                    score = min(score, 0.55)
                    origem += "; digitos verificadores invalidos"
                candidatos.append((cnpj, max(0.0, min(1.0, score)), origem))
        candidatos.sort(key=lambda item: item[1], reverse=True)
        return candidatos[0] if candidatos else ("", 0.0, "CNPJ do cliente nao encontrado")

    def parse(self, texto: str):
        resultado = super().parse(texto)
        resultado.operadora = "VIVO"
        resultado.parser_utilizado = self.nome
        resultado.cnpj_formatado = formatar_cnpj(resultado.cnpj)
        return resultado

    def identificar_codigo_fatura(self, texto: str) -> tuple[str, float, str]:
        texto_norm = sem_acentos(texto)
        conta = re.search(r"numero\s+da\s+conta\s*:?\s*([0-9]{10,14})", texto_norm, re.IGNORECASE)
        if conta:
            return conta.group(1), 0.96, 'Encontrado proximo de "Numero da Conta"'
        return super().identificar_codigo_fatura(texto)

    def identificar_valor(self, texto: str) -> tuple[str, float, str]:
        valor, conf, origem = self._campo_por_rotulo(
            texto,
            ["valor total", "total a pagar", "valor a pagar", "valor da fatura"],
            re.compile(r"(?:R\$\s*)?\d{1,3}(?:\.\d{3})*,\d{2}\b"),
        )
        if valor:
            return normalizar_valor(valor), max(conf, 0.94), origem
        return super().identificar_valor(texto)
