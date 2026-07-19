# SemiPulse Sentinel

SemiPulse Sentinel publishes the original semiconductor chart images embedded
in a qualifying Wenxuecity post. The images are copied byte-for-byte, kept in
source order, and accompanied by provenance and SHA-256 hashes. The scanner
does not redraw the charts or substitute finance-provider data.

Canonical interfaces:

- [GitHub repository](https://github.com/skydiver1118/semipulse-sentinel)
- [SemiPulse Sentinel report](https://skydiver1118.github.io/semipulse-sentinel/)
- [Canonical report.json](https://skydiver1118.github.io/semipulse-sentinel/report.json)
- [Seed source post](https://bbs.wenxuecity.com/cfzh/97669.html)

The hosted scanner starts Monday through Friday at 6:20 PM
America/New_York. An XNYS calendar gate permits automatic source checks only
after a completed trading session. It checks the seed post for edits and a
bounded set of the author’s newest top-level semiconductor posts.

Only a newer qualifying post or a changed ordered image manifest deploys. If
there is no new source data, the public page keeps the last successful report
and no email is sent. After a changed report deploys successfully, one alert
with the permanent report link goes to the hard-locked recipient
`1118xmb@gmail.com`.

## Local verification

Python 3.11 or later is required:

```powershell
python -m pip install --require-hashes -r requirements.lock
python -m pip install --no-deps --no-build-isolation .
python scripts/verify_workflow.py .github/workflows/nightly-report.yml
python -m pytest -q
python -m semipulse_sentinel build-source --output site --json
python -m semipulse_sentinel validate-source --site site --json
```

The source build is failure-atomic: download and validation complete in a
staging directory before replacing the requested destination. See
[docs/methodology.md](docs/methodology.md) for source selection and integrity
rules and [docs/operations.md](docs/operations.md) for scheduling, manual
refreshes, email, and recovery.

## Research boundary

Research only - not individualized investment advice or a recommendation to
buy or sell. The report preserves third-party source images and provenance; it
does not calculate signals, place orders, promise returns, or provide
personalized sizing. Source material may be delayed, incomplete, or revised.

## License

MIT. See [LICENSE](LICENSE).
