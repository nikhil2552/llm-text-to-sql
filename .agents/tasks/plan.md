# Implementation Plan — GitHub CI/CD opt-in flow (`--with-cicd` builds on GitHub, no local Docker)

## Goal (authoritative)
A person opens this project in their IDE, signs in to THEIR OWN GitHub, creates a new repo under their
account and pushes the code, then runs `./deploy-changeset.sh --auto --with-cicd`. That provisions AWS
infra and wires an OIDC role scoped to THEIR repo (auto-detected from the git remote) — it does NOT build
the Docker image locally and does NOT need Docker Desktop. The image is built by GitHub Actions (in their
repo, their AWS account) on `git push origin main`, pushed to ECR, and ECS Fargate is started. The default
`--auto` (no `--with-cicd`) is unchanged: local Docker build + scale-up.

## Files touched
- `deploy-changeset.sh` — add git-remote parse fn; gate OIDC params + gh secret on detected org/repo;
  skip local build/scale-up under `--with-cicd`; add push-to-deploy next-step banner; update usage header.
- `README.md` — rewrite deployment docs around the GitHub CI/CD flow (purely technical wording).
- `cloudformation-github-oidc.yml` — VERIFY ONLY (already has `GitHubOrg`/`GitHubRepo` params; no change
  expected). Only touch if `--parameter-overrides` cannot scope trust cleanly, with explanation.

## Key facts verified in the repo
- `deploy-changeset.sh`: `set -euo pipefail`; `REGION="${AWS_REGION:-eu-north-1}"`; flags parsed in
  `for arg in "$@"` setting `AUTO_MODE`/`WITH_DATABASES`/`WITH_CICD`. First-CREATE safety sets
  `DEPLOY_DESIRED_COUNT=0` / `DEPLOY_STREAMLIT_DESIRED_COUNT=0` — KEEP.
- Local build call: `DESIRED_COUNT="$DESIRED_COUNT" STREAMLIT_DESIRED_COUNT="$STREAMLIT_DESIRED_COUNT" ./scripts/push_ecr.sh`
  inside the `if $AUTO_MODE` block, under the "Building and pushing container image..." banner.
- OIDC block: `if $WITH_CICD` → deploys `cloudformation-github-oidc.yml` (stack `github-actions-oidc`) via
  `DEPLOY_OIDC_ARGS` array; conditionally appends `--parameter-overrides "OIDCProviderArn=$EXISTING_OIDC"`;
  reads `DeployRoleArn`; `gh secret set AWS_DEPLOY_ROLE_ARN --body "$ROLE_ARN"` (NO `--repo` today).
- Template params exist: `GitHubOrg` (default `huraisturkey-lang`), `GitHubRepo` (default `Ai_Agent`),
  `OIDCProviderArn` (default ""). Trust uses `repo:${GitHubOrg}/${GitHubRepo}:*` — overridable, NO template change needed.
- Hardcoded author repo appears in `README.md` lines 1-2, 87-88 (clone URL `huraisturkey-lang/Ai_Agent`).
- Workflow `.github/workflows/deploy.yml`: push to `main` → test gate → `docker build --platform linux/amd64`
  → push ECR → `aws ecs update-service --force-new-deployment` for `data-architecture-ai` and
  `data-architecture-ai-streamlit` → wait stable → print URLs. Auth via `secrets.AWS_DEPLOY_ROLE_ARN`.
- Build/test gate: `make prod-check` = `check` (`python -m compileall src scripts lambda POC/run_smoke.py`)
  + `test` (needs venv) + `smoke`. Current branch `main`, origin = `https://github.com/huraisturkey-lang/Ai_Agent.git`.
- Env: macOS bash 3.2.57 — NO bash-4 constructs (`${VAR,,}`, `${VAR^^}`). Use `tr` for case folding.
- Stop-condition contract for the review loop: `.agents/tasks/review.json`, jsonPath `verdict`, value `APPROVED`.

---

- [ ] 1. Add a git-remote parse function to `deploy-changeset.sh`.
      Add a bash-3.2-compatible function `detect_github_slug()` after the flag-parse loop (after the
      `for arg in "$@"` block, before `reconcile_streamlit_secret`). It runs
      `git remote get-url origin 2>/dev/null` and falls back to `git config --get remote.origin.url`.
      Parse `owner/repo` from BOTH HTTPS (`https://github.com/OWNER/REPO(.git)?`, with or without trailing
      slash) and SSH (`git@github.com:OWNER/REPO(.git)?`). Strip a single trailing `.git` and any trailing
      `/`. Set globals `GITHUB_ORG` and `GITHUB_REPO`. Return non-zero (leaving them empty) when no origin
      URL is found or it does not match a GitHub pattern. Use `sed`/parameter-expansion only (no `${v,,}`).
      Do NOT call it yet — only define it.
      Files: deploy-changeset.sh
      Verify: `bash -n deploy-changeset.sh` exits 0.

