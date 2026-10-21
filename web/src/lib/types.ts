// Tipos espelhando os modelos de resposta da API (api/src/cnpj_api/schemas.py).

export interface Codigo {
  codigo: number | null;
  descricao: string | null;
}

export interface Socio {
  tipo: "PJ" | "PF" | "estrangeiro" | null;
  nome: string | null;
  cpf_cnpj: string | null;
  qualificacao: Codigo | null;
  data_entrada: string | null;
  pais: Codigo | null;
  faixa_etaria: string | null;
  representante: { nome: string | null; cpf: string | null; qualificacao: Codigo | null } | null;
}

export interface ScoreRisco {
  score: number;
  nivel: "baixo" | "medio" | "alto";
  fatores: { fator: string; pontos: number }[];
}

export interface Perfil {
  cnpj: string;
  cnpj_formatado: string;
  cnpj_basico: string;
  matriz: boolean | null;
  razao_social: string | null;
  nome_fantasia: string | null;
  situacao: { codigo: number | null; descricao: string | null; data: string | null; motivo: Codigo | null };
  situacao_especial: string | null;
  data_situacao_especial: string | null;
  data_inicio: string | null;
  idade_anos: number | null;
  natureza_juridica: Codigo | null;
  porte: Codigo | null;
  capital_social: string | number | null;
  ente_federativo: string | null;
  cnae_principal: Codigo | null;
  cnaes_secundarios: Codigo[];
  endereco: {
    tipo_logradouro: string | null;
    logradouro: string | null;
    numero: string | null;
    complemento: string | null;
    bairro: string | null;
    cep: string | null;
    municipio: { codigo_siafi: number | null; codigo_ibge: number | null; nome: string | null };
    uf: string | null;
    pais: Codigo | null;
    cidade_exterior: string | null;
    lat: number | null;
    lng: number | null;
    geo_precisao: "municipio" | "cep" | "rua" | "numero" | null;
  };
  contato: { telefones: string[]; email: string | null };
  simples: {
    optante: boolean | null;
    data_opcao: string | null;
    data_exclusao: string | null;
    mei: boolean | null;
    data_opcao_mei: string | null;
    data_exclusao_mei: string | null;
  } | null;
  socios: Socio[];
  qtd_estabelecimentos: number;
  score_risco: ScoreRisco;
  referencia: string | null;
}

export interface EstabelecimentoResumo {
  cnpj: string;
  cnpj_formatado: string;
  matriz: boolean | null;
  razao_social: string | null;
  nome_fantasia: string | null;
  situacao: string | null;
  data_inicio: string | null;
  cnae_principal: number | null;
  porte: string | null;
  capital_social: string | number | null;
  municipio: string | null;
  uf: string | null;
  cep: string | null;
  lat: number | null;
  lng: number | null;
  distancia_km: number | null;
}

export interface Lista<T> {
  resultados: T[];
  paginacao: { pagina: number; por_pagina: number; tem_mais: boolean };
}

export interface PessoaSocia {
  nome: string | null;
  cpf_cnpj: string | null;
  tipo: "PJ" | "PF" | "estrangeiro" | null;
  empresas: { cnpj_basico: string; razao_social: string | null; qualificacao: Codigo | null; data_entrada: string | null }[];
}

export interface Sugestoes {
  empresas: {
    cnpj: string;
    razao_social: string | null;
    nome_fantasia: string | null;
    uf: string | null;
    situacao: string | null;
    origem: string;
  }[];
  socios: { nome: string | null; cpf_cnpj: string | null; tipo: string | null }[];
}

export interface Grafo {
  nodes: { id: string; tipo: "empresa" | "pessoa"; label: string | null; nivel: number; dados: Record<string, unknown> }[];
  edges: { source: string; target: string; qualificacao: string | null; data_entrada: string | null }[];
  truncado: boolean;
}

export interface Alteracao {
  id: number;
  cnpj: string;
  referencia: string;
  tipo: "situacao" | "endereco" | "socios";
  antes: unknown;
  depois: unknown;
  detectado_em: string;
}

export interface Webhook {
  id: number;
  url: string;
  ativo: boolean;
  criado_em: string;
  segredo: string | null;
}

export interface Limites {
  req_por_minuto: number;
  req_por_dia: number;
  lote_max: number;
  export_max: number;
  monitor_max: number;
}

export interface Usuario {
  id: number;
  email: string;
  nome: string;
  papel: "admin" | "usuario";
  termos_versao: string | null;
  termos_vigentes: string;
  termos_pendentes: boolean;
  plano: Limites & { id: string };
}

export interface Uso {
  chave: string;
  plano: string;
  limites: Limites;
  dias: { dia: string; requisicoes: number; erros: number }[];
  por_rota: Record<string, number>;
}

export interface Municipio {
  codigo_siafi: number;
  codigo_ibge: number;
  nome: string;
  uf: string;
  lat: number;
  lng: number;
}

export type LeadStatus = "novo" | "contatado" | "interessado" | "proposta" | "fechado" | "sem_interesse";

export interface Lead {
  cnpj: string;
  cnpj_formatado: string;
  razao_social: string | null;
  nome_fantasia: string | null;
  cnae_principal: { codigo: number | null; descricao: string | null };
  telefones: { numero: string; celular: boolean; whatsapp: string | null }[];
  email: string | null;
  endereco: string | null;
  bairro: string | null;
  cep: string | null;
  municipio: string | null;
  uf: string | null;
  distancia_km: number | null;
  lat: number | null;
  lng: number | null;
  porte: string | null;
  capital_social: string | number | null;
  idade_anos: number | null;
  decisores: { nome: string; qualificacao: string | null; tipo: string | null }[];
  score: number;
  fatores: { fator: string; pontos: number }[];
  status: LeadStatus;
  nota: string | null;
  proximo_contato: string | null;
  status_em: string | null;
  responsavel: string | null;
}

export interface LeadsConfig {
  centro: { lat: number; lng: number; nome: string };
  raio_km: number;
  segmentos: { id: string; nome: string; consorcio: string; cnaes: { codigo: number; descricao: string | null }[] }[];
  status: LeadStatus[];
}
