import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", "postgresql://cnpj:cnpj@localhost:5432/cnpj")
    )
    redis_url: str = field(default_factory=lambda: _env("REDIS_URL", "redis://localhost:6379/0"))
    pool_min: int = field(default_factory=lambda: int(_env("API_POOL_MIN", "2")))
    pool_max: int = field(default_factory=lambda: int(_env("API_POOL_MAX", "20")))
    cache_ttl: int = field(default_factory=lambda: int(_env("API_CACHE_TTL", "86400")))
    statement_timeout_ms: int = field(default_factory=lambda: int(_env("API_STATEMENT_TIMEOUT_MS", "15000")))
    cors_origins: list[str] = field(default_factory=lambda: [o for o in _env("API_CORS_ORIGINS", "*").split(",") if o])
    # Considera X-Forwarded-For (atrás de proxy reverso) para o IP do log de acesso.
    trust_proxy: bool = field(default_factory=lambda: _env("API_TRUST_PROXY", "0") == "1")
    # Permite webhooks para endereços internos (só para desenvolvimento/testes).
    webhook_allow_private: bool = field(default_factory=lambda: _env("API_WEBHOOK_ALLOW_PRIVATE", "0") == "1")
    graph_max_nodes: int = field(default_factory=lambda: int(_env("API_GRAPH_MAX_NODES", "300")))


def get_settings() -> Settings:
    return Settings()
