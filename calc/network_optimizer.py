"""Compare additional route portfolios at the same weekly block-minute budget."""

import argparse
import csv
import math
from dataclasses import dataclass
from decimal import Decimal
from itertools import product
from pathlib import Path

from economics import INPUT_FILE, ROUTES
from economics_dashboard import OUT, read_routes
from robustness_plus import INPUT as LONGLIST, distance

HUB = "Казань"
MIN_SPOKES = 3
MODES = ("direct", "hub", "hybrid")
SCENARIOS = ("base", "cautious")
DEFAULT_BUDGETS = (20, 30, 40, 50, 60)
WEEKS = 52
PROXY_SPEED_KMH = 700
PROXY_BUFFER_MINUTES = 30
PROXY_ROUND_MINUTES = 5


@dataclass(frozen=True)
class Route:
    cities: tuple[str, str]
    direct_cap: int
    hub_cap: int
    round_trip_minutes: int
    annual_pax: Decimal
    annual_revenue: Decimal
    time_source: str


@dataclass(frozen=True)
class Plan:
    frequencies: tuple[int, ...]
    minutes: int
    passengers: Decimal
    revenue: Decimal
    spokes: int


def read_coordinates():
    coords = {}
    with LONGLIST.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            field = row["indicator"]
            if field not in ("lat", "lon"):
                continue
            values = coords.setdefault(row["city"], {})
            value = float(row["value"])
            limit = 90 if field == "lat" else 180
            if field in values or not math.isfinite(value) or abs(value) > limit:
                raise ValueError(f"Invalid or duplicate coordinates for {row['city']}")
            values[field] = math.radians(value)
    return {city: (values["lat"], values["lon"]) for city, values in coords.items()}


