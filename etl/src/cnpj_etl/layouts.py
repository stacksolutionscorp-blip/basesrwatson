"""Layout dos arquivos dos Dados Abertos CNPJ (sem cabeçalho, ``;``, latin-1).

Fonte: "Metadados CNPJ" publicado pela Receita junto com os arquivos.
"""

import re
from dataclasses import dataclass

EMPRESAS = [
    "cnpj_basico",
    "razao_social",
    "natureza_juridica",
    "qualificacao_responsavel",
    "capital_social",
    "porte",
    "ente_federativo",
]

ESTABELECIMENTOS = [
    "cnpj_basico",
    "cnpj_ordem",
    "cnpj_dv",
    "identificador_matriz_filial",
    "nome_fantasia",
    "situacao_cadastral",
    "data_situacao_cadastral",
    "motivo_situacao_cadastral",
    "nome_cidade_exterior",
    "pais",
    "data_inicio_atividade",
    "cnae_fiscal_principal",
    "cnae_fiscal_secundaria",
    "tipo_logradouro",
    "logradouro",
    "numero",
    "complemento",
    "bairro",
    "cep",
    "uf",
    "municipio",
    "ddd_1",
    "telefone_1",
    "ddd_2",
    "telefone_2",
    "ddd_fax",
    "fax",
    "correio_eletronico",
    "situacao_especial",
    "data_situacao_especial",
]

SOCIOS = [
    "cnpj_basico",
    "identificador_socio",
    "nome_socio",
    "cnpj_cpf_socio",
    "qualificacao_socio",
    "data_entrada_sociedade",
    "pais",
    "representante_legal",
    "nome_representante",
    "qualificacao_representante",
    "faixa_etaria",
]

SIMPLES = [
    "cnpj_basico",
    "opcao_simples",
    "data_opcao_simples",
    "data_exclusao_simples",
    "opcao_mei",
    "data_opcao_mei",
    "data_exclusao_mei",
]

AUX = ["codigo", "descricao"]


@dataclass(frozen=True)
class Dataset:
    name: str  # tabela de destino em rf
    pattern: re.Pattern[str]  # nome do ZIP publicado
    columns: list[str]
    multipart: bool  # Empresas0..9 etc.


DATASETS: list[Dataset] = [
    Dataset("cnae", re.compile(r"^Cnaes\.zip$", re.IGNORECASE), AUX, False),
    Dataset("motivo_situacao", re.compile(r"^Motivos\.zip$", re.IGNORECASE), AUX, False),
    Dataset("municipio", re.compile(r"^Municipios\.zip$", re.IGNORECASE), AUX, False),
    Dataset("natureza_juridica", re.compile(r"^Naturezas\.zip$", re.IGNORECASE), AUX, False),
    Dataset("pais", re.compile(r"^Paises\.zip$", re.IGNORECASE), AUX, False),
    Dataset("qualificacao", re.compile(r"^Qualificacoes\.zip$", re.IGNORECASE), AUX, False),
    Dataset("empresa", re.compile(r"^Empresas\d+\.zip$", re.IGNORECASE), EMPRESAS, True),
    Dataset("estabelecimento", re.compile(r"^Estabelecimentos\d+\.zip$", re.IGNORECASE), ESTABELECIMENTOS, True),
    Dataset("socio", re.compile(r"^Socios\d+\.zip$", re.IGNORECASE), SOCIOS, True),
    Dataset("simples", re.compile(r"^Simples\.zip$", re.IGNORECASE), SIMPLES, False),
]

AUX_TABLES = [d.name for d in DATASETS if d.columns is AUX]


def dataset_for(filename: str) -> Dataset | None:
    for ds in DATASETS:
        if ds.pattern.match(filename):
            return ds
    return None


def missing_datasets(filenames: list[str]) -> list[str]:
    """Datasets sem nenhum ZIP na lista (indica mês publicado pela metade)."""
    found = {ds.name for f in filenames if (ds := dataset_for(f))}
    return [d.name for d in DATASETS if d.name not in found]
