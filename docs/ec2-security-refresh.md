# Refresh Marketplace security updates

`bt-ec2-refresh` installs the available Debian and TurnKey security updates into
unbooted source images, sets EC2 first-boot updates to `FORCE`, and boot-tests
each candidate before submitting a new version to its existing Marketplace
listing. First boot checks for fixes released after the image was built.
If a security update requires stable-repository dependencies, the refresh
installs those dependencies too and requires zero pending security upgrades.

The retained batch directory contains the product/source mapping, resource IDs,
per-image update and boot logs, publication requests, and cleanup evidence. Use
the most recent verified batch as the input to the next refresh:

```sh
./bt-ec2-refresh prepare \
    --from-batch /path/to/previous-batch \
    --state /path/to/new-batch \
    --workers 12
./bt-ec2-refresh run \
    --state /path/to/new-batch \
    --workers 12 --publish --cleanup
./bt-ec2-refresh status --state /path/to/new-batch
```

The first retained batch is
`/home/z/projects/turnkey-release-state/security-refresh-20261104`.
Keep batch state on persistent storage. `prepare` creates workers, a batch SSH
key, and an SSH security group restricted to the controller's address. It reuses
the previous batch's region, subnet, worker image, and catalog mapping. Verified
output AMIs become the next refresh's source images.

The controller needs Python 3 with boto3, AWS credentials for the source-image
account, and access to the configured LibreSBX CloudTask environment. The CLI
accepts overrides for the sandbox, CloudTask interpreter, library paths, and
Marketplace ingestion role. CloudTask uses preallocated workers and their EC2
SSH key. Workers receive no AWS credentials.

## Publication and recovery

The script submits only images that pass first-boot checks, including installed
Brotli fixes, initialization completion, daily updates, and the web initialization
fence. Publication records distinguish submission from AWS's review result.
An existing review on a product defers its new submission. `publish` retries
these submissions. For a legacy security refresh, watch completion records AWS
publication review and availability; delivery retirement follows the caller's
verified cutover workflow:

```sh
./bt-ec2-refresh publish --state /path/to/batch
```

For automatic follow-up while AWS reviews the submissions, run `watch` in a
supervised background service:

```sh
./bt-ec2-refresh watch --state /path/to/batch
```

It checks every five minutes for up to seven days, retries deferred submissions,
and records available, completed, pending, and failed products in
`publication-watch.json`. Its `completion_scope` identifies AWS publication for
legacy refreshes or actual customer verification for a hotfix. This phase
needs controller AWS access but no EC2 workers or batch SSH key.

A nonzero refresh exit means at least one image did not pass verification.
Read the app's `APP-state.json`, `APP.log`, and `APP-boot.log`.
Before cleanup, rerun selected jobs with `run --apps app1,app2`. After cleanup,
prepare a new batch from the retained state.

## Scoped 19.0 hotfix

Use a frozen manifest and plan for the Core/LAMP canary. The accepted package
baseline supplies exact versions and signed APT hashes, including TKLBAM 1.5.6
and Confconsole 2.2.6. These versions are manifest inputs rather than controller
pins. The public release is 19.0.3; its EC2 identity and genuine profile use the
separate technical revision 19.0.3.3. Preserve each app's complete canonical
profile configuration and hook modes.

```sh
./bt-ec2-refresh prepare --from-batch /path/to/worker-seed \
    --state /path/to/hotfix-batch --apps core,lamp --workers 1 \
    --plan-file /path/to/frozen-plan.json \
    --hotfix-manifest /path/to/hotfix.json
./bt-ec2-refresh run --state /path/to/hotfix-batch --apps core,lamp --workers 1
```

The first run exports each pristine EC2
profile and its hash-bound receipt, then pauses at `PROFILE_PENDING_PUBLICATION`
before boot. Retain the batch workers/key while publishing those distinct
profiles additively. Supply `--profile-publications FILE` when resuming run;
each app's receipt must match the exported identity, profile hash and public
readback hash. Run actual native/app QA and provide its evidence through
`--source-acceptance FILE` before publish. Watch with
`--customer-acceptance FILE` after actual Marketplace customer-image launches in
every frozen region. AWS availability alone keeps a hotfix pending.

Prepare and resumed run, publish and watch verify that the executing adapter
matches the declared committed main revision. Cleanup remains usable when
source or input validation fails. App selection applies to every phase.

A failed export after the worker's verified patch resumes that staged output
from its original worker. It validates the complete profile export before
retaining files or snapshotting, and reuses matching bytes after interruption.
Keep that worker available until the export is retained. Every retained volume
without a verified patch boundary requires an explicit fresh unpublished
candidate from frozen inputs, including abrupt interruptions recorded as
`PATCHING` or with no status. Reapplying overlays to that root is refused.
Resolve any existing profile publication/identity before changing candidate
bytes.

Hotfix retirement uses only explicit `superseded_delivery_ids` belonging to
other 19.0 versions, after matching customer QA. Public v18 and unselected
delivery options remain available. Root owns AMI/snapshot retirement after
catalog, customer and reference checks.

## Cleanup

`run --cleanup` waits for its image tasks, runs a separate CloudTask cleanup
phase, terminates batch-tagged workers and test instances, and deletes their
remaining EBS volumes. It retains the snapshots backing registered output AMIs.
After replacement deliveries or Hub mappings are active and verified, retire
the superseded AMIs and delete their unneeded backing snapshots. Do not keep
rollback copies unless requested. Check launch-template references and update
the next batch's worker image before retiring its source. Existing instances
do not require their original AMI or snapshot to remain registered or stored.

A disposable benchmark must also deregister its output AMIs and delete their
snapshots. Record resource lifetimes before cleanup and distinguish costs
calculated from measured usage from charges actually posted by AWS.

After an interrupted controller, run the same cleanup explicitly:

```sh
./bt-ec2-refresh cleanup --state /path/to/batch
```

Confirm `cleanup.json` reports `complete: true` and no remaining volumes.
Marketplace review can continue after the workers and working storage are gone.
