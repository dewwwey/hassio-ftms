# Fork and source control

This checkout is the **dewwwey/hassio-ftms** fork of
[dudanov/hassio-ftms](https://github.com/dudanov/hassio-ftms).

| Remote | URL | Role |
|---|---|---|
| `origin` | `https://github.com/dewwwey/hassio-ftms.git` | Fork; `main` is the active line |
| `upstream` | `https://github.com/dudanov/hassio-ftms.git` | Original project |

Current state (2026-10-19):

- `main` is up to date on `origin` and ahead of `upstream/main`.
- The local snapshot history was grafted onto `upstream/main`, so upstream
  history remains an ancestor and future upstream merges are possible.
- Release checkpoint: tag `v0.24.9-dev10`.
- The pre-graft orphan history is preserved locally as
  `backup/orphan-history-20261019` and as a bundle in
  `../private/hassio-ftms-local-history-20261019.bundle`; it is not pushed.

## Authentication

`gh` is the credential provider for this repository. The repo-local config
uses only the GitHub CLI helper, so no credential is written to
`~/.git-credentials`:

```bash
gh auth status
git config --local credential.https://github.com.helper \
  '!/usr/bin/gh auth git-credential'
```

## Sync with upstream

```bash
git fetch upstream
git log --oneline upstream/main..main   # our commits
git merge upstream/main                 # or rebase; expect conflicts in vendored pyftms
```

The fork vendors `pyftms` under `custom_components/ftms/_vendor/`, so upstream
changes to that dependency usually need to be re-vendored rather than merged
file by file.

## Tests

The source suite runs with a Python environment that has Home Assistant
installed:

```bash
cd ftms-investigation/hassio-ftms      # from the management workspace
python -m unittest discover -s tests -v
```

Synthetic tests do not establish live bike, chest-strap HR, control or delivery
acceptance. Keep private acceptance evidence and the wake profile
(`.basilisk_wake_staging.yaml`) out of this repository.

## Push a checkpoint

```bash
git status --short
git add -A
git commit -m "Describe the change"
git push origin main
git tag -a vX.Y.Z-devN -m "Checkpoint: ..."
git push origin vX.Y.Z-devN
```

Do not commit credentials, `.basilisk_wake_staging.yaml`, private journals,
health samples, device identifiers or raw operational logs.
