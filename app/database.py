from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "telemiza.db"


def agora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@contextmanager
def conectar() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with conectar() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS lojas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cnpj TEXT,
                nome TEXT NOT NULL,
                uf TEXT NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        _migrar_lojas_cnpj_nullable(conn)
        _migrar_colunas_lojas(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS faturas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                arquivo_original TEXT NOT NULL,
                arquivo_final TEXT,
                caminho_final TEXT,
                cnpj TEXT,
                loja_id INTEGER,
                operadora TEXT,
                valor REAL,
                vencimento TEXT,
                codigo_fatura TEXT,
                status TEXT NOT NULL,
                motivo_revisao TEXT,
                texto_extraido TEXT,
                email_message_id TEXT,
                email_attachment_id TEXT,
                email_remetente TEXT,
                email_assunto TEXT,
                email_data TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (loja_id) REFERENCES lojas(id)
            )
            """
        )
        _migrar_colunas_faturas(conn)


def _migrar_colunas_lojas(conn: sqlite3.Connection) -> None:
    colunas = {row["name"] for row in conn.execute("PRAGMA table_info(lojas)").fetchall()}
    novas_colunas = {
        "codigo_loja": "TEXT",
        "tipo_loja": "TEXT",
        "cidade": "TEXT",
        "razao_social": "TEXT",
        "status_cadastro": "TEXT NOT NULL DEFAULT 'OK'",
    }
    for nome, tipo in novas_colunas.items():
        if nome not in colunas:
            conn.execute(f"ALTER TABLE lojas ADD COLUMN {nome} {tipo}")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_lojas_codigo ON lojas(codigo_loja) WHERE codigo_loja IS NOT NULL AND codigo_loja != ''")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_lojas_cnpj ON lojas(cnpj) WHERE cnpj IS NOT NULL AND cnpj != ''")


def _migrar_lojas_cnpj_nullable(conn: sqlite3.Connection) -> None:
    colunas_info = conn.execute("PRAGMA table_info(lojas)").fetchall()
    cnpj_info = next((row for row in colunas_info if row["name"] == "cnpj"), None)
    if not cnpj_info or not cnpj_info["notnull"]:
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    conn.execute("ALTER TABLE lojas RENAME TO lojas_old")
    conn.execute(
        """
        CREATE TABLE lojas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cnpj TEXT,
            nome TEXT NOT NULL,
            uf TEXT NOT NULL,
            ativo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            codigo_loja TEXT,
            tipo_loja TEXT,
            cidade TEXT,
            razao_social TEXT,
            status_cadastro TEXT NOT NULL DEFAULT 'OK'
        )
        """
    )
    colunas_antigas = {row["name"] for row in colunas_info}

    def coluna(nome: str, padrao: str = "NULL") -> str:
        return nome if nome in colunas_antigas else padrao

    conn.execute(
        f"""
        INSERT INTO lojas (
            id, cnpj, nome, uf, ativo, created_at, updated_at,
            codigo_loja, tipo_loja, cidade, razao_social, status_cadastro
        )
        SELECT
            id, cnpj, nome, uf, ativo, created_at, updated_at,
            {coluna('codigo_loja')}, {coluna('tipo_loja')}, {coluna('cidade')},
            {coluna('razao_social')}, {coluna('status_cadastro', "'OK'")}
        FROM lojas_old
        """
    )
    conn.execute("DROP TABLE lojas_old")
    conn.commit()
    conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute("PRAGMA foreign_keys = ON")


def _migrar_colunas_faturas(conn: sqlite3.Connection) -> None:
    _migrar_fk_faturas_lojas(conn)
    colunas = {row["name"] for row in conn.execute("PRAGMA table_info(faturas)").fetchall()}
    novas_colunas = {
        "sha256": "TEXT",
        "registro_principal_id": "INTEGER",
        "ativo_historico": "INTEGER NOT NULL DEFAULT 1",
        "parser_utilizado": "TEXT",
        "confianca_cnpj": "REAL",
        "confianca_valor": "REAL",
        "confianca_vencimento": "REAL",
        "confianca_codigo": "REAL",
        "origem_cnpj": "TEXT",
        "origem_valor": "TEXT",
        "origem_vencimento": "TEXT",
        "origem_codigo": "TEXT",
        "origem_operadora": "TEXT",
        "confianca_operadora": "REAL",
        "metodo_identificacao_loja": "TEXT",
        "cnpj_live_identificado": "TEXT",
        "validacao_cidade": "INTEGER",
        "validacao_uf": "INTEGER",
        "resultado_identificacao_loja": "TEXT",
        "auditoria_loja_json": "TEXT",
        "razao_social": "TEXT",
        "referencia": "TEXT",
        "codigo_cliente": "TEXT",
        "numero_fatura": "TEXT",
        "cnpj_fornecedor": "TEXT",
        "outros_cnpjs": "TEXT",
        "item_email_id": "INTEGER",
        "nome_loja": "TEXT",
        "uf_loja": "TEXT",
        "nome_arquivo_sugerido": "TEXT",
        "comparativo_status": "TEXT",
        "comparativo_json": "TEXT",
        "avisos_parser": "TEXT",
    }
    for nome, tipo in novas_colunas.items():
        if nome not in colunas:
            conn.execute(f"ALTER TABLE faturas ADD COLUMN {nome} {tipo}")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_faturas_sha256_ativo
        ON faturas(sha256)
        WHERE sha256 IS NOT NULL AND sha256 != '' AND ativo_historico = 1
        """
    )
    _criar_tabelas_email(conn)


