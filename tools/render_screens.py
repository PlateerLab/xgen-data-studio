"""Render the README images: the studio screens from the example studio, and the architecture figure.

    python tools/render_screens.py            # needs playwright with chromium installed

Writes assets/screens/{library,ontology,query,decision,map}.png and assets/architecture.png at 2x.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from xgen_data_studio.config import load_studio  # noqa: E402
from xgen_data_studio.preview import render  # noqa: E402


def main() -> None:
    out = ROOT / "assets"
    (out / "screens").mkdir(parents=True, exist_ok=True)
    studio = load_studio(ROOT / "examples" / "library" / "studio.yaml")
    html = render(studio, query="revenueByCategory", decision="returnEligibility", key="I1001")
    with tempfile.TemporaryDirectory() as tmp:
        page_file = Path(tmp) / "studio.html"
        page_file.write_text(html, encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1500, "height": 1000}, device_scale_factor=2)
            page.goto(page_file.as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            for sid in ("library", "ontology", "query", "decision", "map"):
                page.locator(f"#{sid}").screenshot(path=str(out / "screens" / f"{sid}.png"))
            arch = ROOT / "tools" / "architecture.html"
            page.set_viewport_size({"width": 1600, "height": 900})
            page.goto(arch.as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.locator("#figure").screenshot(path=str(out / "architecture.png"))
            browser.close()
    print("written", sorted(str(p.relative_to(ROOT)) for p in out.rglob("*.png")))


if __name__ == "__main__":
    main()
