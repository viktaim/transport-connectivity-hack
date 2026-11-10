"""Render the existing route model outputs as a standalone HTML dashboard."""

import csv
import html
from collections import defaultdict
from decimal import Decimal

from economics import INPUT_FILE, OUTPUT_FILE, MARKET_PAX, ROUTES

OUT = OUTPUT_FILE.parent
YEARS = ("2027", "2028")
SCENARIOS = {"base": "Базовый", "cautious": "Осторожный"}
HYPOTHESES = {"hub": "Хаб в Казани", "direct": "Прямые рейсы"}
METRICS = {
    "passengers_new": ("Дополнительные пассажиры", "чел.", ",d"),
    "revenue_new_rub": ("Дополнительная билетная выручка", "₽", ",d"),
    "market_share_pp": ("Прирост доли рынка", "п.п.", ".6f"),
}


def read_routes(path):
    keys = ("year", "scenario", "hypothesis", "origin", "destination")
    rows = {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            key = tuple(row[field].strip() for field in keys)
            if key in rows:
                raise ValueError(f"{path.name}: duplicate route row {key}")
            rows[key] = row
    return rows


def summarize():
    inputs = read_routes(INPUT_FILE)
    results = read_routes(OUTPUT_FILE)
    expected = {
        (year, scenario, hypothesis, origin, destination)
        for year in YEARS
        for scenario in SCENARIOS
        for hypothesis, routes in ROUTES.items()
        for origin, destination in routes
    }
    if inputs.keys() != expected or results.keys() != expected:
        raise ValueError("Route inputs and results must cover every model route, year and scenario")

    totals = defaultdict(lambda: [0, 0, Decimal(0)])
    for key, row in results.items():
        pax = int(row["passengers_new"])
        revenue = int(row["revenue_new_rub"])
        share_pp = Decimal(row["market_share_pp"])
        total_pax = int(row["passengers_total"])
        if (not 0 <= pax <= total_pax or revenue < 0
                or not share_pp.is_finite() or not 0 <= share_pp <= 100):
            raise ValueError(f"Invalid route model outputs for {key}")
        # The model computes share before rounding passengers to whole numbers.
        pax_based_share = Decimal(pax) * 100 / MARKET_PAX
        rounding_tolerance = Decimal(50) / MARKET_PAX + Decimal("0.0000005")
        if abs(share_pp - pax_based_share) > rounding_tolerance:
            raise ValueError(f"Inconsistent market share for {key}")
        group = totals[key[:3]]
        group[0] += pax
        group[1] += revenue
        group[2] += share_pp

    return [
        {"year": year, "scenario": scenario, "hypothesis": hypothesis,
         **dict(zip(METRICS, totals[(year, scenario, hypothesis)]))}
        for year in YEARS for scenario in SCENARIOS for hypothesis in HYPOTHESES
    ]


def chart(rows, metric, title, unit, number_format):
    maximum = max(row[metric] for row in rows) or 1
    bars = []
    for row in rows:
        value = row[metric]
        scenario = SCENARIOS[row["scenario"]]
        hypothesis = HYPOTHESES[row["hypothesis"]]
        label = html.escape(f'{row["year"]} · {scenario} · {hypothesis}')
        formatted = format(value, number_format).replace(",", " ").replace(".", ",")
        bars.append(
            f'<div class="row"><span>{label}</span>'
            f'<div class="track" aria-hidden="true"><div class="{row["hypothesis"]}" '
            f'style="width:{100 * value / maximum:.5f}%"></div></div>'
            f'<b>{formatted} {unit}</b></div>'
        )
    return f'<section><h2>{title}</h2>{"".join(bars)}</section>'


def main():
    rows = summarize()
    charts = "".join(chart(rows, metric, *labels) for metric, labels in METRICS.items())
    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Red Wings · Экономика гипотез</title>
<style>
body {{font: 16px system-ui; max-width: 1080px; margin: 32px auto; padding: 0 16px;
       background: #f6f7fa; color: #17243a}}
section {{background: white; padding: 20px; margin: 16px 0; border-radius: 12px}}
.row {{display: grid; grid-template-columns: minmax(240px, 1.1fr) 1fr minmax(126px, auto);
       gap: 10px; align-items: center; margin: 12px 0}}
.track {{background: #e6eaf1; height: 14px; border-radius: 6px; overflow: hidden}}
.track div {{height: 100%}}
.hub {{background: #2456a9}}
.direct {{background: #08796a}}
@media (max-width: 620px) {{
  .row {{grid-template-columns: 1fr auto; font-size: 13px; margin: 16px 0}}
  .track {{grid-row: 2; grid-column: 1 / -1}}
}}
</style></head><body>
<h1>Red Wings · Хаб в Казани и прямые рейсы</h1>
<p><b>Сценарное моделирование.</b> Частоты, сроки, загрузка, тарифы и доля новых
пассажиров — сценарные допущения. Выручка показана до вычета расходов.
В модели используется фиксированный рынок {MARKET_PAX / 1_000_000:.1f} млн пассажиров в год.</p>
{charts}
<p>Источник — economics_results.csv. Для каждого года, сценария и гипотезы
суммируются результаты маршрутных строк. Доля рынка суммируется из округлённых
маршрутных значений, поэтому последние знаки могут отличаться от пересчёта
по общему числу пассажиров. Годовые доли между собой не суммируются.</p>
</body></html>"""
    with (OUT / "economics_summary.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (OUT / "economics_dashboard.html").write_text(page, encoding="utf-8")
    print("Created out/economics_summary.csv and out/economics_dashboard.html")


if __name__ == "__main__":
    main()
