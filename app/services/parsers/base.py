from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.utils.formatadores import (
    OPERADORA_ALIASES,
    OPERADORAS,
    formatar_cnpj,
    normalizar_cnpj,
    normalizar_data,
    normalizar_operadora,
    normalizar_valor,
    validar_cnpj,
)
from app.services.cnpj_utils import (
    LIVE_CNPJ_PREFIX,
    extrair_cnpjs,
    identificar_cnpj_live,
    identificar_cnpjs_live,
)
from app.services.operator_detector import detectar_operadora


CNPJ_RE = re.compile(r"(?<!\d)\d{2}[\s./-]*\d{3}[\s./-]*\d{3}[\s./-]*\d{4}[\s./-]*\d{2}(?!\d)")
DATA_RE = re.compile(r"\b\d{2}[/-]\d{2}[/-]\d{4}\b")
VALOR_RE = re.compile(r"(?:R\$\s*)?\d{1,3}(?:\.\d{3})*,\d{2}\b")
CODIGO_RE = re.compile(
    r"(?:codigo\s+(?:da\s+|do\s+)?(?:fatura|cliente)|cod\.\s*fatura|numero\s+da\s+fatura|n[ºo]\s+da\s+fatura|fatura\s+n[ºo]|referencia|identificador|conta)\s*[:\-]?\s*([A-Za-z0-9.\-\/]+)",
    re.IGNORECASE,
)

ROTULOS_CLIENTE = [
    "cliente",
    "razao social",
    "cnpj cliente",
    "cpf/cnpj",
    "tomador",
    "contratante",
    "dados do cliente",
]
ROTULOS_PRESTADOR = ["operadora", "prestador", "emissor", "fornecedor"]


@dataclass
class ResultadoParser:
    operadora: str = ""
    cnpj: str = ""
    cnpj_formatado: str = ""
    cnpj_fornecedor: str = ""
    cnpjs: list[str] = field(default_factory=list)
    outros_cnpjs: list[dict[str, str]] = field(default_factory=list)
    valor: str = ""
    vencimento: str = ""
    codigo_fatura: str = ""
    codigo_cliente: str = ""
    numero_fatura: str = ""
    razao_social: str = ""
    referencia: str = ""
    parser_utilizado: str = "generico"
    confianca: dict[str, float] = field(default_factory=dict)
    origem: dict[str, str] = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "operadora": self.operadora,
            "cnpj": self.cnpj,
            "cnpj_formatado": self.cnpj_formatado,
            "cnpj_fornecedor": self.cnpj_fornecedor,
            "cnpjs": self.cnpjs,
            "outros_cnpjs": self.outros_cnpjs,
            "valor": self.valor,
            "vencimento": self.vencimento,
            "codigo_fatura": self.codigo_fatura,
            "codigo_cliente": self.codigo_cliente,
            "numero_fatura": self.numero_fatura,
            "razao_social": self.razao_social,
            "referencia": self.referencia,
            "parser_utilizado": self.parser_utilizado,
            "confianca": self.confianca,
            "origem": self.origem,
            "avisos": self.avisos,
        }


