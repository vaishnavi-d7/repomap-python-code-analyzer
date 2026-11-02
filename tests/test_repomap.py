from fastapi.testclient import TestClient

from analyzer import analyze_repository
from app import app

client = TestClient(app)


def make_repo(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("from .helpers import work\n")
    (tmp_path / "pkg" / "helpers.py").write_text(
        "import os\n\n"
        "def work(value):\n"
        "    return normalize(value)\n\n"
        "def normalize(value):\n"
        "    return value\n\n"
        "class Runner:\n"
        "    async def run(self):\n"
        "        return normalize('ok')\n"
    )
    return tmp_path


def test_finds_functions_methods_and_async(tmp_path):
    graph = analyze_repository(make_repo(tmp_path))
    definitions = {item["qualified_name"]: item for item in graph["functions"]}
    assert "pkg.helpers.work" in definitions
    assert definitions["pkg.helpers.Runner.run"]["kind"] == "method"
    assert definitions["pkg.helpers.Runner.run"]["is_async"] is True
    assert graph["stats"]["functions"] == 3


def test_finds_unambiguous_call_edges(tmp_path):
    graph = analyze_repository(make_repo(tmp_path))
    edges = {(edge["caller"], edge["callee"]) for edge in graph["call_edges"]}
    assert ("pkg.helpers.work", "pkg.helpers.normalize") in edges
    assert ("pkg.helpers.Runner.run", "pkg.helpers.normalize") in edges


def test_finds_import_edges(tmp_path):
    graph = analyze_repository(make_repo(tmp_path))
    edges = {(edge["source"], edge["target"]) for edge in graph["import_edges"]}
    assert ("pkg", "pkg.helpers") in edges
    assert ("pkg.helpers", "os") in edges


def test_ignores_virtual_environment_and_git_dirs(tmp_path):
    repo = make_repo(tmp_path)
    (repo / ".venv").mkdir()
    (repo / ".venv" / "ignored.py").write_text("def ignored(): pass\n")
    (repo / ".git").mkdir()
    (repo / ".git" / "ignored.py").write_text("def ignored_too(): pass\n")
    graph = analyze_repository(repo)
    assert graph["stats"]["files_scanned"] == 2
    assert all("ignored" not in item["file"] for item in graph["functions"])


def test_reports_syntax_errors_and_continues(tmp_path):
    (tmp_path / "bad.py").write_text("def broken(:\n")
    (tmp_path / "good.py").write_text("def fine():\n    return 1\n")
    graph = analyze_repository(tmp_path)
    assert graph["stats"]["parse_errors"] == 1
    assert graph["errors"][0]["file"] == "bad.py"
    assert [item["name"] for item in graph["functions"]] == ["fine"]


def test_rejects_missing_or_non_directory_path(tmp_path):
    try:
        analyze_repository(tmp_path / "missing")
    except ValueError as exc:
        assert "not an existing directory" in str(exc)
    else:
        raise AssertionError("Expected invalid path to fail")


def test_api_health_and_analyze_graph_round_trip(tmp_path):
    repo = make_repo(tmp_path)
    assert client.get("/health").json() == {"status": "ok"}
    response = client.post("/analyze", json={"path": str(repo)})
    assert response.status_code == 200
    assert response.json()["stats"]["functions"] == 3
    graph_response = client.get("/graph")
    assert graph_response.status_code == 200
    assert graph_response.json()["root"] == str(repo.resolve())


def test_api_rejects_invalid_path(tmp_path):
    response = client.post("/analyze", json={"path": str(tmp_path / "missing")})
    assert response.status_code == 400
