from __future__ import annotations

import hashlib
from pathlib import Path

from app.database import conectar


def sha256_arquivo(caminho: str | Path) -> str:
    h = hashlib.sha256()
    with Path(caminho).open("rb") as f:
        for bloco in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloco)
    return h.hexdigest()


def preencher_sha256_existente() -> int:
    atualizados = 0
    with conectar() as conn:
        rows = conn.execute(
            "SELECT id, caminho_final FROM faturas WHERE (sha256 IS NULL OR sha256 = '') AND caminho_final IS NOT NULL"
        ).fetchall()
        for row in rows:
            caminho = Path(row["caminho_final"])
            if caminho.exists():
                conn.execute("UPDATE faturas SET sha256 = ? WHERE id = ?", (sha256_arquivo(caminho), row["id"]))
                atualizados += 1
    return atualizados


def desativar_duplicados_por_sha256() -> int:
    alterados = 0
    with conectar() as conn:
        grupos = conn.execute(
            """
            SELECT sha256, MAX(id) principal, COUNT(*) total
            FROM faturas
            WHERE sha256 IS NOT NULL AND sha256 != ''
            GROUP BY sha256
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        for grupo in grupos:
            conn.execute(
                """
                UPDATE faturas
                SET ativo_historico = 0, registro_principal_id = ?
                WHERE sha256 = ? AND id != ?
                """,
                (grupo["principal"], grupo["sha256"], grupo["principal"]),
            )
            conn.execute(
                "UPDATE faturas SET ativo_historico = 1, registro_principal_id = NULL WHERE id = ?",
                (grupo["principal"],),
            )
            alterados += grupo["total"] - 1
    return alterados


def corrigir_historico_duplicado() -> dict:
    return {
        "sha256_atualizados": preencher_sha256_existente(),
        "duplicados_desativados": desativar_duplicados_por_sha256(),
    }


def corrigir_identidade_faturas_pendentes() -> dict:
    """Preenche automaticamente CNPJ LIVE!, loja e operadora em registros ja existentes.

    A rotina e deliberadamente conservadora: atua apenas em registros ativos que nao
    estao arquivados. Ela usa o texto ja extraido e o nome original do arquivo, sem
    criar uma nova fatura e sem alterar o PDF.
    """
    from app.models import STATUS_PENDENTE, STATUS_REVISAR
    from app.services.cnpj_utils import identificar_cnpjs_live, motivo_cnpj_live_nao_cadastrado
    from app.services.operator_detector import detectar_operadora
    from app.utils.formatadores import formatar_cnpj

    atualizados = 0
    vinculados_loja = 0
    operadoras_preenchidas = 0

    with conectar() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM faturas
            WHERE ativo_historico = 1
              AND status != 'ARQUIVADA'
              AND (
                    loja_id IS NULL
                 OR cnpj IS NULL OR cnpj = '' OR cnpj NOT LIKE '35303139%'
                 OR operadora IS NULL OR operadora = ''
              )
            ORDER BY id
            """
        ).fetchall()

        for row in rows:
            texto = row["texto_extraido"] or ""
            nome = row["arquivo_original"] or ""
            live = identificar_cnpjs_live(texto)
            if len(live) == 1:
                cnpj = live[0]
                origem_cnpj = "Identificado automaticamente pelo prefixo CNPJ LIVE! 35.303.139"
                confianca_cnpj = 0.99
            elif len(live) > 1:
                cnpj = ""
                origem_cnpj = "Mais de um CNPJ LIVE! encontrado no documento"
                confianca_cnpj = 0.45
            else:
                atual = row["cnpj"] or ""
                cnpj = atual if atual.startswith("35303139") else ""
                origem_cnpj = row["origem_cnpj"] or "Nenhum CNPJ LIVE! 35.303.139 encontrado"
                confianca_cnpj = row["confianca_cnpj"] or 0.0

            detectada = detectar_operadora(texto, nome)
            operadora = detectada.operadora if detectada.segura else (row["operadora"] or "")

            loja = None
            if cnpj:
                loja = conn.execute(
                    "SELECT * FROM lojas WHERE cnpj = ? AND ativo = 1",
                    (cnpj,),
                ).fetchone()

            # Remove mensagens antigas de identidade, mantendo problemas de valor,
            # vencimento, codigo etc. para nao mascarar outros pontos de revisao.
            antigos = [item.strip() for item in (row["motivo_revisao"] or "").split(";") if item.strip()]
            manter = []
            for item in antigos:
                chave = item.lower()
                if "cnpj" in chave or "operadora" in chave:
                    continue
                manter.append(item)

            if not cnpj:
                if len(live) > 1:
                    manter.append("Mais de um CNPJ LIVE! encontrado")
                else:
                    manter.append("CNPJ da loja nao identificado")
            elif not loja:
                manter.append(motivo_cnpj_live_nao_cadastrado(cnpj))
            if not operadora:
                manter.append("Operadora nao identificada")

            motivos = list(dict.fromkeys(manter))
            novo_status = STATUS_REVISAR if motivos else STATUS_PENDENTE

            mudou = (
                (row["cnpj"] or "") != cnpj
                or row["loja_id"] != (loja["id"] if loja else None)
                or (row["operadora"] or "") != operadora
                or (row["motivo_revisao"] or "") != "; ".join(motivos)
                or row["status"] != novo_status
            )
            if not mudou:
                continue

            if loja and row["loja_id"] != loja["id"]:
                vinculados_loja += 1
            if operadora and not (row["operadora"] or ""):
                operadoras_preenchidas += 1

            conn.execute(
                """
                UPDATE faturas
                   SET cnpj = ?, loja_id = ?, operadora = ?, status = ?, motivo_revisao = ?,
                       origem_cnpj = ?, confianca_cnpj = ?
                 WHERE id = ?
                """,
                (
                    cnpj,
                    loja["id"] if loja else None,
                    operadora,
                    novo_status,
                    "; ".join(motivos),
                    origem_cnpj,
                    confianca_cnpj,
                    row["id"],
                ),
            )
            atualizados += 1

    return {
        "atualizados": atualizados,
        "lojas_vinculadas": vinculados_loja,
        "operadoras_preenchidas": operadoras_preenchidas,
    }
