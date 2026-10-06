import sqlite3
import struct
import sys

import fastapi
import jinja2
import multipart
import pymupdf
import uvicorn


def status(nome: str, ok: bool, detalhe: str = "") -> None:
    sufixo = f" ({detalhe})" if detalhe else ""
    print(f"{nome:.<25} {'OK' if ok else 'ERRO'}{sufixo}")


def main() -> int:
    verificacoes = [
        ("Python ", sys.version_info >= (3, 10), sys.version.split()[0]),
        ("Python 64-bit ", struct.calcsize("P") * 8 == 64, f"{struct.calcsize('P') * 8} bits"),
        ("SQLite ", bool(sqlite3.sqlite_version), sqlite3.sqlite_version),
        ("FastAPI ", bool(fastapi.__version__), fastapi.__version__),
        ("Uvicorn ", bool(uvicorn.__version__), uvicorn.__version__),
        ("Jinja2 ", bool(jinja2.__version__), jinja2.__version__),
        ("python-multipart ", multipart is not None, "importado"),
        ("PyMuPDF ", pymupdf is not None, "importado"),
    ]
    for nome, ok, detalhe in verificacoes:
        status(nome, ok, detalhe)
    return 0 if all(item[1] for item in verificacoes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
