# GitHub setup

The ZIP contains GitHub Actions, Dependabot, and pull-request templates. It does **not** create a remote repository.

1. Create a **private** empty repository on GitHub, without initializing a README.
2. Extract this ZIP and open a terminal in the `cacsms-sports` directory.
3. Check that `.env`, credentials, cookies, datasets, screenshots and database dumps are not staged.
4. Run:

```bash
git init -b main
git add .
git status
git commit -m "Initialize CACSMS Sport AI 2.9"
git remote add origin https://github.com/YOUR-ACCOUNT/YOUR-PRIVATE-REPO.git
git push -u origin main
```

5. Enable branch protection for `main`, require CI checks and code review.
6. Configure repository secrets in GitHub settings for any future deployment; never put them in the repository.
7. CI runs backend tests, frontend build, and Docker image build. Deployment is deliberately **not** automatic.

`SPORTS_ADMIN_TOKEN` must be configured securely. GitHub Actions do not grant access to SportyBet or any other source.
