from __future__ import annotations

import sqlite3
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from tests.gerar_pdf_teste import criar_pdf_teste


DB = BASE / "data" / "telemiza.db"
URL = "http://127.0.0.1:8000"


def upload_pdf(pdf: Path, filename: str) -> bytes:
    boundary = "----ShaBoundary"
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="arquivo"; filename="{filename}"\r\n'.encode(),
            b"Content-Type: application/pdf\r\n\r\n",
            pdf.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    req = urllib.request.Request(
        URL + "/faturas/upload",
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return urllib.request.urlopen(req, timeout=10).read()


def main() -> int:
    pdf = BASE / "tests" / "tmp_sha_web_teste.pdf"
    criar_pdf_teste(pdf, "12.345.678/0001-95")
    conn = sqlite3.connect(DB)
    try:
        before = conn.execute("SELECT COUNT(*) FROM faturas").fetchone()[0]
        upload_pdf(pdf, "tmp_sha_web_teste.pdf")
        mid = conn.execute("SELECT COUNT(*) FROM faturas").fetchone()[0]
        upload_pdf(pdf, "tmp_sha_web_teste.pdf")
        after = conn.execute("SELECT COUNT(*) FROM faturas").fetchone()[0]
        print("Criacao:", "OK" if mid == before + 1 else "ERRO")
        print("Duplicado SHA:", "OK" if after == mid else "ERRO")
        rows = conn.execute(
            "SELECT id, caminho_final FROM faturas WHERE arquivo_original = 'tmp_sha_web_teste.pdf'"
        ).fetchall()
        for _id, caminho in rows:
            p = Path(caminho)
            if p.exists() and (BASE / "data").resolve() in p.resolve().parents:
                p.unlink()
        conn.execute("DELETE FROM faturas WHERE arquivo_original = 'tmp_sha_web_teste.pdf'")
        conn.commit()
    finally:
        conn.close()
        if pdf.exists():
            pdf.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
