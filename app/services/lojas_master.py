from __future__ import annotations

import base64
import csv
import io
import json
import shutil
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.database import DB_PATH, agora
from app.utils.formatadores import (
    formatar_cnpj,
    nome_exibicao_loja,
    normalizar_cidade,
    normalizar_cnpj,
    normalizar_cnpj_flex,
    normalizar_codigo_loja,
    normalizar_nome_loja,
    normalizar_uf,
    validar_cnpj,
)


STATUS_OK = "OK"
STATUS_CNPJ_PENDENTE = "CNPJ_PENDENTE"
STATUS_CNPJ_INVALIDO = "CNPJ_INVALIDO"
STATUS_UF_PENDENTE = "UF_PENDENTE"
STATUS_INATIVA = "INATIVA"

UF_POR_CIDADE = {
    "SAO PAULO": "SP",
    "SÃO PAULO": "SP",
    "CAMPINAS": "SP",
    "BELO HORIZONTE": "MG",
    "RECIFE": "PE",
    "RIO DE JANEIRO": "RJ",
    "JARAGUA DO SUL": "SC",
    "JARAGUÁ DO SUL": "SC",
    "LONDRINA": "PR",
    "BRASILIA": "DF",
    "BRASÍLIA": "DF",
    "CASCAVEL": "PR",
    "NITEROI": "RJ",
    "NITERÓI": "RJ",
    "FOZ DO IGUACU": "PR",
    "FOZ DO IGUAÇU": "PR",
    "GOIANIA": "GO",
    "GOIÂNIA": "GO",
    "PETROLINA": "PE",
    "MANAUS": "AM",
    "RIBEIRAO PRETO": "SP",
    "RIBEIRÃO PRETO": "SP",
    "BARUERI": "SP",
    "BAURU": "SP",
    "ARMACAO DOS BUZIOS": "RJ",
    "ARMAÇÃO DOS BÚZIOS": "RJ",
    "UBERLANDIA": "MG",
    "UBERLÂNDIA": "MG",
    "ITAJAI": "SC",
    "ITAJAÍ": "SC",
    "CRICIUMA": "SC",
    "CRICIÚMA": "SC",
    "BLUMENAU": "SC",
    "BALNEARIO CAMBORIU": "SC",
    "BALNEÁRIO CAMBORIÚ": "SC",
    "JOINVILLE": "SC",
    "CURITIBA": "PR",
    "ALEXANIA": "GO",
    "ALEXÂNIA": "GO",
    "MORENO": "PE",
    "CAMACARI": "BA",
    "CAMAÇARI": "BA",
    "ATIBAIA": "SP",
    "ITUPEVA": "SP",
    "GUARULHOS": "SP",
    "SAO ROQUE": "SP",
    "SÃO ROQUE": "SP",
    "DUQUE DE CAXIAS": "RJ",
    "CONTAGEM": "MG",
    "PORTO BELO": "SC",
    "CAMPO LARGO": "PR",
    "PORTO FELIZ": "SP",
    "TRANCOSO": "BA",
    "SAO BERNARDO DO CAMPO": "SP",
    "SÃO BERNARDO DO CAMPO": "SP",
    "POMERODE": "SC",
    "NOVA LIMA": "MG",
    "GRAMADO": "RS",
    "ITAQUAQUECETUBA": "SP",
    "FLORIANOPOLIS": "SC",
    "FLORIANÓPOLIS": "SC",
    "CRAVINHOS": "SP",
    "SAO JOSE DOS CAMPOS": "SP",
    "SÃO JOSÉ DOS CAMPOS": "SP",
}


def _sem_acentos(valor: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", valor or "") if not unicodedata.combining(ch)
    )


def _normalizar_cabecalho(valor: str) -> str:
    return normalizar_nome_loja(_sem_acentos(valor)).replace(" ", "_")


@dataclass
class LinhaLoja:
    row_index: int
    codigo_loja: str
    nome: str
    tipo_loja: str
    razao_social: str
    cnpj: str
    cnpj_original: str
    cidade: str
    uf: str
    ativo: int
    status_cadastro: str
    problemas: list[str]

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def cnpj_coluna_permite_null(conn: sqlite3.Connection) -> bool:
    info = conn.execute("PRAGMA table_info(lojas)").fetchall()
    row = next((item for item in info if item["name"] == "cnpj"), None)
    return bool(row and not row["notnull"])


def garantir_schema_lojas(conn: sqlite3.Connection) -> None:
    colunas = {row["name"] if hasattr(row, "keys") else row[1] for row in conn.execute("PRAGMA table_info(lojas)").fetchall()}
    if "razao_social" not in colunas:
        conn.execute("ALTER TABLE lojas ADD COLUMN razao_social TEXT")


