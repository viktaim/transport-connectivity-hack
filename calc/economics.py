
import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

INPUT_FILE = ROOT / "data" / "processed" / "route_inputs.csv"
OUTPUT_FILE = ROOT / "out" / "economics_results.csv"

MARKET_PAX = 108_900_000

ROUTES = {
    "hub": [
        ("Казань", "Екатеринбург"),
        ("Казань", "Новосибирск"),
        ("Казань", "Сочи"),
        ("Казань", "Уфа"),
        ("Казань", "Самара"),
        ("Казань", "Краснодар"),
    ],
    "direct": [
        ("Екатеринбург", "Казань"),
        ("Екатеринбург", "Уфа"),
        ("Екатеринбург", "Самара"),
        ("Екатеринбург", "Сочи"),
        ("Екатеринбург", "Новосибирск"),
        ("Казань", "Уфа"),
    ],
}

FIELDS = [
    "hypothesis",
    "origin",
    "destination",
    "year",
    "scenario",
    "weekly_round_trips",
    "weeks",
    "seats",
    "load_factor",
    "avg_fare_rub",
    "new_pax_share",
    "type",
    "source",
    "comment",
]


def init_csv():
    INPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    if INPUT_FILE.exists():
        print("Файл уже существует. Данные не перезаписаны.")
        return

    with INPUT_FILE.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()

        for hypothesis, routes in ROUTES.items():
            for origin, destination in routes:
                for year in (2027, 2028):
                    for scenario in ("base", "cautious"):
                        writer.writerow({
                            "hypothesis": hypothesis,
                            "origin": origin,
                            "destination": destination,
                            "year": year,
                            "scenario": scenario,
                            "weekly_round_trips": "",
                            "weeks": "",
                            "seats": "",
                            "load_factor": "",
                            "avg_fare_rub": "",
                            "new_pax_share": "",
                            "type": "assumption",
                            "source": "",
                            "comment": "Требуется заполнить параметры",
                        })

    print(f"Создан файл: {INPUT_FILE}")


def calculate():
    with INPUT_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    results = []
    incomplete = 0

    numeric_fields = [
        "weekly_round_trips",
        "weeks",
        "seats",
        "load_factor",
        "avg_fare_rub",
        "new_pax_share",
    ]

    for row in rows:
        if any(not row[field].strip() for field in numeric_fields):
            incomplete += 1
            continue

        try:
            freq = float(row["weekly_round_trips"])
            weeks = float(row["weeks"])
            seats = float(row["seats"])
            load = float(row["load_factor"])
            fare = float(row["avg_fare_rub"])
            new_share = float(row["new_pax_share"])
        except ValueError:
            raise ValueError(
                f"Некорректные числа: {row['origin']} - {row['destination']}"
            )

        if not (
            freq >= 0
            and 0 <= weeks <= 52
            and seats > 0
            and 0 <= load <= 1
            and fare >= 0
            and 0 <= new_share <= 1
        ):
            raise ValueError(
                f"Параметры вне допустимых границ: "
                f"{row['origin']} - {row['destination']}"
            )

        passengers_total = 2 * freq * weeks * seats * load

        # Не весь поток на дополнительных рейсах обязательно
        # является приростом: часть пассажиров могла бы лететь
        # существующими рейсами Red Wings.
        passengers_new = passengers_total * new_share

        revenue_new = passengers_new * fare

        market_share_pp = passengers_new / MARKET_PAX * 100

        results.append({
            "hypothesis": row["hypothesis"],
            "origin": row["origin"],
            "destination": row["destination"],
            "year": row["year"],
            "scenario": row["scenario"],
            "passengers_total": round(passengers_total),
            "passengers_new": round(passengers_new),
            "revenue_new_rub": round(revenue_new),
            "market_share_pp": round(market_share_pp, 6),
            "type": row["type"],
            "comment": row["comment"],
        })

    if not results:
        print("Пока нет заполненных строк для расчёта.")
        return

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

    print(f"Готово: рассчитано строк {len(results)}")
    print(f"Незаполненных строк: {incomplete}")
    print(f"Результат: {OUTPUT_FILE}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true")
    args = parser.parse_args()

    if args.init:
        init_csv()
    else:
        if not INPUT_FILE.exists():
            print("Сначала запусти: python calc/economics.py --init")
            return
        calculate()


if __name__ == "__main__":
    main()
