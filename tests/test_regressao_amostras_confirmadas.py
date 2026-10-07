import json
import unittest
from pathlib import Path

from app.database import BASE_DIR, conectar
from app.routes.faturas import _ajustar_identidade_automatica
from app.services.pdf_parser import extrair_texto_pdf, parsear_texto
from app.services.store_resolver import MATCH_CONFIRMADO, resolver_loja_por_cnpj_live


class RegressaoAmostrasConfirmadasTests(unittest.TestCase):
    def test_amostras_confirmadas_nao_trocam_de_loja(self):
        manifest = BASE_DIR / "tests" / "amostras_confirmadas" / "manifest.json"
        amostras = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertGreater(len(amostras), 0)
        executadas = 0
        with conectar() as conn:
            for amostra in amostras:
                with self.subTest(arquivo=amostra["arquivo"]):
                    caminho = BASE_DIR / amostra["arquivo"]
                    if not caminho.exists():
                        continue
                    executadas += 1
                    texto = extrair_texto_pdf(caminho)
                    dados = _ajustar_identidade_automatica(parsear_texto(texto), texto, caminho.name)
                    resolucao = resolver_loja_por_cnpj_live(conn, texto, dados.get("cnpj", ""))
                    self.assertEqual(dados.get("operadora"), amostra["operadora"])
                    resultado_esperado = amostra.get("resultado", MATCH_CONFIRMADO)
                    self.assertEqual(resolucao.resultado, resultado_esperado)
                    self.assertEqual(resolucao.cnpj_encontrado, amostra["cnpj"])
                    if resultado_esperado == MATCH_CONFIRMADO:
                        self.assertEqual(resolucao.loja["codigo_loja"], amostra["codigo_loja"])
        if executadas == 0:
            self.skipTest("Nenhuma amostra confirmada local disponivel para regressao.")


if __name__ == "__main__":
    unittest.main()
