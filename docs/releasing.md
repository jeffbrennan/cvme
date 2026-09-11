# Releasing

`cvme` publishes to PyPI from [`.github/workflows/release.yml`](../.github/workflows/release.yml),
triggered by a `v*` tag. Publishing uses PyPI trusted publishing: GitHub mints
a short-lived OIDC token for the run, so no API token is stored in the
repository.

## One-time setup

1. **PyPI pending publisher.** The project does not exist on PyPI until the
   first upload, so register a *pending* publisher at
   <https://pypi.org/manage/account/publishing/>:

   | Field | Value |
   |---|---|
   | PyPI project name | `cvme` |
   | Owner | `jeffbrennan` |
   | Repository name | `cvme` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

2. **GitHub environment.** Create an environment named `pypi` under
   Settings → Environments. Add a required reviewer if you want a release to
   pause for an explicit approval before upload.

3. **TestPyPI (optional).** Repeat both steps on
   <https://test.pypi.org/manage/account/publishing/> with environment name
   `testpypi` to be able to rehearse a release.

## Cutting a release

The version lives in exactly one place, `src/cvme/__init__.py`; the build
backend reads it from there and `cvme version` prints it.

```bash
# bump __version__ in src/cvme/__init__.py, then
uv lock                                   # refreshes the locked version
git commit -am "release 0.2.0"
git tag v0.2.0
git push origin main --tags
```

The workflow builds the sdist and wheel, fails if the tag disagrees with the
packaged version, installs the wheel into a clean environment and runs
`cvme doctor` against it — which fails on a font or template that never made
it into the distribution — and then uploads.

A version cannot be replaced once uploaded. To rehearse against TestPyPI
first, run the workflow manually (Actions → release → Run workflow) and leave
the index set to `testpypi`; the tag check is skipped for a manual run.

## Building locally

```bash
uv build                                  # dist/*.whl and dist/*.tar.gz
uv tool install --force dist/cvme-*.whl   # try the built artifact
```
