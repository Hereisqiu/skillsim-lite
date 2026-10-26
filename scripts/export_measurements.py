"""Export all measurements for the report (no API calls):

    python -m scripts.export_measurements [--sessions-per-month 8]

Writes exports/measurements.json (measured + projected, clearly separated),
exports/simulations.csv and exports/requests.csv.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

from backend import config, ledger, measure, store
from backend.main import SCENARIOS_BY_ID


def main_cli():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions-per-month", type=float, default=measure.DEFAULT_SESSIONS_PER_USER_MONTH)
    args = ap.parse_args()

    report = measure.report(store.all_sessions(), SCENARIOS_BY_ID, args.sessions_per_month, request_limit=10**9)
    report["generated_at"] = datetime.now(timezone.utc).isoformat()
    out = config.ROOT / "exports"
    out.mkdir(exist_ok=True)
    (out / "measurements.json").write_text(json.dumps(report, indent=2))
    (out / "simulations.csv").write_text(measure.simulations_csv(report["measured"]["simulations"]))
    (out / "requests.csv").write_text(measure.requests_csv(ledger.read_all()))
    s = report["measured"]["simulation_summary"]
    print(f"Wrote exports/measurements.json, simulations.csv, requests.csv ({s['runs']} simulations, "
          f"{report['measured']['all_requests']['requests']} requests)")


if __name__ == "__main__":
    main_cli()
