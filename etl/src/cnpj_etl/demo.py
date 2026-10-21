"""Gera ZIPs no formato dos Dados Abertos CNPJ, com as sujeiras reais dos arquivos:
latin-1/cp1252, tudo entre aspas, ``;`` dentro de campo, datas "0"/"00000000",
capital com vírgula, bytes NUL, CRLF, quebra de linha dentro de campo e duplicatas.

Usado nos testes e pelo comando ``cnpj-etl demo``, que carrega esta amostra para
ver a plataforma funcionando sem baixar a base da Receita.
"""

import zipfile
from pathlib import Path

from cnpj_core import compute_dv


def cnpj(basico: str, ordem: str) -> tuple[str, str, str]:
    return basico, ordem, compute_dv(basico + ordem)


def line(*fields: str) -> str:
    return ";".join(f'"{f}"' for f in fields)


def estab(basico, ordem, *, fantasia="", situacao="02", inicio="20150310", cnae="1091102",
          secundarias="", logradouro="DAS FLORES", numero="123", uf="SP", municipio="7107",
          cep="01001000", email="", matriz=None, ddd="11", telefone="33334444", ddd2="", telefone2="",
          bairro="CENTRO"):  # fmt: skip
    b, o, dv = cnpj(basico, ordem)
    mf = matriz or ("1" if ordem == "0001" else "2")
    return line(
        b, o, dv, mf, fantasia, situacao, "20150310", "00", "", "", inicio, cnae, secundarias,
        "RUA", logradouro, numero, "SALA 2", bairro, cep, uf, municipio,
        ddd, telefone, ddd2, telefone2, "", "", email, "", "",
    )  # fmt: skip


EMPRESAS_0 = [
    line("11222333", "PADARIA SÃO JOÃO LTDA", "2062", "49", "15000,00", "01", ""),
    line("44555666", "HOLDING AÇÚCAR; PARTICIPAÇÕES S.A.", "2054", "10", "1.500.000,50", "05", ""),
    line("77888999", "JOSÉ DA SILVA 12345678900", "2135", "50", "0,00", "01", ""),
]
EMPRESAS_1 = [
    line("12ABC345", "EMPRESA ALFANUMÉRICA LTDA", "2062", "49", "1000,00", "03", ""),
    # duplicata (a Receita às vezes publica a mesma linha em dois arquivos)
    line("77888999", "JOSÉ DA SILVA 12345678900", "2135", "50", "0,00", "01", ""),
]

ESTABELECIMENTOS_0 = [
    estab("11222333", "0001", fantasia="PADARIA SÃO JOÃO", secundarias="4721102,5611203",
          email="CONTATO@PADARIA.COM.BR"),
    estab("11222333", "0002", fantasia="PADARIA FILIAL", logradouro="AV. BRASIL", numero="S/N",
          municipio="6001", uf="RJ", cep="20040002"),
    estab("44555666", "0001", situacao="08", inicio="0", cnae="6462000",
          logradouro="DA LINHA\nQUEBRADA", numero="10"),
]  # fmt: skip
ESTABELECIMENTOS_1 = [
    estab("77888999", "0001", fantasia="", inicio="00000000", cnae="4520001"),
    estab("12ABC345", "01DE", fantasia="ALFA", municipio="9999"),  # município sem centroide
]

SOCIOS_0 = [
    line("11222333", "2", "JOSÉ DA SILVA", "***123456**", "49", "20150310", "", "***000000**",
         "", "00", "5"),
    line("11222333", "1", "HOLDING AÇÚCAR; PARTICIPAÇÕES S.A.", "44555666000100", "22",
         "20200101", "", "***000000**", "", "00", "0"),
    line("44555666", "2", "JOSÉ DA SILVA", "***123456**", "16", "20190101", "", "***000000**",
         "", "00", "5"),
    line("44555666", "3", "JOHN SMITH", "", "37", "0", "249", "***987654**", "MARIA REPR",
         "17", "0"),
]  # fmt: skip

SIMPLES = [
    line("11222333", "S", "20150310", "00000000", "N", "00000000", "00000000"),
    line("77888999", "S", "20200101", "00000000", "S", "20200101", "00000000"),
]