def inferir_uf(cidade: str, uf: str = "") -> tuple[str, bool]:
    uf_norm = normalizar_uf(uf)
    if uf_norm:
        return uf_norm, True
    cidade_norm = normalizar_nome_loja(cidade)
    uf_derivada = UF_POR_CIDADE.get(cidade_norm, "")
    return uf_derivada, bool(uf_derivada)


def status_da_linha(cnpj: str, cnpj_original: str, uf: str, ativo: int) -> str:
    if not ativo:
        return STATUS_INATIVA
    if not cnpj_original.strip():
        return STATUS_CNPJ_PENDENTE
    if not cnpj or not validar_cnpj(cnpj):
        return STATUS_CNPJ_INVALIDO
    if not uf:
        return STATUS_UF_PENDENTE
    return STATUS_OK


def normalizar_linha(row_index: int, raw: dict[str, str]) -> LinhaLoja:
    dados = {_normalizar_cabecalho(k): (v or "").strip() for k, v in raw.items()}
    codigo = normalizar_codigo_loja(dados.get("CODIGO_LOJA") or dados.get("CODIGO") or dados.get("CODIGO_L") or "")
    nome = normalizar_nome_loja(dados.get("NOME") or dados.get("UNIDADE") or dados.get("LOJA") or "")
    tipo = (dados.get("TIPO_LOJA") or dados.get("TIPO") or "").strip()
    razao_social = normalizar_nome_loja(dados.get("RAZAO_SOCIAL") or dados.get("RAZÃO_SOCIAL") or "")
    cidade = normalizar_cidade(dados.get("CIDADE") or "")
    uf, _ = inferir_uf(cidade, dados.get("UF") or "")
    cnpj_original = dados.get("CNPJ") or ""
    cnpj_digits = normalizar_cnpj_flex(cnpj_original)
    cnpj = normalizar_cnpj(cnpj_original)
    ativo = 0 if (dados.get("STATUS") or dados.get("STATUS_CADASTRO") or "").upper() in {"INATIVA", "INATIVO"} else 1
    problemas = []
    if not nome:
        problemas.append("Nome/unidade ausente")
    if cnpj_original and len(cnpj_digits) != 14:
        problemas.append("CNPJ com quantidade de digitos invalida")
    if cnpj_original and cnpj and not validar_cnpj(cnpj):
        problemas.append("CNPJ com dígitos verificadores inválidos")
    if not cnpj_original:
        problemas.append("CNPJ ausente")
    if not uf:
        problemas.append("UF pendente")
    return LinhaLoja(
        row_index=row_index,
        codigo_loja=codigo,
        nome=nome,
        tipo_loja=tipo,
        razao_social=razao_social,
        cnpj=cnpj,
        cnpj_original=cnpj_original,
        cidade=cidade,
        uf=uf,
        ativo=ativo,
        status_cadastro=status_da_linha(cnpj, cnpj_original, uf, ativo),
        problemas=problemas,
    )


def ler_csv(conteudo: bytes) -> list[LinhaLoja]:
    texto = conteudo.decode("utf-8-sig")
    sample = texto[:2048]
    dialect = csv.Sniffer().sniff(sample, delimiters=",;	")
    reader = csv.DictReader(io.StringIO(texto), dialect=dialect)
    return [normalizar_linha(i + 1, row) for i, row in enumerate(reader)]


def gerar_preview(conteudo: bytes) -> dict:
    linhas = ler_csv(conteudo)
    cnpjs = [linha.cnpj for linha in linhas if linha.cnpj]
    codigos = [linha.codigo_loja for linha in linhas if linha.codigo_loja]
    cnpj_dup = {item for item, count in Counter(cnpjs).items() if count > 1}
    codigo_dup = {item for item, count in Counter(codigos).items() if count > 1}
    conn = sqlite3.connect(DB_PATH)
    try:
        garantir_schema_lojas(conn)
        conn.row_factory = sqlite3.Row
        existentes_cnpj = {
            row["cnpj"]: row["id"]
            for row in conn.execute("SELECT id, cnpj FROM lojas WHERE cnpj IS NOT NULL AND cnpj != ''")
        }
        existentes_codigo = {
            row["codigo_loja"]: row["id"]
            for row in conn.execute("SELECT id, codigo_loja FROM lojas WHERE codigo_loja IS NOT NULL AND codigo_loja != ''")
        }
        cnpj_nullable = cnpj_coluna_permite_null(conn)
    finally:
        conn.close()

    novas = existentes = atualizacoes = 0
    for linha in linhas:
        if linha.cnpj in cnpj_dup:
            linha.problemas.append("CNPJ duplicado no arquivo")
        if linha.codigo_loja in codigo_dup:
            linha.problemas.append("Código duplicado no arquivo")
        if not linha.cnpj and not cnpj_nullable:
            linha.problemas.append("Banco atual ainda exige CNPJ fisico para novas lojas")
        if linha.cnpj and linha.cnpj in existentes_cnpj:
            existentes += 1
            atualizacoes += 1
        elif linha.codigo_loja and linha.codigo_loja in existentes_codigo:
            existentes += 1
            atualizacoes += 1
        else:
            novas += 1

    resumo = {
        "total_linhas": len(linhas),
        "novas_unidades": novas,
        "unidades_existentes": existentes,
        "atualizacoes": atualizacoes,
        "cnpjs_invalidos": sum(1 for l in linhas if l.status_cadastro == STATUS_CNPJ_INVALIDO),
        "cnpjs_ausentes": sum(1 for l in linhas if l.status_cadastro == STATUS_CNPJ_PENDENTE),
        "codigos_duplicados": len(codigo_dup),
        "cnpjs_duplicados": len(cnpj_dup),
        "uf_pendente": sum(1 for l in linhas if l.status_cadastro == STATUS_UF_PENDENTE or "UF pendente" in l.problemas),
    }
    payload = {"linhas": [linha.as_dict() for linha in linhas], "resumo": resumo}
    payload_b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return {"linhas": linhas, "resumo": resumo, "payload": payload_b64}


