# backend/app/catalog_template/build_examples.py
"""Генерирует заполненные примеры Catalog Template v1.0 (PR-008 acceptance
criteria: "частично заполненный", "полностью заполненный") — те же 5 листов,
что и мастер-шаблон (app.catalog_template.build.build_workbook), с
заполненным листом «Каталог». Используются в тестах для проверки полного
пайплайна Parser -> Validator -> Mapper на реалистичных данных.
"""

from pathlib import Path

from app.catalog_template.build import build_workbook

EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "docs" / "02-domain" / "templates" / "examples"

# SellerProductId пуст — все строки новые, ещё не публиковались.
PARTIAL_ROWS = [
    [None, "Апельсины оптом", "Цитрусовые", "Апельсин", 99.5, "кг", 10, "", "", "1"],
    [None, "Минеральная вода 'Летняя'", "Напитки", "", 45, "л", 50, "", "", "1"],
]

FULL_ROWS = [
    [
        None,
        "Апельсины оптом",
        "Цитрусовые",
        "Апельсин",
        99.5,
        "кг",
        10,
        "Свежие апельсины из Абхазии",
        "Сорт: Washington navel",
        "1",
    ],
    [
        None,
        "Молоко фермерское 3.2%",
        "Молоко",
        "Молоко",
        89,
        "л",
        30,
        "Цельное коровье молоко",
        "Жирность 3.2%",
        "1",
    ],
    [
        None,
        "Мандарины абхазские",
        "Цитрусовые",
        "Прочее",
        180,
        "кг",
        25,
        "Новый товар, ожидает модерации",
        "Сладкие, тонкая кожура",
        "1",
    ],
]


def main() -> None:
    EXAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    build_workbook(catalog_rows=PARTIAL_ROWS).save(EXAMPLES_DIR / "catalog_template_v1_partial.xlsx")
    build_workbook(catalog_rows=FULL_ROWS).save(EXAMPLES_DIR / "catalog_template_v1_full.xlsx")

    print(f"Примеры сохранены: {EXAMPLES_DIR}")


if __name__ == "__main__":
    main()
