# manifests/artifacts

`<bench>-<run-id>.manifest.json`, written by `klt artifact put` through
`sim/bin/artifact_store.py`:

```json
{"schema_version": 1,
 "entries": [{"sha256": "<64 hex>", "size": 1234, "kind": "evidence",
              "producer": {"tool": "klt", "version": "..."},
              "uri": "artifact:<key>", "name": "sim/<bench>/runs/<run-id>/<file>"}]}
```

- Every `uri` is `artifact:<key>`; no `s3://`, bucket, account id or broker URL
  ever appears in a manifest (`git grep -nE 's3://|arn:aws:' --
  'manifests/artifacts/*.manifest.json'` is empty).
- Append-only: a correction is a new run with a new id.
- Verify from a fleet worker: `klt artifact verify manifests/artifacts/<file>`.
- CI: `python3 sim/bin/check_artifact_manifests.py check`.
