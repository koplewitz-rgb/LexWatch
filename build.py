name: Build & Publish LexWatch

on:
  push:
    branches: ["main"]       # run when you commit
  schedule:
    - cron: "0 9 * * *"      # daily at 09:00 UTC (~12:00 Israel time)
  workflow_dispatch:          # enables the green "Run workflow" button

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - run: python -m pip install --upgrade pip
      - run: pip install -r requirements.txt

      # Your build.py creates public/index.html (leave build.py as-is)
      - run: python build.py

      # Upload the folder that build.py actually created:
      - uses: actions/upload-pages-artifact@v3
        with:
          path: public

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
