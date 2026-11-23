import json

import pytest

from datasource_semantic_migration.analysis_batches import build_analysis_batches


def test_build_analysis_batches_skips_duplicates_and_chunks_unique_assets():
    inventory = {
        "assets": [
            {"duplicate_of": None},
            {"duplicate_of": "asset-0"},
            {"duplicate_of": None},
            {"duplicate_of": None},
            {"duplicate_of": None},
        ]
    }

    batches = [json.loads(item) for item in build_analysis_batches(inventory, batch_size=2)]

    assert batches == [[0, 2], [3, 4]]


def test_build_analysis_batches_rejects_non_positive_size():
    with pytest.raises(ValueError, match="positive"):
        build_analysis_batches({"assets": []}, batch_size=0)
