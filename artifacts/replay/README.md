# Replay evidence

`local-replay.json` contains executed SQLite/Python fixture evidence. It does not
prove BigQuery or Power BI behavior.

The executed [BigQuery proof](bigquery-replay.json) passed **24/24 checks** on
2026-11-18, ending at 12:26:39 UTC. Its 33 recorded verification queries completed,
and the active real release `dsny_20261118` was restored and read back successfully.
Thirteen fictional current request keys remained thirteen when one old open
request became closed. The earlier backlog stayed six; the later observation
recorded five. Exact B replay preserved rows, metrics and the mart hash. These
values describe synthetic fixtures, not NYC performance.

The opt-in cloud proof writes `bigquery-replay.json` only when executed. It uses
the unchanged, explicitly synthetic A/B captures under `data/fixtures`, performs
real BigQuery writes and dbt builds, and retains full verification SQL, query
parameters, returned rows and job metadata. Synthetic results are never claims
about historical NYC performance.

```powershell
python -m nyc311 replay-cloud --cloud-config .local/cloud.json
```

Publish a real release first. The command holds the same `.local/operator.lock`
as normal pipeline runs for the whole sequence: publish A, publish B, replay B,
then intentionally inject the application validation-gate error after another
real dbt build. The last step demonstrates the response to an injected gate
failure; it is not a naturally failing dbt SQL test. Audit rows grow by design;
idempotence checks compare observations, captured rows, current keys, registered
releases, reporting rows and metrics.

In the executed failure check, the expected `ContractError` was observed after
dbt completed, the cloud audit recorded the failed validation phase, B remained
the active last good release, no new release was registered, and both A and B
facts/backlogs stayed unchanged. This does not demonstrate a mid-publication
network interruption or a naturally failing SQL test. Those cases must not be
inferred from this bounded injected-gate demonstration.

The command records the original real active release and restores that selection
in `finally`, using a transaction that compares the current pointer and original
release identity. It restores only from one of this proof's three release IDs.
If another operation changes the pointer, restoration refuses to overwrite it.
Always inspect the evidence's `restoration` result before the next operation.
Power BI should remain pinned to the selected real release, independently of this
temporary control pointer.

This transition proof requires an unused synthetic fixture scope. It never
deletes cloud history or resets current rows to manufacture a new transition.
Existing evidence files are also never overwritten. After a completed proof,
use ordinary `nyc311 run` with the original B capture and `cloud_replay_b` release
ID for additional exact replay. If an interrupted first attempt leaves fixture
state, inspect its partial evidence and retained cloud state before recovery;
do not erase history or claim an incomplete sequence passed.
