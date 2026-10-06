from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


OPERADORAS = {
    "VIVO",
    "UNIFIQUE",
    "CLARO",
    "TIM",
    "OI",
    "ALGAR",
    "VERO",
    "CACTA TELECOM",
    "4B TELECOM",
    "SUSTENTA",
    "VOZIO",
    "BLUE",
    "PONTO TELECOM",
    "FIBRION",
    "ISPTEC",
    "EXO",
    "NIPBR",
}

OPERADORA_ALIASES = {
    "VIVO": ("VIVO", "TELEFONICA BRASIL", "TELEFÔNICA BRASIL"),
    "UNIFIQUE": ("UNIFIQUE", "UNIFIQUE TELECOMUNICACOES", "UNIFIQUE TELECOMUNICAÇÕES"),
    "CLARO": ("CLARO",),
    "TIM": ("TIM", "TIM S/A", "TIM SA"),
    "OI": ("OI",),
    "ALGAR": ("ALGAR", "ALGAR TELECOM"),
    "VERO": ("VERO", "VERO INTERNET"),
    "CACTA TELECOM": ("CACTA TELECOM", "CACTA TELECOMUNICACOES", "CACTA TELECOMUNICAÇÕES"),
    "4B TELECOM": ("4B TELECOM", "4B TELECOM SERVICOS DE COMUNICACAO", "4B TELECOM SERVIÇOS DE COMUNICAÇÃO"),
    "SUSTENTA": ("SUSTENTA", "SUSTENTA TELECOM", "SUSTENTA TELECOMUNICACOES", "SUSTENTA TELECOMUNICAÇÕES"),
    "VOZIO": ("VOZIO", "VOZIO COMUNICACAO", "VOZIO COMUNICAÇÃO"),
    "BLUE": ("BLUE", "BLUE TELECOM", "BLUE INTERNET"),
    "PONTO TELECOM": ("PONTO TELECOM", "PONTO TELECOM COMUNICACOES", "PONTO TELECOM COMUNICAÇÕES"),
    "FIBRION": ("FIBRION", "FIBRION INTERNET"),
    "ISPTEC": ("ISPTEC", "ISPTEC SISTEMAS DE COMUNICACAO", "ISPTEC SISTEMAS DE COMUNICAÇÃO"),
    "EXO": ("EXO", "CONNECTRONIC", "CONNECTRONIC SERVICOS", "CONNECTRONIC SERVIÇOS"),
    "NIPBR": ("NIPBR", "NIP BR", "NIPBR TELECOM"),
}


def somente_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def normalizar_cnpj(cnpj: str | None) -> str:
    digitos = somente_digitos(cnpj)
    return digitos if len(digitos) == 14 else ""


def normalizar_cnpj_flex(cnpj: str | None) -> str:
    return somente_digitos(cnpj)


def validar_cnpj(cnpj: str | None) -> bool:
    digitos = normalizar_cnpj(cnpj)
    if not digitos or digitos == digitos[0] * 14:
        return False

    def calcular(posicoes: int) -> int:
        soma = 0
        peso = posicoes - 7
        for item in digitos[:posicoes]:
            soma += int(item) * peso
            peso -= 1
            if peso < 2:
                peso = 9
        resto = soma % 11
        return 0 if resto < 2 else 11 - resto

    return calcular(12) == int(digitos[12]) and calcular(13) == int(digitos[13])


def formatar_cnpj(cnpj: str | None) -> str:
    digitos = normalizar_cnpj(cnpj)
    if not digitos:
        return cnpj or ""
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/{digitos[8:12]}-{digitos[12:]}"


def formatar_cnpj_arquivo(cnpj: str | None) -> str:
    digitos = normalizar_cnpj(cnpj)
    if not digitos:
        return "CNPJ-INVALIDO"
    return f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}-{digitos[8:12]}-{digitos[12:]}"


