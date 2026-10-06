from pathlib import Path

import fitz


def criar_pdf_teste(destino: str | Path, cnpj: str = "35.303.139/0037-08") -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    pagina = doc.new_page()
    texto = f"""VIVO

CNPJ:
{cnpj}

Vencimento:
20/08/2026

Valor Total:
R$ 389,90

Codigo da Fatura:
899929200608
"""
    pagina.insert_text((72, 72), texto, fontsize=12)
    doc.save(destino)
    doc.close()
    return destino


if __name__ == "__main__":
    print(criar_pdf_teste(Path(__file__).parent / "fatura_vivo_teste.pdf"))
