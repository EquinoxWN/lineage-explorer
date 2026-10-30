# lineage-explorer (Python)

The custom OpenLineage emitter for plain scripts (`lineage_explorer.emitter`), offline event
validation against the bundled OpenLineage schemas (`lineage_explorer.validate`), and the
`lineage-emit` command (`demo`, `validate`). See the main README one level up.

```python
from lineage_explorer.emitter import DatasetRef, LineageEmitter, client_for

em = LineageEmitter("scripts", client_for("http://localhost:5000"))
with em.run(
    "nightly_export",
    inputs=[DatasetRef("file", "/data/in.csv")],
    outputs=[DatasetRef("file", "/data/out.csv", [("id", "INTEGER")])],
):
    ...  # START is sent on entry; COMPLETE on success, FAIL (then re-raise) on an exception
```
