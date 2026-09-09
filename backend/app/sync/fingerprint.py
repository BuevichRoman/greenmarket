import hashlib
import json

# Порядок полей фиксирован и является частью контракта: отпечаток считают две
# стороны — сервер по базе и клиент по рабочей книге, — и любое расхождение в
# правиле даёт ложное срабатывание шлюза.
FINGERPRINT_FIELDS = (
    "seller_product_id",
    "seller_sku",
    "product_id",
    "seller_name",
    "price",
    "stock",
    "unit",
    "description",
    "origin_country",
    "supply_date",
    "is_published",
)


def _decimal(value, places: int) -> str:
    return f"{float(value):.{places}f}"


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
        {
            "seller_product_id": row.id,
            "seller_sku": row.seller_sku,
            "product_id": row.product_id,
            "seller_name": row.seller_name,
            "price": _decimal(row.price, 2),
            "stock": _decimal(row.stock, 3),
            "unit": row.unit,
            "description": row.description,
            "origin_country": row.origin_country,
            "supply_date": row.supply_date.isoformat() if row.supply_date is not None else None,
            "is_published": bool(row.is_published),
        }
        for row in sorted(rows, key=lambda r: r.id)
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
