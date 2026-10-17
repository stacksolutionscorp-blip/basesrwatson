import polars as pl
from cnpj_etl.demo import EMPRESAS_0, ESTABELECIMENTOS_0, line, write_zip
from cnpj_etl.layouts import EMPRESAS, ESTABELECIMENTOS
from cnpj_etl.reader import decode, iter_batches, iter_raw_chunks, parse


def test_decode_latin1_nul_crlf():
    raw = '"1";"AÇÚCAR – “ÓTIMO”"\r\n'.encode("cp1252").replace(b"A", b"A\x00", 1)
    assert decode(raw) == '"1";"AÇÚCAR – “ÓTIMO”"\n'


def test_zip_inteiro_em_um_lote(tmp_path):
    path = write_zip(tmp_path / "Empresas0.zip", EMPRESAS_0, crlf=True, nul=True)
    batches = list(iter_batches(path, EMPRESAS, batch_bytes=64 * 1024 * 1024))
    assert len(batches) == 1
    df = batches[0].df
    assert df.height == 3 and batches[0].malformed == 0
    assert df["razao_social"].to_list()[0] == "PADARIA SÃO JOÃO LTDA"  # NUL removido
    assert df["razao_social"].to_list()[1] == "HOLDING AÇÚCAR; PARTICIPAÇÕES S.A."


def test_lotes_pequenos_cortam_so_em_fim_de_registro(tmp_path):
    lines = [line(str(i).zfill(8), f"EMPRESA {i}\nCOM QUEBRA", "2062", "49", "1,00", "01", "")
             for i in range(500)]  # fmt: skip
    path = write_zip(tmp_path / "Empresas1.zip", lines)
    chunks = list(iter_raw_chunks(path, batch_bytes=1000))
    assert len(chunks) > 10
    assert all(c.endswith(b'"\n') for c in chunks)
    df = pl.concat(b.df for b in iter_batches(path, EMPRESAS, batch_bytes=1000))
    assert df.height == 500
    assert df["cnpj_basico"].to_list() == [str(i).zfill(8) for i in range(500)]
    assert df["razao_social"][7] == "EMPRESA 7\nCOM QUEBRA"


def test_aspas_internas_e_linha_truncada():
    good = ESTABELECIMENTOS_0[0]
    broken = good.replace('"PADARIA SÃO JOÃO"', '"PADARIA "BOA" SÃO JOÃO"')
    truncated = '"11222333";"0003"'
    batch = parse("\n".join([good, broken, truncated]) + "\n", ESTABELECIMENTOS)
    assert batch.df.height == 2
    assert batch.malformed == 1
    assert batch.df["nome_fantasia"][1] == 'PADARIA "BOA" SÃO JOÃO'


def test_zip_vazio(tmp_path):
    path = write_zip(tmp_path / "Socios9.zip", [])
    assert list(iter_batches(path, EMPRESAS, batch_bytes=1024)) == []