AUX = {
    "Cnaes.zip": [
        line("1091102", "Fabricação de produtos de padaria e confeitaria"),
        line("4721102", "Padaria e confeitaria com predominância de revenda"),
        line("5611203", "Lanchonetes, casas de chá, de sucos e similares"),
        line("6462000", "Holdings de instituições não-financeiras"),
        line("4520001", "Serviços de manutenção e reparação mecânica de veículos automotores"),
    ],
    "Motivos.zip": [line("00", "SEM MOTIVO"), line("01", "EXTINCAO POR ENCERRAMENTO LIQUIDACAO VOLUNTARIA")],
    "Municipios.zip": [line("7107", "SAO PAULO"), line("6001", "RIO DE JANEIRO"), line("9999", "TESTE")],
    "Naturezas.zip": [
        line("2062", "Sociedade Empresária Limitada"),
        line("2054", "Sociedade Anônima Fechada"),
        line("2135", "Empresário (Individual)"),
    ],
    "Paises.zip": [line("249", "ESTADOS UNIDOS")],
    "Qualificacoes.zip": [
        line("49", "Sócio-Administrador"), line("22", "Sócio"), line("16", "Presidente"),
        line("37", "Sócio Pessoa Jurídica Domiciliado no Exterior"), line("10", "Diretor"),
        line("50", "Empresário"), line("17", "Procurador"), line("00", "Não informada"),
    ],
}  # fmt: skip


def write_zip(path: Path, lines: list[str], *, crlf: bool = False, nul: bool = False) -> Path:
    eol = "\r\n" if crlf else "\n"
    data = (eol.join(lines) + eol).encode("cp1252")
    if nul:
        data = data.replace(b"PADARIA", b"PADA\x00RIA", 1)
    inner = "K3241.K03200Y0.D61011." + path.stem.upper() + "CSV"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(inner, data)
    return path


