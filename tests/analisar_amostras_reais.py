from __future__ import annotations

from pathlib import Path
import sys


BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app.services.manutencao import sha256_arquivo
from app.services.pdf_parser import extrair_texto_pdf, parsear_texto


AMOSTRAS = BASE / "tests" / "amostras_reais"
RELATORIO = BASE / "tests" / "relatorio_parser_amostras_reais.txt"


def main() -> int:
    AMOSTRAS.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(AMOSTRAS.glob("*.pdf"))
    linhas = [
        "RELATORIO TECNICO - PARSER DE AMOSTRAS REAIS",
        "",
        f"Pasta: {AMOSTRAS}",
        f"PDFs encontrados: {len(pdfs)}",
        "",
    ]
    if not pdfs:
        linhas.append("Nenhum PDF real encontrado para analise nesta rodada.")
    for pdf in pdfs:
        texto = extrair_texto_pdf(pdf)
        dados = parsear_texto(texto)
        confianca = dados.get("confianca", {})
        linhas.extend(
            [
                "----------------------------------------",
                f"Arquivo: {pdf.name}",
                f"SHA-256: {sha256_arquivo(pdf)}",
                f"Operadora: {dados.get('operadora') or 'NAO IDENTIFICADA'}",
                f"CNPJ cliente: {dados.get('cnpj_formatado') or dados.get('cnpj') or 'NAO IDENTIFICADO'}",
                f"CNPJ fornecedor: {dados.get('cnpj_fornecedor') or 'NAO IDENTIFICADO'}",
                f"Valor: {dados.get('valor') or 'NAO IDENTIFICADO'}",
                f"Vencimento: {dados.get('vencimento') or 'NAO IDENTIFICADO'}",
                f"Codigo cliente: {dados.get('codigo_cliente') or 'NAO IDENTIFICADO'}",
                f"Codigo fatura/conta: {dados.get('codigo_fatura') or 'NAO IDENTIFICADO'}",
                f"Numero fatura/cobranca: {dados.get('numero_fatura') or 'NAO IDENTIFICADO'}",
                f"Parser utilizado: {dados.get('parser_utilizado') or 'generico'}",
                f"Confianca: CNPJ={confianca.get('cnpj', 0):.2f}; Valor={confianca.get('valor', 0):.2f}; Vencimento={confianca.get('vencimento', 0):.2f}; Codigo={confianca.get('codigo', 0):.2f}",
                f"Avisos: {'; '.join(dados.get('avisos', [])) or 'Nenhum'}",
            ]
        )
    RELATORIO.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    print(RELATORIO)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
