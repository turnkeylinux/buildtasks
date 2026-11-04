# Refresh Marketplace security updates

`bt-ec2-refresh` installs the available Debian and TurnKey security updates into
unbooted source images, sets EC2 first-boot updates to `FORCE`, and boot-tests
each candidate before submitting a new version to its existing Marketplace
listing. First boot checks for fixes released after the image was built.

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
these submissions and retires older public delivery options after AWS approves
the replacement and makes it public:

```sh
./bt-ec2-refresh publish --state /path/to/batch
```

For automatic follow-up while AWS reviews the submissions, run `watch` in a
supervised background service:

```sh
./bt-ec2-refresh watch --state /path/to/batch
```

It checks every five minutes for up to seven days, retries deferred submissions,
and retires superseded deliveries after the replacement is public. Inspect
`publication-watch.json` for completed, pending, and failed products. This phase
needs controller AWS access but no EC2 workers or batch SSH key.

A nonzero refresh exit means at least one image did not pass verification.
Read that appliance's `APP-state.json`, `APP.log`, and `APP-boot.log`.
Before cleanup, rerun selected jobs with `run --apps app1,app2`. After cleanup,
prepare a new batch from the retained state.

## Cleanup

`run --cleanup` waits for its image tasks, runs a separate CloudTask cleanup
phase, terminates batch-tagged workers and test instances, and deletes their
remaining EBS volumes. It retains the snapshots backing registered output AMIs.
The source images and their snapshots remain available for rollback.

After an interrupted controller, run the same cleanup explicitly:

```sh
./bt-ec2-refresh cleanup --state /path/to/batch
```

Confirm `cleanup.json` reports `complete: true` and no remaining volumes.
Marketplace review can continue after the workers and working storage are gone.
