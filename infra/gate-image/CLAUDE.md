# infra/gate-image

The gate image: the one environment a gate test run uses. The commit hook runs
the test files a commit adds or changes in it, sealed
(`tools/test_register/birth/_run.py`), and the deploy gate's test runs read the
same pin. Bible: `workflow/module-standard`.

```
gate-image/
  Dockerfile               python, the locked environment at /opt/gate-env, git, jq, libfaketime, uv
  Dockerfile.dockerignore  deny by default; names every COPY source
  pin                      the image by digest, and `# built from: <sha>`
  build.sh                 build from a clean export of one commit, check, push, rewrite `pin`
```

## Rules

- **`pin` is the one place the image is named**, by digest, on its last line,
  read by `tools.test_register.read_pin`. A line without `@sha256:` names
  nothing, and the hook then runs the staged tests locally and says so. Never
  write a tag there, and never name the image anywhere else.
- **Build only with `infra/gate-image/build.sh [<ref>]`.** It pushes
  `<repository>:git-<sha12>` (never reused) and rewrites `pin`. The repository
  is `GATE_IMAGE_REPOSITORY`, else `rg.<SCW_REGION>.scw.cloud/<SCW_REGISTRY>/gate`
  (`config/harness.env`). Commit `pin` in the same commit as whatever needed
  the build; the hook refuses a staged pin whose manifest the registry lacks.
- **Rebuild when `uv.lock`, a `pyproject.toml` or this Dockerfile moves.**
  `python3 -m tools.test_register --pin-drift` names what moved past
  `# built from:`. A lock the image was not built from breaks the hook's offline
  re-sync, and the hook falls back to a local run, loudly.
- **No script of ours in the image, and no kubectl, scw, gh or docker.** The
  workspace members are copied only to build the environment; every run
  re-syncs them from the mounted tree. A test that needs a live tool reads the
  live machine, which the birth check refuses.
- **Torch stays out unless the lock asks for it**: the image is whatever
  `uv sync --frozen --all-packages --all-extras --all-groups` gives.

## Gotchas

- The environment and its uv cache are world-writable, in the same layer as the
  sync (hardlinks, no second copy): the hook runs as whoever commits, and its
  offline re-sync writes the editable members. The mounted tree must be owned by
  that same uid, or setuptools cannot touch its `*.egg-info`.
