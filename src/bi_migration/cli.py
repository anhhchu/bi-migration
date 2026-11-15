from __future__ import annotations

import argparse
import json
from pathlib import Path

from bi_migration.grouping import dependency_graph, group_assets
from bi_migration.mapping import draft_mapping, write_mapping_outputs
from bi_migration.tableau import find_tableau_files, parse_tableau


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def analyze(args: argparse.Namespace) -> int:
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    files = find_tableau_files(args.input)
    if not files:
        raise SystemExit(f"No Tableau files found under {args.input}")
    assets = [parse_tableau(path) for path in files]
    groups = group_assets(assets)
    graph = dependency_graph(assets)
    target_metadata = json.loads(Path(args.target_metadata).read_text(encoding="utf-8"))
    mapping, unresolved, kpis = draft_mapping(assets, target_metadata, args.domain)

    _write_json(output / "inventory.json", assets)
    _write_json(output / "dependency_graph.json", graph)
    _write_json(output / "groups.json", groups)
    write_mapping_outputs(mapping, unresolved, kpis, output)
    print(f"Analyzed {len(assets)} assets into {len(groups)} semantic groups")
    print(f"Drafted {len(mapping['fields'])} field mappings; {len(unresolved)} unresolved")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bi-migrate")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze_parser = subparsers.add_parser("analyze", help="Inventory Tableau files and draft mappings")
    analyze_parser.add_argument("--input", required=True)
    analyze_parser.add_argument("--target-metadata", required=True)
    analyze_parser.add_argument("--domain", required=True)
    analyze_parser.add_argument("--output", required=True)
    analyze_parser.set_defaults(handler=analyze)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
