from __future__ import annotations

import argparse
import json
from pathlib import Path

from datasource_semantic_migration.twbx_converter import (
    convert_twbx_directory,
    upload_tdsx_files,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_DIRECTORY = REPOSITORY_ROOT / "samples" / "tableau"
DEFAULT_OUTPUT_DIRECTORY = REPOSITORY_ROOT / "build" / "tdsx-conversion"
DEFAULT_VOLUME_ROOT = "/Volumes/main/bi_migration/tableau_datasources"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert every Tableau TWBX workbook into validated standalone TDSX packages."
    )
    parser.add_argument("--input-dir", default=DEFAULT_INPUT_DIRECTORY.as_posix())
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIRECTORY.as_posix())
    parser.add_argument("--upload", action="store_true", help="Upload validated TDSX files to UC Volumes")
    parser.add_argument("--volume-root", default=DEFAULT_VOLUME_ROOT)
    parser.add_argument("--profile", default="DEFAULT")
    return parser


def main() -> None:
    arguments = build_parser().parse_args()
    manifest = convert_twbx_directory(arguments.input_dir, arguments.output_dir)
    result = {"conversion": manifest}
    if arguments.upload:
        result["upload"] = upload_tdsx_files(
            Path(arguments.output_dir) / "datasources",
            volume_root=arguments.volume_root,
            profile=arguments.profile,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
