# RepoMap

RepoMap is a small, local-first prototype that scans Python source files with the standard-library `ast` module and returns a JSON representation of functions, classes (through their methods), function-call relationships, and imports. A FastAPI service exposes the analysis.

> **Scope:** RepoMap currently analyzes a directory available on the same machine as the API. It does not clone GitHub URLs, execute analyzed code, resolve all dynamic calls, or generate an AI summary. Call detection is best-effort static analysis, not a complete Python call graph.

## Requirements

- Python 3.10+
- pip

## Run locally

From this directory, create and activate a virtual environment, install the dependencies, then start the API:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
python -m pip install -r requirements-dev.txt
uvicorn app:app --reload
```

The API listens at `http://127.0.0.1:8000`. Interactive API documentation is available at `http://127.0.0.1:8000/docs`.

## Analyze a repository

`POST /analyze` expects a JSON body with a directory path on the API machine:

```bash
curl -X POST http://127.0.0.1:8000/analyze \
  -H 'Content-Type: application/json' \
  -d '{"path":"/absolute/path/to/python-project"}'
```

The response contains the analysis graph. The most recent successful graph is also available from `GET /graph`. `GET /health` is a simple liveness check. The latest graph is stored in memory, so it resets when the server restarts.

### Response shape

```json
{
  "root": "/absolute/path/to/python-project",
  "modules": [{"name": "mypackage.worker", "file": "mypackage/worker.py"}],
  "functions": [
    {
      "id": "mypackage.worker.run",
      "name": "run",
      "qualified_name": "mypackage.worker.run",
      "module": "mypackage.worker",
      "kind": "function",
      "file": "mypackage/worker.py",
      "line": 4,
      "is_async": false
    }
  ],
  "call_edges": [
    {"caller": "mypackage.worker.run", "callee": "mypackage.worker.load", "kind": "call"}
  ],
  "import_edges": [
    {"source": "mypackage.worker", "target": "json", "kind": "import"}
  ],
  "errors": [],
  "stats": {
    "files_scanned": 1,
    "modules": 1,
    "functions": 1,
    "call_edges": 1,
    "import_edges": 1,
    "parse_errors": 0
  }
}
```

Parse failures are returned in `errors`; valid files are still analyzed. Common generated or environment directories such as `.git`, `.venv`, `venv`, `build`, and `dist` are skipped.

## Static-analysis behavior and limitations

- Definitions include functions, async functions, and methods. Classes are represented by their qualified method names; class metadata itself is not currently a separate graph node.
- Calls are reported when the target can be identified conservatively: bare calls resolve to a same-module definition first, then to a uniquely named project-wide definition; attribute calls are included only when their final method/function name is unique in the repository.
- Ambiguous calls, dynamic dispatch, reflection, monkey-patching, and many imported aliases cannot be resolved reliably. Built-in or external calls are not call-graph nodes unless a matching project definition is found.
- Import edges include imported module names, including external dependencies. Relative imports are normalized as far as the source syntax permits.
- The API accepts a filesystem path and should only be exposed to trusted users. It reads source files under the supplied directory; do not make it a public arbitrary-path service without adding authentication, path restrictions, and resource limits.

## Tests

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```

The tests cover extraction, call/import edges, ignored directories, parse errors, invalid paths, and the HTTP endpoints. GitHub Actions runs the same suite on pushes and pull requests.

## Project status

This is an initial portfolio-sized prototype, not a production code-intelligence platform. Before publishing it, review the implementation, understand its limitations, run it against repositories you are permitted to analyze, and make your own improvements. Do not describe GitHub URL ingestion or an LLM summary as implemented unless you add and test those features.
