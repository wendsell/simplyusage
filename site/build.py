# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 wendsell
"""Build the GitHub Pages site into _site/.

- site/index.html is the landing page (copied as-is, version filled in)
- docs/SETUP.md is rendered into site/guide.html -> setup.html, so the guide on
  GitHub and on the site are always the same text

    pip install markdown==3.7 && python site/build.py
"""
from __future__ import annotations

import html
import re
import shutil
import sys
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
OUT = ROOT / "_site"
REPO = "https://github.com/wendsell/simplyusage"

ALERTS = {"NOTE": "Note", "TIP": "Tip", "IMPORTANT": "Important", "WARNING": "Warning", "CAUTION": "Caution"}


def github_slug(text: str, sep: str = "-") -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def version() -> str:
    m = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "simplyusage" / "__init__.py").read_text())
    return m.group(1) if m else ""


def post_process(h: str) -> str:
    def alert(m: re.Match) -> str:
        kind, rest = m.group(1).upper(), re.sub(r"^\s*<br\s*/?>\s*", "", m.group(2).lstrip())
        return (f'<div class="callout {kind.lower()}"><p class="callout-title">{ALERTS[kind]}</p>'
                f"<p>{rest}</div>")
    h = re.sub(r"<blockquote>\s*<p>\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*?)</blockquote>",
               alert, h, flags=re.S)
    h = re.sub(r"(<table>.*?</table>)", r'<div class="table-wrap">\1</div>', h, flags=re.S)
    h = re.sub(r'<a href="(https?://[^"]+)">', r'<a href="\1" target="_blank" rel="noopener">', h)
    # Relative links into the repo (LICENSE, compose.yaml, ...) point at GitHub.
    h = re.sub(r'<a href="(?!https?:|#|mailto:)([^"]+)">',
               lambda m: f'<a href="{REPO}/blob/main/{m.group(1).lstrip("./")}">', h)
    return h


def render_guide() -> str:
    text = (ROOT / "docs" / "SETUP.md").read_text(encoding="utf-8")
    title_m = re.match(r"#\s+(.+)\n", text)
    title = title_m.group(1).strip() if title_m else "Setup guide"
    body = text[title_m.end():] if title_m else text

    md = markdown.Markdown(extensions=["extra", "sane_lists", "toc"],
                           extension_configs={"toc": {"slugify": github_slug, "toc_depth": "2"}})
    body_html = post_process(md.convert(body))
    nav = "\n".join(f'<li><a href="#{t["id"]}">{t["name"]}</a></li>' for t in md.toc_tokens)

    chunks = re.split(r'(?=<h2 id=")', body_html)
    body_html = f'<div class="lead">{chunks[0]}</div>' + "".join(f'<section class="sec">{c}</section>' for c in chunks[1:])

    tpl = (SITE / "guide.html").read_text(encoding="utf-8")
    return (tpl.replace("{{title}}", html.escape(title)).replace("{{nav}}", nav)
               .replace("{{body}}", body_html).replace("{{repo}}", REPO).replace("{{version}}", version()))


def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    index = (SITE / "index.html").read_text(encoding="utf-8").replace("{{version}}", version())
    (OUT / "index.html").write_text(index, encoding="utf-8")
    (OUT / "setup.html").write_text(render_guide(), encoding="utf-8")
    shutil.copy(SITE / "style.css", OUT / "style.css")
    (OUT / ".nojekyll").write_text("")
    print(f"built {OUT}", file=sys.stderr)


if __name__ == "__main__":
    build()
