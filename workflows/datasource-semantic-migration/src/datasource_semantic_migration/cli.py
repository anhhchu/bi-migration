from __future__ import annotations

import argparse
import json

from .config import load_workflow_config
from .discovery import discover_inputs, write_inventory
from .input_contract import InputContract
from .manifest import build_workflow_manifest
from .schema_registry import SchemaRegistry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Datasource Semantic Migration workflow utilities")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_input = subparsers.add_parser("validate-input", help="Validate the one-parameter input contract")
    validate_input.add_argument("--input-volume-path", required=True)

    manifest = subparsers.add_parser("create-manifest", help="Render the deterministic workflow manifest")
    manifest.add_argument("--input-volume-path", required=True)
    manifest.add_argument("--workflow-run-id", required=True)
    manifest.add_argument("--job-run-id", required=True)
    manifest.add_argument("--config", required=True)

    discover = subparsers.add_parser("discover-inputs", help="Inventory TDS/TDSX inputs and safely unpack packages")
    discover.add_argument("--input-volume-path", required=True)
    discover.add_argument("--workflow-run-id", required=True)
    discover.add_argument("--output-path", required=True)

    schemas = subparsers.add_parser("list-schemas", help="List registered artifact schemas")
    schemas.add_argument("--schemas-root", required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "validate-input":
        print(json.dumps(InputContract.create(args.input_volume_path).as_dict(), indent=2))
        return
    if args.command == "create-manifest":
        config = load_workflow_config(args.config)
        manifest = build_workflow_manifest(
            workflow_run_id=args.workflow_run_id,
            job_run_id=args.job_run_id,
            input_volume_path=args.input_volume_path,
            config=config,
        )
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return
    if args.command == "discover-inputs":
        contract = InputContract.create(args.input_volume_path)
        output_path = InputContract.create(args.output_path).input_volume_path
        inventory = discover_inputs(
            datasources_path=contract.datasources_path,
            mappings_path=contract.mappings_path,
            extraction_root=f"{output_path}/extracted",
            workflow_run_id=args.workflow_run_id,
        )
        inventory_path = write_inventory(inventory, f"{output_path}/inventory/input-inventory.json")
        print(json.dumps({"inventory_path": str(inventory_path), "summary": inventory["summary"]}, indent=2))
        return
    registry = SchemaRegistry(args.schemas_root)
    print(json.dumps({"schemas": registry.names()}, indent=2))


if __name__ == "__main__":
    main()
