from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from app.database import BASE_DIR


load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    tenant_id: str
    client_id: str
    client_secret: str
    shared_mailbox: str
    telemiza_sender: str
    mail_sync_interval_seconds: int
    mail_lookback_days: int

    @property
    def graph_configurado(self) -> bool:
        return all([self.tenant_id, self.client_id, self.client_secret, self.shared_mailbox])


def _int_env(nome: str, padrao: int) -> int:
    try:
        return int(os.getenv(nome, str(padrao)))
    except ValueError:
        return padrao


def get_settings() -> Settings:
    return Settings(
        tenant_id=os.getenv("TENANT_ID", "").strip(),
        client_id=os.getenv("CLIENT_ID", "").strip(),
        client_secret=os.getenv("CLIENT_SECRET", "").strip(),
        shared_mailbox=os.getenv("SHARED_MAILBOX", "").strip(),
        telemiza_sender=os.getenv("TELEMIZA_SENDER", "faturas@telemiza.com.br").strip().lower(),
        mail_sync_interval_seconds=max(30, _int_env("MAIL_SYNC_INTERVAL_SECONDS", 300)),
        mail_lookback_days=max(1, _int_env("MAIL_LOOKBACK_DAYS", 30)),
    )
