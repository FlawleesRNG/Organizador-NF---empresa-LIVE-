import shutil
import tempfile
import unittest
from pathlib import Path

from app.database import DATA_DIR
from app.services.arquivamento import caminho_arquivado, proximo_nome_disponivel
from app.services.pdf_parser import parsear_texto
from app.utils.formatadores import (
    formatar_cnpj,
    normalizar_cnpj,
    normalizar_data,
    normalizar_operadora,
    normalizar_valor,
    validar_cnpj,
)


class CoreTests(unittest.TestCase):
    def test_cnpj(self):
        self.assertEqual(normalizar_cnpj("35.303.139/0037-08"), "35303139003708")
        self.assertEqual(formatar_cnpj("35303139003708"), "35.303.139/0037-08")
        self.assertTrue(validar_cnpj("35.303.139/0037-08"))
        self.assertFalse(validar_cnpj("35.303.139/0037-09"))

    def test_valor(self):
        self.assertEqual(normalizar_valor("R$ 389,90"), "389.90")

    def test_data(self):
        self.assertEqual(normalizar_data("20/08/2026"), "2026-08-20")

    def test_operadora(self):
        self.assertEqual(normalizar_operadora("Vivo"), "VIVO")
        self.assertEqual(normalizar_operadora("VIVO"), "VIVO")
        self.assertEqual(normalizar_operadora("vivo"), "VIVO")
        self.assertEqual(normalizar_operadora("Telefonica Brasil"), "VIVO")
        self.assertEqual(normalizar_operadora("CACTA TELECOM"), "CACTA TELECOM")
        self.assertEqual(normalizar_operadora("4B Telecom"), "4B TELECOM")
        self.assertEqual(normalizar_operadora("Sustenta Telecomunicacoes"), "SUSTENTA")
        self.assertEqual(normalizar_operadora("Vozio Comunicacao"), "VOZIO")

    def test_parser_basico(self):
        texto = """
        VIVO
        CNPJ: 35.303.139/0037-08
        Vencimento: 20/08/2026
        Valor Total: R$ 389,90
        Codigo da Fatura: 899929200608
        """
        dados = parsear_texto(texto)
        self.assertEqual(dados["cnpjs"], ["35303139003708"])
        self.assertEqual(dados["operadora"], "VIVO")
        self.assertEqual(dados["valor"], "389.90")
        self.assertEqual(dados["vencimento"], "2026-08-20")
        self.assertEqual(dados["codigo_fatura"], "899929200608")
        self.assertEqual(dados["parser_utilizado"], "vivo")
        self.assertGreaterEqual(dados["confianca"]["valor"], 0.8)

    def test_parser_prioriza_cnpj_do_cliente(self):
        texto = """
        PRESTADOR VIVO
        CNPJ 02.449.992/0001-64

        DADOS DO CLIENTE
        EMPRESA TESTE LTDA
        CPF/CNPJ 35.303.139/0037-08

        Vencimento: 20/08/2026
        Valor Total: R$ 389,90
        Numero da Fatura: 123456789
        """
        dados = parsear_texto(texto)
        self.assertEqual(dados["cnpj"], "35303139003708")
        self.assertGreaterEqual(dados["confianca"]["cnpj"], 0.8)


    def test_parser_prioriza_prefixo_live_em_fatura_generica(self):
        texto = """
        CACTA TELECOMUNICACOES LTDA
        CNPJ Beneficiario: 49.644.175/0004-73
        Pagador LIVE STORE BRASIL COMERCIO DE ROUPAS LTDA 35.303.139/0089-20
        Vencimento 15/10/2026
        Valor Documento R$ 226,90
        Numero Documento 7773
        """
        dados = parsear_texto(texto)
        self.assertEqual(dados["cnpj"], "35303139008920")
        self.assertEqual(dados["operadora"], "CACTA TELECOM")
        self.assertGreaterEqual(dados["confianca"]["cnpj"], 0.9)

    def test_parser_unifique_layout_sintetico(self):
        texto = """
        Live Roupas Esportivas Ltda
        Unifique Telecomunicacoes S/A
        CNPJ: 05.108.435/0001-78
        CNPJ: 58.074.301/0001-40
        Codigo do cliente: 36264
        CNPJ da Matriz: 02.255.187/0001-08
        Periodo de cobranca
        Codigo de cobranca
        Vencimento
        Valor
        01/07/2026 - 31/07/2026
        57144230
        25/08/2026
        R$ 189,90
        Descritivo
        Bilhetagem
        Circuito
        SC/PR - Uni Fibra SE Play 500 Mega
        04794627001
        01/07/2026 - 31/07/2026
        R$ 139,90
        Beneficiario
        UNIFIQUE TELECOMUNICACOES S/A
        CNPJ: 02.255.187/0001-08
        """
        dados = parsear_texto(texto)
        self.assertEqual(dados["parser_utilizado"], "unifique")
        self.assertEqual(dados["cnpj"], "05108435000178")
        self.assertEqual(dados["cnpj_fornecedor"], "02255187000108")
        self.assertEqual(dados["vencimento"], "2026-08-25")
        self.assertEqual(dados["valor"], "189.90")
        self.assertEqual(dados["codigo_cliente"], "36264")
        self.assertEqual(dados["codigo_fatura"], "04794627001")
        self.assertGreaterEqual(dados["confianca"]["codigo"], 0.8)

    def test_arquivamento_seguro(self):
        caminho = caminho_arquivado(
            "..\\SHOPPING/CENTER:NORTE",
            "SP",
            "VIVO",
            "2026-08-20",
            "389.90",
            "35303139003708",
        )
        self.assertIn(str(DATA_DIR / "arquivadas"), str(caminho))
        self.assertNotIn("..", str(caminho))
        self.assertTrue(str(caminho).endswith("20-08-2026 - VIVO - R$389,90 - 35.303.139-0037-08.pdf"))

    def test_protecao_sobrescrita(self):
        temp = Path(tempfile.mkdtemp(dir=DATA_DIR))
        try:
            arquivo = temp / "fatura.pdf"
            arquivo.write_text("x", encoding="utf-8")
            proximo = proximo_nome_disponivel(arquivo)
            self.assertEqual(proximo.name, "fatura (2).pdf")
        finally:
            shutil.rmtree(temp)


if __name__ == "__main__":
    unittest.main()
