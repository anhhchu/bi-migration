import pytest

from datasource_semantic_migration.input_contract import InputContract


def test_input_contract_derives_standard_paths():
    contract = InputContract.create("/Volumes/main/bi_migration/tableau_sources/")

    assert contract.input_volume_path == "/Volumes/main/bi_migration/tableau_sources"
    assert contract.datasources_path.endswith("/datasources")
    assert contract.mappings_path.endswith("/mappings")


def test_input_contract_rejects_local_paths():
    with pytest.raises(ValueError, match="Unity Catalog Volume"):
        InputContract.create("samples/tableau")