- [ ] 2. Gate CI/CD on a detected GitHub slug; fail fast with an actionable message when absent.
      At the TOP of the existing `if $WITH_CICD; then` OIDC block (before the "Setting up GitHub Actions
      OIDC" banner), call `detect_github_slug`. If `GITHUB_ORG`/`GITHUB_REPO` are empty, print the
      sign-in/create-repo/push guidance (`git remote add origin https://github.com/<you>/<repo>.git`,
      `git branch -M main`, `git push -u origin main`, then re-run `./deploy-changeset.sh --auto --with-cicd`)
      and `exit 1`. Never fall back to the author's repo. Echo the detected `GITHUB_ORG/GITHUB_REPO` for
      visibility. Note: this gate must also run on an UPDATE (stack already exists) path, so place the
      detect+guard just inside `if $WITH_CICD` before the `OIDC_STATUS` branch.
      Files: deploy-changeset.sh
      Verify: `bash -n deploy-changeset.sh` exits 0; manual read confirms the exit precedes any OIDC deploy.

- [ ] 3. Pass detected org/repo to the OIDC stack and scope the `gh secret set` to that repo.
      In the OIDC deploy, append `GitHubOrg=$GITHUB_ORG GitHubRepo=$GITHUB_REPO` to `--parameter-overrides`
      alongside the conditional `OIDCProviderArn=...` (ensure a single `--parameter-overrides` with all
      key=value pairs; append to the `DEPLOY_OIDC_ARGS` array so org/repo are always passed and
      `OIDCProviderArn` only when `$EXISTING_OIDC` is set). Change both `gh secret set` invocations (the
      real call and the printed manual-fallback hint) to `gh secret set AWS_DEPLOY_ROLE_ARN --repo
      "$GITHUB_ORG/$GITHUB_REPO" --body "$ROLE_ARN"`.
      Files: deploy-changeset.sh
      Verify: `bash -n deploy-changeset.sh` exits 0; read confirms org/repo in overrides and `--repo` in both gh hints.

- [ ] 4. Under `--with-cicd`, skip the local Docker build and the local scale-up.
      Guard the "Building and pushing container image..." banner + the `./scripts/push_ecr.sh` call so they
      run only when `$WITH_CICD` is false. When `$WITH_CICD` is true, print a short note that the image is
      built by GitHub Actions (no local Docker) and leave ECS at its current desired count — do NOT scale
      up locally. Keep the existing first-CREATE `DEPLOY_DESIRED_COUNT=0`/`DEPLOY_STREAMLIT_DESIRED_COUNT=0`
      logic untouched (do not force 0 on an UPDATE). Seeding, crawlers, and S3-notification steps still run
      in both modes.
      Files: deploy-changeset.sh
      Verify: `bash -n deploy-changeset.sh` exits 0; read confirms `push_ecr.sh` is unreachable when `$WITH_CICD` true, and the CREATE=0 block is unchanged.

- [ ] 5. Add a prominent push-to-deploy NEXT STEP banner for the CI/CD path.
      After OIDC setup succeeds (secret set or printed), when `$WITH_CICD` is true, print a clearly marked
      NEXT STEP block: run `git push origin main` to trigger `.github/workflows/deploy.yml`, which builds
      the image on GitHub, pushes to ECR, and starts the ECS services; mention watching progress in the
      repo's Actions tab and that the workflow prints the API/Streamlit URLs. This must print on BOTH the
      first-CREATE and UPDATE CI/CD paths. Keep the existing non-CI/CD completion/URL output intact for the
      default path.
      Files: deploy-changeset.sh
      Verify: `bash -n deploy-changeset.sh` exits 0; read confirms the banner is inside the `$WITH_CICD` branch and after secret handling.

- [ ] 6. Update the usage header / inline comments in `deploy-changeset.sh`.
      Revise the top-of-file usage comment so `--with-cicd` is documented as "GitHub Actions builds and
      pushes the image (no local Docker); requires an `origin` remote pointing at your own GitHub repo."
      Update the OIDC-block lead comment to match the new auto-detect + skip-local-build behavior. Keep all
      comments accurate to the code.
      Files: deploy-changeset.sh
      Verify: `bash -n deploy-changeset.sh` exits 0; read confirms header text matches new behavior.

- [ ] 7. Rewrite the README deployment docs around the GitHub CI/CD flow (technical wording only).
      Edit `README.md`: remove the top preamble block and the hardcoded `huraisturkey-lang/Ai_Agent` clone
      lines; present a numbered sequence — (a) open project in IDE; (b) sign in to own GitHub in the IDE;
      (c) create a new empty repo under own account, then `git remote add origin
      https://github.com/<you>/<repo>.git` + `git branch -M main` + `git push -u origin main`; (d)
      `./deploy-changeset.sh --auto --with-cicd` — state it does NOT build the image locally and does NOT
      need Docker; it provisions AWS infra, creates the GitHub OIDC role scoped to YOUR repo
      (auto-detected from your git remote), and sets the `AWS_DEPLOY_ROLE_ARN` secret in your repo; (e)
      `git push origin main` → GitHub Actions builds on GitHub, pushes to ECR, starts ECS; watch in the
      repo Actions tab; URLs printed by the workflow. Keep the non-CI/CD `--auto` (local Docker build)
      documented as the alternative that requires Docker. Preserve existing prerequisites (Python 3.11,
      AWS CLI + `aws configure`, Bedrock Nova access); add that the CI/CD flow also needs a GitHub account
      and optional `gh` CLI (script falls back to printing the secret for manual entry when `gh` is
      absent). Update the OIDC troubleshooting entry: org/repo is auto-detected, so common causes are "no
      `origin` remote set" or "pushed to a different repo than the one deployed from". Do NOT use the words
      "training", "instructor", "candidate", "student", or "learner" anywhere. Do NOT reintroduce
      `huraisturkey-lang/Ai_Agent` as a required value — mention it only as the historical template default
      now overridden by auto-detection (or omit entirely). Keep the "How it fits together", stacks, and
      config-reference sections accurate.
      Files: README.md
      Verify: `grep -niE "training|instructor|candidate|student|learner" README.md` prints nothing;
      `grep -n "huraisturkey-lang/Ai_Agent" README.md` prints nothing (or only a clearly-labeled historical
      note, never a clone/required value); manual read confirms the five-step flow reads coherently.

- [ ] 8. Verify `cloudformation-github-oidc.yml` needs no change.
      Confirm `GitHubOrg`/`GitHubRepo` params are consumed by the trust `StringLike`
      `repo:${GitHubOrg}/${GitHubRepo}:*`, so `--parameter-overrides GitHubOrg=.. GitHubRepo=..` scopes
      trust without a template edit. Make NO change unless overrides cannot scope cleanly; if a minimal
      change is unavoidable, keep the OIDC thumbprint logic and role permission policies untouched and
      explain the change in the commit message.
      Files: cloudformation-github-oidc.yml (expected: unchanged)
      Verify: read confirms the `StringLike` sub uses both params; no edit committed unless justified.

- [ ] 9. Unit-test the git-remote parser with a throwaway harness.
      Write a temporary harness (e.g. `/tmp/test_parse_slug.sh`) that sources the parse logic (or copies the
      function) and asserts it extracts `acme/widgets` from each of:
      `https://github.com/acme/widgets.git`, `https://github.com/acme/widgets`,
      `git@github.com:acme/widgets.git`, and a trailing-slash variant
      `https://github.com/acme/widgets/`. Also assert empty/non-GitHub input yields empty org/repo (the
      fail-fast case). Delete the harness after it passes.
      Files: (none committed — throwaway harness under /tmp)
      Verify: harness prints PASS for all four URL forms and the empty-input case; then remove the harness file.

- [ ] 10. Run the project verification gate and the no-regression greps.
      Run `make prod-check` (compile + unit tests + smoke). If venv/network blocks `test`/`smoke`, fall
      back to `make check` plus `bash -n deploy-changeset.sh` and record which ran. Then run the
      anti-regression greps: `grep -rn ',,}' deploy-changeset.sh` and `grep -rn '\^\^}' deploy-changeset.sh`
      must be empty (no bash-4 case folding); `grep -rn 'huraisturkey-lang' deploy-changeset.sh` must be
      empty (no hardcoded author repo in the script).
      Files: (none)
      Verify: `make prod-check` passes (or documented `make check` + `bash -n` fallback passes); all three
      greps return no matches.

## Notes / assumptions
- The repo's actual origin is currently `huraisturkey-lang/Ai_Agent`; the parser is validated against
  synthetic URLs (`acme/widgets`) so it is not biased toward the author's slug.
- Review loop writes its verdict to `/.agents/tasks/review.json` (`verdict` = `APPROVED` to stop); the
  implementer runs first, the verdict-writer last.
- Pre-existing `.agents/tasks/{plan.md was overwritten, review.json, review.md, verification.md}` relate to
  an earlier bug-fix task and are not part of this change's deliverables.
