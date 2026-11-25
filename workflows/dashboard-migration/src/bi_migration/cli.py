from __future__ import annotations

import argparse
import json
from pathlib import Path

from bi_migration.corpus import generate_corpus
from bi_migration.grouping import dependency_graph, group_assets
from bi_migration.mapping import draft_mapping, write_mapping_outputs
from bi_migration.pipeline import run_backend_pipeline
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


def backend(args: argparse.Namespace) -> int:
    result = run_backend_pipeline(
        input_path=args.input,
        mapping_documents_path=args.mapping_docs,
        target_metadata_path=args.target_metadata,
        domain=args.domain,
        output_path=args.output,
        run_id=args.run_id,
        source_base_uri=args.source_base_uri,
    )
    print(
        f"Registered {result['artifacts']} artifacts; inventoried {result['assets']} assets; "
        f"quarantined {result['quarantined']}"
    )
    print(
        f"Created {result['groups']} semantic groups; drafted {result['fields']} fields; "
        f"{result['unresolved']} unresolved; ready={result['ready']}"
    )
    return 0


def generate_test_corpus(args: argparse.Namespace) -> int:
    result = generate_corpus(args.output)
    print(
        f"Generated {result['workbooks']} workbook artifacts and "
        f"{result['mapping_documents']} mapping document under {result['output']}"
    )
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
    backend_parser = subparsers.add_parser("backend", help="Run the V2 backend pipeline")
    backend_parser.add_argument("--input", required=True)
    backend_parser.add_argument("--mapping-docs")
    backend_parser.add_argument("--target-metadata", required=True)
    backend_parser.add_argument("--domain", required=True)
    backend_parser.add_argument("--output", required=True)
    backend_parser.add_argument("--run-id", default="local-run")
    backend_parser.add_argument("--source-base-uri")
    backend_parser.set_defaults(handler=backend)
    corpus_parser = subparsers.add_parser("generate-corpus", help="Generate the V2 Tableau test corpus")
    corpus_parser.add_argument("--output", required=True)
    corpus_parser.set_defaults(handler=generate_test_corpus)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
