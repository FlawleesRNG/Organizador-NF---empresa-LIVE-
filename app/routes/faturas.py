from __future__ import annotations

import hashlib
import io
import json
import logging
import zipfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app.database import DATA_DIR, agora, conectar
from app.models import STATUS_ARQUIVADA, STATUS_ERRO, STATUS_REVISAR
from app.services.arquivamento import caminho_arquivado, caminho_revisar, mover_pdf
from app.services.cnpj_utils import identificar_cnpjs_live, motivo_cnpj_live_nao_cadastrado
from app.services.operator_detector import detectar_operadora
from app.services.pdf_parser import extrair_texto_pdf, parsear_texto
from app.services.store_resolver import MATCH_CONFIRMADO, auditar_base_mestre, resolver_loja_por_cnpj_live
from app.utils.formatadores import (
    formatar_cnpj,
    nome_exibicao_loja,
    normalizar_cnpj,
    normalizar_data,
    normalizar_operadora,
    normalizar_valor,
    sanitizar_nome_path,
    validar_cnpj,
)


router = APIRouter(tags=["faturas"])
logger = logging.getLogger("telemiza")

MAX_PDFS_ZIP = 250
MAX_PDF_BYTES = 40 * 1024 * 1024
MAX_ZIP_UNCOMPRESSED_BYTES = 500 * 1024 * 1024


def _caminho_pdf_fatura(fatura) -> Path:
    if not fatura or not fatura["caminho_final"]:
        raise HTTPException(status_code=404, detail="Arquivo da fatura nao encontrado.")
    caminho = Path(fatura["caminho_final"]).resolve()
    data_root = DATA_DIR.resolve()
    if data_root not in caminho.parents and caminho != data_root:
        raise HTTPException(status_code=403, detail="Caminho fora da pasta de dados.")
    if not caminho.exists() or not caminho.is_file():
        raise HTTPException(status_code=404, detail="Arquivo da fatura nao encontrado.")
    if caminho.suffix.lower() != ".pdf":
        raise HTTPException(status_code=400, detail="Arquivo da fatura nao e PDF.")
    return caminho


def _buscar_loja(conn, cnpj: str):
    cnpj_norm = normalizar_cnpj(cnpj)
    if not cnpj_norm:
        return None
    return conn.execute("SELECT * FROM lojas WHERE cnpj = ? AND ativo = 1", (cnpj_norm,)).fetchone()


def _bool_db(valor):
    if valor is None:
        return None
    return 1 if valor else 0


def _sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def _json_lista(valor) -> str:
    return json.dumps(valor or [], ensure_ascii=False)


def _motivos_confianca(dados: dict) -> list[str]:
    motivos = []
    confianca = dados.get("confianca", {})
    limites = {"cnpj": 0.80, "valor": 0.80, "vencimento": 0.80, "operadora": 0.80}
    for campo, minimo in limites.items():
        # Ausencia de CNPJ recebe uma mensagem funcional mais clara em _motivos_processamento.
        if campo == "cnpj" and not dados.get("cnpj"):
            continue
        if float(confianca.get(campo, 0.0) or 0.0) < minimo:
            motivos.append(f"Confianca baixa para {campo}")
    live = [cnpj for cnpj in dados.get("cnpjs", []) if (cnpj or "").startswith("35303139")]
    if len(set(live)) > 1:
        motivos.append("Mais de um CNPJ LIVE! encontrado")
    return motivos


def _motivos(cnpj: str, loja, operadora: str, valor: str, vencimento: str) -> list[str]:
    motivos = []
    if not cnpj:
        motivos.append("CNPJ da loja nao identificado")
    elif not cnpj.startswith("35303139"):
        motivos.append("CNPJ identificado nao pertence ao prefixo LIVE! 35.303.139")
    elif not loja:
        motivos.append(motivo_cnpj_live_nao_cadastrado(cnpj))
    if not operadora:
        motivos.append("Operadora nao identificada com seguranca.")
    if not valor:
        motivos.append("Valor nao identificado")
    if not vencimento:
        motivos.append("Vencimento nao identificado")
    if cnpj and not validar_cnpj(cnpj):
        motivos.append("CNPJ com digitos verificadores invalidos")
    return motivos


