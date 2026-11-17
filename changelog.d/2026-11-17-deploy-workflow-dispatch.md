### Security — The deploy trigger's token can no longer change the deployment repository

- `notify-ops.yml` now starts the deploy workflow of the private deployment
  repository directly, on its `main` branch with the commit as the workflow's
  input, instead of sending that repository a `repository_dispatch` event.
  That event needs a token that may also write to the repository; the new
  call needs only the Actions permission, which runs and manages the
  repository's workflows but cannot read or change its files.
- The step also accepts GitHub's answer under newer API versions (200 instead
  of 204), names the status code when GitHub refuses the dispatch, and shows
  GitHub's answer only then.
