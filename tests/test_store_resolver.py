import sqlite3
import unittest

from app.services.store_resolver import (
    MATCH_CONFIRMADO,
    REVISAR_CNPJ_NAO_IDENTIFICADO,
    REVISAR_CONFLITO,
    REVISAR_LOJA_NAO_CADASTRADA,
    resolver_loja_por_cnpj_live,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE lojas (
            id INTEGER PRIMARY KEY,
            codigo_loja TEXT,
            nome TEXT,
            cidade TEXT,
            uf TEXT,
            cnpj TEXT UNIQUE,
            ativo INTEGER
        )
        """
    )
    conn.execute(
        """
        INSERT INTO lojas (id, codigo_loja, nome, cidade, uf, cnpj, ativo)
        VALUES (206, 'L206', 'OUTLET CAMPO LARGO', 'Campo Largo', 'PR', '35303139005409', 1)
        """
    )
    return conn


class StoreResolverTests(unittest.TestCase):
    def test_match_exato_cnpj_completo(self):
        conn = _conn()
        try:
            resolucao = resolver_loja_por_cnpj_live(
                conn,
                "Tomador LIVE OUTLET CAMPO LARGO PR CNPJ 35.303.139/0054-09",
            )
            self.assertEqual(resolucao.resultado, MATCH_CONFIRMADO)
            self.assertEqual(resolucao.loja["codigo_loja"], "L206")
            self.assertEqual(resolucao.metodo_identificacao_loja, "CNPJ_EXATO")
        finally:
            conn.close()

    def test_nao_cadastrada_nao_aproxima(self):
        conn = _conn()
        try:
            resolucao = resolver_loja_por_cnpj_live(
                conn,
                "Tomador LIVE OUTLET CAMPO LARGO PR CNPJ 35.303.139/0092-26",
            )
            self.assertEqual(resolucao.resultado, REVISAR_LOJA_NAO_CADASTRADA)
            self.assertIsNone(resolucao.loja)
        finally:
            conn.close()

    def test_sem_cnpj_live_vai_revisar(self):
        conn = _conn()
        try:
            resolucao = resolver_loja_por_cnpj_live(conn, "Beneficiario 12.345.678/0001-99")
            self.assertEqual(resolucao.resultado, REVISAR_CNPJ_NAO_IDENTIFICADO)
            self.assertIsNone(resolucao.loja)
        finally:
            conn.close()

    def test_conflito_secundario_vai_revisar_sem_substituir_match(self):
        conn = _conn()
        try:
            resolucao = resolver_loja_por_cnpj_live(
                conn,
                "Endereco do tomador Cidade Curitiba UF SC CNPJ 35.303.139/0054-09",
            )
            self.assertEqual(resolucao.resultado, REVISAR_CONFLITO)
            self.assertEqual(resolucao.loja["codigo_loja"], "L206")
            self.assertTrue(resolucao.conflitos)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
