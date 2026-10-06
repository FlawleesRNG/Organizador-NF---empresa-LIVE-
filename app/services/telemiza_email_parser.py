from __future__ import annotations

import json
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

from app.utils.formatadores import normalizar_cnpj, normalizar_data, normalizar_operadora


@dataclass
class ItemEmail:
    row_index: int
    razao_social: str = ""
    cnpj: str = ""
    cliente: str = ""
    unidade_email: str = ""
    operadora: str = ""
    vencimento: str = ""
    referencia: str = ""
    codigo_fatura: str = ""
    tipo: str = ""
    servico: str = ""
    interface: str = ""
    acesso_banda: str = ""
    liberacao: str = ""
    dados_originais: dict | None = None

    def as_db_tuple(self, mensagem_id: int) -> tuple:
        return (
            mensagem_id,
            self.row_index,
            self.razao_social,
            self.cnpj,
            self.cliente,
            self.unidade_email,
            self.operadora,
            self.vencimento,
            self.referencia,
            self.codigo_fatura,
            self.tipo,
            self.servico,
            self.interface,
            self.acesso_banda,
            self.liberacao,
            json.dumps(self.dados_originais or {}, ensure_ascii=False),
        )


def _norm_header(valor: str) -> str:
    texto = re.sub(r"\s+", " ", valor or "").strip().lower()
    mapa = {
        "razao social": "razao_social",
        "razão social": "razao_social",
        "cnpj": "cnpj",
        "cpf/cnpj": "cnpj",
        "cnpj/cpf": "cnpj",
        "cliente": "cliente",
        "unidade": "unidade_email",
        "loja": "unidade_email",
        "operadora": "operadora",
        "vencimento": "vencimento",
        "data vencimento": "vencimento",
        "referencia": "referencia",
        "referência": "referencia",
        "codigo": "codigo_fatura",
        "código": "codigo_fatura",
        "codigo da fatura": "codigo_fatura",
        "código da fatura": "codigo_fatura",
        "conta": "codigo_fatura",
        "tipo": "tipo",
        "servico": "servico",
        "serviço": "servico",
        "interface": "interface",
        "acesso/banda": "acesso_banda",
        "acesso": "acesso_banda",
        "banda": "acesso_banda",
        "liberacao": "liberacao",
        "liberação": "liberacao",
    }
    return mapa.get(texto, texto.replace(" ", "_"))


def _normalizar_item(row_index: int, dados: dict[str, str]) -> ItemEmail:
    item = ItemEmail(row_index=row_index, dados_originais=dados)
    for chave, valor in dados.items():
        if hasattr(item, chave):
            setattr(item, chave, valor.strip())
    item.cnpj = normalizar_cnpj(item.cnpj)
    item.operadora = normalizar_operadora(item.operadora)
    item.vencimento = normalizar_data(item.vencimento)
    item.codigo_fatura = re.sub(r"[^A-Za-z0-9./-]", "", item.codigo_fatura or "")
    return item


def parsear_email_telemiza(html: str) -> list[ItemEmail]:
    soup = BeautifulSoup(html or "", "html.parser")
    itens: list[ItemEmail] = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue
        headers = [_norm_header(cell.get_text(" ", strip=True)) for cell in rows[0].find_all(["th", "td"])]
        if not headers:
            continue
        for row in rows[1:]:
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
            if not any(cells):
                continue
            dados = {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}
            if any(k in dados for k in ("cnpj", "operadora", "vencimento", "codigo_fatura")):
                itens.append(_normalizar_item(len(itens), dados))
    return itens
