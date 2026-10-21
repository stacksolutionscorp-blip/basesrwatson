import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", "postgresql://cnpj:cnpj@localhost:5432/cnpj")
    )
    # Índice com as pastas mensais (AAAA-MM/). A Receita já mudou esse endereço
    # algumas vezes; ajuste aqui se mudar de novo.
    rf_base_url: str = field(
        default_factory=lambda: _env(
            "RF_BASE_URL", "https://arquivos.receitafederal.gov.br/dados/cnpj/dados_abertos_cnpj/"
        )
    )
    data_dir: Path = field(default_factory=lambda: Path(_env("DATA_DIR", "./data")))
    download_concurrency: int = field(default_factory=lambda: int(_env("DOWNLOAD_CONCURRENCY", "3")))
    # Tamanho de cada lote lido do CSV (MB descompactados) antes de ir para o COPY.
    batch_mb: int = field(default_factory=lambda: int(_env("ETL_BATCH_MB", "128")))
    index_workers: int = field(default_factory=lambda: int(_env("ETL_INDEX_WORKERS", "2")))
    # Aborta o swap se uma tabela nova tiver menos que esta fração das linhas atuais.
    min_row_ratio: float = field(default_factory=lambda: float(_env("ETL_MIN_ROW_RATIO", "0.9")))
    keep_zips: bool = field(default_factory=lambda: _env("ETL_KEEP_ZIPS", "1") == "1")
    check_interval_hours: float = field(default_factory=lambda: float(_env("ETL_CHECK_INTERVAL_HOURS", "24")))

    # Carga regional (ver cnpj_etl.regiao). Vazio = Brasil inteiro.
    regiao_centro: str = field(default_factory=lambda: _env("ETL_CENTRO", ""))
    regiao_raio_km: float = field(default_factory=lambda: float(_env("ETL_RAIO_KM", "0") or 0))
    regiao_ufs: list[str] = field(default_factory=lambda: [u for u in _env("ETL_UFS", "").split(",") if u.strip()])
    regiao_municipios_ibge: list[int] = field(
        default_factory=lambda: [int(m) for m in _env("ETL_MUNICIPIOS_IBGE", "").split(",") if m.strip()]
    )
    somente_ativas: bool = field(default_factory=lambda: _env("ETL_SOMENTE_ATIVAS", "0") == "1")

    nominatim_url: str = field(default_factory=lambda: _env("NOMINATIM_URL", "http://localhost:8080"))
    nominatim_rps: float = field(default_factory=lambda: float(_env("NOMINATIM_RPS", "1")))
    nominatim_concurrency: int = field(default_factory=lambda: int(_env("NOMINATIM_CONCURRENCY", "1")))
    nominatim_user_agent: str = field(default_factory=lambda: _env("NOMINATIM_USER_AGENT", "cnpj-intel-etl/0.1"))
    municipios_url: str = field(
        default_factory=lambda: _env(
            "MUNICIPIOS_URL",
            "https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv",
        )
    )


def get_settings() -> Settings:
    return Settings()