def read_block_times(path, expected_pairs):
    times = {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            pair = tuple(sorted((row["origin"].strip(), row["destination"].strip())))
            minutes = int(row["round_trip_block_minutes"])
            if pair in times or pair not in expected_pairs or minutes <= 0:
                raise ValueError(f"Invalid or duplicate block time for {pair}")
            times[pair] = minutes
    if set(times) != expected_pairs:
        raise ValueError(f"Missing block times for {sorted(expected_pairs - times.keys())}")
    return times


def read_options(scenario, block_times_path=None):
    source = read_routes(INPUT_FILE)
    candidates = {}
    for mode in ("direct", "hub"):
        for origin, destination in ROUTES[mode]:
            row = source["2028", scenario, mode, origin, destination]
            pair = tuple(sorted((origin, destination)))
            cap = int(row["weekly_round_trips"])
            seats = int(row["seats"])
            load = Decimal(row["load_factor"])
            fare = Decimal(row["avg_fare_rub"])
            new_share = Decimal(row["new_pax_share"])
            if (
                int(row["weeks"]) != WEEKS or cap < 0 or seats <= 0
                or not all(value.is_finite() for value in (load, fare, new_share))
                or not (0 <= load <= 1 and 0 <= new_share <= 1 and fare >= 0)
            ):
                raise ValueError(f"Invalid 2028 route inputs for {pair}, {scenario}")
            params = (seats, load, fare, new_share)
            entry = candidates.setdefault(pair, {"params": params})
            if entry["params"] != params or mode in entry:
                raise ValueError(f"Conflicting inputs for shared route {pair}")
            entry[mode] = cap

    if block_times_path is None:
        coords = read_coordinates()
        time_source = "distance_proxy"
        times = {}
        for a, b in candidates:
            km = distance(coords[a], coords[b])
            one_way = km * 60 / PROXY_SPEED_KMH + PROXY_BUFFER_MINUTES
            times[a, b] = 2 * PROXY_ROUND_MINUTES * math.ceil(one_way / PROXY_ROUND_MINUTES)
    else:
        time_source = "provided_csv"
        times = read_block_times(block_times_path, set(candidates))

    routes = []
    for pair, entry in sorted(candidates.items()):
        seats, load, fare, new_share = entry["params"]
        pax = 2 * WEEKS * seats * load * new_share
        routes.append(Route(pair, entry.get("direct", 0), entry.get("hub", 0),
                            times[pair], pax, pax * fare, time_source))
    return routes


def optimize(routes, mode, budgets):
    if mode == "direct":
        caps = [route.direct_cap for route in routes]
    elif mode == "hub":
        caps = [route.hub_cap for route in routes]
    elif mode == "hybrid":
        caps = [max(route.direct_cap, route.hub_cap) for route in routes]
    else:
        raise ValueError(f"Unknown mode: {mode}")

    winners = dict.fromkeys(budgets)
    best_keys = {}
    for frequencies in product(*(range(cap + 1) for cap in caps)):
        active = [(route, freq) for route, freq in zip(routes, frequencies) if freq]
        minutes = sum(route.round_trip_minutes * freq for route, freq in active)
        if minutes > max(budgets):
            continue
        spokes = sum(HUB in route.cities and route.hub_cap > 0 for route, _ in active)
        if mode != "direct" and spokes < MIN_SPOKES:
            continue
        if mode == "hybrid" and not any(route.hub_cap == 0 for route, _ in active):
            continue

        passengers = sum((route.annual_pax * freq for route, freq in active), Decimal(0))
        revenue = sum((route.annual_revenue * freq for route, freq in active), Decimal(0))
        plan = Plan(frequencies, minutes, passengers, revenue, spokes)
        score = (passengers, revenue, -minutes)
        for budget in budgets:
            if minutes <= budget and (budget not in best_keys or score > best_keys[budget]):
                winners[budget] = plan
                best_keys[budget] = score
    return winners


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(fields)
        writer.writerows(rows)


def generate(budget_hours, block_times_path, output):
    summary = []
    allocations = []
    budgets = tuple(hours * 60 for hours in budget_hours)
    for scenario in SCENARIOS:
        routes = read_options(scenario, block_times_path)
        plans = {mode: optimize(routes, mode, budgets) for mode in MODES}
        for hours, budget in zip(budget_hours, budgets):
            direct = plans["direct"][budget]
            for mode in MODES:
                plan = plans[mode][budget]
                if plan is None:
                    summary.append((2028, scenario, hours, mode, "infeasible",
                                    "", "", "", "", "", "", "", routes[0].time_source))
                    continue
                summary.append((2028, scenario, hours, mode, "optimal", plan.minutes,
                                budget - plan.minutes, plan.spokes, plan.passengers,
                                plan.revenue, plan.passengers - direct.passengers,
                                plan.revenue - direct.revenue, routes[0].time_source))
                for route, freq in zip(routes, plan.frequencies):
                    if freq:
                        allocations.append((2028, scenario, hours, mode, *route.cities,
                                            freq, route.round_trip_minutes,
                                            freq * route.round_trip_minutes,
                                            freq * route.annual_pax,
                                            freq * route.annual_revenue, route.time_source))

    output.mkdir(parents=True, exist_ok=True)
    write_csv(output / "network_optimizer_summary.csv",
              ("year", "scenario", "budget_block_hours_week", "mode", "status",
               "used_block_minutes_week", "spare_block_minutes_week", "hub_spokes",
               "additional_passenger_segments_year", "additional_ticket_revenue_rub_year",
               "passenger_segments_delta_vs_direct", "ticket_revenue_delta_vs_direct_rub",
               "block_time_source"), summary)
    write_csv(output / "network_optimizer_routes.csv",
              ("year", "scenario", "budget_block_hours_week", "mode", "city_a", "city_b",
               "weekly_round_trips", "round_trip_block_minutes", "used_block_minutes_week",
               "additional_passenger_segments_year", "additional_ticket_revenue_rub_year",
               "block_time_source"), allocations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", nargs="+", type=int, default=DEFAULT_BUDGETS,
                        help="weekly block-hour budgets, default: 20 30 40 50 60")
    parser.add_argument("--block-times", type=Path,
                        help="CSV with origin,destination,round_trip_block_minutes for all pairs")
    parser.add_argument("--out-dir", type=Path, default=OUT)
    args = parser.parse_args()
    if any(hours <= 0 for hours in args.hours):
        parser.error("--hours must contain positive integers")
    generate(sorted(set(args.hours)), args.block_times, args.out_dir)


if __name__ == "__main__":
    main()
