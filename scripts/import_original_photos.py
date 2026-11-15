#!/usr/bin/env python3
"""Bulk-import publicly accessible images from Nevada Silver Construction's original site.
Run: python scripts/import_original_photos.py
Requires: pip install requests beautifulsoup4 pillow
Review public/images/original/manifest.csv before using the photos on the site.
"""
import csv
import hashlib
import io
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageOps

SOURCE = "https://www.nvsilverconstruction.com/"
OUT = Path("public/images/original")
MAX_IMAGES = 100
MAX_BYTES = 15 * 1024 * 1024
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SitePhotoImporter/1.0)"}

def collect():
    html = requests.get(SOURCE, headers=HEADERS, timeout=30)
    html.raise_for_status()
    soup = BeautifulSoup(html.text, "html.parser")
    urls = {}
    def add(raw, context):
        if not raw or raw.startswith(("data:", "blob:")):
            return
        url = urljoin(SOURCE, raw.strip())
        if urlparse(url).scheme not in ("https", "http"):
            return
        if urlparse(url).netloc not in ("cdn.prod.website-files.com", "www.nvsilverconstruction.com", "nvsilverconstruction.com"):
            return
        urls.setdefault(url, context.strip()[:150])
    for img in soup.select("img"):
        ctx = img.get("alt") or img.get("aria-label") or ""
        for attr in ("src", "data-src", "data-original", "data-lazy-src"):
            add(img.get(attr), ctx)
        for attr in ("srcset", "data-srcset"):
            for entry in (img.get(attr) or "").split(","):
                add(entry.strip().split(" ")[0], ctx)
    for node in soup.select("[style]"):
        for url in re.findall(r'url\(["\']?([^"\')]+)', node.get("style", "")):
            add(url, node.get("class", ["background"])[0])
    for style in soup.select("style"):
        for url in re.findall(r'url\(["\']?([^"\')]+)', style.get_text()):
            add(url, "CSS background")
    # Webflow may embed background-image URLs directly in the page HTML.
    for url in re.findall(r'https?://cdn\.prod\.website-files\.com/[^"\'<>\s)]+', html.text):
        add(url.replace("&amp;", "&"), "HTML asset")
    return urls

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    seen = set()
    rows = []
    session = requests.Session()
    session.headers.update(HEADERS)
    for url, context in list(collect().items())[:400]:
        if len(rows) >= MAX_IMAGES:
            break
        try:
            response = session.get(url, timeout=25)
            response.raise_for_status()
            if len(response.content) > MAX_BYTES:
                continue
            with Image.open(io.BytesIO(response.content)) as im:
                if im.width < 450 or im.height < 300:
                    continue  # skip small icons, logos, thumbnails
                im = ImageOps.exif_transpose(im).convert("RGB")
                im.thumbnail((1800, 1800))
                data = io.BytesIO()
                im.save(data, "WEBP", quality=82, method=6)
                content = data.getvalue()
                digest = hashlib.sha256(content).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                name = f"original-{len(rows)+1:03d}.webp"
                (OUT / name).write_bytes(content)
                rows.append({"filename": name, "source_url": url, "original_filename": unquote(Path(urlparse(url).path).name), "alt_or_context": context, "width": im.width, "height": im.height})
                print(f"{name}: {context} ({im.width}x{im.height})")
        except Exception as exc:
            print(f"Skipped {url}: {exc}")
    with (OUT / "manifest.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=["filename", "source_url", "original_filename", "alt_or_context", "width", "height"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Imported {len(rows)} photos into {OUT}")

if __name__ == "__main__":
    main()
