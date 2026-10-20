"""Usuários do painel web: senha (scrypt), sessões por cookie e termos de uso."""

import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from importlib.resources import files
from pathlib import Path

from psycopg import AsyncConnection, Connection

from cnpj_api.auth import generate_key, token_hash

_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
MIN_SENHA = 10


def hash_password(senha: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(senha.encode(), salt=salt, dklen=32, **_SCRYPT)
    b64 = base64.b64encode
    return f"scrypt${_SCRYPT['n']}${_SCRYPT['r']}${_SCRYPT['p']}${b64(salt).decode()}${b64(digest).decode()}"


def verify_password(senha: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
    except ValueError:
        return False
    if algo != "scrypt":
        return False
    calc = hashlib.scrypt(senha.encode(), salt=base64.b64decode(salt), dklen=32, n=int(n), r=int(r), p=int(p))
    return hmac.compare_digest(calc, base64.b64decode(digest))


def validate_password(senha: str) -> None:
    if len(senha) < MIN_SENHA:
        raise ValueError(f"a senha deve ter ao menos {MIN_SENHA} caracteres")
    if senha.isdigit() or senha.isalpha():
        raise ValueError("a senha deve misturar letras e números ou símbolos")


# ---------------------------------------------------------------- termos de uso


def terms(path: str | None) -> tuple[str, str]:
    """(versão, texto em Markdown). A primeira linha do arquivo é ``versao: AAAA-MM-DD``."""
    raw = Path(path).read_text(encoding="utf-8") if path else files("cnpj_api").joinpath("termos.md").read_text("utf-8")
    first, _, body = raw.partition("\n")
    versao = first.removeprefix("versao:").strip()
    return versao, body.strip()


# ---------------------------------------------------------------- criação (síncrona, usada pela CLI e pelo admin)

_CREATE_USER = """
INSERT INTO app.usuario (email, nome, senha_hash, papel) VALUES (%s, %s, %s, %s) RETURNING id
"""
_CREATE_PERSONAL_KEY = """
INSERT INTO app.api_key (nome, prefixo, hash, plano_id, usuario_id, pessoal) VALUES (%s, %s, %s, %s, %s, true)
"""


def create_user_sync(conn: Connection, email: str, nome: str, senha: str, papel: str = "usuario",
                     plano: str = "pro") -> int:  # fmt: skip
    validate_password(senha)
    with conn.transaction():
        uid = conn.execute(_CREATE_USER, (email.strip().lower(), nome.strip(), hash_password(senha), papel)).fetchone()[
            0
        ]
        _, prefixo, digest = generate_key()  # chave interna: o segredo é descartado
        conn.execute(_CREATE_PERSONAL_KEY, (f"painel:{email}", prefixo, digest, plano, uid))
    return uid


async def create_user(conn: AsyncConnection, email: str, nome: str, senha: str, papel: str, plano: str) -> int:
    validate_password(senha)
    async with conn.transaction():
        cur = await conn.execute(_CREATE_USER, (email.strip().lower(), nome.strip(), hash_password(senha), papel))
        uid = (await cur.fetchone())["id"]
        _, prefixo, digest = generate_key()
        await conn.execute(_CREATE_PERSONAL_KEY, (f"painel:{email}", prefixo, digest, plano, uid))
    return uid


async def create_session(conn: AsyncConnection, usuario_id: int, hours: int, ip: str | None,
                         user_agent: str | None) -> str:  # fmt: skip
    token = secrets.token_urlsafe(32)
    await conn.execute(
        """INSERT INTO app.sessao (token_hash, usuario_id, expira_em, ip, user_agent)
           VALUES (%s, %s, now() + %s, %s, %s)""",
        (token_hash(token), usuario_id, timedelta(hours=hours), ip, user_agent),
    )
    await conn.execute("UPDATE app.usuario SET ultimo_login_em = now() WHERE id = %s", (usuario_id,))
    return token
