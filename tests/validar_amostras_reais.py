from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.database import DB_PATH, init_db
from app.models import STATUS_ARQUIVADA, STATUS_REVISAR
from app.services.manutencao import sha256_arquivo
from app.services.pdf_parser import extrair_texto_pdf, parsear_texto


AMOSTRAS = BASE / "tests" / "amostras_reais"


def buscar_loja(conn: sqlite3.Connection, cnpj: str):
    return conn.execute("SELECT id, nome, uf FROM lojas WHERE cnpj = ? AND ativo = 1", (cnpj,)).fetchone()


def atualizar_registro(conn: sqlite3.Connection, pdf: Path, dados: dict) -> int | None:
    sha = sha256_arquivo(pdf)
    row = conn.execute(
        "SELECT id, status FROM faturas WHERE sha256 = ? AND ativo_historico = 1 ORDER BY id DESC LIMIT 1",
        (sha,),
    ).fetchone()
    if not row:
        return None

    loja = buscar_loja(conn, dados["cnpj"]) if dados.get("cnpj") else None
    status = row["status"]
    motivos = []
    if dados.get("cnpj") and not loja:
        motivos.append("CNPJ nao cadastrado")
    for campo, minimo in {"cnpj": 0.80, "valor": 0.80, "vencimento": 0.80, "codigo": 0.80}.items():
        if float(dados.get("confianca", {}).get(campo, 0.0) or 0.0) < minimo:
            motivos.append(f"Confianca baixa para {campo}")
    if status != STATUS_ARQUIVADA and motivos:
        status = STATUS_REVISAR

    conn.execute(
        """
        UPDATE faturas SET cnpj = ?, loja_id = ?, operadora = ?, valor = ?, vencimento = ?,
            codigo_fatura = ?, status = ?, motivo_revisao = ?, texto_extraido = ?,
            parser_utilizado = ?, confianca_cnpj = ?, confianca_valor = ?, confianca_vencimento = ?,
            confianca_codigo = ?, origem_cnpj = ?, origem_valor = ?, origem_vencimento = ?,
            origem_codigo = ?, razao_social = ?, referencia = ?, codigo_cliente = ?,
            numero_fatura = ?, cnpj_fornecedor = ?, outros_cnpjs = ?, avisos_parser = ?
        WHERE id = ?
        """,
        (
            dados.get("cnpj", ""),
            loja["id"] if loja else None,
            dados.get("operadora", ""),
            float(dados["valor"]) if dados.get("valor") else None,
            dados.get("vencimento", ""),
            dados.get("codigo_fatura", ""),
            status,
            "; ".join(dict.fromkeys(motivos)),
            dados.get("_texto", "")[:200000],
            dados.get("parser_utilizado", "generico"),
            dados.get("confianca", {}).get("cnpj", 0.0),
            dados.get("confianca", {}).get("valor", 0.0),
            dados.get("confianca", {}).get("vencimento", 0.0),
            dados.get("confianca", {}).get("codigo", 0.0),
            dados.get("origem", {}).get("cnpj", ""),
            dados.get("origem", {}).get("valor", ""),
            dados.get("origem", {}).get("vencimento", ""),
            dados.get("origem", {}).get("codigo", ""),
            dados.get("razao_social", ""),
            dados.get("referencia", ""),
            dados.get("codigo_cliente", ""),
            dados.get("numero_fatura", ""),
            dados.get("cnpj_fornecedor", ""),
            json.dumps(dados.get("outros_cnpjs", []), ensure_ascii=False),
            json.dumps(dados.get("avisos", []), ensure_ascii=False),
            row["id"],
        ),
    )
    return row["id"]


def main() -> int:
    init_db()
    saidas = []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        for pdf in sorted(AMOSTRAS.glob("*.pdf")):
            texto = extrair_texto_pdf(pdf)
            dados = parsear_texto(texto)
            dados["_texto"] = texto
            registro = atualizar_registro(conn, pdf, dados)
            loja = buscar_loja(conn, dados.get("cnpj", "")) if dados.get("cnpj") else None
            saidas.append(
                {
                    "arquivo": pdf.name,
                    "registro": registro,
                    "loja": f"{loja['nome']} - {loja['uf']}" if loja else "CNPJ NAO CADASTRADO",
                    "dados": {k: v for k, v in dados.items() if k != "_texto"},
                }
            )
        conn.commit()
    finally:
        conn.close()
    print(json.dumps(saidas, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
