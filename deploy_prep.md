# Getting newsdesk onto GitHub

Everything below assumes you're running these commands from the repo root
(`C:\Users\clanc\dev\injinia\newsdesk`) and that you've already reviewed the
findings in the latest bug/slop pass. This repo has no remote configured yet
(`git remote -v` returns nothing) and is on branch `master`.

## 1. Pre-flight checks

Confirm the working tree is clean and there's nothing you don't want in
history:

```bash
git status
git log --oneline
```

Confirm nothing sensitive is tracked. `my.yaml`, `*.sqlite3*`, `.cache/`,
`out/`, and `*.state.json` are already gitignored, but it's worth a last
look before the history becomes public and permanent:

```bash
git ls-files | grep -iE "my\.yaml|\.env|secret|key"
```

Expected: no output. If anything comes back, remove it from tracking
(`git rm --cached <file>`) and add it to `.gitignore` before continuing --
once pushed, treat any leaked secret as compromised and rotate it, since
force-pushing history away doesn't reliably scrub it from forks/caches.

## 2. Rename the default branch (optional but recommended)

GitHub's default branch name is `main`; this repo is currently `master`.
Purely cosmetic, but worth doing before the first push so you don't have to
change GitHub's default branch setting afterward:

```bash
git branch -m master main
```

## 3. Create the GitHub repository

Pick whichever path matches your setup.

### Option A: GitHub CLI (`gh`)

Not currently installed in this environment (`gh` wasn't found on `PATH`).
If you install it (`winget install --id GitHub.cli`) and run `gh auth login`
first, the whole thing is one command:

```bash
gh repo create newsdesk --public --source=. --remote=origin --push \
  --description "A daily news board you actually control."
```

That single command creates the GitHub repo, adds it as `origin`, and pushes
`main` in one step -- skip to step 5 if you use this path.

### Option B: GitHub web UI (no `gh` needed)

1. Go to https://github.com/new
2. Repository name: `newsdesk` (or whatever you prefer)
3. **Leave "Initialize this repository with a README" unchecked**, and don't
   add a `.gitignore` or license template -- this repo already has all
   three (`README.md`, `.gitignore`, `LICENSE`). Adding them on GitHub's
   side would create a repo that conflicts with your first push.
4. Choose Public or Private, then click **Create repository**.
5. Copy the HTTPS or SSH URL GitHub shows you on the next page.

## 4. Add the remote and push (if you used Option B)

```bash
git remote add origin https://github.com/<your-username>/newsdesk.git
git push -u origin main
```

(Swap in the SSH URL instead if that's your usual auth method.)

## 5. Verify

```bash
git remote -v
git log --oneline -1
```

Then load the repo in a browser and confirm: the README renders with the
badges/sections you expect, GitHub's "License" badge in the sidebar shows
GPL-3.0 (it auto-detects from the `LICENSE` file), and the file tree matches
what's in `git ls-files` locally.

## 6. Small follow-ups once the URL exists

- `pyproject.toml` doesn't have a `[project.urls]` section yet (deliberately
  left out since the repo didn't exist when it was written). Add:

  ```toml
  [project.urls]
  Repository = "https://github.com/<your-username>/newsdesk"
  ```

  Commit that as a small follow-up push.
- If you want the sample board visible without cloning, GitHub Pages can
  serve `sample-board.html` directly (Settings -> Pages -> deploy from the
  `main` branch, `/` root) -- optional, not required for the repo to work.
- Consider a repo description and topics (`Settings -> General`, or `gh repo
  edit --description "..." --add-topic rss --add-topic self-hosted`) so it's
  discoverable if you ever want it found.

## What you do NOT need to do

- No CI is required for this to work -- there's no build step beyond
  `uv sync`, and the test suites (`tests/test_pipeline.py`,
  `tests/test_state.py`, `tests/test_webapp.py`) are meant to be run locally.
  Add a GitHub Actions workflow later if you want PRs to run them
  automatically; it's not a blocker for the initial push.
- No PyPI publish step -- this is a CLI tool meant to be `uv sync`'d from a
  clone, not installed from a package index. `pyproject.toml`'s
  `[project.scripts]` entry point works fine straight from the repo.
