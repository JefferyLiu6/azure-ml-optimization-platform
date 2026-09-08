# Public-edition verification

These checks were executed locally against this export, not inherited from the original
research project. No exact dates or confidential workload records are published.

| Check | Actual result |
| --- | --- |
| Full suite, including live Azurite Blob concurrency | 45 passed; 85% source coverage |
| Formatting and lint | Passed for 35 Python files |
| Strict type checking | Passed for 17 source files |
| Frozen dependency lock | Offline consistency check passed |
| API, worker, and MLflow Docker builds | Passed on local ARM64 Docker |
| Compose health/readiness | API, worker, MLflow, and Azurite healthy |
| End-to-end demo | Completed; five metric points; matching MLflow tracking finished |
| GitHub workflow static validation | actionlint passed |
| Bicep compilation | Passed with three warnings |
| Azure deployment of this edition | Not performed |
| GitHub Actions execution | Not performed |

The test suite emitted two third-party deprecation warnings. Bicep warnings concern an
unused parameter and conservative minimum-length checks for generated resource names.
Compilation is not proof of Azure admission, quota, or live deployment success.

The predecessor engineering platform ran on AKS with durable jobs and tracking. That was
a different release; its cloud evidence is not a deployment claim for this public edition.

## Repeat the checks

```bash
make install
make verify
docker compose up -d --build --wait --wait-timeout 180
make smoke
```

The live Blob concurrency test needs `MFBO_TEST_AZURITE`. For this local emulator only:

```bash
export MFBO_TEST_AZURITE='DefaultEndpointsProtocol=http;AccountName=devstoreaccount1;AccountKey=bm90LWEtcHJvZHVjdGlvbi1jcmVkZW50aWFs;BlobEndpoint=http://127.0.0.1:11000/devstoreaccount1;QueueEndpoint=http://127.0.0.1:11001/devstoreaccount1'
make test
```

Without that variable, the optional Blob test skips. The end-to-end Compose smoke still
uses the real Azure SDKs against the emulator. This account key is not a cloud credential.

No cloud throughput gain, high availability, monitored alert, or algorithm-quality result
is claimed. New changes require fresh validation.