def normalizar_uf(uf: str | None) -> str:
    uf_limpa = re.sub(r"[^A-Za-z]", "", uf or "").upper()
    return uf_limpa[:2]


def normalizar_codigo_loja(codigo: str | None) -> str:
    texto = re.sub(r"\s+", "", codigo or "").upper()
    if not texto:
        return ""
    achado = re.fullmatch(r"L?(\d{1,6})", texto)
    if achado:
        return f"L{int(achado.group(1))}"
    return texto


def normalizar_nome_loja(nome: str | None) -> str:
    return re.sub(r"\s+", " ", (nome or "").strip()).upper()


def normalizar_cidade(cidade: str | None) -> str:
    texto = re.sub(r"\s+", " ", (cidade or "").strip())
    if not texto:
        return ""
    minusculas = {"de", "da", "do", "das", "dos", "e"}
    return " ".join(parte if parte in minusculas else parte.capitalize() for parte in texto.lower().split())


def nome_exibicao_loja(loja) -> str:
    if not loja:
        return ""
    if isinstance(loja, dict):
        get = loja.get
    else:
        keys = loja.keys()
        get = lambda key, default="": loja[key] if key in keys else default
    partes = []
    codigo = get("codigo_loja", "") or ""
    nome = get("nome", "") or get("nome_loja", "") or ""
    uf = get("uf", "") or get("uf_loja", "") or ""
    if codigo:
        partes.append(codigo)
    if nome:
        partes.append(normalizar_nome_loja(nome))
    if uf:
        partes.append(normalizar_uf(uf))
    return " - ".join(partes)


def _chave_operadora(valor: str | None) -> str:
    texto = (valor or "").upper()
    texto = (
        texto.replace("Á", "A").replace("À", "A").replace("Ã", "A").replace("Â", "A")
        .replace("É", "E").replace("Ê", "E")
        .replace("Í", "I")
        .replace("Ó", "O").replace("Ô", "O").replace("Õ", "O")
        .replace("Ú", "U").replace("Ç", "C")
    )
    return re.sub(r"[^A-Z0-9]", "", texto)


def normalizar_operadora(valor: str | None) -> str:
    chave = _chave_operadora(valor)
    if not chave:
        return ""
    for canonica, aliases in OPERADORA_ALIASES.items():
        if chave == _chave_operadora(canonica):
            return canonica
        for alias in aliases:
            if chave == _chave_operadora(alias):
                return canonica
    return ""


def normalizar_valor(valor: str | None) -> str:
    texto = (valor or "").strip().replace("R$", "").replace(" ", "")
    texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        return ""
    if numero <= 0:
        return ""
    return f"{numero:.2f}"


def formatar_valor(valor: str | float | Decimal | None) -> str:
    if valor in (None, ""):
        return ""
    try:
        numero = Decimal(str(valor))
    except InvalidOperation:
        return str(valor)
    return f"R${numero:.2f}".replace(".", ",")


def normalizar_data(valor: str | None) -> str:
    texto = (valor or "").strip()
    for formato in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            pass
    return ""


def formatar_data_br(valor: str | None) -> str:
    data_iso = normalizar_data(valor)
    if not data_iso:
        return valor or ""
    return datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")


def data_para_nome_arquivo(valor: str | None) -> str:
    data_iso = normalizar_data(valor)
    if not data_iso:
        return "DATA-INVALIDA"
    return datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d-%m-%Y")


def sanitizar_nome_path(valor: str | None, padrao: str = "SEM-NOME") -> str:
    texto = re.sub(r'[<>:"/\\|?*]', "-", valor or "")
    texto = texto.replace("..", ".")
    texto = re.sub(r"[\x00-\x1f]", "", texto)
    texto = re.sub(r"\s+", " ", texto).strip(" .")
    return texto or padrao


def status_badge(status: str | None) -> str:
    texto = re.sub(r"[^A-Za-z0-9]+", "-", status or "").strip("-")
    return texto.lower()
