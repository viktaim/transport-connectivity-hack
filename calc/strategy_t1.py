"""Build the offline T1 prototype from the team's route model."""
import json

from economics_dashboard import OUT, summarize


def main():
    pilot = [
        {key: row[key] for key in ("year", "scenario", "hypothesis",
                                   "passengers_new", "revenue_new_rub")}
        for row in summarize()
    ]
    model = {"baseYear": 2025, "redWings": 2_700_000,
             "benchmark": 13_800_000, "pilot": pilot}
    template = OUT.parent / "calc" / "strategy_t1_template.html"
    page = template.read_text(encoding="utf-8").replace(
        "/* MODEL_DATA */ null", json.dumps(model, ensure_ascii=False)
    )
    (OUT / "strategy_t1.html").write_text(page, encoding="utf-8")


if __name__ == "__main__":
    main()