def sem_acentos(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", texto or "")
    return "".join(ch for ch in normalizado if not unicodedata.combining(ch))


def limpar_linhas(texto: str) -> list[str]:
    return [re.sub(r"\s+", " ", linha).strip() for linha in texto.splitlines() if linha.strip()]


def trecho_ao_redor(texto: str, inicio: int, tamanho: int = 120) -> str:
    ini = max(0, inicio - tamanho)
    fim = min(len(texto), inicio + tamanho)
    return re.sub(r"\s+", " ", texto[ini:fim]).strip()


class ParserGenerico:
    nome = "generico"

    def parse(self, texto: str) -> ResultadoParser:
        resultado = ResultadoParser(parser_utilizado=self.nome)
        resultado.operadora = self.identificar_operadora(texto)
        resultado.cnpjs = self.identificar_cnpjs(texto)
        resultado.cnpj, resultado.confianca["cnpj"], resultado.origem["cnpj"] = self.escolher_cnpj(texto)
        resultado.cnpj_formatado = formatar_cnpj(resultado.cnpj)
        resultado.cnpj_fornecedor = self.identificar_cnpj_fornecedor(texto, resultado.cnpj)
        resultado.outros_cnpjs = self.outros_cnpjs(resultado.cnpjs, resultado.cnpj, resultado.cnpj_fornecedor)
        resultado.valor, resultado.confianca["valor"], resultado.origem["valor"] = self.identificar_valor(texto)
        resultado.vencimento, resultado.confianca["vencimento"], resultado.origem["vencimento"] = self.identificar_vencimento(texto)
        resultado.codigo_fatura, resultado.confianca["codigo"], resultado.origem["codigo"] = self.identificar_codigo_fatura(texto)
        resultado.razao_social = self.identificar_razao_social(texto)
        resultado.referencia = self.identificar_referencia(texto)
        resultado.avisos.extend(self.gerar_avisos(resultado))
        return resultado

    def identificar_cnpjs(self, texto: str) -> list[str]:
        return extrair_cnpjs(texto)

    def outros_cnpjs(self, cnpjs: list[str], cnpj_cliente: str, cnpj_fornecedor: str) -> list[dict[str, str]]:
        outros = []
        for cnpj in cnpjs:
            if cnpj == cnpj_cliente:
                classificacao = "cliente"
            elif cnpj == cnpj_fornecedor:
                classificacao = "provavel fornecedor/operadora"
            else:
                classificacao = "outro CNPJ detectado"
            outros.append({"cnpj": cnpj, "classificacao": classificacao})
        return outros

    def identificar_cnpj_fornecedor(self, texto: str, cnpj_cliente: str = "") -> str:
        candidatos = []
        linhas = texto.splitlines()
        for idx, linha in enumerate(linhas):
            for match in CNPJ_RE.finditer(linha):
                cnpj = normalizar_cnpj(match.group(0))
                if cnpj == cnpj_cliente:
                    continue
                contexto = sem_acentos(" ".join(linhas[max(0, idx - 2) : idx + 3])).lower()
                score = 0.0
                if any(rotulo in contexto for rotulo in ROTULOS_PRESTADOR):
                    score = 0.80
                if "matriz" in contexto or "emitente" in contexto or "beneficiario" in contexto:
                    score = max(score, 0.92)
                if score:
                    candidatos.append((cnpj, score))
        if not candidatos:
            return ""
        candidatos.sort(key=lambda item: item[1], reverse=True)
        return candidatos[0][0]

    def identificar_operadora(self, texto: str) -> str:
        detectada = detectar_operadora(texto)
        return detectada.operadora if detectada.segura else ""

    def escolher_cnpj(self, texto: str) -> tuple[str, float, str]:
        live_cnpj, live_conf, live_origem = identificar_cnpj_live(texto)
        if live_cnpj or live_conf:
            return live_cnpj, live_conf, live_origem
        candidatos = []
        linhas = texto.splitlines()
        for idx, linha in enumerate(linhas):
            for match in CNPJ_RE.finditer(linha):
                cnpj = normalizar_cnpj(match.group(0))
                bloco = " ".join(linhas[max(0, idx - 2) : idx + 3])
                contexto = sem_acentos(bloco).lower()
                score = 0.45
                origem = "Encontrado por padrao de CNPJ"
                if any(rotulo in contexto for rotulo in ROTULOS_CLIENTE):
                    score = 0.92
                    origem = "Encontrado proximo de dados do cliente"
                if any(rotulo in contexto for rotulo in ROTULOS_PRESTADOR):
                    score -= 0.25
                    origem = "Encontrado em area possivelmente ligada ao prestador"
                if not validar_cnpj(cnpj):
                    score = min(score, 0.55)
                    origem += "; digitos verificadores invalidos"
                candidatos.append((cnpj, max(0.0, min(1.0, score)), origem))
        if not candidatos:
            for match in CNPJ_RE.finditer(texto):
                cnpj = normalizar_cnpj(match.group(0))
                origem = "Encontrado por padrao de CNPJ"
                score = 0.45 if validar_cnpj(cnpj) else 0.30
                candidatos.append((cnpj, score, origem))
        if not candidatos:
            return "", 0.0, "CNPJ nao encontrado"
        candidatos.sort(key=lambda item: item[1], reverse=True)
        if len(candidatos) > 1 and candidatos[0][1] == candidatos[1][1]:
            return "", 0.45, "Mais de um CNPJ com confianca semelhante"
        return candidatos[0]

    def _campo_por_rotulo(self, texto: str, rotulos: list[str], regex: re.Pattern[str]) -> tuple[str, float, str]:
        linhas = limpar_linhas(texto)
        for idx, linha in enumerate(linhas):
            linha_norm = sem_acentos(linha).lower()
            if any(rotulo in linha_norm for rotulo in rotulos):
                bloco = " ".join(linhas[idx : idx + 3])
                achado = regex.search(bloco)
                if achado:
                    valor = achado.group(1) if achado.groups() else achado.group(0)
                    return valor, 0.92, f'Encontrado proximo de "{linha[:60]}"'
        achado = regex.search(texto)
        if achado:
            valor = achado.group(1) if achado.groups() else achado.group(0)
            return valor, 0.55, "Encontrado por busca generica"
        return "", 0.0, "Nao encontrado"

    def identificar_vencimento(self, texto: str) -> tuple[str, float, str]:
        valor, conf, origem = self._campo_por_rotulo(
            texto,
            ["vencimento", "venc.", "data de vencimento", "data vencimento"],
            DATA_RE,
        )
        return normalizar_data(valor), conf if valor else 0.0, origem

    def identificar_valor(self, texto: str) -> tuple[str, float, str]:
        valor, conf, origem = self._campo_por_rotulo(
            texto,
            ["valor total", "valor a pagar", "total a pagar", "valor da fatura", "total"],
            VALOR_RE,
        )
        return normalizar_valor(valor), conf if valor else 0.0, origem

    def identificar_codigo_fatura(self, texto: str) -> tuple[str, float, str]:
        valor, conf, origem = self._campo_por_rotulo(
            texto,
            ["codigo da fatura", "codigo fatura", "numero da fatura", "nº da fatura", "fatura nº", "referencia", "identificador"],
            CODIGO_RE,
        )
        return valor.strip()[:80], conf if valor else 0.0, origem

    def identificar_razao_social(self, texto: str) -> str:
        linhas = limpar_linhas(texto)
        for idx, linha in enumerate(linhas):
            if "razao social" in sem_acentos(linha).lower() and idx + 1 < len(linhas):
                return linhas[idx + 1][:120]
        return ""

    def identificar_referencia(self, texto: str) -> str:
        valor, _, _ = self._campo_por_rotulo(texto, ["referencia", "mes referencia"], re.compile(r"([A-Za-z0-9/.-]{4,30})"))
        return valor[:40]

    def gerar_avisos(self, resultado: ResultadoParser) -> list[str]:
        avisos = []
        if resultado.cnpj and not validar_cnpj(resultado.cnpj):
            avisos.append("CNPJ com digitos verificadores invalidos")
        if len(resultado.cnpjs) > 1:
            avisos.append("Mais de um CNPJ encontrado")
        if not resultado.operadora:
            avisos.append("Operadora nao identificada")
        for campo in ["cnpj", "valor", "vencimento", "codigo"]:
            if resultado.confianca.get(campo, 0.0) < 0.80:
                avisos.append(f"Confianca baixa para {campo}")
        return avisos