def _migrar_fk_faturas_lojas(conn: sqlite3.Connection) -> None:
    tabelas_fk = {row["table"] for row in conn.execute("PRAGMA foreign_key_list(faturas)").fetchall()}
    if "lojas_old" not in tabelas_fk:
        return

    row_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'faturas'").fetchone()
    if not row_sql or not row_sql["sql"]:
        return
    sql_novo = row_sql["sql"].replace("CREATE TABLE faturas", "CREATE TABLE faturas_new", 1)
    sql_novo = sql_novo.replace('REFERENCES "lojas_old"', "REFERENCES lojas")
    sql_novo = sql_novo.replace("REFERENCES lojas_old", "REFERENCES lojas")
    colunas = [row["name"] for row in conn.execute("PRAGMA table_info(faturas)").fetchall()]
    lista_colunas = ", ".join(colunas)

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(sql_novo)
    conn.execute(f"INSERT INTO faturas_new ({lista_colunas}) SELECT {lista_colunas} FROM faturas")
    conn.execute("DROP TABLE faturas")
    conn.execute("ALTER TABLE faturas_new RENAME TO faturas")
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def _criar_tabelas_email(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mensagens_email (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT NOT NULL UNIQUE,
            remetente TEXT,
            assunto TEXT,
            data_recebimento TEXT,
            processada_em TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS itens_email (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mensagem_id INTEGER NOT NULL,
            row_index INTEGER NOT NULL,
            razao_social TEXT,
            cnpj TEXT,
            cliente TEXT,
            unidade_email TEXT,
            operadora TEXT,
            vencimento TEXT,
            referencia TEXT,
            codigo_fatura TEXT,
            tipo TEXT,
            servico TEXT,
            interface TEXT,
            acesso_banda TEXT,
            liberacao TEXT,
            dados_originais TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(mensagem_id, row_index),
            FOREIGN KEY (mensagem_id) REFERENCES mensagens_email(id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS anexos_email (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mensagem_id INTEGER NOT NULL,
            attachment_id TEXT NOT NULL,
            nome_original TEXT NOT NULL,
            sha256 TEXT,
            caminho_original TEXT,
            fatura_id INTEGER,
            created_at TEXT NOT NULL,
            UNIQUE(mensagem_id, attachment_id),
            FOREIGN KEY (mensagem_id) REFERENCES mensagens_email(id),
            FOREIGN KEY (fatura_id) REFERENCES faturas(id)
        )
        """
    )


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row else None
