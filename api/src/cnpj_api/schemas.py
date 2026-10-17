"""Modelos de resposta (documentação OpenAPI e contrato com quem integra)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class Codigo(BaseModel):
    codigo: int | None
    descricao: str | None


class Situacao(BaseModel):
    codigo: int | None
    descricao: str | None
    data: date | None
    motivo: Codigo | None


class Municipio(BaseModel):
    codigo_siafi: int | None = Field(description="Código usado pela Receita (SIAFI/TOM)")
    codigo_ibge: int | None
    nome: str | None


class Endereco(BaseModel):
    tipo_logradouro: str | None
    logradouro: str | None
    numero: str | None
    complemento: str | None
    bairro: str | None
    cep: str | None
    municipio: Municipio
    uf: str | None
    pais: Codigo | None
    cidade_exterior: str | None
    lat: float | None
    lng: float | None
    geo_precisao: Literal["municipio", "cep", "rua", "numero"] | None


class Contato(BaseModel):
    telefones: list[str]
    email: str | None


class Simples(BaseModel):
    optante: bool | None
    data_opcao: date | None
    data_exclusao: date | None
    mei: bool | None
    data_opcao_mei: date | None
    data_exclusao_mei: date | None


class Representante(BaseModel):
    nome: str | None
    cpf: str | None = Field(description="Mascarado, como publicado pela Receita")
    qualificacao: Codigo | None


class Socio(BaseModel):
    tipo: Literal["PJ", "PF", "estrangeiro"] | None
    nome: str | None
    cpf_cnpj: str | None = Field(description="PF: CPF mascarado como publicado pela Receita (***123456**)")
    qualificacao: Codigo | None
    data_entrada: date | None
    pais: Codigo | None
    faixa_etaria: str | None
    representante: Representante | None


class FatorRisco(BaseModel):
    fator: str
    pontos: int


class ScoreRisco(BaseModel):
    score: int = Field(ge=0, le=100, description="0 = menor risco, 100 = maior risco")
    nivel: Literal["baixo", "medio", "alto"]
    fatores: list[FatorRisco]


class Perfil(BaseModel):
    cnpj: str
    cnpj_formatado: str
    cnpj_basico: str
    matriz: bool | None
    razao_social: str | None
    nome_fantasia: str | None
    situacao: Situacao
    situacao_especial: str | None
    data_situacao_especial: date | None
    data_inicio: date | None
    idade_anos: float | None
    natureza_juridica: Codigo | None
    porte: Codigo | None
    capital_social: Decimal | None
    ente_federativo: str | None
    cnae_principal: Codigo | None
    cnaes_secundarios: list[Codigo]
    endereco: Endereco
    contato: Contato
    simples: Simples | None
    socios: list[Socio]
    qtd_estabelecimentos: int
    score_risco: ScoreRisco
    referencia: str | None = Field(description="Mês da base da Receita (AAAA-MM)")


class EstabelecimentoResumo(BaseModel):
    cnpj: str
    cnpj_formatado: str
    matriz: bool | None
    razao_social: str | None
    nome_fantasia: str | None
    situacao: str | None
    data_inicio: date | None
    cnae_principal: int | None
    porte: str | None
    capital_social: Decimal | None
    municipio: str | None
    uf: str | None
    cep: str | None
    lat: float | None
    lng: float | None
    distancia_km: float | None = None


class Pagina(BaseModel):
    pagina: int
    por_pagina: int
    tem_mais: bool


class ListaEstabelecimentos(BaseModel):
    resultados: list[EstabelecimentoResumo]
    paginacao: Pagina


class VinculoSocio(BaseModel):
    cnpj_basico: str
    razao_social: str | None
    qualificacao: Codigo | None
    data_entrada: date | None


class PessoaSocia(BaseModel):
    nome: str | None
    cpf_cnpj: str | None
    tipo: Literal["PJ", "PF", "estrangeiro"] | None
    empresas: list[VinculoSocio]


class ListaSocios(BaseModel):
    resultados: list[PessoaSocia]


class NoGrafo(BaseModel):
    id: str
    tipo: Literal["empresa", "pessoa"]
    label: str | None
    nivel: int
    dados: dict


class ArestaGrafo(BaseModel):
    source: str = Field(description="Sócio (pessoa ou empresa)")
    target: str = Field(description="Empresa")
    qualificacao: str | None
    data_entrada: date | None


class Grafo(BaseModel):
    nodes: list[NoGrafo]
    edges: list[ArestaGrafo]
    truncado: bool = Field(description="True se o limite de nós foi atingido")


class LoteEntrada(BaseModel):
    cnpjs: list[str] = Field(min_length=1, max_length=500)


class LoteItem(BaseModel):
    cnpj: str
    ok: bool
    erro: str | None = None
    dados: Perfil | None = None


class LoteResposta(BaseModel):
    resultados: list[LoteItem]


class MonitorEntrada(BaseModel):
    cnpjs: list[str] = Field(min_length=1, max_length=1000)


class MonitorItem(BaseModel):
    cnpj: str
    criado_em: datetime


class Alteracao(BaseModel):
    id: int
    cnpj: str
    referencia: str
    tipo: Literal["situacao", "endereco", "socios"]
    antes: dict | list | None
    depois: dict | list | None
    detectado_em: datetime


class WebhookEntrada(BaseModel):
    url: str = Field(pattern=r"^https?://", description="Recebe POST JSON a cada alteração detectada")


class Webhook(BaseModel):
    id: int
    url: str
    ativo: bool
    criado_em: datetime
    segredo: str | None = Field(
        None, description="Mostrado só na criação. Assinatura: X-CNPJ-Signature: sha256=HMAC(segredo, corpo)"
    )


class UsoDia(BaseModel):
    dia: date
    requisicoes: int
    erros: int


class Uso(BaseModel):
    chave: str
    plano: str
    limites: dict[str, int]
    dias: list[UsoDia]
    por_rota: dict[str, int]
