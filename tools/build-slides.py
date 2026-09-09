#!/usr/bin/env python3
"""Split presentation.html into one self-contained file per slide.

The deck (presentation.html) is the single source of truth. This script slices
it into slides/1.html .. slides/30.html so each slide can be opened, embedded or
handed to an external player on its own. Every generated file carries the full
shared <style> and <script> from the deck, so it renders identically with no
external dependency of any kind.

The deck wrapper in a generated file gets data-standalone, which makes the CSS
show its single slide without needing a :target fragment, and makes the runtime
skip navigation (there is nowhere to navigate to).

Usage:
    python3 tools/build-slides.py [--deck presentation.html] [--out slides]

Re-run this after any edit to presentation.html.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

SLIDE_RE = re.compile(r'<section class="slide" id="slide-(\d\d)">.*?</section>', re.S)
STYLE_RE = re.compile(r"<style>.*?</style>", re.S)
# Spans from the first <script tag to the last </script> tag, so it captures
# every script element in the deck (the external KaTeX loader plus both
# inline <script> blocks) as one contiguous chunk, not just the first bare
# <script>...</script> pair. Relies on all script tags being contiguous at
# the end of the document, which is how the deck is built.
SCRIPT_RE = re.compile(r"<script.*</script>", re.S)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
CHROME_RE = re.compile(
    r'<div class="chrome".*?</div>\s*'
    r'<div class="counter[^>]*>.*?</div>\s*'
    r'<div class="brand[^>]*>.*?</div>', re.S)
PRESENTER_RE = re.compile(r'<div id="presenter" hidden>.*?\n</div>\n', re.S)

TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
{style}
</head>
<body>
<main class="deck" data-standalone="{num}">
{slide}
</main>
{script}
</body>
</html>
"""


def build(deck_path: str, out_dir: str) -> int:
    with open(deck_path, encoding="utf-8") as fh:
        deck = fh.read()

    style_m = STYLE_RE.search(deck)
    script_m = SCRIPT_RE.search(deck)
    if not style_m or not script_m:
        print("error: could not find the shared <style>/<script> block", file=sys.stderr)
        return 1

    title_m = TITLE_RE.search(deck)
    base_title = title_m.group(1).strip() if title_m else "rpitx_webtx"

    slides = list(SLIDE_RE.finditer(deck))
    if len(slides) != 30:
        print("error: expected 30 slides, found %d" % len(slides), file=sys.stderr)
        return 1

    os.makedirs(out_dir, exist_ok=True)
    written = []
    for m in slides:
        num = int(m.group(1))
        html = TEMPLATE.format(
            title="%s - %02d/30" % (base_title, num),
            style=style_m.group(0),
            script=script_m.group(0),
            slide=m.group(0),
            num="%02d" % num,
        )
        path = os.path.join(out_dir, "%d.html" % num)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        written.append(path)

    print("wrote %d files to %s/ (1.html .. %d.html)" % (len(written), out_dir, len(written)))
    return 0


def main() -> int:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deck", default=os.path.join(here, "presentation.html"),
                    help="path to the source deck (default: %(default)s)")
    ap.add_argument("--out", default=os.path.join(here, "slides"),
                    help="output directory (default: %(default)s)")
    args = ap.parse_args()
    return build(args.deck, args.out)


if __name__ == "__main__":
    sys.exit(main())