def _ajustar_identidade_automatica(dados: dict, texto: str, nome_original: str) -> dict:
    """Forca CNPJ LIVE! como chave da loja e completa a operadora automaticamente."""
    dados = dict(dados)
    dados["confianca"] = dict(dados.get("confianca") or {})
    dados["origem"] = dict(dados.get("origem") or {})
    cnpjs = list(dict.fromkeys(dados.get("cnpjs") or []))

    live = identificar_cnpjs_live(texto)
    for cnpj in live:
        if cnpj not in cnpjs:
            cnpjs.insert(0, cnpj)
    dados["cnpjs"] = cnpjs

    if len(live) == 1:
        dados["cnpj"] = live[0]
        dados["cnpj_formatado"] = formatar_cnpj(live[0])
        dados["confianca"]["cnpj"] = 0.99
        dados["origem"]["cnpj"] = "Identificado automaticamente pelo prefixo CNPJ LIVE! 35.303.139"
    elif len(live) > 1:
        dados["cnpj"] = ""
        dados["cnpj_formatado"] = ""
        dados["confianca"]["cnpj"] = 0.45
        dados["origem"]["cnpj"] = "Mais de um CNPJ LIVE! encontrado no documento"
    elif not (dados.get("cnpj") or "").startswith("35303139"):
        # Evita vincular o CNPJ do fornecedor como se fosse a loja.
        dados["cnpj"] = ""
        dados["cnpj_formatado"] = ""
        dados["confianca"]["cnpj"] = 0.0
        dados["origem"]["cnpj"] = "Nenhum CNPJ com prefixo LIVE! 35.303.139 foi encontrado"

    detectada = detectar_operadora(texto, nome_original)
    if detectada.segura:
        dados["operadora"] = detectada.operadora
        dados["confianca"]["operadora"] = detectada.confianca
        dados["origem"]["operadora"] = f"{detectada.regra}: {detectada.alias or detectada.operadora}"
    else:
        dados["operadora"] = ""
        dados["confianca"]["operadora"] = detectada.confianca
        dados["origem"]["operadora"] = detectada.regra
    return dados


