#!/usr/bin/env python3
"""
Local Google Scholar citation updater (fetch + write + push).

Why this exists: the GitHub Action (main.py + scholarly) gets blocked by Google
Scholar from GitHub's datacenter IPs, so it fails/hangs. This script fetches your
public Scholar profile from YOUR machine (which Scholar does not block), parses the
citation count, writes the two JSON files the citation badge reads, and force-pushes
them to the `google-scholar-stats` branch that the badge loads via jsDelivr.

Usage:
    python google_scholar_crawler/update_local.py            # fetch, write, and push
    python google_scholar_crawler/update_local.py --no-push  # just write the JSON files

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

SCHOLAR_ID = "rNBVr8gAAAAJ"
BRANCH = "google-scholar-stats"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(HERE, "results")


def fetch_and_write():
    url = f"https://scholar.google.com/citations?user={SCHOLAR_ID}&hl=en"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")

    cells = re.findall(r'gsc_rsb_std\"?>(\d+)<', html)
    if not cells:
        raise SystemExit(
            "Could not parse the citation count. Google may have shown a robot check; "
            "wait a minute and run again (or open the profile URL in a browser first)."
        )
    citedby = int(cells[0])
    name_match = re.search(r'id=\"gsc_prf_in\">([^<]+)<', html)
    name = name_match.group(1) if name_match else "Shubhro Dev"

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "gs_data.json"), "w", encoding="utf-8") as f:
        json.dump({"name": name, "citedby": citedby, "publications": {}}, f, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "gs_data_shieldsio.json"), "w", encoding="utf-8") as f:
        json.dump({"schemaVersion": 1, "label": "citations", "message": str(citedby)}, f, ensure_ascii=False)
    print(f"Wrote results/gs_data.json and gs_data_shieldsio.json  (citedby={citedby}, name={name})")
    return citedby


def git(args, cwd, check=True):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")  # never hang waiting for credentials
    return subprocess.run(["git"] + args, cwd=cwd, check=check, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def push_to_branch():
    try:
        origin = git(["remote", "get-url", "origin"], cwd=REPO_ROOT).stdout.strip()
    except Exception:
        raise SystemExit("Could not read the 'origin' remote. Run this from inside the repo.")

    tmp = tempfile.mkdtemp(prefix="gs-stats-")
    try:
        for fn in ("gs_data.json", "gs_data_shieldsio.json"):
            shutil.copy(os.path.join(OUT_DIR, fn), os.path.join(tmp, fn))
        git(["init", "-q"], cwd=tmp)
        git(["checkout", "-q", "-B", BRANCH], cwd=tmp)
        git(["add", "gs_data.json", "gs_data_shieldsio.json"], cwd=tmp)
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
        print("The badge updates via jsDelivr (cached ~12h). To refresh now, open:")
        print(f"  https://purge.jsdelivr.net/gh/spearb0lt/acad-homepage@{BRANCH}/gs_data_shieldsio.json")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    fetch_and_write()
    if "--no-push" in sys.argv:
        print("Skipped push (--no-push). Files are in google_scholar_crawler/results/.")
    else:
        push_to_branch()
