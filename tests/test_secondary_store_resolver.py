import sqlite3
import unittest

from app.database import agora, init_db
from app.services.secondary_store_resolver import resolver_loja_por_dados_documento
from app.services.store_resolver import MATCH_CONFIRMADO


class SecondaryStoreResolverTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE lojas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cnpj TEXT,
                nome TEXT NOT NULL,
                uf TEXT NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                codigo_loja TEXT,
                tipo_loja TEXT,
                cidade TEXT,
                razao_social TEXT,
                status_cadastro TEXT NOT NULL DEFAULT 'OK'
            )
            """
        )
        lojas = [
            ("L321", "CASCAVEL SHOPP CATUAI", "35303139009650", "Cascavel", "PR"),
            ("L342", "SJC SHOPP VALE SUL", "35303139010070", "Sao Jose dos Campos", "SP"),
            ("L241", "FAZENDA BOA VISTA", "35303139007010", "Porto Feliz", "SP"),
        ]
        for codigo, nome, cnpj, cidade, uf in lojas:
            self.conn.execute(
                """
                INSERT INTO lojas (codigo_loja, nome, cnpj, cidade, uf, ativo, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (codigo, nome, cnpj, cidade, uf, agora(), agora()),
            )
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_cascavel_catuai_por_dados_do_documento(self):
        texto = "Condominio: Shopping Cascavel Catuai - Referencia End: LOJA LUC 3019 Cascavel PR"
        resolucao = resolver_loja_por_dados_documento(self.conn, texto, "35303139008920", "conflito")
        self.assertEqual(resolucao.resultado, MATCH_CONFIRMADO)
        self.assertEqual(resolucao.loja["codigo_loja"], "L321")
        self.assertEqual(resolucao.metodo_identificacao_loja, "DADOS_DOCUMENTO_UNICO")

    def test_vale_sul_por_endereco(self):
        texto = "Avenida Andromeda, 227, LOJA SUC 297- Shopping Vale Sul - Sao Jose dos Campos - SP"
        resolucao = resolver_loja_por_dados_documento(self.conn, texto, "", "sem cnpj")
        self.assertEqual(resolucao.resultado, MATCH_CONFIRMADO)
        self.assertEqual(resolucao.loja["codigo_loja"], "L342")

    def test_boa_vista_village_por_endereco(self):
        texto = "RODOVIA CASTELO BRANCO KM 99 COND BOA VISTA VILLAGE Cidade: Porto Feliz UF: Sao Paulo"
        resolucao = resolver_loja_por_dados_documento(self.conn, texto, "35303139010666", "cnpj ausente na base")
        self.assertEqual(resolucao.resultado, MATCH_CONFIRMADO)
        self.assertEqual(resolucao.loja["codigo_loja"], "L241")


if __name__ == "__main__":
    unittest.main()