# Empresas fictícias da região de Jundiaí, só para o comando `cnpj-etl demo` (prospecção de leads).
# Nomes, telefones e CPFs são inventados. SIAFI: Jundiaí 6619, Itatiba 6569, Campinas 6291.
JUNDIAI_EMPRESAS = [
    line("21000001", "TRANSPORTADORA SERRA DO JAPI LTDA", "2062", "49", "250000,00", "03", ""),
    line("21000002", "CONSTRUTORA VALE DO JUNDIAI LTDA", "2062", "49", "1200000,00", "05", ""),
    line("21000003", "CLIMA FRIO INSTALACOES LTDA", "2062", "49", "30000,00", "01", ""),
    line("21000004", "CARLOS ALBERTO MENDES 98765432100", "2135", "50", "50000,00", "01", ""),
    line("21000005", "CLINICA ODONTOLOGICA SORRISO LTDA", "2062", "49", "80000,00", "01", ""),
    line("21000006", "AGRO MAQUINAS CAMPINAS LTDA", "2062", "49", "2000000,00", "05", ""),
]
JUNDIAI_ESTABELECIMENTOS = [
    estab("21000001", "0001", fantasia="SERRA DO JAPI LOG", inicio="20120515", cnae="4930202", municipio="6619",
          logradouro="DOS IMIGRANTES", numero="1500", bairro="DISTRITO INDUSTRIAL", cep="13213000",
          ddd="11", telefone="987654321", email="COMERCIAL@SERRADOJAPI.COM.BR"),
    estab("21000002", "0001", fantasia="VALE DO JUNDIAI", inicio="20080310", cnae="4120400", municipio="6619",
          logradouro="JUNDIAI", numero="200", bairro="ANHANGABAU", cep="13208000", ddd="11", telefone="45231234",
          ddd2="11", telefone2="991112222", email="CONTATO@VALEDOJUNDIAI.COM.BR"),
    estab("21000003", "0001", fantasia="CLIMA FRIO", inicio="20190801", cnae="4322302", municipio="6619",
          logradouro="BARAO DE JUNDIAI", numero="45", bairro="CENTRO", cep="13201010", ddd="11",
          telefone="976543210"),
    estab("21000004", "0001", fantasia="SITIO SANTO ANTONIO", inicio="20100120", cnae="0132600", municipio="6619",
          logradouro="DA UVA", numero="KM 3", bairro="CAXAMBU", cep="13219000", ddd="11", telefone="999887766"),
    estab("21000005", "0001", fantasia="SORRISO ODONTO", inicio="20160405", cnae="8630504", municipio="6569",
          logradouro="SAO PAULO", numero="310", bairro="CENTRO", cep="13250000", ddd="11", telefone="44871234",
          email="AGENDA@SORRISOODONTO.COM.BR"),
    estab("21000006", "0001", fantasia="AGRO MAQUINAS", inicio="20050620", cnae="4661300", municipio="6291",
          logradouro="JOHN BOYD DUNLOP", numero="3900", bairro="JARDIM IPAUSSURAMA", cep="13060000", ddd="19",
          telefone="32345678", ddd2="19", telefone2="988776655", email="VENDAS@AGROMAQUINAS.COM.BR"),
]  # fmt: skip
JUNDIAI_SOCIOS = [
    line("21000001", "2", "MARCOS ANTONIO PEREIRA", "***234567**", "49", "20120515", "", "***000000**", "", "00", "5"),
    line("21000002", "2", "ANA PAULA RODRIGUES", "***345678**", "49", "20080310", "", "***000000**", "", "00", "5"),
    line("21000002", "2", "RICARDO GOMES", "***456789**", "22", "20150101", "", "***000000**", "", "00", "6"),
    line("21000003", "2", "FERNANDO LIMA", "***567890**", "49", "20190801", "", "***000000**", "", "00", "4"),
    line("21000005", "2", "JULIANA COSTA", "***678901**", "49", "20160405", "", "***000000**", "", "00", "4"),
    line("21000006", "2", "PAULO SERGIO ALMEIDA", "***789012**", "49", "20050620", "", "***000000**", "", "00", "6"),
]  # fmt: skip
JUNDIAI_SIMPLES = [line("21000003", "S", "20190801", "00000000", "N", "00000000", "00000000")]
JUNDIAI_AUX = {
    "Cnaes.zip": [
        line("4930202", "Transporte rodoviário de carga, exceto produtos perigosos e mudanças, intermunicipal"),
        line("4120400", "Construção de edifícios"),
        line(
            "4322302", "Instalação e manutenção de sistemas centrais de ar condicionado, de ventilação e refrigeração"
        ),
        line("0132600", "Cultivo de uva"),
        line("8630504", "Atividade odontológica"),
        line("4661300", "Comércio atacadista de máquinas, aparelhos e equipamentos para uso agropecuário"),
    ],
    "Municipios.zip": [line("6619", "JUNDIAI"), line("6569", "ITATIBA"), line("6291", "CAMPINAS")],
}


def make_release(dest: Path, *, small: bool = False, regiao_jundiai: bool = False) -> Path:
    """Cria os 37 ZIPs esperados (multipartes extras vazias, como faz a Receita)."""
    dest.mkdir(parents=True, exist_ok=True)
    parts = {
        "Empresas": [EMPRESAS_0, EMPRESAS_1],
        "Estabelecimentos": [ESTABELECIMENTOS_0, ESTABELECIMENTOS_1],
        "Socios": [SOCIOS_0, []],
    }
    if regiao_jundiai:
        parts = {
            "Empresas": [EMPRESAS_0, EMPRESAS_1, JUNDIAI_EMPRESAS],
            "Estabelecimentos": [ESTABELECIMENTOS_0, ESTABELECIMENTOS_1, JUNDIAI_ESTABELECIMENTOS],
            "Socios": [SOCIOS_0, [], JUNDIAI_SOCIOS],
        }
    if small:  # carga suspeita, muito menor que a anterior
        parts = {"Empresas": [EMPRESAS_0[:1]], "Estabelecimentos": [ESTABELECIMENTOS_0[:1]],
                 "Socios": [SOCIOS_0[:1]]}  # fmt: skip
    for prefix, chunks in parts.items():
        for i in range(10):
            lines = chunks[i] if i < len(chunks) else []
            write_zip(dest / f"{prefix}{i}.zip", lines, crlf=(prefix == "Empresas"), nul=(i == 0))
    write_zip(dest / "Simples.zip", SIMPLES + (JUNDIAI_SIMPLES if regiao_jundiai else []))
    for name, lines in AUX.items():
        extra = JUNDIAI_AUX.get(name, []) if regiao_jundiai else []
        write_zip(dest / name, lines + extra)
    return dest
