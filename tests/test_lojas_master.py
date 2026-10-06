import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services import lojas_master
from app.services.lojas_master import (
    STATUS_CNPJ_PENDENTE,
    aplicar_importacao,
    gerar_preview,
    normalizar_linha,
)
from app.utils.formatadores import (
    formatar_cnpj,
    nome_exibicao_loja,
    normalizar_cnpj,
    normalizar_codigo_loja,
)


def _payload(linhas: list[dict]) -> str:
    return base64.b64encode(json.dumps({"linhas": linhas, "resumo": {}}, ensure_ascii=False).encode("utf-8")).decode("ascii")


class LojasMasterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_original = lojas_master.DB_PATH
        lojas_master.DB_PATH = Path(self.tmp.name) / "telemiza.db"
        conn = sqlite3.connect(lojas_master.DB_PATH)
        try:
            conn.execute(
                """
                CREATE TABLE lojas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    codigo_loja TEXT UNIQUE,
                    nome TEXT NOT NULL,
                    tipo_loja TEXT,
                    cnpj TEXT UNIQUE,
                    cidade TEXT,
                    uf TEXT,
                    ativo INTEGER NOT NULL DEFAULT 1,
                    status_cadastro TEXT NOT NULL DEFAULT 'OK',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                INSERT INTO lojas (codigo_loja, nome, tipo_loja, cnpj, cidade, uf, ativo, status_cadastro, created_at, updated_at)
                VALUES ('L001', 'ANTIGA', 'Loja', '35303139003708', 'Sao Paulo', 'SP', 1, 'OK', '2026-08-14', '2026-08-14')
                """
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        lojas_master.DB_PATH = self.db_original
        self.tmp.cleanup()

    def test_normaliza_codigo_loja(self):
        self.assertEqual(normalizar_codigo_loja("l164"), "L164")
        self.assertEqual(normalizar_codigo_loja("L 164"), "L164")

    def test_cnpj_formatacao_e_pontuacao_quebrada(self):
        self.assertEqual(normalizar_cnpj("35..303/139--0037 08"), "35303139003708")
        self.assertEqual(formatar_cnpj("35303139003708"), "35.303.139/0037-08")

    def test_linha_sem_cnpj_fica_pendente(self):
        linha = normalizar_linha(1, {"Código": "L 164", "Unidade": "Center Norte", "Cidade": "Sao Paulo"})
        self.assertEqual(linha.codigo_loja, "L164")
        self.assertEqual(linha.status_cadastro, STATUS_CNPJ_PENDENTE)

    def test_display_com_e_sem_codigo(self):
        self.assertEqual(
            nome_exibicao_loja({"codigo_loja": "L164", "nome": "Center Norte", "uf": "SP"}),
            "L164 - CENTER NORTE - SP",
        )
        self.assertEqual(
            nome_exibicao_loja({"nome": "Galpao 1 Vieira", "uf": "SC"}),
            "GALPAO 1 VIEIRA - SC",
        )

    def test_preview_detecta_codigo_e_cnpj_duplicados(self):
        csv = (
            "Código;Unidade;CNPJ;Cidade;UF\n"
            "L164;Center Norte;35.303.139/0037-08;Sao Paulo;SP\n"
            "L 164;Outra;35..303/139--0037 08;Sao Paulo;SP\n"
        ).encode("utf-8")
        preview = gerar_preview(csv)
        problemas = " ".join(" ".join(l.problemas) for l in preview["linhas"])
        self.assertIn("Codigo duplicado", problemas)
        self.assertIn("CNPJ duplicado", problemas)

    def test_importacao_atualiza_por_cnpj_sem_duplicar(self):
        linha = normalizar_linha(
            1,
            {
                "codigo_loja": "L164",
                "nome": "Center Norte",
                "tipo_loja": "Loja Propria",
                "cnpj": "35.303.139/0037-08",
                "cidade": "Sao Paulo",
                "uf": "SP",
            },
        ).as_dict()
        aplicar_importacao(_payload([linha]))
        conn = sqlite3.connect(lojas_master.DB_PATH)
        try:
            conn.row_factory = sqlite3.Row
            lojas = conn.execute("SELECT * FROM lojas").fetchall()
            self.assertEqual(len(lojas), 1)
            self.assertEqual(lojas[0]["codigo_loja"], "L164")
            self.assertEqual(lojas[0]["nome"], "CENTER NORTE")
        finally:
            conn.close()

    def test_importacao_faz_rollback_se_der_erro(self):
        primeira = normalizar_linha(
            1,
            {"codigo_loja": "L200", "nome": "Nova", "cnpj": "02.255.187/0001-08", "cidade": "Jaragua do Sul", "uf": "SC"},
        ).as_dict()
        segunda = normalizar_linha(
            2,
            {"codigo_loja": "L201", "nome": "", "cnpj": "05.108.435/0001-78", "cidade": "Recife", "uf": "PE"},
        ).as_dict()
        segunda["nome"] = None
        with self.assertRaises(sqlite3.IntegrityError):
            aplicar_importacao(_payload([primeira, segunda]))
        conn = sqlite3.connect(lojas_master.DB_PATH)
        try:
            total = conn.execute("SELECT COUNT(*) FROM lojas").fetchone()[0]
            nova = conn.execute("SELECT COUNT(*) FROM lojas WHERE codigo_loja = 'L200'").fetchone()[0]
            self.assertEqual(total, 1)
            self.assertEqual(nova, 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
