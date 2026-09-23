# Branching and promotion policy

## Branches

- `main` is production/release history. No feature work is done directly on it.
- `UAT` is the integration and acceptance branch.
- Improvements start from the current `UAT` tip in `feature/<short-name>` branches.
- Feature branches are merged into `UAT` through pull requests.
- `main` is promoted only through a pull request whose source branch is exactly `UAT`.

## Golden build

A commit is a golden build only when the `Package Packizard Builder` workflow succeeds at that exact commit and the `Golden build` job has verified all six platform artifacts:

- Windows x64
- Windows arm64
- Linux x64
- Linux arm64
- macOS x64
- macOS arm64

The workflow also requires tests to pass, validates the reconstructed packaging scripts, generates checksums, and publishes a combined golden-build artifact.

## Promotion sequence

1. Create `feature/<short-name>` from `UAT`.
2. Open a PR from the feature branch to `UAT`.
3. Merge only after `PR policy · branch flow`, `Tests · Linux x64`, all six platform builds, and `Golden build` succeed.
4. After UAT acceptance, open a PR from `UAT` to `main`.
5. Merge to `main` only when the same required checks succeed on the promotion PR.
6. Create release tags only from commits already present on `main`; the release workflow rejects tags pointing elsewhere.

## Required repository rules for `main`

GitHub branch/ruleset protection should require:

- pull requests for all changes;
- source branch `UAT` enforced by the `PR policy · branch flow` required status check;
- required status checks `PR policy · branch flow` and `Golden build`;
- branch must be up to date before merge;
- conversation resolution before merge;
- no force pushes;
- no branch deletion;
- administrators included in the rule (no bypass for normal development).

The same model can be applied to `UAT`, requiring pull requests and the `PR policy · branch flow` / `Golden build` checks, while allowing only `feature/*` source branches through the workflow policy.
