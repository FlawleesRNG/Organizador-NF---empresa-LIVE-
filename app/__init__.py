from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import BASE_DIR, init_db
from app.routes import dashboard, faturas, lojas
from app.services.email_sync import loop_sincronizacao
from app.services.manutencao import corrigir_identidade_faturas_pendentes
from app.utils.formatadores import formatar_cnpj, formatar_data_br, formatar_valor, nome_exibicao_loja, status_badge


LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=LOG_DIR / "app.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("telemiza")

app = FastAPI(title="Organizador de Faturas")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["cnpj"] = formatar_cnpj
templates.env.filters["data_br"] = formatar_data_br
templates.env.filters["valor_br"] = formatar_valor
templates.env.filters["status_badge"] = status_badge
templates.env.filters["from_json"] = lambda value: json.loads(value or "{}")
templates.env.filters["loja_display"] = nome_exibicao_loja

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.state.templates = templates


@app.on_event("startup")
async def startup() -> None:
    init_db()
    for pasta in ["entrada", "arquivadas", "revisar", "caixa_compartilhada/originais", "caixa_compartilhada/processamento"]:
        Path(BASE_DIR / "data" / pasta).mkdir(parents=True, exist_ok=True)
    try:
        resultado_identidade = corrigir_identidade_faturas_pendentes()
        logger.info("Correcao automatica de identidade no startup: %s", resultado_identidade)
    except Exception:
        logger.exception("Falha ao corrigir automaticamente CNPJ/loja/operadora no startup")
    app.state.mail_sync_stop = asyncio.Event()
    app.state.mail_sync_task = asyncio.create_task(loop_sincronizacao(app.state.mail_sync_stop))
    logger.info("Aplicacao inicializada")


@app.on_event("shutdown")
async def shutdown() -> None:
    stop = getattr(app.state, "mail_sync_stop", None)
    task = getattr(app.state, "mail_sync_task", None)
    if stop:
        stop.set()
    if task:
        await task


@app.exception_handler(Exception)
async def erro_inesperado(request: Request, exc: Exception) -> HTMLResponse:
    logger.exception("Erro inesperado em %s", request.url.path)
    return templates.TemplateResponse(
        request,
        "erro.html",
        {"mensagem": "Ocorreu um erro inesperado. Veja o log tecnico."},
        status_code=500,
    )


app.include_router(dashboard.router)
app.include_router(lojas.router)
app.include_router(faturas.router)
