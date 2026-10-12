#!/usr/bin/env python3
"""Download and prepare the binary assets (photos, fonts) listed in assets.json.

Photos come from Wikimedia Commons (CC0, public domain, CC BY, CC BY-SA; credited
on each page); fonts come from Google Fonts (SIL Open Font License). Each photo is
cropped, resized and compressed exactly as for the local build, then checked
against the expected SHA-256.
"""
import hashlib, io, json, os, shutil, sys, time, urllib.error, urllib.parse, urllib.request
from PIL import Image, ImageOps

UA = {"User-Agent": "kensington-restaurant-demos-asset-builder/1.0 (+https://github.com/liliputnikos-tech/kensington-restaurant-demos)"}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def fetch(url, attempts=8):
    """GET with polite pacing and back-off (Wikimedia rate-limits shared CI IPs)."""
    for attempt in range(attempts):
        time.sleep(1)
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        except urllib.error.HTTPError as e:
            if attempt == attempts - 1 or e.code not in (429, 500, 502, 503, 504):
                raise
            wait = e.headers.get("Retry-After")
            time.sleep(int(wait) if wait and wait.isdigit() else min(60, 5 * 2 ** attempt))
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))


def commons_url(title, width=1920):
    q = urllib.parse.urlencode({"action": "query", "titles": title if title.startswith("File:") else "File:" + title, "prop": "imageinfo",
                                "iiprop": "url", "iiurlwidth": width, "format": "json"})
    d = json.loads(fetch("https://commons.wikimedia.org/w/api.php?" + q))
    ii = list(d["query"]["pages"].values())[0]["imageinfo"][0]
    return ii.get("thumburl") or ii["url"]


def save_budget(img, budget, q=78, qmin=58):
    while True:
        b = io.BytesIO()
        img.save(b, "JPEG", quality=q, optimize=True, progressive=True)
        if b.tell() <= budget or q <= qmin:
            return b.getvalue()
        q -= 3


def prep(data, maxw, crop):
    i = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    if crop:
        rw, rh, fx, fy = crop if len(crop) == 4 else (crop[0], crop[1], 0.5, crop[2])
        W, H = i.size
        tr = rw / rh
        if W / H > tr:
            nw = int(H * tr); x = int((W - nw) * fx); i = i.crop((x, 0, x + nw, H))
        else:
            nh = int(W / tr); y = int((H - nh) * fy); i = i.crop((0, y, W, y + nh))
    if i.size[0] > maxw:
        i = i.resize((maxw, int(i.size[1] * maxw / i.size[0])), Image.LANCZOS)
    return save_budget(i, 200_000 if maxw >= 1200 else 120_000)


def og(data):
    i = Image.open(io.BytesIO(data)).convert("RGB")
    W, H = i.size; tr = 1200 / 630
    if W / H > tr:
        nw = int(H * tr); i = i.crop(((W - nw) // 2, 0, (W - nw) // 2 + nw, H))
    else:
        nh = int(W / tr); i = i.crop((0, (H - nh) // 2, W, (H - nh) // 2 + nh))
    return save_budget(i.resize((1200, 630), Image.LANCZOS), 120_000)


def main():
    manifest = json.load(open(os.path.join(ROOT, "assets.json")))
    built, mismatched = {}, []
    for a in manifest["assets"]:
        path = os.path.join(ROOT, a["path"])
        kind = a.get("kind")
        if kind == "font":
            data = fetch(a["url"])
        elif kind == "og":
            data = og(built[a["from"]])
        elif kind == "copy":
            data = built[a["from"]]
        else:
            try:
                src = fetch(a["url"])
            except urllib.error.HTTPError:
                src = fetch(commons_url(a["commons"]))
            if a.get("src_sha256") and hashlib.sha256(src).hexdigest() != a["src_sha256"]:
                print("source changed:", a["path"])
            data = prep(src, a["maxw"], a.get("crop"))
        built[a["path"]] = data
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "wb").write(data)
        h = hashlib.sha256(data).hexdigest()
        if a.get("sha256") and h != a["sha256"]:
            mismatched.append(a["path"])
        print(a["path"], len(data), h)
    print(f"{len(built)} assets written, {len(mismatched)} differ from the expected hash: {mismatched}")
    if "--strict" in sys.argv and mismatched:
        sys.exit(1)


if __name__ == "__main__":
    main()
