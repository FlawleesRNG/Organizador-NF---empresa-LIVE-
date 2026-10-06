# Telemiza / Organizador de Faturas

Sistema local para importar, identificar, revisar e arquivar faturas da LIVE!.

## Principais recursos

- Upload de PDF individual ou ZIP com múltiplos PDFs.
- SHA-256 por PDF para evitar duplicidade.
- Detecção automática de operadora com aliases e confiança.
- Identificação de CNPJ LIVE! pela raiz `35.303.139`.
- Vínculo de loja somente por match exato do CNPJ completo na base mestre.
- Auditoria da decisão de loja por fatura.
- Tela de revisão para casos sem confiança suficiente.
- Histórico, dashboard e cadastro mestre de lojas.

## Como iniciar

No Windows:

```bat
iniciar.bat
```

Ou manualmente:

```powershell
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Acesse:

```text
http://127.0.0.1:8000/
```

## Segurança de dados

O repositório não versiona:

- banco SQLite local (`*.db`);
- PDFs reais em `data/`;
- backups;
- logs;
- `.env`;
- ambiente virtual.

Use `.env.example` como referência para configuração local.

## Testes

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -q
```

As amostras reais confirmadas ficam fora do versionamento por conterem documentos sensíveis. O manifesto em `tests/amostras_confirmadas/manifest.json` documenta os cenários esperados quando esses arquivos estiverem presentes localmente.