def backup_banco() -> Path:
    destino_dir = DB_PATH.parent / "backups"
    destino_dir.mkdir(parents=True, exist_ok=True)
    destino = destino_dir / f"telemiza_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}.db"
    shutil.copy2(DB_PATH, destino)
    return destino


def aplicar_importacao(payload_b64: str) -> dict:
    payload = json.loads(base64.b64decode(payload_b64.encode("ascii")).decode("utf-8"))
    linhas = [LinhaLoja(**linha) for linha in payload["linhas"]]
    backup = backup_banco()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("BEGIN")
        garantir_schema_lojas(conn)
        for linha in linhas:
            if any("duplicado" in problema.lower() for problema in linha.problemas):
                raise ValueError(f"Linha {linha.row_index}: duplicidade no arquivo")
            if not linha.cnpj and not cnpj_coluna_permite_null(conn):
                raise ValueError(f"Linha {linha.row_index}: banco atual exige CNPJ para nova loja")
            existente = None
            if linha.cnpj:
                existente = conn.execute("SELECT id FROM lojas WHERE cnpj = ?", (linha.cnpj,)).fetchone()
            if not existente and linha.codigo_loja:
                existente = conn.execute("SELECT id FROM lojas WHERE codigo_loja = ?", (linha.codigo_loja,)).fetchone()
            if existente:
                conn.execute(
                    """
                    UPDATE lojas SET codigo_loja = ?, nome = ?, tipo_loja = ?, razao_social = ?, cnpj = ?, cidade = ?,
                        uf = ?, ativo = ?, status_cadastro = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        linha.codigo_loja or None,
                        linha.nome,
                        linha.tipo_loja or None,
                        linha.razao_social or None,
                        linha.cnpj or None,
                        linha.cidade or None,
                        linha.uf or None,
                        linha.ativo,
                        linha.status_cadastro,
                        agora(),
                        existente["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO lojas (codigo_loja, nome, tipo_loja, razao_social, cnpj, cidade, uf, ativo, status_cadastro, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        linha.codigo_loja or None,
                        linha.nome,
                        linha.tipo_loja or None,
                        linha.razao_social or None,
                        linha.cnpj or None,
                        linha.cidade or None,
                        linha.uf or None,
                        linha.ativo,
                        linha.status_cadastro,
                        agora(),
                        agora(),
                    ),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {"backup": str(backup), "linhas": len(linhas)}


def exportar_csv() -> str:
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["codigo_loja", "nome", "tipo_loja", "razao_social", "cnpj", "cidade", "uf", "status"])
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT * FROM lojas ORDER BY COALESCE(codigo_loja, ''), nome"):
            writer.writerow(
                [
                    row["codigo_loja"] or "",
                    row["nome"] or "",
                    row["tipo_loja"] or "",
                    row["razao_social"] if "razao_social" in row.keys() and row["razao_social"] else "",
                    formatar_cnpj(row["cnpj"]) if row["cnpj"] else "",
                    row["cidade"] or "",
                    row["uf"] or "",
                    row["status_cadastro"] or (STATUS_OK if row["ativo"] else STATUS_INATIVA),
                ]
            )
    finally:
        conn.close()
    return output.getvalue()


def atualizar_center_norte(conn: sqlite3.Connection) -> None:
    row = conn.execute("SELECT id FROM lojas WHERE cnpj = ?", ("35303139003708",)).fetchone()
    if row:
        conn.execute(
            """
            UPDATE lojas
            SET codigo_loja = 'L164', nome = 'CENTER NORTE', tipo_loja = 'Loja Propria',
                cidade = 'Sao Paulo', uf = 'SP', ativo = 1, status_cadastro = 'OK', updated_at = ?
            WHERE id = ?
            """,
            (agora(), row["id"]),
        )
