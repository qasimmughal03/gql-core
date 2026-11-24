"""Command-line interface: ``service-impact <command>``.

    service-impact impact orders-db            what breaks, who owns it, and why
    service-impact dependents catalog-db       stored readers and writers of a database
    service-impact teams sessions-cache        teams to notify
    service-impact hotspots --min 3            services with a large fan-out (typed plan)
    service-impact tier-owners --tier 1        owner of each tier-1 service (typed plan)
    service-impact plan --tier 1               print that typed plan as JSON, as an agent would send it
    service-impact serve --port 8080           JSON API
    service-impact version                     installed gql-core version and location
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import version

from service_impact.analysis import ImpactAnalyzer, UnknownComponent, as_dict


def _print_impact(an: ImpactAnalyzer, failed: str) -> None:
    affected = an.impact(failed)
    print(f"If {failed} fails, {len(affected)} components are affected:\n")
    for a in affected:
        owner = f"{a.team} (lead {a.team_lead}, {a.channel})" if a.team else "NO OWNER"
        print(f"  tier {a.tier}  {a.id:<20} {a.dependency:<8} {a.hops} hop(s)  owner: {owner}")
        path = a.evidence_path[0].src + "".join(f" -[{s.rel}]-> {s.dst}" for s in a.evidence_path)
        print(f"          evidence: {path}")
        if a.dependency == "indirect":
            print(f"          inferred by: {', '.join(a.derived_by)}")
    unowned = an.unowned_affected(failed)
    if unowned:
        print(f"\nAffected components with no owning team: {', '.join(unowned)}")
    print("\nTeams to notify:")
    for t in an.teams_to_notify(failed):
        print(f"  {t['team']:<10} {t['channel']:<18} {t['components']} component(s): {', '.join(sorted(t['affected']))}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="service-impact", description="Service dependency and impact analysis")
    ap.add_argument("--catalog", help="path to a catalog JSON file (default: the bundled example)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of text")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("impact").add_argument("component")
    sub.add_parser("dependents").add_argument("database")
    sub.add_parser("teams").add_argument("component")
    sub.add_parser("hotspots").add_argument("--min", type=int, default=3)
    sub.add_parser("tier-owners").add_argument("--tier", type=int, default=1)
    sub.add_parser("plan").add_argument("--tier", type=int, default=1)
    srv = sub.add_parser("serve")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8080)
    sub.add_parser("version")
    args = ap.parse_args(argv)

    if args.cmd == "version":
        import gql_core
        print(f"gql-core {version('gql-core')} at {gql_core.__file__}")
        return 0

    an = ImpactAnalyzer.from_catalog(args.catalog)
    try:
        if args.cmd == "impact":
            if args.json:
                print(json.dumps([as_dict(a) for a in an.impact(args.component)], indent=2))
            else:
                _print_impact(an, args.component)
        elif args.cmd == "dependents":
            print(json.dumps(an.dependents_of_database(args.database), indent=2))
        elif args.cmd == "teams":
            print(json.dumps(an.teams_to_notify(args.component), indent=2))
        elif args.cmd == "hotspots":
            print(json.dumps(an.fan_out_hotspots(args.min), indent=2))
        elif args.cmd == "tier-owners":
            print(json.dumps(an.tier_owners(args.tier), indent=2))
        elif args.cmd == "plan":
            from gql_core import PlanBuilder
            print(PlanBuilder(an.tier_owners_plan(args.tier)).to_json())
        elif args.cmd == "serve":
            from service_impact.api import make_server
            server = make_server(an, args.host, args.port)
            print(f"serving on http://{args.host}:{server.server_address[1]}  (Ctrl+C to stop)")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    except UnknownComponent as exc:
        print(f"error: unknown component {exc.args[0]}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
