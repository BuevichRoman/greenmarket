import hashlib
import json
from decimal import Decimal

# Единственное определение состава отпечатка: и порядок полей, и способ
# получить значение. Раньше список полей и сборка payload существовали порознь,
# и добавить редактируемое поле в одно место, забыв про другое, было делом
# одной невнимательной правки — при том, что список выглядел как контракт.
#
# Порядок фиксирован и является частью контракта: отпечаток считают две
# стороны — сервер по базе и клиент по рабочей книге, — и любое расхождение в
# правиле даёт ложное срабатывание шлюза.


def _money(value) -> str:
    return _fixed(value, 2)


def _quantity(value) -> str:
    return _fixed(value, 3)


def _fixed(value, places: int) -> str:
    """Канонизация числа без участия float.

    `Decimal → float → строка` вносила бы двоичное представление в механизм,
    который обязан давать бит-в-бит одинаковый результат на двух независимых
    реализациях. Квантование идёт по правилу по умолчанию — ROUND_HALF_EVEN;
    оно же должно быть записано в контракте для клиента.
    """
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(number.quantize(Decimal(1).scaleb(-places)), "f")


def _date(value) -> str | None:
    return value.isoformat() if value is not None else None


FINGERPRINT_FIELDS: tuple[tuple[str, object], ...] = (
    ("seller_product_id", lambda row: row.id),
    ("seller_sku", lambda row: row.seller_sku),
    ("product_id", lambda row: row.product_id),
    ("seller_name", lambda row: row.seller_name),
    ("price", lambda row: _money(row.price)),
    ("stock", lambda row: _quantity(row.stock)),
    ("unit", lambda row: row.unit),
    ("description", lambda row: row.description),
    ("origin_country", lambda row: row.origin_country),
    ("supply_date", lambda row: _date(row.supply_date)),
    ("is_published", lambda row: bool(row.is_published)),
)

FINGERPRINT_FIELD_NAMES = tuple(name for name, _ in FINGERPRINT_FIELDS)


def catalog_fingerprint(rows) -> str:
    """Отпечаток состояния каталога продавца.

    Шлюз создания baseline: клиент присылает такой же отпечаток, посчитанный по
    книге, сервер считает свой по базе и сравнивает. Совпало — состояния равны,
    и снимок можно фиксировать; разошлось — сверка ещё не сделана.

    Фотографии, `version`, `moderation_status` и прочие служебные поля в
    отпечаток не входят: их в книге нет, и расхождение по ним не означает, что
    каталог и книга разные.

    Строки сортируются по `seller_product_id`: порядок выдачи из базы не должен
    влиять на результат.
    """
    payload = [
        {name: extract(row) for name, extract in FINGERPRINT_FIELDS}
        for row in sorted(rows, key=lambda r: r.id)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
