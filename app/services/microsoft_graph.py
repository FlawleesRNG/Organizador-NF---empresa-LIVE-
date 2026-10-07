from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
import msal

from app.config import Settings


GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
SCOPES = ["https://graph.microsoft.com/.default"]


@dataclass
class GraphMessage:
    id: str
    subject: str
    sender: str
    received_at: str
    body_html: str
    has_attachments: bool


@dataclass
class GraphAttachment:
    id: str
    name: str
    content_type: str
    content_bytes: bytes


class GraphNotConfigured(RuntimeError):
    pass


class MicrosoftGraphClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        if not settings.graph_configurado:
            raise GraphNotConfigured("Integracao Microsoft 365 aguardando configuracao")
        authority = f"https://login.microsoftonline.com/{settings.tenant_id}"
        self.app = msal.ConfidentialClientApplication(
            settings.client_id,
            authority=authority,
            client_credential=settings.client_secret,
        )

    def _token(self) -> str:
        result = self.app.acquire_token_for_client(scopes=SCOPES)
        token = result.get("access_token")
        if not token:
            raise RuntimeError("Não foi possível adquirir token Microsoft Graph")
        return token

    async def _get(self, path_or_url: str, params: dict | None = None) -> dict:
        url = path_or_url if path_or_url.startswith("https://") else f"{GRAPH_ROOT}{path_or_url}"
        headers = {"Authorization": f"Bearer {self._token()}"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            return resp.json()

    async def listar_mensagens_telemiza(self) -> list[GraphMessage]:
        since = (datetime.now(timezone.utc) - timedelta(days=self.settings.mail_lookback_days)).isoformat()
        path = f"/users/{self.settings.shared_mailbox}/mailFolders/inbox/messages"
        params = {
            "$top": "50",
            "$select": "id,subject,receivedDateTime,from,body,hasAttachments",
            "$orderby": "receivedDateTime desc",
            "$filter": f"receivedDateTime ge {since}",
        }
        data = await self._get(path, params=params)
        mensagens: list[GraphMessage] = []
        for item in data.get("value", []):
            sender = (
                item.get("from", {})
                .get("emailAddress", {})
                .get("address", "")
                .strip()
                .lower()
            )
            if sender != self.settings.telemiza_sender:
                continue
            mensagens.append(
                GraphMessage(
                    id=item["id"],
                    subject=item.get("subject", ""),
                    sender=sender,
                    received_at=item.get("receivedDateTime", ""),
                    body_html=item.get("body", {}).get("content", ""),
                    has_attachments=bool(item.get("hasAttachments")),
                )
            )
        return mensagens

    async def listar_anexos_pdf(self, message_id: str) -> list[GraphAttachment]:
        data = await self._get(f"/users/{self.settings.shared_mailbox}/messages/{message_id}/attachments")
        anexos: list[GraphAttachment] = []
        for item in data.get("value", []):
            name = item.get("name", "")
            content_type = item.get("contentType", "")
            if not name.lower().endswith(".pdf") and content_type.lower() != "application/pdf":
                continue
            content = item.get("contentBytes")
            if not content:
                continue
            anexos.append(
                GraphAttachment(
                    id=item["id"],
                    name=name,
                    content_type=content_type,
                    content_bytes=base64.b64decode(content),
                )
            )
        return anexos
