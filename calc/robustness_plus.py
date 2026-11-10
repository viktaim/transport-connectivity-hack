"""Дополнительная проверка устойчивости рейтинга Red Wings.

Запуск из корня репозитория: python calc/robustness_plus.py
Вход: data/processed/longlist.csv и calc/weights*.yaml. Зависимости: стандартная библиотека Python.

НЕ изменяет основной рейтинг и входные данные; создаёт четыре новых файла out/.
"""
import csv
import html
import math
import random
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "data" / "processed" / "longlist.csv"
OUT = ROOT / "out"
RUNS = 1000
SEED = 20261110
CRITERIA = ("airport_pax", "avg_dist_to_others", "redwings_presence", "population", "competitor_hub")
WEIGHT_FILES = {
    "base": "weights.yaml",
    "demand": "weights_demand.yaml",
    "geography": "weights_geography.yaml",
}
CONCENTRATION = 60
NEUTRAL = 0.5
FILLS = (0.0, NEUTRAL, 1.0)
REVERSED = {"avg_dist_to_others", "competitor_hub"}


def read_weights(filename):
    # The team files are flat YAML mappings with numeric values and comments.
    weights = {}
    for line in (ROOT / "calc" / filename).read_text(encoding="utf-8-sig").splitlines():
        line = line.partition("#")[0].strip()
        if line:
            key, value = line.split(":", 1)
            key = key.strip()
            if key in weights:
                raise ValueError(f"{filename}: duplicate weight {key}")
            weights[key] = float(value)
    if (set(weights) != set(CRITERIA)
            or any(not 0 < weight <= 1 for weight in weights.values())
            or not math.isclose(sum(weights.values()), 1, rel_tol=0, abs_tol=1e-12)):
        raise ValueError(f"{filename}: expected positive weights with sum 1")
    return tuple(weights[criterion] for criterion in CRITERIA)


def distance(a, b):
    lat_a, lon_a = a
    lat_b, lon_b = b
    h = (math.sin((lat_b - lat_a) / 2) ** 2
         + math.cos(lat_a) * math.cos(lat_b) * math.sin((lon_b - lon_a) / 2) ** 2)
    return 2 * 6371.01 * math.asin(math.sqrt(min(1, h)))


def read_ranking():
    raw = {}
    required = {"lat", "lon"} | (set(CRITERIA) - {"avg_dist_to_others"})
    with INPUT.open(encoding="utf-8-sig", newline="") as file:
        for record in csv.DictReader(file):
            city, indicator = record["city"].strip(), record["indicator"].strip()
            if indicator not in required:
                continue
            values = raw.setdefault(city, {})
            if not city or indicator in values:
                raise ValueError(f"Empty city or duplicate indicator: {city}, {indicator}")
            value = record["value"].strip()
            values[indicator] = float(value) if value else None

    if len(raw) != 12:
        raise ValueError(f"Expected 12 candidate cities, found {len(raw)}")
    for city, values in raw.items():
        for field, (low, high) in {
            "lat": (-90, 90), "lon": (-180, 180), "population": (1, math.inf),
            "airport_pax": (0, math.inf), "redwings_presence": (0, 1),
            "competitor_hub": (0, 1),
        }.items():
            value = values.get(field)
            if field == "airport_pax" and value is None:
                values[field] = None
                continue
            if value is None or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Invalid {field} for {city}: {value}")
            if field in {"redwings_presence", "competitor_hub"} and value not in (0, 1):
                raise ValueError(f"Expected binary {field} for {city}")

    coords = {
        city: (math.radians(values["lat"]), math.radians(values["lon"]))
        for city, values in raw.items()
    }
    for city, values in raw.items():
        values["avg_dist_to_others"] = sum(
            distance(coords[city], point) for other, point in coords.items() if other != city
        ) / (len(coords) - 1)

    bounds = {}
    for criterion in CRITERIA:
        observed = [values[criterion] for values in raw.values() if values[criterion] is not None]
        if not observed:
            raise ValueError(f"No observed values for {criterion}")
        bounds[criterion] = min(observed), max(observed)

    rows = []
    for city, values in raw.items():
        scores = []
        for criterion in CRITERIA:
            value = values[criterion]
            low, high = bounds[criterion]
            if value is None or low == high:
                score = NEUTRAL
            elif criterion in REVERSED:
                score = (high - value) / (high - low)
            else:
                score = (value - low) / (high - low)
            scores.append(score)
        rows.append({"city": city, "airport_missing": values["airport_pax"] is None,
                     "scores": scores})
    return rows


