from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from app.database import DATA_DIR
from app.utils.formatadores import (
    data_para_nome_arquivo,
    formatar_cnpj_arquivo,
    formatar_valor,
    sanitizar_nome_path,
)


MESES = {
    1: "Janeiro",
    2: "Fevereiro",
    3: "Março",
    4: "Abril",
    5: "Maio",
    6: "Junho",
    7: "Julho",
    8: "Agosto",
    9: "Setembro",
    10: "Outubro",
    11: "Novembro",
    12: "Dezembro",
}


def _garantir_dentro_data(caminho: Path) -> Path:
    resolvido = caminho.resolve()
    data_root = DATA_DIR.resolve()
    if data_root not in resolvido.parents and resolvido != data_root:
        raise ValueError("Caminho final fora da pasta data.")
    return resolvido


def caminho_arquivado(loja_nome: str, uf: str, operadora: str, vencimento: str, valor: str, cnpj: str) -> Path:
    data = datetime.strptime(vencimento, "%Y-%m-%d")
    mes = f"{data.month:02d} - {MESES[data.month]}"
    loja_rotulo = f"{loja_nome} - {uf}" if uf else loja_nome
    loja = sanitizar_nome_path(loja_rotulo)
    operadora_segura = sanitizar_nome_path(operadora.upper())
    nome_pdf = (
        f"{data_para_nome_arquivo(vencimento)} - {operadora_segura} - "
        f"{formatar_valor(valor)} - {formatar_cnpj_arquivo(cnpj)}.pdf"
    )
    caminho = DATA_DIR / "arquivadas" / str(data.year) / mes / loja / operadora_segura / sanitizar_nome_path(nome_pdf)
    return _garantir_dentro_data(caminho)


def caminho_revisar(nome_original: str) -> Path:
    return _garantir_dentro_data(DATA_DIR / "revisar" / sanitizar_nome_path(nome_original, "fatura.pdf"))


def proximo_nome_disponivel(caminho: Path) -> Path:
    caminho = _garantir_dentro_data(caminho)
    if not caminho.exists():
        return caminho
    indice = 2
    while True:
        candidato = caminho.with_name(f"{caminho.stem} ({indice}){caminho.suffix}")
        if not candidato.exists():
            return candidato
        indice += 1


def mover_pdf(origem: str | Path, destino: str | Path) -> Path:
    origem_path = Path(origem).resolve()
    destino_path = proximo_nome_disponivel(Path(destino))
    destino_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem_path), str(destino_path))
    return destino_path
