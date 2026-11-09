import argparse
import csv
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CRITERIA = {
    "population": True,
    "airport_pax": True,
    "avg_dist_to_others": False,
    "competitor_hub": False,
    "redwings_presence": True,
}

EARTH_RADIUS_KM = 6371.0088
TIE_EPS = 0.01

def parse_number(raw):
    if raw is None:
        return None
    s = str(raw).strip().replace("\u00a0", "").replace(" ", "")
    if s == "":
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def read_longlist(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        rows = []
        for r in reader:
            rows.append({(k or "").strip(): (v or "").strip() for k, v in r.items()})
    needed = {"city", "indicator", "value"}
    if not rows or not needed.issubset(rows[0].keys()):
        sys.exit(f"Ошибка: в {path} должны быть колонки city, indicator, value.")
    return rows


def pivot(rows):
    data = {}
    for r in rows:
        city, ind = r["city"], r["indicator"].lower()
        if not city or not ind:
            continue
        data.setdefault(city, {})
        val = parse_number(r.get("value"))
        if val is not None or ind not in data[city]:
            data[city][ind] = val
    return data


def read_weights(path):
    text = Path(path).read_text(encoding="utf-8")
    weights = None
    try:
        import yaml  # type: ignore
        loaded = yaml.safe_load(text)
        if isinstance(loaded, dict):
            weights = loaded.get("weights", loaded)
    except ImportError:
        pass
    if weights is None:
        weights = {}
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            num = parse_number(v)
            if num is not None:
                weights[k.strip()] = num
    out = {}
    for k, v in weights.items():
        num = parse_number(v)
        if num is not None and k in CRITERIA:
            out[k] = num
    missing = [c for c in CRITERIA if c not in out]
    if missing:
        sys.exit(f"Ошибка: в весах нет критериев: {', '.join(missing)}")
    total = sum(out.values())
    if total <= 0:
        sys.exit("Ошибка: сумма весов должна быть положительной.")
    if abs(total - 1.0) > 1e-6:
        print(f"Предупреждение: сумма весов = {total:.4f}, нормирую до 1.", file=sys.stderr)
        out = {k: v / total for k, v in out.items()}
    return out

def haversine(lat1, lon1, lat2, lon2):
    """Расстояние по большому кругу в км."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def add_avg_dist(data):
    cities = [c for c in data if data[c].get("lat") is not None and data[c].get("lon") is not None]
    no_coords = [c for c in data if c not in cities]
    for c in no_coords:
        print(f"Предупреждение: у города «{c}» нет lat/lon, avg_dist_to_others не посчитать.",
              file=sys.stderr)
        data[c]["avg_dist_to_others"] = None
    if len(cities) < 2:
        sys.exit("Ошибка: нужно минимум 2 города с координатами.")
    for c in cities:
        dists = [haversine(data[c]["lat"], data[c]["lon"], data[o]["lat"], data[o]["lon"])
                 for o in cities if o != c]
        data[c]["avg_dist_to_others"] = sum(dists) / len(dists)


def normalize(data, criterion, higher_better):
    vals = {c: d.get(criterion) for c, d in data.items()}
    present = [v for v in vals.values() if v is not None]
    if not present:
        print(f"Предупреждение: нет данных по критерию {criterion}.", file=sys.stderr)
        return {c: None for c in vals}
    lo, hi = min(present), max(present)
    out = {}
    for c, v in vals.items():
        if v is None:
            out[c] = None
        elif hi == lo:
            out[c] = 0.5
        else:
            x = (v - lo) / (hi - lo)
            out[c] = x if higher_better else 1.0 - x
    return out


def rank(data, weights):
    add_avg_dist(data)
    norm = {crit: normalize(data, crit, hb) for crit, hb in CRITERIA.items()}

    results = []
    for city in data:
        row = {"city": city}
        total = 0.0
        for crit in CRITERIA:
            raw = data[city].get(crit)
            n = norm[crit][city]
            row[crit] = raw
            if n is None:
                print(f"Предупреждение: нет значения {crit} для «{city}», оценка принята 0.",
                      file=sys.stderr)
                n = 0.0
            row[f"{crit}_score"] = n
            total += weights[crit] * n
        row["total_score"] = total
        results.append(row)

    results.sort(key=lambda r: (-round(r["total_score"], 12), r["city"]))
    for i, r in enumerate(results, 1):
        r["rank"] = i
    return results


def write_ranking(results, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["city"]
    cols += [f"{c}_score" for c in CRITERIA]
    cols += ["total_score", "rank"]
    raw_cols = list(CRITERIA)
    header = ["city"] + raw_cols + [f"{c}_score" for c in CRITERIA] + ["total_score", "rank"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in results:
            line = [r["city"]]
            for c in raw_cols:
                v = r[c]
                line.append("" if v is None else round(v, 3))
            line += [round(r[f"{c}_score"], 4) for c in CRITERIA]
            line += [round(r["total_score"], 4), r["rank"]]
            w.writerow(line)


def print_summary(results):
    print(f"\n{'Место':<6}{'Город':<20}{'Балл':>8}")
    for r in results:
        print(f"{r['rank']:<6}{r['city']:<20}{r['total_score']:>8.4f}")
    top3 = [r["city"] for r in results[:3]]
    print("\nТоп-3:", ", ".join(top3))
    if len(results) > 3:
        gap = results[2]["total_score"] - results[3]["total_score"]
        if gap < TIE_EPS:
            print(f"Внимание: 3-е и 4-е места почти равны (разница {gap:.4f}): "
                  f"«{results[2]['city']}» и «{results[3]['city']}» идут дальше (ТЗ, раздел 7).")


def demo_data():
    fake = {
        "Город А": dict(population=1_500_000, airport_pax=6_000_000, lat=56.84, lon=60.60,
                        competitor_hub=0, redwings_presence=1),
        "Город Б": dict(population=1_200_000, airport_pax=4_000_000, lat=55.79, lon=49.12,
                        competitor_hub=1, redwings_presence=1),
        "Город В": dict(population=1_100_000, airport_pax=9_000_000, lat=45.04, lon=38.98,
                        competitor_hub=1, redwings_presence=0),
        "Город Г": dict(population=1_600_000, airport_pax=7_000_000, lat=55.03, lon=82.92,
                        competitor_hub=0, redwings_presence=0),
    }
    return {c: dict(v) for c, v in fake.items()}


DEMO_WEIGHTS = {
    "population": 0.15,
    "airport_pax": 0.30,
    "avg_dist_to_others": 0.25,
    "competitor_hub": 0.10,
    "redwings_presence": 0.20,
}


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Рейтинг городов для хаба Red Wings")
    ap.add_argument("--data", default=str(ROOT / "data" / "processed" / "longlist.csv"))
    ap.add_argument("--weights", default=str(ROOT / "calc" / "weights.yaml"))
    ap.add_argument("--out", default=str(ROOT / "out" / "ranking.csv"))
    ap.add_argument("--demo", action="store_true",
                    help="тест на выдуманной таблице из 4 городов (файлы не читаются)")
    args = ap.parse_args()

    if args.demo:
        data, weights = demo_data(), DEMO_WEIGHTS
        out = ROOT / "out" / "ranking_demo.csv"
        print("ДЕМО-режим: данные выдуманные.")
    else:
        for p in (args.data, args.weights):
            if not Path(p).exists():
                sys.exit(f"Ошибка: не найден файл {p}")
        data = pivot(read_longlist(args.data))
        weights = read_weights(args.weights)
        out = Path(args.out)

    results = rank(data, weights)
    write_ranking(results, out)
    print_summary(results)
    print(f"\nРезультат записан: {out}")


if __name__ == "__main__":
    main()
