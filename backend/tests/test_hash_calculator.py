from app.parsing.raw_workbook import RawSheet, RawWorkbook
from app.publication.hash_calculator import HashCalculator


def make_workbook(catalog_rows: list[list[object]]) -> RawWorkbook:
    header = ["SellerProductId", "Наименование продавца", "Цена"]
    return RawWorkbook(source="sheet", sheets=[RawSheet(name="Каталог", index=0, rows=[header, *catalog_rows])])


def test_same_content_produces_same_hash():
    workbook = make_workbook([[1, "Ферма А", 50]])

    first = HashCalculator().compute(workbook)
    second = HashCalculator().compute(make_workbook([[1, "Ферма А", 50]]))

    assert first == second


def test_different_content_produces_different_hash():
    a = HashCalculator().compute(make_workbook([[1, "Ферма А", 50]]))
    b = HashCalculator().compute(make_workbook([[1, "Ферма А", 99]]))

    assert a != b


def test_row_order_affects_hash():
    a = HashCalculator().compute(make_workbook([[1, "A", 50], [2, "B", 60]]))
    b = HashCalculator().compute(make_workbook([[2, "B", 60], [1, "A", 50]]))

    assert a != b


def test_header_row_is_excluded_from_hash():
    # Заголовок не данные каталога — смена заголовка не должна менять хеш.
    header_a = RawSheet(name="Каталог", index=0, rows=[["X", "Y", "Z"], [1, "A", 50]])
    header_b = RawSheet(name="Каталог", index=0, rows=[["SellerProductId", "Наименование продавца", "Цена"], [1, "A", 50]])

    a = HashCalculator().compute(RawWorkbook(source="s", sheets=[header_a]))
    b = HashCalculator().compute(RawWorkbook(source="s", sheets=[header_b]))

    assert a == b


def test_missing_catalog_sheet_does_not_crash():
    workbook = RawWorkbook(source="s", sheets=[])

    result = HashCalculator().compute(workbook)

    assert isinstance(result, str) and len(result) == 64


def test_hash_is_sha256_hex_digest_length():
    result = HashCalculator().compute(make_workbook([[1, "A", 50]]))

    assert len(result) == 64
    int(result, 16)  # не бросает — валидный hex
