from enzyme_searcher.__main__ import main


def test_providers_command(capsys):
    assert main(["providers"]) == 0
    out = capsys.readouterr().out
    assert "bacdive" in out and "kegg" in out and "brenda" in out


def test_fetch_command(tmp_path, providers, kegg_client, monkeypatch, capsys):
    monkeypatch.setattr("enzyme_searcher.__main__.fetch_enzyme_names", lambda: __import__(
        "enzyme_searcher").fetch_enzyme_names(kegg_client))
    xlsx = tmp_path / "g.xlsx"
    code = main(["fetch", "--genus", "gordonia", "--max-organisms", "2", "--cache", str(tmp_path / "c"),
                 "--excel", str(xlsx)])
    assert code == 0 and xlsx.exists()
    assert "Gordonia" in capsys.readouterr().out
