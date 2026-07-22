#!/usr/bin/env python3
"""
Local Google Scholar citation updater (fetch + write + push).

Why this exists: the GitHub Action (main.py + scholarly) gets blocked by Google
Scholar from GitHub's datacenter IPs, so it fails/hangs. This script fetches your
public Scholar profile from YOUR machine, parses the citation counts, writes the
JSON files the citation badges read, and force-pushes them to the
`google-scholar-stats` branch that the badges load via jsDelivr.

Google Scholar sometimes blocks even a home IP (HTTP 403 / robot check). When the
scrape fails, the script falls back to the MANUAL_* values below so the badges can
still be published. Keep MANUAL_PUBLICATIONS in sync with your profile; edit the
numbers by hand whenever Scholar blocks the automated read.

Usage:
    python google_scholar_crawler/update_local.py            # try to scrape, else manual, then push
    python google_scholar_crawler/update_local.py --manual   # skip scraping, use MANUAL_* values, then push
    python google_scholar_crawler/update_local.py --no-push   # write the JSON files only (no push)

Only the Python standard library and git are required. The push uses your existing
`origin` remote and cached git credentials (the same ones you push the repo with).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error

SCHOLAR_ID = "rNBVr8gAAAAJ"
BRANCH = "google-scholar-stats"

# Browser-like headers. Scholar 403s bare requests, so we mimic a real Chrome.
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8"),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://scholar.google.com/",
    "Upgrade-Insecure-Requests": "1",
}

# ---------------------------------------------------------------------------
# MANUAL FALLBACK: used when Scholar blocks the scrape (403 / robot check), or
# when you run with --manual. Key = Google Scholar author_pub_id (the
# `citation_for_view` value; same id used in the badge file name and the
# scholar link in about.md). Value = citation count for that paper.
# Update these by hand when the numbers change and Scholar is blocking you.
MANUAL_NAME = "Shubhro Dev"
MANUAL_PUBLICATIONS = {
    "rNBVr8gAAAAJ:u5HHmVD_uO8C": 3,   # Lung Cancer Identification ... (IEEE ISACC 2025)
}
# Total citations shown by the site-wide badge. Defaults to the sum of the
# per-paper counts above; set an explicit number if your profile total differs.
MANUAL_TOTAL = sum(MANUAL_PUBLICATIONS.values())
# ---------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, "results")


def scrape_scholar():
    """Fetch and parse the public Scholar profile. Raises on block/parse failure."""
    url = f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en"
    req = urllib.request.Request(url, headers=HEADERS)
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")

    cells = re.findall(r'gsc_rsb_std\"?>(\d+)<', html)
    if not cells:
        raise ValueError("robot-check / unexpected page (no citation table found)")
    citedby = int(cells[0])
    name_match = re.search(r'id=\"gsc_prf_in\">([^<]+)<', html)
    name = name_match.group(1) if name_match else MANUAL_NAME

    ids = re.findall(r'citation_for_view=([\w-]+:[\w-]+)', html)
    counts = re.findall(r'class=\"gsc_a_ac[^\"]*\"[^>]*>(\d*)<', html)
    publications = {}
    for i, pid in enumerate(ids):
        c = counts[i] if i < len(counts) else ""
        publications[pid] = int(c) if c else 0
    if not publications:
        raise ValueError("robot-check / unexpected page (no publications found)")
    return name, citedby, publications


def write_files(name, citedby, publications):
    """publications: {author_pub_id: num_citations}."""
    os.makedirs(OUT_DIR, exist_ok=True)
    pubs_obj = {pid: {"num_citations": n} for pid, n in publications.items()}
    with open(os.path.join(OUT_DIR, "gs_data.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "citedby": citedby, "publications": pubs_obj}, f, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "gs_data_shieldsio.json"), "w", encoding="utf-8") as f:
        json.dump({"schemaVersion": 1, "label": "citations", "message": str(citedby)}, f, ensure_ascii=False)

    # Per-paper shields.io endpoint files, one per publication, so each paper can
    # show its own Google Scholar citation badge. Filename replaces ':' with '_'.
    for pid, n in publications.items():
        safe = pid.replace(":", "_")
        with open(os.path.join(OUT_DIR, f"gs_cite_{safe}.json"), "w", encoding="utf-8") as f:
            json.dump({"schemaVersion": 1, "label": "citations", "message": str(n)}, f, ensure_ascii=False)

    print(f"Wrote results/gs_data.json, gs_data_shieldsio.json and "
          f"{len(publications)} per-paper badge file(s)  (citedby={citedby}, name={name})")


def fetch_and_write(force_manual=False):
    if force_manual:
        print("Using MANUAL_* values (--manual).")
        write_files(MANUAL_NAME, MANUAL_TOTAL, MANUAL_PUBLICATIONS)
        return
    try:
        name, citedby, publications = scrape_scholar()
        write_files(name, citedby, publications)
    except (urllib.error.HTTPError, urllib.error.URLError, ValueError, TimeoutError) as e:
        print(f"Scholar scrape failed ({e}). Falling back to MANUAL_* values.")
        print("If the numbers are stale, edit MANUAL_PUBLICATIONS/MANUAL_TOTAL at the "
              "top of this script, or try again later (Scholar rate-limits).")
        write_files(MANUAL_NAME, MANUAL_TOTAL, MANUAL_PUBLICATIONS)


def result_json_files():
    return [fn for fn in os.listdir(OUT_DIR) if fn.endswith(".json")]


def git(args, cwd, check=True):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")  # never hang waiting for credentials
    return subprocess.run(["git"] + args, cwd=cwd, check=check, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def push_to_branch():
    try:
        origin = git(["remote", "get-url", "origin"], cwd=REPO_ROOT).stdout.strip()
    except Exception:
        raise SystemExit("Could not read the 'origin' remote. Run this from inside the repo.")

    files = result_json_files()
    tmp = tempfile.mkdtemp(prefix="gs-stats-")
    try:
        for fn in files:
            shutil.copy(os.path.join(OUT_DIR, fn), os.path.join(tmp, fn))
        git(["init", "-q"], cwd=tmp)
        git(["checkout", "-q", "-B", BRANCH], cwd=tmp)
        git(["add"] + files, cwd=tmp)
        git(["-c", "user.name=scholar-bot", "-c", "user.email=scholar-bot@local",
             "commit", "-qm", "Update citation data"], cwd=tmp)
        r = git(["push", "-f", origin, f"HEAD:{BRANCH}"], cwd=tmp, check=False)
        if r.returncode != 0:
            print(r.stdout)
            raise SystemExit(
                f"git push failed. Make sure you can push to {origin} "
                "(the same credentials you use for the repo)."
            )
        print(f"Pushed citation data to the '{BRANCH}' branch of {origin}")
        purge_cdn()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def purge_cdn():
    """Bust the jsDelivr cache so the site sees the new data immediately.

    jsDelivr caches gh files for ~12h; without this the badges can lag a full day
    behind a push (and a stale empty `publications: {}` copy blanks the spans).
    """
    for fn in result_json_files():
        purge_url = f"https://purge.jsdelivr.net/gh/spearb0lt/acad-homepage@{BRANCH}/{fn}"
        try:
            urllib.request.urlopen(urllib.request.Request(purge_url), timeout=30).read()
            print(f"Purged jsDelivr cache: {fn}")
        except Exception as e:
            print(f"Could not purge {fn} ({e}); open this once to refresh: {purge_url}")


if __name__ == "__main__":
    fetch_and_write(force_manual="--manual" in sys.argv)
    if "--no-push" in sys.argv:
        print("Skipped push (--no-push). Files are in google_scholar_crawler/results/.")
    else:
        push_to_branch()