import pytest

from enzyme_searcher.genera import flatten, load_genera, parse_genera
from enzyme_searcher.normalize import (normalize_collection_number, normalize_ec, normalize_enzyme_name,
                                       normalize_genus, normalize_result, split_species_strain)


@pytest.mark.parametrize("raw,expected", [
    ("Ca. Microthrix", "Candidatus Microthrix"), ("Ca.Nitrotoga", "Candidatus Nitrotoga"),
    ("candidatus  anammoximicrobium", "Candidatus Anammoximicrobium"), ("  gordonia ", "Gordonia"),
])
def test_normalize_genus(raw, expected):
    assert normalize_genus(raw) == expected


def test_normalize_values():
    assert normalize_ec("EC 3.2.1.21") == "3.2.1.21" == normalize_ec("ec:3.2.1.21")
    assert normalize_ec("3.2.1.-") == "3.2.1.-" and normalize_ec("n/a") == "" and normalize_ec(None) == ""
    assert normalize_enzyme_name("  Esterase   Lipase (C 8) ") == "esterase lipase (c 8)"
    assert [normalize_result(v) for v in ("+", "-", "+/-", None, "positive")] == ["+", "-", "NA", "NA", "+"]
    assert normalize_collection_number("dsm-43247") == "DSM43247" == normalize_collection_number("DSM 43247")


@pytest.mark.parametrize("name,genus,expected", [
    ("Gordonia bronchialis DSM 43247", "Gordonia", ("Gordonia bronchialis", "DSM 43247")),
    ("Gordonia sp. KTR9", "Gordonia", ("Gordonia sp.", "KTR9")),
    ("Nitrospira defluvii", "Nitrospira", ("Nitrospira defluvii", "")),
    ("Candidatus Nitrospira inopinata", "Nitrospira", ("Candidatus Nitrospira inopinata", "")),
    ("Candidatus Nitrotoga sp. AM1P", "Candidatus Nitrotoga", ("Candidatus Nitrotoga sp.", "AM1P")),
])
def test_split_species_strain(name, genus, expected):
    assert split_species_strain(name, genus) == expected


def test_parse_genera_groups():
    groups = parse_genera("# Header sentence.\nLoose\n# Actinomycetota\nGordonia\nCa. Microthrix\ngordonia\n")
    assert groups == {"Other": ["Loose"], "Actinomycetota": ["Gordonia", "Candidatus Microthrix"]}


def test_packaged_genera_list():
    groups = load_genera()
    assert len(flatten(groups)) == 36 and len(groups) == 7
    assert "Candidatus Nitrotoga" in flatten(groups)
