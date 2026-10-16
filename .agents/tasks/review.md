# `--with-cicd` builds the image on GitHub, auto-detects the deploy repo from the git remote

`deploy-changeset.sh` gains a `detect_github_slug` function that parses the owner/repo from the `origin` remote and reshapes the `--with-cicd` path so the Docker image is built by GitHub Actions in the user's own repo instead of locally. Under `--with-cicd` the local `push_ecr.sh` build and scale-up are skipped, the OIDC trust is scoped to the detected repo (never a hardcoded author default), the `gh secret set` targets `--repo "$ORG/$REPO"`, and a prominent push-to-deploy NEXT STEP banner is printed. If no GitHub `origin` remote exists the script fails fast with actionable guidance and a non-zero exit. The README is rewritten around a five-step CI/CD flow (open IDE → sign in → create repo + push → `--with-cicd` deploy → `git push origin main`), with the local-Docker path preserved as an explicitly Docker-requiring alternative, and the forbidden words scrubbed.

Watch for: nothing blocking. The change set reviewed is commit `de7472d`, which touches exactly `deploy-changeset.sh` and `README.md` (confirmed). All six authoritative requirements are met, verified by reading the diff and re-running the forbidden-word, bash-4-ism, hardcoded-repo, and `bash -n` spot-checks (all green).

**Verdict**: APPROVED

## High-level view

The git-remote parser handles all four required URL forms (HTTPS with/without `.git`, SSH, trailing slash) plus `http://` and `ssh://` variants, strips a single trailing slash then a single `.git`, and rejects empty or non-GitHub URLs by returning non-zero with empty globals. It is bash 3.2 compatible — `case` matching and `${x%%/*}` / `${x#*/}` expansions only, no `${v,,}` case folding.

The CI/CD gate runs at the top of the `if $WITH_CICD` block, before the OIDC_STATUS create/update branch, so both the first-CREATE and the stack-exists UPDATE paths fail fast when no origin remote is present. There is no fallback to the author's repo — the only outcome without a detected slug is an actionable message and `exit 1`.

The OIDC parameter wiring always appends `GitHubOrg`/`GitHubRepo` to a single `--parameter-overrides`, and conditionally adds `OIDCProviderArn` only when an existing provider is found. Both the real and the manual-fallback `gh secret set` calls carry `--repo "$ORG/$REPO"`. The CloudFormation template is untouched and already consumes both params in the trust `StringLike`, so overrides scope the role cleanly.

The local build gate wraps the `push_ecr.sh` call so it is unreachable under `--with-cicd`; since `push_ecr.sh` is the only thing that scales ECS up (`--desired-count`), skipping it leaves services at the stack's desired count — which is 0 on first CREATE via the untouched `DEPLOY_DESIRED_COUNT=0` logic. The push-to-deploy banner prints on both CREATE and UPDATE because it sits outside the OIDC_STATUS branch but inside `$WITH_CICD`.

<details>
<summary>Issues (0)</summary>

No blocking or non-blocking findings. All six requirements satisfied.

</details>

<details>
<summary>Details</summary>

### Git-remote parser is bash-3.2-safe and covers the required forms

`detect_github_slug` resets the globals, reads `git remote get-url origin` with a `git config --get remote.origin.url` fallback, strips `%/` then `%.git`, and dispatches on a `case` over `git@github.com:`, `https://github.com/`, `http://github.com/`, and `ssh://git@github.com/` prefixes. The post-conditions (`owner`/`repo` non-empty, `owner != slug` to catch a slug with no slash, `repo` free of a further `/`) reject malformed input. Non-GitHub hosts hit the `*)` arm and return 1. The verification note's throwaway harness confirmed `acme/widgets` extraction across the four required forms plus the trailing-slash and `ssh://` variants, and the empty / `gitlab.com` rejections — consistent with the code read here.

### CI/CD gate fails closed, no author-repo fallback

The gate is the first statement inside `if $WITH_CICD`, ahead of the OIDC_STATUS describe. A failed `detect_github_slug` prints the sign-in / create-repo / `git remote add` / `git push` / re-run sequence and exits 1. There is no branch that substitutes a default org/repo — the fail-closed posture is correct for a trust-boundary change, since falling back would mint a role trusting a repo the operator does not control.

