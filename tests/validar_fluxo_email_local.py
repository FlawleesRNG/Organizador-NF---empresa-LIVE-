from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import fitz

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.database import DB_PATH, init_db
from app.services.email_sync import processar_anexo, upsert_mensagem
from app.services.microsoft_graph import GraphAttachment, GraphMessage


MESSAGE_ID = "local-test-message-prompt3"
ATTACHMENT_ID = "local-test-attachment-vivo"


def criar_pdf_unifique(destino: Path) -> None:
    texto = """Empresa Ficticia Ltda
Unifique Telecomunicacoes S/A
CNPJ: 12.345.678/0001-95
CNPJ: 11.222.333/0001-81
Codigo do cliente: 36264
CNPJ da Matriz: 11.222.333/0001-81
Periodo de cobranca
Codigo de cobranca
Vencimento
Valor
01/07/2026 - 31/07/2026
57144230
25/08/2026
R$ 189,90
Descritivo
Circuito
FIBRA EMPRESARIAL
04794627001
01/07/2026 - 31/07/2026
R$ 189,90
Beneficiario
UNIFIQUE TELECOMUNICACOES S/A
CNPJ: 11.222.333/0001-81
"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), texto, fontsize=12)
    doc.save(destino)
    doc.close()


def criar_pdf_vivo(destino: Path) -> None:
    texto = """VIVO
Nome do Cliente
EMPRESA TESTE LTDA
CPF/CNPJ: 35.303.139/0037-08
Numero da Conta: 899929200608
VENCIMENTO
20/08/2026
TOTAL A PAGAR
R$ 151,01
"""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), texto, fontsize=12)
    doc.save(destino)
    doc.close()


def limpar() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        msg = conn.execute("SELECT id FROM mensagens_email WHERE message_id = ?", (MESSAGE_ID,)).fetchone()
        if msg:
            rows = conn.execute("SELECT caminho_original FROM anexos_email WHERE mensagem_id = ?", (msg["id"],)).fetchall()
            for row in rows:
                p = Path(row["caminho_original"] or "")
                if p.exists() and (BASE / "data").resolve() in p.resolve().parents:
                    p.unlink()
            conn.execute("DELETE FROM faturas WHERE email_message_id = ?", (MESSAGE_ID,))
            conn.execute("DELETE FROM anexos_email WHERE mensagem_id = ?", (msg["id"],))
            conn.execute("DELETE FROM itens_email WHERE mensagem_id = ?", (msg["id"],))
            conn.execute("DELETE FROM mensagens_email WHERE id = ?", (msg["id"],))
            conn.commit()
    finally:
        conn.close()


def main() -> int:
    init_db()
    limpar()
    html = """
    <table>
      <tr><th>CNPJ</th><th>Operadora</th><th>Vencimento</th><th>Conta</th></tr>
      <tr><td>35.303.139/0037-08</td><td>VIVO</td><td>20/08/2026</td><td>899929200608</td></tr>
    </table>
    """
    message = GraphMessage(
        id=MESSAGE_ID,
        subject="TESTE LOCAL - FATURAS TELEMIZA",
        sender="faturas@telemiza.com.br",
        received_at="2026-08-14T09:42:00Z",
        body_html=html,
        has_attachments=True,
    )
    from app.services.telemiza_email_parser import parsear_email_telemiza

    mensagem_id = upsert_mensagem(message, parsear_email_telemiza(html))
    pdf = BASE / "tests" / "tmp_email_fluxo_vivo.pdf"
    criar_pdf_vivo(pdf)
    attachment = GraphAttachment(
        id=ATTACHMENT_ID,
        name="tmp_email_fluxo_vivo.pdf",
        content_type="application/pdf",
        content_bytes=pdf.read_bytes(),
    )
    fatura_id = processar_anexo(mensagem_id, message, attachment)
    fatura_id_2 = processar_anexo(mensagem_id, message, attachment)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT comparativo_status, loja_id, email_message_id FROM faturas WHERE id = ?",
            (fatura_id,),
        ).fetchone()
        total = conn.execute("SELECT COUNT(*) total FROM faturas WHERE email_message_id = ?", (MESSAGE_ID,)).fetchone()["total"]
        print("Fluxo email-pdf-loja-comparativo:", "OK" if row and row["comparativo_status"] == "CONFERE" and row["loja_id"] else "ERRO")
        print("Idempotencia:", "OK" if fatura_id == fatura_id_2 and total == 1 else "ERRO")
    finally:
        conn.close()
        if pdf.exists():
            pdf.unlink()
        limpar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
