from __future__ import annotations

import re
import unicodedata
from sqlite3 import Connection

from app.services.store_resolver import MATCH_CONFIRMADO, ResolucaoLoja
from app.utils.formatadores import formatar_cnpj, normalizar_cnpj


def _sem_acentos(valor: str) -> str:
    normalizado = unicodedata.normalize("NFKD", valor or "")
    return "".join(ch for ch in normalizado if not unicodedata.combining(ch))


def _norm(valor: str) -> str:
    return re.sub(r"\s+", " ", _sem_acentos(valor or "").upper()).strip()


def _tem(texto_norm: str, *termos: str) -> bool:
    return all(_norm(termo) in texto_norm for termo in termos)


def _buscar_por_codigo(conn: Connection, codigo: str):
    return conn.execute("SELECT * FROM lojas WHERE codigo_loja = ? AND ativo = 1", (codigo,)).fetchone()


def resolver_loja_por_dados_documento(conn: Connection, texto: str, cnpj_live: str = "", motivo_original: str = "") -> ResolucaoLoja | None:
    """Resolve loja por sinais fortes do documento quando CNPJ exato da base falha.

    Esta camada só confirma quando os dados extraídos apontam para uma unidade única e
    conhecida. Ela não faz aproximação por CNPJ parecido nem por "primeira loja".
    """
    texto_norm = _norm(texto)
    cnpj = normalizar_cnpj(cnpj_live)
    regras = [
        {
            "codigo": "L320",
            "nome": "CASCAVEL SHOPP CATUAI",
            "sinais": [
                lambda t: _tem(t, "CASCAVEL", "CATUAI"),
                lambda t: _tem(t, "SHOPPING CASCAVEL CATUAI"),
                lambda t: _tem(t, "LOJA LUC 3019", "CASCAVEL"),
            ],
        },
        {
            "codigo": "L341",
            "nome": "SJC SHOPP VALE SUL",
            "sinais": [
                lambda t: _tem(t, "SHOPPING VALE SUL"),
                lambda t: _tem(t, "VALE SUL", "SAO JOSE DOS CAMPOS"),
                lambda t: _tem(t, "AVENIDA ANDROMEDA", "SAO JOSE DOS CAMPOS"),
            ],
        },
        {
            "codigo": "L393",
            "nome": "BOA VISTA VILLAGE",
            "sinais": [
                lambda t: _tem(t, "BOA VISTA VILLAGE", "PORTO FELIZ"),
                lambda t: _tem(t, "COND BOA VISTA VILLAGE"),
                lambda t: _tem(t, "RODOVIA CASTELO BRANCO", "BOA VISTA VILLAGE"),
            ],
        },
        {
            "codigo": "L380",
            "nome": "VITORIA SHOPP",
            "sinais": [
                lambda t: _tem(t, "AV AMERICO BUAIZ", "VITORIA"),
                lambda t: _tem(t, "ENSEADA DO SUA", "VITORIA"),
                lambda t: _tem(t, "VITORIA", "29050-420"),
            ],
        },
        {
            "codigo": "L381",
            "nome": "CAMPINA GRANDE SHOPP PARTAGE",
            "sinais": [
                lambda t: _tem(t, "CAMPINA GRANDE", "CATOL"),
                lambda t: _tem(t, "PREFEITO SEVERINO BEZERRA CABRAL", "CAMPINA GRANDE"),
                lambda t: _tem(t, "SHOPPING PARTAGE", "CAMPINA GRANDE"),
            ],
        },
        {
            "codigo": "L447",
            "nome": "SJC SHOPP CENTER VALE",
            "sinais": [
                lambda t: _tem(t, "CENTER VALE", "SAO JOSE DOS CAMPOS"),
                lambda t: _tem(t, "DEP BENEDITO MATARAZZO", "LJ M137"),
                lambda t: _tem(t, "JARDIM OSWALDO CRUZ", "SAO JOSE DOS CAMPOS"),
            ],
        },
    ]

    candidatos = []
    for regra in regras:
        if any(sinal(texto_norm) for sinal in regra["sinais"]):
            loja = _buscar_por_codigo(conn, regra["codigo"])
            if loja:
                candidatos.append((regra, loja))

    codigos = {loja["codigo_loja"] for _, loja in candidatos}
    if len(codigos) != 1:
        return None

    regra, loja = candidatos[0]
    observacoes_base = []
    if cnpj and loja["cnpj"] and cnpj != loja["cnpj"]:
        observacoes_base.append(
            f"Nota real informa {formatar_cnpj(cnpj)} para {regra['nome']}; cadastro atual da unidade registra {formatar_cnpj(loja['cnpj'])}."
        )
    if motivo_original:
        observacoes_base.append(f"Regra primária por base mestre não confirmou: {motivo_original}")

    return ResolucaoLoja(
        resultado=MATCH_CONFIRMADO,
        metodo_identificacao_loja="DADOS_DOCUMENTO_UNICO",
        cnpj_encontrado=cnpj,
        loja=loja,
        motivo=f"Loja confirmada por dados fortes do documento: {regra['nome']}",
        validacao_cidade=True,
        validacao_uf=True,
        auditoria={
            "origem_cnpj": "CNPJ informado no documento" if cnpj else "CNPJ LIVE! nao identificado",
            "confianca_cnpj": 0.99 if cnpj else 0.0,
            "sinais_identificacao_loja": regra["nome"],
            "observacao": "Nota real prevaleceu por unidade/endereco extraidos do documento.",
            "observacoes_base": observacoes_base,
        },
    )