def rank(rows, weights, missing_score=NEUTRAL):
    result = []
    for row in rows:
        scores = row["scores"].copy()
        if row["airport_missing"]:
            scores[CRITERIA.index("airport_pax")] = missing_score
        total = math.fsum(weight * score for weight, score in zip(weights, scores))
        result.append((row["city"], total))
    return sorted(result, key=lambda entry: (-round(entry[1], 12), entry[0]))


def random_weights(rng, base_weights):
    draws = [rng.gammavariate(CONCENTRATION * weight, 1) for weight in base_weights]
    total = math.fsum(draws)
    return tuple(draw / total for draw in draws)


def save_csv(path, columns, data):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(data)


def main():
    rows = read_ranking()
    scenarios = {name: read_weights(filename) for name, filename in WEIGHT_FILES.items()}
    base_weights = scenarios["base"]
    missing_cities = sorted(row["city"] for row in rows if row["airport_missing"])
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    hits = Counter()
    places = {row["city"]: Counter() for row in rows}
    for _ in range(RUNS):
        order = rank(rows, random_weights(rng, base_weights))
        for place, (city, _) in enumerate(order, 1):
            places[city][place] += 1
            if place <= 3:
                hits[city] += 1

    distribution = {place: f"rank_{place}_count" for place in range(1, len(rows) + 1)}
    summary = [
        {"city": r["city"], "top3_count": hits[r["city"]],
         "top3_percent": round(100 * hits[r["city"]] / RUNS, 1),
         "mean_rank": round(sum(place * count for place, count in places[r["city"]].items()) / RUNS, 3),
         **{column: places[r["city"]][place] for place, column in distribution.items()}}
        for r in rows
    ]
    summary.sort(key=lambda r: (-r["top3_percent"], r["mean_rank"], r["city"]))
    save_csv(OUT / "monte_carlo_summary.csv",
             list(summary[0]), summary)

    sensitivity = []
    for scenario, weights in scenarios.items():
        neutral_ranks = {city: place for place, (city, _) in enumerate(rank(rows, weights), 1)}
        for fill in FILLS:
            for place, (city, score) in enumerate(rank(rows, weights, fill), 1):
                sensitivity.append({"missing_score": fill, "scenario": scenario,
                                    "rank": place, "city": city,
                                    "airport_pax_missing": int(city in missing_cities),
                                    "rank_delta_vs_neutral": place - neutral_ranks[city],
                                    "total_score": round(score, 6)})
    save_csv(OUT / "missing_sensitivity.csv", list(sensitivity[0]), sensitivity)

    lines = [
        "# Дополнительная проверка устойчивости рейтинга Red Wings", "",
        f"Использовано {RUNS} случайных допустимых наборов весов, seed={SEED}.",
        "Веса получены нормировкой Gamma-выборок с параметрами 60 × базовый вес.",
        "Это **локальная чувствительность к выбору весов**, а не вероятность коммерческого успеха города.",
        "Все запуски используют одни и те же 12 городов и нормализованные показатели.", "",
        "## Частота попадания в тройку", "",
        "| Город | Попадание в топ-3 | Среднее место |", "|---|---:|---:|",
    ]
    for row in summary:
        lines.append(f"| {row['city']} | {row['top3_percent']:.1f}% | {row['mean_rank']:.2f} |")
    lines += [
        "", "## Стресс-тест по пропущенному пассажиропотоку", "",
        ("Пропуски airport_pax: " + ", ".join(missing_cities) + "." if missing_cities
         else "Пропусков airport_pax нет. Все три оценки дают одинаковый рейтинг."),
        "Во всех найденных пропусках одновременно задаём нормализованную оценку 0 (пессимистично), 0.5 (нейтрально), 1 (оптимистично).",
        "**Это не восстановление реального пассажиропотока**, а проверка методологического риска.", "",
        "| Балл пропуска | Сценарий | Топ-3 |", "|---:|---|---|",
    ]
    for fill in FILLS:
        for scenario in scenarios:
            top = [r["city"] for r in sensitivity
                   if r["missing_score"] == fill and r["scenario"] == scenario and r["rank"] <= 3]
            lines.append(f"| {fill:.1f} | {scenario} | {', '.join(top)} |")
    lines += ["", "### Места городов с пропусками", "",
              "| Город | Веса | Балл 0 | Балл 0.5 | Балл 1 |", "|---|---|---:|---:|---:|"]
    for city in missing_cities:
        for scenario in scenarios:
            ranks = [str(row["rank"]) for row in sensitivity
                     if row["city"] == city and row["scenario"] == scenario]
            lines.append(f"| {city} | {scenario} | {' | '.join(ranks)} |")
    if not missing_cities:
        lines.append("| Пропусков нет | — | — | — | — |")
    lines += [
        "", "## Ограничения и интерпретация", "",
        "- Весовые вариации **не** выводят объективные веса из реального спроса.",
        "- База из 12 городов не равна всей России: расширение списка изменит min-max шкалу.",
        "- Наличие текущего аэропорта и действующих баз — отдельные ограничения применимости.",
        "- Рейтинг не оценивает прибыль, спрос между парами городов или доступность флота.",
        "- При изменении общего longlist пересчитать основной рейтинг и повторить эксперимент.", "",
        "## Запуск", "",
        "`python calc/robustness_plus.py` из корня репозитория.",
        "Входы: `data/processed/longlist.csv` и `calc/weights*.yaml`. Все созданные файлы помещаются в `out/`.",
    ]
    (OUT / "robustness_plus.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    chart_rows = []
    for item in summary:
        percent = item["top3_percent"]
        chart_rows.append(
            f'<div class="row"><span>{html.escape(item["city"])}</span>'
            f'<div class="track"><div class="fill" style="width:{percent}%"></div></div>'
            f'<b>{percent:.1f}%</b></div>'
        )
    base_top = ", ".join(html.escape(city) for city, _ in rank(rows, base_weights)[:3])
    dashboard = f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Red Wings — устойчивость выбора хаба</title><style>
body{{font:16px system-ui;max-width:960px;margin:40px auto;padding:0 20px;background:#f5f7fb;color:#14223b}}
section{{background:white;padding:24px;border-radius:14px;margin:18px 0}}
.row{{display:grid;grid-template-columns:190px 1fr 70px;gap:12px;align-items:center;margin:12px 0}}
.track{{height:22px;border-radius:8px;background:#e5e9f0;overflow:hidden}}
.fill{{height:100%;background:#3b65c6}}.hint{{color:#536273}}
@media(max-width:570px){{.row{{grid-template-columns:110px 1fr 55px;font-size:12px}}}}
</style><h1>Red Wings: устойчивость рейтинга</h1>
<p class="hint">{RUNS} случайных вариаций весов, фиксированный набор из {len(rows)} городов. Частота попадания в топ-3 — не вероятность окупаемости хаба.</p>
<section><h2>Базовый топ-3</h2><p>{base_top}</p></section>
<section><h2>Частота попадания в топ-3</h2>{''.join(chart_rows)}</section>
<section><h2>Достоверность</h2><p>Монте-Карло использует оценку 0.5 для отсутствующего airport_pax.
Подробная таблица стресс-теста: <a href="missing_sensitivity.csv">missing_sensitivity.csv</a>.</p></section>
</html>'''
    (OUT / "robustness_dashboard.html").write_text(dashboard, encoding="utf-8")
    print(f"Monte Carlo: {RUNS} runs; {len(summary)} cities; {len(sensitivity)} sensitivity rows")
    print("Top three by frequency: " + ", ".join(r["city"] for r in summary[:3]))
    print("Created in out/: monte_carlo_summary.csv, missing_sensitivity.csv, robustness_plus.md, robustness_dashboard.html")


if __name__ == "__main__":
    main()
