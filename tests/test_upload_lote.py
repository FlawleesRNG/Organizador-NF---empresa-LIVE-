import io
import unittest
import zipfile

from app.routes.faturas import _ajustar_identidade_automatica, _extrair_pdfs_zip
from app.services.cnpj_utils import identificar_cnpjs_live
from app.services.operator_detector import detectar_operadora


class UploadLoteTests(unittest.TestCase):
    def test_zip_aceita_subpastas_e_ignora_outros_arquivos(self):
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as zf:
            zf.writestr("loja1/nota.pdf", b"%PDF-1.4\nA")
            zf.writestr("loja2/nota.pdf", b"%PDF-1.4\nB")
            zf.writestr("leia-me.txt", b"texto")
        itens = _extrair_pdfs_zip(bio.getvalue())
        self.assertEqual(len(itens), 2)
        self.assertTrue(all(nome.lower().endswith(".pdf") for nome, _ in itens))

    def test_identidade_live_sobrepoe_cnpj_do_fornecedor(self):
        dados = {
            "cnpj": "49644175000473",
            "cnpjs": ["49644175000473", "35303139008920"],
            "operadora": "CACTA TELECOM",
            "confianca": {"cnpj": 0.9},
            "origem": {"cnpj": "fornecedor"},
        }
        ajustado = _ajustar_identidade_automatica(
            dados,
            "Beneficiario 49.644.175/0004-73 Pagador LIVE 35.303.139/0089-20",
            "fatura.pdf",
        )
        self.assertEqual(ajustado["cnpj"], "35303139008920")
        self.assertGreaterEqual(ajustado["confianca"]["cnpj"], 0.9)

    def test_nome_do_arquivo_prioriza_operadora_comercial(self):
        dados = {
            "cnpj": "35303139004852",
            "cnpjs": ["35303139004852", "58480388000155"],
            "operadora": "VOZIO",
            "confianca": {"cnpj": 0.99},
            "origem": {"cnpj": "cliente"},
        }
        ajustado = _ajustar_identidade_automatica(
            dados,
            "VOZIO COMUNICACAO LTDA Pagador LIVE STORE 35.303.139/0048-52",
            "BLUE - BANDA LARGA 100MB - 10 2026 - BOLETO+NF.pdf",
        )
        self.assertEqual(ajustado["operadora"], "BLUE")

    def test_cnpj_live_quebrado_por_espacos(self):
        texto = "Pagador LIVE\nCNPJ 35 303 139 0054 09\nBeneficiario 12.345.678/0001-99"
        self.assertEqual(identificar_cnpjs_live(texto), ["35303139005409"])

    def test_conteudo_confiavel_vence_nome_arquivo(self):
        detectada = detectar_operadora(
            "Razao social: CACTA TELECOMUNICACOES LTDA\nCNPJ 49.644.175/0004-73",
            "VIVO - arquivo com nome errado.pdf",
        )
        self.assertEqual(detectada.operadora, "CACTA TELECOM")

    def test_zip_sem_pdf_tem_mensagem_amigavel(self):
        bio = io.BytesIO()
        with zipfile.ZipFile(bio, "w") as zf:
            zf.writestr("readme.txt", b"sem pdf")
        with self.assertRaisesRegex(ValueError, "nao contem arquivos PDF"):
            _extrair_pdfs_zip(bio.getvalue())

    def test_operadoras_reais_do_lote_sao_detectadas(self):
        casos = {
            "PONTO TELECOM COMUNICACOES LTDA": "PONTO TELECOM",
            "Fibrion Internet LTDA": "FIBRION",
            "Isptec Sistemas De Comunicacao Ltda": "ISPTEC",
            "CONNECTRONIC SERVICOS LTDA": "EXO",
            "NIPBR TELECOM": "NIPBR",
        }
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(detectar_operadora(texto).operadora, esperado)


if __name__ == "__main__":
    unittest.main()
