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
            ("L320", "CASCAVEL SHOPP CATUAI", "35303139008920", "Cascavel", "PR"),
            ("L341", "SJC SHOPP VALE SUL", "35303139009900", "Sao Jose dos Campos", "SP"),
            ("L393", "BOA VISTA VILLAGE", "35303139010666", "Porto Feliz", "SP"),
            ("L380", "VITORIA SHOPP", "35303139010585", "Vitoria", "ES"),
            ("L381", "CAMPINA GRANDE SHOPP PARTAGE", "35303139010402", "Campina Grande", "PB"),
            ("L447", "SJC SHOPP CENTER VALE", "35303139011557", "Sao Jose dos Campos", "SP"),
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
        resolucao = resolver_loja_por_dados_documento(self.conn, texto, "35303139008920", "base nao confirmou")
        self.assertEqual(resolucao.resultado, MATCH_CONFIRMADO)
        self.assertEqual(resolucao.loja["codigo_loja"], "L320")
        self.assertEqual(resolucao.metodo_identificacao_loja, "DADOS_DOCUMENTO_UNICO")
        self.assertFalse(resolucao.conflitos)
        self.assertIn("observacoes_base", resolucao.auditoria)

    def test_vale_sul_por_endereco(self):
        texto = "Avenida Andromeda, 227, LOJA SUC 297- Shopping Vale Sul - Sao Jose dos Campos - SP"
        resolucao = resolver_loja_por_dados_documento(self.conn, texto, "", "sem cnpj")
        self.assertEqual(resolucao.resultado, MATCH_CONFIRMADO)
        self.assertEqual(resolucao.loja["codigo_loja"], "L341")

    def test_boa_vista_village_por_endereco(self):
        texto = "RODOVIA CASTELO BRANCO KM 99 COND BOA VISTA VILLAGE Cidade: Porto Feliz UF: Sao Paulo"
        resolucao = resolver_loja_por_dados_documento(self.conn, texto, "35303139010666", "cnpj ausente na base")
        self.assertEqual(resolucao.resultado, MATCH_CONFIRMADO)
        self.assertEqual(resolucao.loja["codigo_loja"], "L393")

    def test_vitoria_por_endereco(self):
        texto = "AV. AMERICO BUAIZ, 200, ENSEADA DO SUA 29050-420 - VITORIA - ES"
        resolucao = resolver_loja_por_dados_documento(self.conn, texto, "35303139010585", "")
        self.assertEqual(resolucao.resultado, MATCH_CONFIRMADO)
        self.assertEqual(resolucao.loja["codigo_loja"], "L380")

    def test_campina_grande_por_endereco(self):
        texto = "Avenida Prefeito Severino Bezerra Cabral, 1050, LOJA LUC 27 Catole Campina Grande PB"
        resolucao = resolver_loja_por_dados_documento(self.conn, texto, "35303139010402", "")
        self.assertEqual(resolucao.resultado, MATCH_CONFIRMADO)
        self.assertEqual(resolucao.loja["codigo_loja"], "L381")

    def test_center_vale_por_endereco(self):
        texto = "AV DEP BENEDITO MATARAZZO, 09403 LJ M137 Jardim Oswaldo Cruz Sao Jose dos Campos SP"
        resolucao = resolver_loja_por_dados_documento(self.conn, texto, "35303139011557", "")
        self.assertEqual(resolucao.resultado, MATCH_CONFIRMADO)
        self.assertEqual(resolucao.loja["codigo_loja"], "L447")


if __name__ == "__main__":
    unittest.main()
