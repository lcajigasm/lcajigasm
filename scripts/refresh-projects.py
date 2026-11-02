#!/usr/bin/env python3
"""Refresh the featured-projects block in README.md from the public GitHub API.

Rewrites only the region between the markers <!-- projects:start --> and
<!-- projects:end -->. Descriptions, Homebrew commands, and screenshot URLs
are fixed. Versions, release links, Pages links, and .dmg assets come from
the latest published release. The script writes the file only when the text
changes, so a second run is a no-op.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

OWNER = "lcajigasm"
README = Path(__file__).resolve().parents[1] / "README.md"
START = "<!-- projects:start -->"
END = "<!-- projects:end -->"
API = "https://api.github.com"
USER_AGENT = "lcajigasm-profile-refresh"

# One line taken from each project's README. Screenshot URLs are raw files
# on the default branch, produced by that repo's capture workflow.
PROJECTS = [
    {
        "repo": "lux",
        "description": (
            "A folder opens with its children in the sidebar, and "
            "`lux file-a file-b` opens each file as its own tab."
        ),
        "brew": "brew install --cask lcajigasm/tap/lux",
        "pages": "https://lcajigasm.github.io/lux/",
        "images": [
            {
                "alt": "Lux file tree beside Sublime Text and Zed",
                "url": "https://raw.githubusercontent.com/lcajigasm/lux/main/docs/compare/tree.png",
            },
            {
                "alt": "Lux tabs beside Sublime Text and Zed",
                "url": "https://raw.githubusercontent.com/lcajigasm/lux/main/docs/compare/tabs.png",
            },
        ],
    },
    {
        "repo": "ownterm",
        "description": (
            "Local workflows stay on this machine: "
            "`ownterm-tui workflow add` saves a command for the palette, "
            "with no Warp account or telemetry."
        ),
        "brew": "brew install --cask lcajigasm/tap/ownterm",
        "pages": "https://lcajigasm.github.io/ownterm/",
        "images": [
            {
                "alt": "ownterm-tui workflow list",
                "url": "https://raw.githubusercontent.com/lcajigasm/ownterm/master/docs/screenshots/ownterm-tui-workflows.png",
            }
        ],
    },
    {
        "repo": "omega",
        "description": (
            "Private keys and credential files stay on the machine, "
            "`omega doctor` checks the configured model, and a 429 waits for `Retry-After`."
        ),
        "brew": "brew install lcajigasm/tap/omega",
        "pages": "https://lcajigasm.github.io/omega/",
        "images": [
            {
                "alt": "A failure diagnosed and an approval card",
                "url": "https://raw.githubusercontent.com/lcajigasm/omega/main/docs/assets/confirm.png",
            }
        ],
    },
]


class FetchError(RuntimeError):
    pass


def _request(url: str, accept: str) -> tuple[int, str, dict[str, str]]:
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", "replace")
            header_map = {key.lower(): value for key, value in response.headers.items()}
            return response.status, body, header_map
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        if error.code in (403, 429, 500, 502, 503, 504):
            raise FetchError(f"{url} returned HTTP {error.code}: {detail[:200]}") from error
        return error.code, detail, {key.lower(): value for key, value in error.headers.items()}
    except urllib.error.URLError as error:
        raise FetchError(f"{url} could not be fetched: {error.reason}") from error


def latest_release(repo: str) -> dict:
    status, body, _headers = _request(
        f"{API}/repos/{OWNER}/{repo}/releases/latest",
        "application/vnd.github+json",
    )
    if status != 200:
        raise FetchError(f"{OWNER}/{repo} latest release returned HTTP {status}")
    payload = json.loads(body)
    if payload.get("draft") or payload.get("prerelease"):
        raise FetchError(f"{OWNER}/{repo} latest release is not a final release")
    tag = payload.get("tag_name")
    html_url = payload.get("html_url")
    if not tag or not html_url:
        raise FetchError(f"{OWNER}/{repo} latest release is missing tag or url")
    return payload


def url_ok(url: str, image: bool) -> bool:
    status, _body, headers = _request(url, "*/*")
    if status == 200:
        if image and not headers.get("content-type", "").lower().startswith("image/"):
            raise FetchError(f"{url} is not an image")
        return True
    if status == 404:
        return False
    raise FetchError(f"{url} returned HTTP {status}")


def dmg_assets(release: dict) -> list[dict]:
    assets = []
    for asset in release.get("assets") or []:
        name = asset.get("name") or ""
        download = asset.get("browser_download_url") or ""
        if name.lower().endswith(".dmg") and download:
            assets.append({"name": name, "url": download})
    assets.sort(key=lambda item: item["name"])
    return assets


def render_project(project: dict, release: dict) -> str:
    repo = project["repo"]
    tag = release["tag_name"]
    repo_url = f"https://github.com/{OWNER}/{repo}"
    release_url = release["html_url"]
    lines = [
        f"### [{repo}]({repo_url}) · [{tag}]({release_url})",
        "",
        project["description"],
        "",
    ]
    for image in project["images"]:
        if url_ok(image["url"], image=True):
            lines.append(f"![{image['alt']}]({image['url']})")
            lines.append("")
    links = [
        f"[Repository]({repo_url})",
        f"[Release {tag}]({release_url})",
    ]
    if url_ok(project["pages"], image=False):
        links.append(f"[Pages]({project['pages']})")
    for asset in dmg_assets(release):
        links.append(f"[{asset['name']}]({asset['url']})")
    lines.append(" · ".join(links))
    lines.append("")
    lines.append("```bash")
    lines.append(project["brew"])
    lines.append("```")
    return "\n".join(lines)


def render_block(releases: list[tuple[dict, dict]]) -> str:
    parts = [
        START,
        "## Featured",
        "",
        "Versions and links follow the latest published release. "
        "Homebrew packages come from the "
        "[lcajigasm/tap](https://github.com/lcajigasm/homebrew-tap).",
        "",
    ]
    rendered = [render_project(project, release) for project, release in releases]
    parts.append("\n\n".join(rendered))
    parts.append("")
    parts.append(END)
    return "\n".join(parts)


def replace_block(text: str, block: str) -> str:
    start = text.find(START)
    end = text.find(END)
    if start < 0 or end < 0 or end < start:
        raise SystemExit("README is missing <!-- projects:start --> / <!-- projects:end -->")
    end += len(END)
    return text[:start] + block + text[end:]


def main() -> int:
    if not README.is_file():
        raise SystemExit(f"README not found: {README}")
    original = README.read_text(encoding="utf-8")
    releases = [(project, latest_release(project["repo"])) for project in PROJECTS]
    updated = replace_block(original, render_block(releases))
    if updated == original:
        print("README unchanged")
        return 0
    README.write_text(updated, encoding="utf-8")
    for project, release in releases:
        names = ", ".join(asset["name"] for asset in dmg_assets(release)) or "no dmg"
        print(f"{project['repo']} {release['tag_name']} ({names})")
    print("README updated")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except FetchError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