def _extrair_pdfs_zip(conteudo: bytes) -> list[tuple[str, bytes]]:
    """Le ZIP em memoria; nao extrai caminhos para o disco (protege contra Zip Slip)."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(conteudo))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise ValueError("O arquivo ZIP esta corrompido ou e invalido.") from exc

    arquivos: list[tuple[str, bytes]] = []
    total_descompactado = 0
    with zf:
        infos = [info for info in zf.infolist() if not info.is_dir() and info.filename.lower().endswith(".pdf")]
        if not infos:
            raise ValueError("O ZIP nao contem arquivos PDF.")
        if len(infos) > MAX_PDFS_ZIP:
            raise ValueError(f"O ZIP contem mais de {MAX_PDFS_ZIP} PDFs e foi recusado por seguranca.")
        for info in infos:
            if info.flag_bits & 0x1:
                raise ValueError(f"PDF protegido por senha dentro do ZIP: {Path(info.filename).name}")
            if info.file_size > MAX_PDF_BYTES:
                raise ValueError(f"PDF muito grande dentro do ZIP: {Path(info.filename).name}")
            total_descompactado += info.file_size
            if total_descompactado > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ValueError("O ZIP descompactado ultrapassa o limite de seguranca.")
            try:
                pdf = zf.read(info)
            except Exception as exc:
                # A falha de leitura de um item vira um pseudo-PDF invalido para que o lote continue.
                logger.exception("Falha ao ler item do ZIP: %s", info.filename)
                pdf = b""
            nome_relativo = info.filename.replace("\\", " / ").replace("/", " - ")
            nome = sanitizar_nome_path(nome_relativo, "fatura.pdf")
            arquivos.append((nome, pdf))
    return arquivos


def _detalhes_existente(conn, sha256: str):
    return conn.execute(
        """
        SELECT f.id, f.status, f.cnpj, f.operadora, l.codigo_loja loja_codigo, l.nome loja_nome,
               l.cidade loja_cidade, l.uf loja_uf
        FROM faturas f
        LEFT JOIN lojas l ON l.id = f.loja_id
        WHERE f.sha256 = ? AND f.ativo_historico = 1
        ORDER BY f.id DESC LIMIT 1
        """,
        (sha256,),
    ).fetchone()


def _processar_pdf(nome_original: str, conteudo: bytes) -> dict:
    resultado = {
        "arquivo": nome_original,
        "status": "ERRO",
        "fatura_id": None,
        "operadora": "",
        "cnpj": "",
        "loja": "",
        "cidade_uf": "",
        "motivo": "",
    }
    if not conteudo.startswith(b"%PDF"):
        resultado["motivo"] = "Arquivo nao parece ser um PDF valido."
        return resultado

    arquivo_sha256 = _sha256(conteudo)
    with conectar() as conn:
        existente = _detalhes_existente(conn, arquivo_sha256)
        if existente:
            resultado.update(
                {
                    "status": "DUPLICADO",
                    "fatura_id": existente["id"],
                    "operadora": existente["operadora"] or "",
                    "cnpj": existente["cnpj"] or "",
                    "loja": " - ".join(filter(None, [existente["loja_codigo"], existente["loja_nome"]])),
                    "cidade_uf": " / ".join(filter(None, [existente["loja_cidade"], existente["loja_uf"]])),
                    "motivo": "Este PDF ja foi processado anteriormente.",
                }
            )
            return resultado

    entrada = DATA_DIR / "entrada"
    entrada.mkdir(parents=True, exist_ok=True)
    caminho_temp = entrada / f"{uuid4().hex}_{sanitizar_nome_path(nome_original, 'fatura.pdf')}"
    caminho_temp.write_bytes(conteudo)

    try:
        texto = extrair_texto_pdf(caminho_temp)
        if not texto.strip():
            raise ValueError("PDF sem texto extraivel.")
        dados = _ajustar_identidade_automatica(parsear_texto(texto), texto, nome_original)
    except ValueError as exc:
        motivo = str(exc)
        logger.warning("%s: %s", motivo, nome_original)
        destino = mover_pdf(caminho_temp, caminho_revisar(nome_original))
        with conectar() as conn:
            cur = conn.execute(
                """
                INSERT INTO faturas (
                    arquivo_original, arquivo_final, caminho_final, sha256, status,
                    motivo_revisao, texto_extraido, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (nome_original, destino.name, str(destino), arquivo_sha256, STATUS_REVISAR, motivo, texto if 'texto' in locals() else "", agora()),
            )
            resultado["fatura_id"] = cur.lastrowid
        resultado.update({"status": "REVISAR", "motivo": motivo})
        return resultado
    except Exception:
        logger.exception("Erro de PDF no upload: %s", nome_original)
        destino = mover_pdf(caminho_temp, caminho_revisar(nome_original)) if caminho_temp.exists() else caminho_temp
        with conectar() as conn:
            cur = conn.execute(
                "INSERT INTO faturas (arquivo_original, arquivo_final, caminho_final, sha256, status, motivo_revisao, texto_extraido, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (nome_original, destino.name, str(destino), arquivo_sha256, STATUS_ERRO, "Erro ao processar PDF", "", agora()),
            )
            resultado["fatura_id"] = cur.lastrowid
        resultado["motivo"] = "Erro ao processar PDF."
        return resultado

    cnpj = dados.get("cnpj", "")
    with conectar() as conn:
        resolucao_loja = resolver_loja_por_cnpj_live(conn, texto, cnpj)
        loja = resolucao_loja.loja if resolucao_loja.confirmado else None
        cnpj = resolucao_loja.cnpj_encontrado or cnpj
        if resolucao_loja.auditoria.get("origem_cnpj"):
            dados.setdefault("origem", {})["cnpj"] = resolucao_loja.auditoria["origem_cnpj"]
        if resolucao_loja.auditoria.get("confianca_cnpj") is not None:
            dados.setdefault("confianca", {})["cnpj"] = resolucao_loja.auditoria["confianca_cnpj"]
        motivos = _motivos_confianca(dados)
        if resolucao_loja.resultado != MATCH_CONFIRMADO:
            motivos.append(resolucao_loja.motivo)
            motivos.extend(resolucao_loja.conflitos)
        loja_para_validacao = resolucao_loja.loja if cnpj else None
        motivos.extend(_motivos(cnpj, loja_para_validacao, dados.get("operadora", ""), dados.get("valor", ""), dados.get("vencimento", "")))
        motivos = list(dict.fromkeys(motivos))
        if motivos:
            destino_final = mover_pdf(caminho_temp, caminho_revisar(nome_original))
            status_banco = STATUS_REVISAR
            status_resultado = "REVISAR"
        else:
            destino_final = mover_pdf(
                caminho_temp,
                caminho_arquivado(
                    nome_exibicao_loja(loja),
                    "",
                    dados.get("operadora", ""),
                    dados.get("vencimento", ""),
                    dados.get("valor", ""),
                    cnpj,
                ),
            )
            status_banco = STATUS_ARQUIVADA
            status_resultado = "ARQUIVADA"
        cur = conn.execute(
            """
            INSERT INTO faturas (
                arquivo_original, arquivo_final, caminho_final, sha256, cnpj, loja_id, operadora,
                valor, vencimento, codigo_fatura, status, motivo_revisao, texto_extraido,
                parser_utilizado, confianca_cnpj, confianca_valor, confianca_vencimento,
                confianca_codigo, origem_cnpj, origem_valor, origem_vencimento, origem_codigo,
                origem_operadora, confianca_operadora,
                metodo_identificacao_loja, cnpj_live_identificado, validacao_cidade, validacao_uf,
                resultado_identificacao_loja, auditoria_loja_json,
                razao_social, referencia, codigo_cliente, numero_fatura, cnpj_fornecedor,
                outros_cnpjs, avisos_parser, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nome_original, destino_final.name, str(destino_final), arquivo_sha256, cnpj,
                loja["id"] if loja else None, dados.get("operadora", ""),
                float(dados["valor"]) if dados.get("valor") else None, dados.get("vencimento", ""),
                dados.get("codigo_fatura", ""), status_banco,
                "; ".join(motivos), texto[:200000], dados.get("parser_utilizado", "generico"),
                dados.get("confianca", {}).get("cnpj", 0.0), dados.get("confianca", {}).get("valor", 0.0),
                dados.get("confianca", {}).get("vencimento", 0.0), dados.get("confianca", {}).get("codigo", 0.0),
                dados.get("origem", {}).get("cnpj", ""), dados.get("origem", {}).get("valor", ""),
                dados.get("origem", {}).get("vencimento", ""), dados.get("origem", {}).get("codigo", ""),
                dados.get("origem", {}).get("operadora", ""), dados.get("confianca", {}).get("operadora", 0.0),
                resolucao_loja.metodo_identificacao_loja, cnpj,
                _bool_db(resolucao_loja.validacao_cidade), _bool_db(resolucao_loja.validacao_uf),
                resolucao_loja.resultado, resolucao_loja.auditoria_json(),
                dados.get("razao_social", ""), dados.get("referencia", ""), dados.get("codigo_cliente", ""),
                dados.get("numero_fatura", ""), dados.get("cnpj_fornecedor", ""),
                _json_lista(dados.get("outros_cnpjs", [])), _json_lista(dados.get("avisos", [])), agora(),
            ),
        )
        fatura_id = cur.lastrowid
        resultado.update(
            {
                "status": "REVISAR" if motivos else "PROCESSADO",
                "fatura_id": fatura_id,
                "operadora": dados.get("operadora", ""),
                "cnpj": cnpj,
                "loja": " - ".join(filter(None, [loja["codigo_loja"], loja["nome"]])) if loja else "",
                "cidade_uf": " / ".join(filter(None, [loja["cidade"], loja["uf"]])) if loja else "",
                "motivo": "; ".join(motivos),
            }
        )
        resultado["status"] = status_resultado
    logger.info("PDF processado: %s | %s | %s", nome_original, resultado["status"], resultado["loja"] or "sem loja")
    return resultado


@router.get("/faturas/upload")
def upload_form(request: Request, msg: str = ""):
    return request.app.state.templates.TemplateResponse(request, "upload.html", {"msg": msg, "erro": ""})


@router.post("/faturas/upload")
async def upload(request: Request, arquivo: UploadFile = File(...)):
    nome_upload = sanitizar_nome_path(arquivo.filename or "fatura.pdf", "fatura.pdf")
    extensao = Path(nome_upload).suffix.lower()
    if extensao not in {".pdf", ".zip"}:
        return request.app.state.templates.TemplateResponse(
            request, "upload.html", {"msg": "", "erro": "Selecione um arquivo PDF ou ZIP valido."}, status_code=400
        )

    conteudo = await arquivo.read()
    if extensao == ".pdf":
        resultado = _processar_pdf(nome_upload, conteudo)
        if resultado["status"] == "DUPLICADO":
            destino = f"/faturas/{resultado['fatura_id']}/revisar" if resultado["fatura_id"] else "/historico"
            return RedirectResponse(f"{destino}?msg=Este PDF ja foi processado anteriormente.", status_code=303)
        if resultado["status"] == "ERRO":
            return request.app.state.templates.TemplateResponse(
                request, "upload.html", {"msg": "", "erro": resultado["motivo"]}, status_code=400
            )
        if resultado["status"] == "ARQUIVADA":
            return RedirectResponse("/historico?msg=PDF processado e arquivado automaticamente.", status_code=303)
        return RedirectResponse(f"/faturas/{resultado['fatura_id']}/revisar?msg=PDF processado", status_code=303)

    try:
        pdfs = _extrair_pdfs_zip(conteudo)
    except ValueError as exc:
        return request.app.state.templates.TemplateResponse(
            request, "upload.html", {"msg": "", "erro": str(exc)}, status_code=400
        )

    resultados = []
    for nome_pdf, pdf_bytes in pdfs:
        try:
            resultados.append(_processar_pdf(nome_pdf, pdf_bytes))
        except Exception as exc:
            logger.exception("Falha isolada no lote ZIP: %s", nome_pdf)
            resultados.append(
                {
                    "arquivo": nome_pdf, "status": "ERRO", "fatura_id": None, "operadora": "", "cnpj": "",
                    "loja": "", "cidade_uf": "", "motivo": f"Erro inesperado no item: {type(exc).__name__}"
                }
            )

    resumo = {
        "encontrados": len(resultados),
        "processados": sum(1 for item in resultados if item["status"] in {"PROCESSADO", "ARQUIVADA"}),
        "duplicados": sum(1 for item in resultados if item["status"] == "DUPLICADO"),
        "revisao": sum(1 for item in resultados if item["status"] == "REVISAR"),
        "erros": sum(1 for item in resultados if item["status"] == "ERRO"),
    }
    return request.app.state.templates.TemplateResponse(
        request, "upload_resultado.html", {"resultados": resultados, "resumo": resumo, "msg": "Lote processado.", "erro": ""}
    )


@router.get("/faturas/{fatura_id}/revisar")
def revisar_fatura(request: Request, fatura_id: int, msg: str = ""):
    with conectar() as conn:
        fatura = conn.execute("SELECT * FROM faturas WHERE id = ?", (fatura_id,)).fetchone()
        cnpjs = parsear_texto(fatura["texto_extraido"] or "").get("cnpjs", []) if fatura else []
        loja = _buscar_loja(conn, fatura["cnpj"]) if fatura and fatura["cnpj"] else None
        outros_cnpjs = json.loads(fatura["outros_cnpjs"] or "[]") if fatura else []
    return request.app.state.templates.TemplateResponse(
        request,
        "revisar.html",
        {"fatura": fatura, "loja": loja, "cnpjs": cnpjs, "outros_cnpjs": outros_cnpjs, "msg": msg, "erro": ""},
    )


@router.get("/faturas/{fatura_id}/arquivo")
def abrir_arquivo_fatura(fatura_id: int):
    with conectar() as conn:
        fatura = conn.execute("SELECT * FROM faturas WHERE id = ?", (fatura_id,)).fetchone()
    caminho = _caminho_pdf_fatura(fatura)
    nome = fatura["arquivo_final"] or fatura["arquivo_original"] or caminho.name
    return FileResponse(
        path=str(caminho),
        media_type="application/pdf",
        filename=nome,
        headers={"Content-Disposition": f'inline; filename="{nome}"'},
    )


@router.get("/faturas/{fatura_id}/download")
def baixar_arquivo_fatura(fatura_id: int):
    with conectar() as conn:
        fatura = conn.execute("SELECT * FROM faturas WHERE id = ?", (fatura_id,)).fetchone()
    caminho = _caminho_pdf_fatura(fatura)
    nome = fatura["arquivo_final"] or fatura["arquivo_original"] or caminho.name
    return FileResponse(path=str(caminho), media_type="application/pdf", filename=nome)


@router.post("/faturas/{fatura_id}/confirmar")
def confirmar(
    request: Request,
    fatura_id: int,
    cnpj: str = Form(""),
    operadora: str = Form(""),
    valor: str = Form(""),
    vencimento: str = Form(""),
    codigo_fatura: str = Form(""),
):
    cnpj_norm = normalizar_cnpj(cnpj)
    operadora_norm = normalizar_operadora(operadora)
    valor_norm = normalizar_valor(valor)
    vencimento_norm = normalizar_data(vencimento)
    codigo = sanitizar_nome_path(codigo_fatura, "")[:80]

    with conectar() as conn:
        fatura = conn.execute("SELECT * FROM faturas WHERE id = ?", (fatura_id,)).fetchone()
        loja = _buscar_loja(conn, cnpj_norm) if cnpj_norm else None
        motivos = _motivos(cnpj_norm, loja, operadora_norm, valor_norm, vencimento_norm)
        origem = Path(fatura["caminho_final"]) if fatura and fatura["caminho_final"] else None
        if not fatura or not origem or not origem.exists():
            motivos.append("Arquivo temporario nao encontrado")

        if motivos:
            destino = mover_pdf(origem, caminho_revisar(fatura["arquivo_original"])) if origem and origem.exists() else origem
            conn.execute(
                """
                UPDATE faturas SET arquivo_final = ?, caminho_final = ?, cnpj = ?, loja_id = ?, operadora = ?,
                    valor = ?, vencimento = ?, codigo_fatura = ?, status = ?, motivo_revisao = ?
                WHERE id = ?
                """,
                (
                    destino.name if destino else "",
                    str(destino) if destino else "",
                    cnpj_norm,
                    loja["id"] if loja else None,
                    operadora_norm,
                    float(valor_norm) if valor_norm else None,
                    vencimento_norm,
                    codigo,
                    STATUS_REVISAR,
                    "; ".join(motivos),
                    fatura_id,
                ),
            )
            logger.info("Fatura enviada para revisao: %s", "; ".join(motivos))
            return RedirectResponse(f"/revisar?msg=Fatura enviada para revisao", status_code=303)

        destino = caminho_arquivado(nome_exibicao_loja(loja), "", operadora_norm, vencimento_norm, valor_norm, cnpj_norm)
        final = mover_pdf(origem, destino)
        conn.execute(
            """
            UPDATE faturas SET arquivo_final = ?, caminho_final = ?, cnpj = ?, loja_id = ?, operadora = ?,
                valor = ?, vencimento = ?, codigo_fatura = ?, status = ?, motivo_revisao = ''
            WHERE id = ?
            """,
            (
                final.name,
                str(final),
                cnpj_norm,
                loja["id"],
                operadora_norm,
                float(valor_norm),
                vencimento_norm,
                codigo,
                STATUS_ARQUIVADA,
                fatura_id,
            ),
        )
    logger.info("Fatura arquivada: %s", final)
    return RedirectResponse("/historico?msg=Fatura arquivada", status_code=303)


@router.get("/historico")
def historico(request: Request, loja: str = "", operadora: str = "", status: str = "", q: str = "", msg: str = ""):
    sql = """
        SELECT f.*, l.codigo_loja loja_codigo, l.nome loja_nome, l.cidade loja_cidade, l.uf loja_uf
        FROM faturas f
        LEFT JOIN lojas l ON l.id = f.loja_id
        WHERE f.ativo_historico = 1
    """
    params = []
    if not status:
        sql += " AND f.status != 'PENDENTE'"
    if loja:
        sql += " AND l.id = ?"
        params.append(loja)
    if operadora:
        sql += " AND f.operadora = ?"
        params.append(operadora)
    if status:
        sql += " AND f.status = ?"
        params.append(status)
    if q:
        sql += " AND (f.arquivo_original LIKE ? OR f.codigo_fatura LIKE ? OR f.cnpj LIKE ? OR l.nome LIKE ?)"
        busca = f"%{q}%"
        params.extend([busca, busca, busca, busca])
    sql += " ORDER BY f.created_at DESC"
    with conectar() as conn:
        faturas = conn.execute(sql, params).fetchall()
        lojas = conn.execute("SELECT id, codigo_loja, nome, uf FROM lojas ORDER BY COALESCE(codigo_loja, ''), nome").fetchall()
        operadoras = conn.execute("SELECT DISTINCT operadora FROM faturas WHERE ativo_historico = 1 AND operadora IS NOT NULL AND operadora != '' ORDER BY operadora").fetchall()
    return request.app.state.templates.TemplateResponse(
        request,
        "historico.html",
        {"faturas": faturas, "lojas": lojas, "operadoras": operadoras, "filtro": {"loja": loja, "operadora": operadora, "status": status, "q": q}, "msg": msg},
    )


@router.get("/revisar")
def listar_revisar(request: Request, msg: str = ""):
    with conectar() as conn:
        faturas = conn.execute(
            """
            SELECT f.*, l.codigo_loja loja_codigo, l.nome loja_nome, l.cidade loja_cidade, l.uf loja_uf
            FROM faturas f
            LEFT JOIN lojas l ON l.id = f.loja_id
            WHERE f.status = ? AND f.ativo_historico = 1
            ORDER BY f.created_at DESC
            """,
            (STATUS_REVISAR,),
        ).fetchall()
    return request.app.state.templates.TemplateResponse(request, "revisar_lista.html", {"faturas": faturas, "msg": msg})


@router.post("/faturas/{fatura_id}/reprocessar")
def reprocessar(fatura_id: int):
    with conectar() as conn:
        fatura = conn.execute("SELECT * FROM faturas WHERE id = ?", (fatura_id,)).fetchone()
        if not fatura:
            return RedirectResponse("/historico?msg=Fatura nao encontrada", status_code=303)
        caminho = Path(fatura["caminho_final"] or "")
        if not caminho.exists():
            return RedirectResponse(f"/faturas/{fatura_id}/revisar?msg=Arquivo da fatura nao encontrado para reprocessar", status_code=303)
        texto = extrair_texto_pdf(caminho)
        dados = _ajustar_identidade_automatica(parsear_texto(texto), texto, fatura["arquivo_original"] or caminho.name)
        cnpj = dados.get("cnpj", "")
        resolucao_loja = resolver_loja_por_cnpj_live(conn, texto, cnpj)
        loja = resolucao_loja.loja if resolucao_loja.confirmado else None
        cnpj = resolucao_loja.cnpj_encontrado or cnpj
        if resolucao_loja.auditoria.get("origem_cnpj"):
            dados.setdefault("origem", {})["cnpj"] = resolucao_loja.auditoria["origem_cnpj"]
        if resolucao_loja.auditoria.get("confianca_cnpj") is not None:
            dados.setdefault("confianca", {})["cnpj"] = resolucao_loja.auditoria["confianca_cnpj"]
        motivos = _motivos_confianca(dados)
        if resolucao_loja.resultado != MATCH_CONFIRMADO:
            motivos.append(resolucao_loja.motivo)
            motivos.extend(resolucao_loja.conflitos)
        loja_para_validacao = resolucao_loja.loja if cnpj else None
        motivos.extend(_motivos(cnpj, loja_para_validacao, dados.get("operadora", ""), dados.get("valor", ""), dados.get("vencimento", "")))
        motivos = list(dict.fromkeys(motivos))
        if motivos:
            novo_status = STATUS_REVISAR
            destino = mover_pdf(caminho, caminho_revisar(fatura["arquivo_original"])) if caminho.exists() and "revisar" not in str(caminho).lower() else caminho
        else:
            novo_status = STATUS_ARQUIVADA
            destino = mover_pdf(
                caminho,
                caminho_arquivado(
                    nome_exibicao_loja(loja),
                    "",
                    dados.get("operadora", ""),
                    dados.get("vencimento", ""),
                    dados.get("valor", ""),
                    cnpj,
                ),
            ) if caminho.exists() else caminho
        conn.execute(
            """
            UPDATE faturas SET arquivo_final = ?, caminho_final = ?, cnpj = ?, loja_id = ?, operadora = ?, valor = ?, vencimento = ?,
                codigo_fatura = ?, status = ?, motivo_revisao = ?, texto_extraido = ?,
                parser_utilizado = ?, confianca_cnpj = ?, confianca_valor = ?, confianca_vencimento = ?,
                confianca_codigo = ?, origem_cnpj = ?, origem_valor = ?, origem_vencimento = ?,
                origem_codigo = ?, origem_operadora = ?, confianca_operadora = ?,
                metodo_identificacao_loja = ?, cnpj_live_identificado = ?, validacao_cidade = ?,
                validacao_uf = ?, resultado_identificacao_loja = ?, auditoria_loja_json = ?,
                razao_social = ?, referencia = ?, codigo_cliente = ?,
                numero_fatura = ?, cnpj_fornecedor = ?, outros_cnpjs = ?, avisos_parser = ?
            WHERE id = ?
            """,
            (
                destino.name if destino else "",
                str(destino) if destino else "",
                cnpj,
                loja["id"] if loja else None,
                dados["operadora"],
                float(dados["valor"]) if dados["valor"] else None,
                dados["vencimento"],
                dados["codigo_fatura"],
                novo_status,
                "; ".join(dict.fromkeys(motivos)),
                texto[:200000],
                dados.get("parser_utilizado", "generico"),
                dados.get("confianca", {}).get("cnpj", 0.0),
                dados.get("confianca", {}).get("valor", 0.0),
                dados.get("confianca", {}).get("vencimento", 0.0),
                dados.get("confianca", {}).get("codigo", 0.0),
                dados.get("origem", {}).get("cnpj", ""),
                dados.get("origem", {}).get("valor", ""),
                dados.get("origem", {}).get("vencimento", ""),
                dados.get("origem", {}).get("codigo", ""),
                dados.get("origem", {}).get("operadora", ""),
                dados.get("confianca", {}).get("operadora", 0.0),
                resolucao_loja.metodo_identificacao_loja,
                cnpj,
                _bool_db(resolucao_loja.validacao_cidade),
                _bool_db(resolucao_loja.validacao_uf),
                resolucao_loja.resultado,
                resolucao_loja.auditoria_json(),
                dados.get("razao_social", ""),
                dados.get("referencia", ""),
                dados.get("codigo_cliente", ""),
                dados.get("numero_fatura", ""),
                dados.get("cnpj_fornecedor", ""),
                _json_lista(dados.get("outros_cnpjs", [])),
                _json_lista(dados.get("avisos", [])),
                fatura_id,
            ),
        )
    logger.info("Fatura reprocessada: %s", fatura_id)
    return RedirectResponse(f"/faturas/{fatura_id}/revisar?msg=Fatura reprocessada", status_code=303)
