from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from sqlite3 import Connection, Row

from app.services.cnpj_utils import identificar_cnpj_live, motivo_cnpj_live_nao_cadastrado
from app.utils.formatadores import formatar_cnpj, normalizar_cnpj, validar_cnpj


MATCH_CONFIRMADO = "MATCH_CONFIRMADO"
REVISAR_CONFLITO = "REVISAR_CONFLITO"
REVISAR_LOJA_NAO_CADASTRADA = "REVISAR_LOJA_NAO_CADASTRADA"
REVISAR_CNPJ_NAO_IDENTIFICADO = "REVISAR_CNPJ_NAO_IDENTIFICADO"
REVISAR_BASE_INCONSISTENTE = "REVISAR_BASE_INCONSISTENTE"


def _sem_acentos(valor: str) -> str:
    normalizado = unicodedata.normalize("NFKD", valor or "")
    return "".join(ch for ch in normalizado if not unicodedata.combining(ch))


def _norm(valor: str) -> str:
    return re.sub(r"\s+", " ", _sem_acentos(valor or "").upper()).strip()


@dataclass
class ResolucaoLoja:
    resultado: str
    metodo_identificacao_loja: str
    cnpj_encontrado: str = ""
    loja: Row | None = None
    motivo: str = ""
    validacao_cidade: bool | None = None
    validacao_uf: bool | None = None
    conflitos: list[str] = field(default_factory=list)
    auditoria: dict = field(default_factory=dict)

    @property
    def confirmado(self) -> bool:
        return self.resultado == MATCH_CONFIRMADO and self.loja is not None

    def auditoria_json(self) -> str:
        payload = {
            "metodo_identificacao_loja": self.metodo_identificacao_loja,
            "cnpj_encontrado": formatar_cnpj(self.cnpj_encontrado) if self.cnpj_encontrado else "",
            "loja_id": self.loja["id"] if self.loja else None,
            "codigo_loja": self.loja["codigo_loja"] if self.loja else "",
            "validacao_cidade": self.validacao_cidade,
            "validacao_uf": self.validacao_uf,
            "resultado": self.resultado,
            "conflitos": self.conflitos,
            **self.auditoria,
        }
        return json.dumps(payload, ensure_ascii=False)


