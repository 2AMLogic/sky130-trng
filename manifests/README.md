# manifests

Committed manifests of evidence stored in the fleet artifact store (issue #347,
DR-0016). Only manifests live here, never the stored bytes.

- `artifacts/` -- one `<bench>-<run-id>.manifest.json` per run, written by
  `sim/bin/artifact_store.py`. Append-only.

See "Artifact store" in `sim/README.md`.
