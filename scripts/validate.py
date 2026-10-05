#!/usr/bin/env python3
"""Check local links, required copy, and GitHub Pages files."""

import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []
        self.title = []
        self.in_title = False
        self.has_desc = False
        self.missing_alt = 0

    def handle_starttag(self, tag, attrs):
        found = dict(attrs)
        if tag == "a" and "href" in found:
            self.urls.append(found["href"])
        if tag == "img":
            if "src" in found:
                self.urls.append(found["src"])
            if "alt" not in found:
                self.missing_alt += 1
        if tag in ("script", "source") and "src" in found:
            self.urls.append(found["src"])
        if tag == "video" and "poster" in found:
            self.urls.append(found["poster"])
        if tag == "link" and "href" in found:
            rel = found.get("rel", "")
            if "stylesheet" in rel or "icon" in rel:
                self.urls.append(found["href"])
        if tag == "meta" and found.get("name") == "description" and found.get("content", "").strip():
            self.has_desc = True
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)


def local_target(url):
    if url.startswith(("http://", "https://", "mailto:", "tel:", "#")):
        return None
    path = url.split("#", 1)[0].split("?", 1)[0]
    return path or None


def main():
    errors = []
    html_files = sorted(ROOT.glob("*.html"))
    if not html_files:
        errors.append("no html files")
    for html in html_files:
        parser = Parser()
        parser.feed(html.read_text(encoding="utf-8"))
        if not "".join(parser.title).strip():
            errors.append(f"{html.name}: missing title")
        if "G-8QK7CXD707" not in html.read_text(encoding="utf-8"):
            errors.append(f"{html.name}: missing Google tag")
        if not parser.has_desc:
            errors.append(f"{html.name}: missing meta description")
        if parser.missing_alt:
            errors.append(f"{html.name}: {parser.missing_alt} img without alt")
        page_text = html.read_text(encoding="utf-8")
        for url in (
            "https://www.facebook.com/valuxgames",
            "https://www.youtube.com/@ValuxGames",
            "https://www.tiktok.com/@valuxgamesofficial",
        ):
            if url not in page_text:
                errors.append(f"{html.name}: missing link {url}")
        for url in parser.urls:
            rel = local_target(url)
            if rel is None:
                continue
            if not (html.parent / rel).resolve().exists():
                errors.append(f"{html.name}: missing {url}")

    for css in sorted(ROOT.glob("css/*.css")):
        for url in re.findall(r"url\([\"']?([^\"')]+)", css.read_text(encoding="utf-8")):
            rel = local_target(url)
            if rel and not (css.parent / rel).resolve().exists():
                errors.append(f"{css.name}: missing {url}")

    cname = (ROOT / "CNAME").read_text(encoding="utf-8").strip()
    if cname != "valuxgames.com":
        errors.append(f"CNAME is {cname!r}")
    if not (ROOT / ".nojekyll").is_file():
        errors.append("missing .nojekyll")

    index = (ROOT / "index.html").read_text(encoding="utf-8")
    for phrase in (
        "Valux Games LLC",
        "Civic Watch",
        "Mecca Gecko",
        "Raleigh",
        "support@valuxgames.com",
    ):
        if phrase not in index:
            errors.append(f"index missing {phrase}")
    for page in ("privacy.html", "terms.html"):
        text = (ROOT / page).read_text(encoding="utf-8")
        if "support@valuxgames.com" not in text:
            errors.append(f"{page} missing studio email")
    privacy = (ROOT / "privacy.html").read_text(encoding="utf-8")
    if "Google Analytics" not in privacy:
        errors.append("privacy.html does not describe Google Analytics")
    for url in (
        "https://civicwatchgame.com/",
        "https://apps.apple.com/us/app/civic-watch-fps/id6811555006",
        "https://www.meccagecko.com/",
        "https://apps.apple.com/us/app/mecca-gecko/id6801449754",
        "https://www.roblox.com/games/83952850539551/ECHO-BRAWLERS-Roll-Fight",
        "https://www.facebook.com/valuxgames",
        "https://www.youtube.com/@ValuxGames",
        "https://www.tiktok.com/@valuxgamesofficial",
    ):
        if url not in index:
            errors.append(f"index missing link {url}")

    if errors:
        print("\n".join(errors))
        return 1
    print(f"ok {len(html_files)} html files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