### OIDC overrides and secret scoping

`OIDC_OVERRIDES` is seeded with `GitHubOrg`/`GitHubRepo` and conditionally extended with `OIDCProviderArn`, then passed as a single `--parameter-overrides "${OIDC_OVERRIDES[@]}"`. This correctly replaces the prior logic that only passed overrides when an existing provider was present (which would otherwise have dropped the org/repo scoping entirely). Both `gh secret set` invocations — the live call and the printed manual hint — carry `--repo "$GITHUB_ORG/$GITHUB_REPO"`, so the secret lands on the detected repo rather than whatever `gh`'s default happens to be.

### Local build skipped, ECS left at stack desired count

Under `--with-cicd` the "Building and pushing container image" banner and the `push_ecr.sh` call are replaced by a "Skipping local image build (CI/CD mode)" note. `push_ecr.sh` is the sole caller of `aws ecs update-service --desired-count`, so skipping it means no local scale-up. The first-CREATE `DEPLOY_DESIRED_COUNT=0` / `DEPLOY_STREAMLIT_DESIRED_COUNT=0` block (lines 167-170) is unchanged, so on a fresh CREATE under CI/CD the services stay at 0 until the GitHub workflow pushes an image — matching requirement 2. On UPDATE nothing forces the count to 0; the services keep their existing count. The non-cicd `--auto` path still reaches the local build and scale-up unchanged.

### Push-to-deploy banner on both paths; usage header updated

The NEXT STEP banner sits after the OIDC_STATUS if/else but still inside `$WITH_CICD`, so it prints whether the OIDC stack was just created or already existed. It names `git push origin main`, the `deploy.yml` workflow in `$GITHUB_ORG/$GITHUB_REPO`, the build/ECR/ECS steps, and the Actions tab. The top-of-file usage comment now documents `--with-cicd` as "GitHub Actions builds and pushes the image (no local Docker)" with the origin-remote requirement, and the OIDC-block lead comment matches the auto-detect behavior.

### README flow and word scrub

The README leads with a two-path overview, then Part 2 lays out the five numbered steps (open IDE, sign in, create repo + the three git commands, `--with-cicd` deploy described as no-Docker with OIDC scoped to the auto-detected repo and the secret set, then `git push origin main` with the Actions tab). Part 2B preserves the local Docker path marked as Docker-requiring. Prerequisites list the GitHub account and optional `gh` CLI alongside the existing Python/AWS/Bedrock items. The OIDC troubleshooting entry is rewritten around auto-detection ("no origin remote" / "pushed to a different repo"). Spot-check greps confirm `training|instructor|candidate|student|learner` and `huraisturkey-lang/Ai_Agent` are both absent from README.md. The lone remaining reference to the historical default is prose noting the template ships placeholder defaults the deploy overrides — not a required value.

### Template untouched

`cloudformation-github-oidc.yml` is not in the commit's file list. It already declares `GitHubOrg` and `GitHubRepo` and the trust `StringLike` uses `!Sub "repo:${GitHubOrg}/${GitHubRepo}:*"`, so `--parameter-overrides` scopes the trust with no template edit. Thumbprint and permission logic untouched — requirement 5 satisfied with zero template change.

### Verification evidence corroborated

The coder's note records `bash -n` SYNTAX_OK, the parser harness PASS across all forms, empty greps for the bash-4-isms / hardcoded repo / forbidden words, and `make prod-check` green (127 tests + smoke). Per the review method I did not re-run the suites; I re-ran only the narrow greps and `bash -n`, all of which reproduce the note's results.

</details>

<details>
<summary>File map</summary>

- `deploy-changeset.sh` — new `detect_github_slug` parser; `--with-cicd` fail-fast gate; org/repo in OIDC overrides; `gh secret set --repo`; local build/scale-up skipped under CI/CD; push-to-deploy NEXT STEP banner; usage header updated.
- `README.md` — rewritten around the five-step GitHub CI/CD flow; local Docker path kept as Docker-requiring alternative; prerequisites + OIDC troubleshooting updated; forbidden words and hardcoded clone URL removed.
- `cloudformation-github-oidc.yml` — unchanged (verified it already accepts `GitHubOrg`/`GitHubRepo`).

Full diff: `git show de7472d` on branch `main`.

</details>
