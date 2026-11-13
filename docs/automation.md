# Portfolio automation credentials

## Workflows

- `portfolio-audit.yml` runs weekly and uploads live public-repository evidence.
- `project-sync.yml` runs daily and mirrors open public issues and pull requests into the user-owned **Styayur Portfolio** Project V2.
- `self-governance.yml` runs the central policy tests.
- `reusable-portfolio-gate.yml` is retired. It is not an executable workflow; the historical copy is `evidence/retired/reusable-portfolio-gate.yml`.

## Authentication

The project sync uses a hybrid, least-privilege model:

1. A GitHub App installation token reads repository metadata, issues, and pull requests across `styayur` public repositories.
2. `PORTFOLIO_PROJECT_TOKEN` is a classic personal access token with only the `project` scope. It is used only for GraphQL access to the user-owned Project V2.

GitHub's platform currently does not grant fine-grained personal access tokens or installation tokens access to Projects V2 owned by a user account. This is why the project mutation uses the narrowly scoped classic token rather than claiming full GitHub App coverage.

## Stored configuration

- Variable: `PORTFOLIO_APP_CLIENT_ID`.
- Secret: `PORTFOLIO_APP_PRIVATE_KEY`.
- Secret: `PORTFOLIO_PROJECT_TOKEN`.

The app installation is limited to `styayur` and all current/future repositories owned by that account. Repository permissions are read-only except Projects, while the classic token is restricted to the `project` scope.

## Rotation

- The classic project token expires **2027-02-06**. Rotate it before expiry and update `PORTFOLIO_PROJECT_TOKEN`.
- Rotate the GitHub App private key through **Settings → Developer settings → GitHub Apps → Styayur Portfolio Governor Actions → Credentials** and update `PORTFOLIO_APP_PRIVATE_KEY`.
- Expiry or missing secrets must fail the scheduled workflow closed; they must never be converted into a PASS result.

## Residual limitation

A GitHub App installation token cannot perform the user-owned Project V2 mutation in this setup. The GitHub App is therefore used only for installed-repository reads; the project mutation remains dependent on the explicitly scoped classic token and its rotation.
