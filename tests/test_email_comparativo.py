import unittest

from app.services.comparativo import (
    STATUS_CNPJ_NAO_CADASTRADO,
    STATUS_CONFERE,
    STATUS_DIVERGENCIA,
    comparar_campos,
    encontrar_match,
)
from app.services.telemiza_email_parser import parsear_email_telemiza


class EmailComparativoTests(unittest.TestCase):
    def test_parser_email_telemiza_tabela_html(self):
        html = """
        <table>
          <tr><th>Razao Social</th><th>CNPJ</th><th>Operadora</th><th>Vencimento</th><th>Conta</th></tr>
          <tr><td>Empresa Teste Ltda</td><td>35.303.139/0037-08</td><td>vivo</td><td>20/08/2026</td><td>899929200608</td></tr>
        </table>
        """
        itens = parsear_email_telemiza(html)
        self.assertEqual(len(itens), 1)
        self.assertEqual(itens[0].cnpj, "35303139003708")
        self.assertEqual(itens[0].operadora, "VIVO")
        self.assertEqual(itens[0].vencimento, "2026-08-20")
        self.assertEqual(itens[0].codigo_fatura, "899929200608")

    def test_match_prioriza_cnpj_e_codigo(self):
        itens = [
            {"id": 1, "cnpj": "11111111000191", "codigo_fatura": "ABC", "operadora": "VIVO", "vencimento": "2026-08-20"},
            {"id": 2, "cnpj": "35303139003708", "codigo_fatura": "899929200608", "operadora": "VIVO", "vencimento": "2026-08-20"},
        ]
        pdf = {"cnpj": "35303139003708", "codigo_fatura": "899929200608", "operadora": "VIVO", "vencimento": "2026-08-20"}
        match = encontrar_match(itens, pdf)
        self.assertEqual(match.item_id, 2)
        self.assertGreaterEqual(match.score, 85)

    def test_comparativo_confere(self):
        item = {"cnpj": "35303139003708", "codigo_fatura": "899929200608", "operadora": "VIVO", "vencimento": "2026-08-20"}
        pdf = {
            "cnpj": "35303139003708",
            "codigo_fatura": "899929200608",
            "operadora": "VIVO",
            "vencimento": "2026-08-20",
            "valor": "151.01",
            "confianca": {"cnpj": 0.95, "valor": 0.95, "vencimento": 0.95, "codigo": 0.95},
        }
        self.assertEqual(comparar_campos(item, pdf, loja_encontrada=True)["status"], STATUS_CONFERE)

    def test_comparativo_divergencia(self):
        item = {"cnpj": "35303139003708", "codigo_fatura": "899929200608", "operadora": "VIVO", "vencimento": "2026-08-21"}
        pdf = {
            "cnpj": "35303139003708",
            "codigo_fatura": "899929200608",
            "operadora": "VIVO",
            "vencimento": "2026-08-20",
            "valor": "151.01",
            "confianca": {"cnpj": 0.95, "valor": 0.95, "vencimento": 0.95, "codigo": 0.95},
        }
        self.assertEqual(comparar_campos(item, pdf, loja_encontrada=True)["status"], STATUS_DIVERGENCIA)

    def test_comparativo_cnpj_nao_cadastrado(self):
        item = {"cnpj": "35303139003708", "codigo_fatura": "899929200608", "operadora": "VIVO", "vencimento": "2026-08-20"}
        pdf = {
            "cnpj": "35303139003708",
            "codigo_fatura": "899929200608",
            "operadora": "VIVO",
            "vencimento": "2026-08-20",
            "valor": "151.01",
            "confianca": {"cnpj": 0.95, "valor": 0.95, "vencimento": 0.95, "codigo": 0.95},
        }
        self.assertEqual(comparar_campos(item, pdf, loja_encontrada=False)["status"], STATUS_CNPJ_NAO_CADASTRADO)


if __name__ == "__main__":
    unittest.main()
