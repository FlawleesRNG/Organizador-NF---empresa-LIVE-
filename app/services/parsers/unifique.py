from __future__ import annotations

import re

from app.services.parsers.base import CNPJ_RE, ParserGenerico, ResultadoParser, identificar_cnpjs_live, limpar_linhas, sem_acentos
from app.utils.formatadores import formatar_cnpj, normalizar_cnpj, normalizar_data, normalizar_valor, validar_cnpj


class ParserUnifique(ParserGenerico):
    nome = "unifique"

    def parse(self, texto: str) -> ResultadoParser:
        resultado = super().parse(texto)
        resultado.operadora = "UNIFIQUE"
        resultado.parser_utilizado = self.nome
        resultado.cnpj, resultado.confianca["cnpj"], resultado.origem["cnpj"] = self.escolher_cnpj(texto)
        resultado.cnpj_formatado = formatar_cnpj(resultado.cnpj)
        resultado.cnpj_fornecedor = self.identificar_cnpj_fornecedor(texto, resultado.cnpj)
        resultado.outros_cnpjs = self.outros_cnpjs(resultado.cnpjs, resultado.cnpj, resultado.cnpj_fornecedor)
        resultado.vencimento, resultado.confianca["vencimento"], resultado.origem["vencimento"] = self.identificar_vencimento(texto)
        resultado.valor, resultado.confianca["valor"], resultado.origem["valor"] = self.identificar_valor(texto)
        resultado.codigo_cliente = self.identificar_codigo_cliente(texto)
        resultado.codigo_fatura, resultado.confianca["codigo"], resultado.origem["codigo"] = self.identificar_codigo_fatura(texto)
        resultado.numero_fatura = self.identificar_numero_fatura(texto)
        resultado.avisos = self.gerar_avisos(resultado)
        return resultado

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
                contexto = sem_acentos(" ".join(linhas[max(0, idx - 2) : idx + 3])).lower()
                score = 0.45
                origem = "Encontrado por padrao de CNPJ"
                cnpjs_na_linha = [normalizar_cnpj(item.group(0)) for item in CNPJ_RE.finditer(linha)]
                if "pagador" in contexto:
                    score = 0.97
                    origem = "Encontrado no bloco do pagador/cliente"
                elif "unifique" in contexto and "codigo do cliente" in contexto and cnpjs_na_linha and cnpj == cnpjs_na_linha[0]:
                    score = 0.90
                    origem = "Encontrado no cabecalho antes dos dados da operadora"
                if "cnpj da matriz" in contexto or "beneficiario" in contexto or (
                    "unifique telecomunicacoes" in contexto and not (cnpjs_na_linha and cnpj == cnpjs_na_linha[0])
                ):
                    score -= 0.35
                    origem = "Encontrado em area da operadora/beneficiario"
                if not validar_cnpj(cnpj):
                    score = min(score, 0.55)
                    origem += "; dígitos verificadores inválidos"
                candidatos.append((cnpj, max(0.0, min(1.0, score)), origem))
        candidatos.sort(key=lambda item: item[1], reverse=True)
        if not candidatos:
            return "", 0.0, "CNPJ do cliente não encontrado"
        return candidatos[0]

    def identificar_cnpj_fornecedor(self, texto: str, cnpj_cliente: str = "") -> str:
        linhas = limpar_linhas(texto)
        candidatos = []
        for idx, linha in enumerate(linhas):
            for match in CNPJ_RE.finditer(linha):
                cnpj = normalizar_cnpj(match.group(0))
                if cnpj == cnpj_cliente:
                    continue
                contexto = sem_acentos(" ".join(linhas[max(0, idx - 2) : idx + 3])).lower()
                score = 0.0
                if "beneficiario" in contexto and "unifique" in contexto:
                    score = 0.98
                elif "cnpj da matriz" in contexto:
                    score = 0.95
                elif "unifique telecomunicacoes" in contexto:
                    score = 0.80
                if score:
                    candidatos.append((cnpj, score))
        candidatos.sort(key=lambda item: item[1], reverse=True)
        return candidatos[0][0] if candidatos else ""

    def identificar_vencimento(self, texto: str) -> tuple[str, float, str]:
        linhas = limpar_linhas(texto)
        for idx, linha in enumerate(linhas):
            if sem_acentos(linha).lower() == "vencimento":
                proximas = linhas[idx + 1 : idx + 8]
                for candidata in proximas:
                    if " - " in candidata:
                        continue
                    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", candidata):
                        return normalizar_data(candidata), 0.97, 'Encontrado na coluna "Vencimento"'
        return super().identificar_vencimento(texto)

    def identificar_valor(self, texto: str) -> tuple[str, float, str]:
        linhas = limpar_linhas(texto)
        for idx, linha in enumerate(linhas):
            if sem_acentos(linha).lower() == "valor":
                proximas = linhas[idx + 1 : idx + 8]
                for candidata in proximas:
                    if re.fullmatch(r"R\$\s*\d{1,3}(?:\.\d{3})*,\d{2}", candidata):
                        return normalizar_valor(candidata), 0.96, 'Encontrado na coluna "Valor" do resumo da cobrança'
        return super().identificar_valor(texto)

    def identificar_codigo_cliente(self, texto: str) -> str:
        achado = re.search(r"codigo\s+do\s+cliente\s*:?\s*([0-9]{3,14})", sem_acentos(texto), re.IGNORECASE)
        return achado.group(1) if achado else ""

    def identificar_numero_fatura(self, texto: str) -> str:
        linhas = limpar_linhas(texto)
        for idx, linha in enumerate(linhas):
            if sem_acentos(linha).lower() == "codigo de cobranca":
                for candidata in linhas[idx + 1 : idx + 6]:
                    if re.fullmatch(r"[0-9]{6,14}", candidata):
                        return candidata
        return ""

    def identificar_codigo_fatura(self, texto: str) -> tuple[str, float, str]:
        linhas = limpar_linhas(texto)
        for idx, linha in enumerate(linhas):
            contexto = sem_acentos(" ".join(linhas[max(0, idx - 4) : idx + 2])).lower()
            if "circuito" in contexto and re.fullmatch(r"[0-9]{10,14}", linha):
                return linha, 0.93, 'Encontrado na tabela de servicos, coluna "Circuito"'
        return "", 0.0, "Conta/circuito não encontrado"
