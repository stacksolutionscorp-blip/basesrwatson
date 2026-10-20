"""Normalização de texto usada na busca (trigram) e na chave de endereço.

A mesma regra é aplicada no ETL (via polars, em ``cnpj_etl.transform``) e na API,
para que o termo pesquisado e a coluna indexada sejam comparáveis.
"""

import re
import unicodedata

_SPACES = re.compile(r"\s+")


def normalize_text(value: str | None) -> str | None:
    """MAIÚSCULAS, sem acentos e com espaços colapsados. ``None``/vazio → ``None``."""
    if value is None:
        return None
    decomposed = unicodedata.normalize("NFKD", value)
    no_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
    out = _SPACES.sub(" ", no_accents).strip().upper()
    return out or None


# CPF completo dentro de um texto (ex.: razão social de empresário individual/MEI: "JOSE DA SILVA 12345678900").
_CPF_IN_TEXT = re.compile(r"(?<!\d)\d{3}\.?(\d{3})\.?(\d{3})-?\d{2}(?!\d)")


def mask_cpf(text: str | None) -> str | None:
    """Mascara CPFs completos no mesmo formato que a Receita usa para sócios: ***456789**."""
    if text is None:
        return None
    return _CPF_IN_TEXT.sub(lambda m: f"***{m.group(1)}{m.group(2)}**", text)