def auditar_base_mestre(conn: Connection) -> list[str]:
    problemas: list[str] = []
    duplicados_cnpj = conn.execute(
        """
        SELECT cnpj, COUNT(*) total
        FROM lojas
        WHERE cnpj IS NOT NULL AND cnpj != ''
        GROUP BY cnpj
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for row in duplicados_cnpj:
        problemas.append(f"CNPJ duplicado na base mestre: {formatar_cnpj(row['cnpj'])}")

    duplicados_codigo = conn.execute(
        """
        SELECT codigo_loja, COUNT(*) total
        FROM lojas
        WHERE codigo_loja IS NOT NULL AND codigo_loja != ''
        GROUP BY codigo_loja
        HAVING COUNT(*) > 1
        """
    ).fetchall()
    for row in duplicados_codigo:
        problemas.append(f"Código de loja duplicado na base mestre: {row['codigo_loja']}")

    invalidos = conn.execute(
        """
        SELECT id, codigo_loja, nome, cnpj
        FROM lojas
        WHERE ativo = 1 AND (cnpj IS NULL OR cnpj = '' OR LENGTH(cnpj) != 14)
        """
    ).fetchall()
    for row in invalidos:
        problemas.append(f"Loja ativa sem CNPJ valido na base mestre: {row['codigo_loja'] or row['id']}")
    for row in conn.execute("SELECT id, codigo_loja, cnpj FROM lojas WHERE ativo = 1 AND cnpj IS NOT NULL AND cnpj != ''").fetchall():
        if not validar_cnpj(row["cnpj"]):
            problemas.append(f"Loja ativa com CNPJ invalido na base mestre: {row['codigo_loja'] or row['id']}")
    return problemas


def _validar_secundarios(texto: str, loja: Row) -> tuple[bool | None, bool | None, list[str]]:
    texto_norm = _norm(texto)
    conflitos: list[str] = []

    cidade = _norm(loja["cidade"] if "cidade" in loja.keys() else "")
    uf = _norm(loja["uf"] if "uf" in loja.keys() else "")

    validacao_cidade = None
    validacao_uf = None
    if cidade:
        if cidade in texto_norm:
            validacao_cidade = True
        elif "MUNICIPIO" in texto_norm or "CIDADE" in texto_norm or "ENDERECO" in texto_norm:
            validacao_cidade = False
            conflitos.append(f"Cidade da base ({loja['cidade']}) não encontrada/coerente no documento")

    if uf:
        padrao_uf = re.compile(rf"(?<![A-Z]){re.escape(uf)}(?![A-Z])")
        if padrao_uf.search(texto_norm):
            validacao_uf = True
        elif " UF " in f" {texto_norm} " or "ESTADO" in texto_norm or "ENDERECO" in texto_norm:
            validacao_uf = False
            conflitos.append(f"UF da base ({loja['uf']}) não encontrada/coerente no documento")

    return validacao_cidade, validacao_uf, conflitos


def resolver_loja_por_cnpj_live(conn: Connection, texto: str, cnpj_live: str = "") -> ResolucaoLoja:
    cnpj = normalizar_cnpj(cnpj_live)
    origem = "Informado pelo parser"
    confianca = 0.99 if cnpj else 0.0
    if not cnpj:
        cnpj, confianca, origem = identificar_cnpj_live(texto)

    if not cnpj:
        return ResolucaoLoja(
            resultado=REVISAR_CNPJ_NAO_IDENTIFICADO,
            metodo_identificacao_loja="CNPJ_EXATO",
            motivo="CNPJ da loja LIVE! não identificado no documento.",
            auditoria={"origem_cnpj": origem, "confianca_cnpj": confianca},
        )

    row = conn.execute("SELECT * FROM lojas WHERE cnpj = ? AND ativo = 1", (cnpj,)).fetchone()
    if not row:
        return ResolucaoLoja(
            resultado=REVISAR_LOJA_NAO_CADASTRADA,
            metodo_identificacao_loja="CNPJ_EXATO",
            cnpj_encontrado=cnpj,
            motivo=motivo_cnpj_live_nao_cadastrado(cnpj),
            auditoria={"origem_cnpj": origem, "confianca_cnpj": confianca},
        )

    if not validar_cnpj(row["cnpj"]):
        return ResolucaoLoja(
            resultado=REVISAR_BASE_INCONSISTENTE,
            metodo_identificacao_loja="CNPJ_EXATO",
            cnpj_encontrado=cnpj,
            loja=row,
            motivo=f"Registro da base mestre possui CNPJ invalido: {formatar_cnpj(cnpj)}",
            auditoria={"origem_cnpj": origem, "confianca_cnpj": confianca},
        )

    validacao_cidade, validacao_uf, conflitos = _validar_secundarios(texto, row)
    if conflitos:
        return ResolucaoLoja(
            resultado=REVISAR_CONFLITO,
            metodo_identificacao_loja="CNPJ_EXATO",
            cnpj_encontrado=cnpj,
            loja=row,
            motivo="CNPJ LIVE! encontrado na base, mas há conflito em dado secundário.",
            validacao_cidade=validacao_cidade,
            validacao_uf=validacao_uf,
            conflitos=conflitos,
            auditoria={"origem_cnpj": origem, "confianca_cnpj": confianca},
        )

    return ResolucaoLoja(
        resultado=MATCH_CONFIRMADO,
        metodo_identificacao_loja="CNPJ_EXATO",
        cnpj_encontrado=cnpj,
        loja=row,
        motivo="Match exato pelo CNPJ completo da LIVE!",
        validacao_cidade=validacao_cidade,
        validacao_uf=validacao_uf,
        auditoria={"origem_cnpj": origem, "confianca_cnpj": confianca},
    )
