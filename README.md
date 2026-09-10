# GitHub 动态日报

This repository generates a daily GitHub activity digest as an HTML page.

The GitHub Actions workflow runs every day at 08:18 Beijing time, queries the
GitHub REST API for the account's recent public activity, and summarizes:

- Newly starred repositories
- Pushes and commits
- Issues, pull requests, and comments

Each run regenerates `report.html` and `docs/index.html`, commits the result,
and publishes `docs/index.html` to GitHub Pages.

## Files

- `scripts/update_github_digest.py`: fetches GitHub events and renders the HTML report.
- `data/github-history.json`: daily summary history.
- `report.html`: local report page.
- `docs/index.html`: GitHub Pages entry point.
- `.github/workflows/github-daily-digest.yml`: scheduled automation.

## Configuration

The workflow targets the repository owner (`github.repository_owner`) and uses
the built-in `GITHUB_TOKEN`. It only includes public activity.

To also count private repositories, create a fine-grained personal access token
with read access to your repos and save it as a repository secret named
`GH_PAT`, then set the workflow's `GH_TOKEN` to
`${{ secrets.GH_PAT || secrets.GITHUB_TOKEN }}`.

## Run Locally

```bash
GH_USER=your-github-username python scripts/update_github_digest.py
```
