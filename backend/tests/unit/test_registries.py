"""Unit tests for registries module and failure policies."""

from backend.app.registries import IssuerRegistryConnector, SanctionsWatchlistConnector, RegistryResult


def test_issuer_registry_exact_and_fuzzy_matches():
    connector = IssuerRegistryConnector()
    
    # Exact match
    res = connector.lookup("Bureau Veritas SA")
    assert res.matched is True
    assert res.match_score == 1.0
    assert res.match_type == "exact_name"
    assert res.status == "healthy"
    assert res.source_version != ""

    # Exact match on short_name matches exact_name
    short_res = connector.lookup("Bureau Veritas")
    assert short_res.matched is True
    assert short_res.match_score == 1.0
    assert short_res.match_type == "exact_name"

    # Fuzzy match on minor typo
    fuzzy_res = connector.lookup("Buro Veritas SA")
    assert fuzzy_res.matched is True
    assert fuzzy_res.match_score >= 0.75
    assert fuzzy_res.match_type == "fuzzy_name"

    # Unknown issuer
    unknown_res = connector.lookup("Fake Certification Body Worldwide LLC")
    assert unknown_res.matched is False
    assert unknown_res.match_type == "none"


def test_sanctions_connector_screening():
    connector = SanctionsWatchlistConnector()

    # Clean entity
    clean_res = connector.screen("Sunrise Electronics Shanghai Ltd", "CN")
    assert clean_res.matched is False
    assert clean_res.status == "healthy"

    # Sanctioned entity
    blocked_res = connector.screen("Blocked Entity Test Trade Corp", "RU")
    assert blocked_res.matched is True
    assert blocked_res.match_score == 1.0


def test_registry_result_snapshot_hash():
    connector = IssuerRegistryConnector()
    res = connector.lookup("SGS")
    h = res.snapshot_hash()
    assert len(h) == 64
    assert isinstance(h, str)
