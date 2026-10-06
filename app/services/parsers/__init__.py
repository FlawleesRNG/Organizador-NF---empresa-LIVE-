from app.services.parsers.base import ParserGenerico, ResultadoParser
from app.services.parsers.unifique import ParserUnifique
from app.services.parsers.vivo import ParserVivo


PARSERS = {
    "VIVO": ParserVivo(),
    "UNIFIQUE": ParserUnifique(),
}


def selecionar_parser(operadora: str | None):
    return PARSERS.get((operadora or "").upper(), ParserGenerico())
