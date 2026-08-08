"""Download and prepare the source data. Run once before the pipeline.

  python scripts/fetch_data.py

Downloads the Sabin Center report, extracts the 33 false claims (each with its
verbatim real-world quote and the expert rebuttal), and pulls the FrugalAI
claim pool used by later phases.

Safe to re-run: anything already on disk is skipped.
"""

from __future__ import annotations

import csv
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SABIN_URL = (
    "https://scholarship.law.columbia.edu/cgi/viewcontent.cgi"
    "?article=1218&context=sabin_climate_change"
)
FRUGAL_BASE = (
    "https://huggingface.co/datasets/QuotaClimat/frugalaichallenge-text-train"
    "/resolve/main/data/"
)

SABIN_PDF = ROOT / "data" / "raw" / "sabin" / "sabin_33_claims.pdf"
SABIN_TXT = ROOT / "data" / "interim" / "sabin_raw.txt"
CLAIMS_JSON = ROOT / "data" / "interim" / "sabin_claims.json"
CLAIMS_CSV = ROOT / "data" / "interim" / "sabin_claims.csv"
FRUGAL_DIR = ROOT / "data" / "raw" / "frugalai"

BODY_MARKER = "PART A: FALSE CLAIMS ABOUT SOLAR"


# Columbia's repository rejects requests carrying a recognisable bot or browser
# User-Agent and serves an HTML interstitial to others, so try a few header sets
# and keep the first response whose bytes are actually the file we asked for.
HEADER_VARIANTS = (
    {},
    {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "*/*"},
    {"User-Agent": "curl/8.4.0", "Accept": "*/*"},
)

MAGIC = {".pdf": b"%PDF", ".parquet": b"PAR1"}


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  have {dest.name}")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {dest.name} ...", flush=True)

    want = MAGIC.get(dest.suffix)
    last = ""
    for headers in HEADER_VARIANTS:
        try:
            req = urllib.request.Request(url, headers=headers)
            data = urllib.request.urlopen(req, timeout=180).read()
        except Exception as exc:  # noqa: BLE001 - try the next variant
            last = str(exc)
            continue
        if want and not data.startswith(want):
            last = f"got {data[:40]!r} instead of {want!r}"
            continue
        if not data:
            last = "empty response"
            continue
        dest.write_bytes(data)
        print(f"  saved {dest.name} ({len(data) // 1024} KB)")
        return

    sys.exit(
        f"\nERROR: could not download {dest.name} ({last})\n"
        f"Download it manually from:\n  {url}\n"
        f"and save it as:\n  {dest}"
    )


def extract_pdf_text() -> str:
    if SABIN_TXT.exists():
        return SABIN_TXT.read_text(encoding="utf-8")
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("ERROR: pypdf missing. Run: pip install -r requirements.txt")
    reader = PdfReader(str(SABIN_PDF))
    text = "\n".join((p.extract_text() or "") for p in reader.pages)
    SABIN_TXT.parent.mkdir(parents=True, exist_ok=True)
    SABIN_TXT.write_text(text, encoding="utf-8")
    print(f"  extracted {len(reader.pages)} pages")
    return text


def parse_claims(text: str) -> list[dict]:
    text = re.sub(r"[‘’�]", "'", text)
    text = re.sub(r"[“”]", '"', text)

    # The marker appears in the contents list first; the report body is the
    # last occurrence.
    hits = [m.start() for m in re.finditer(re.escape(BODY_MARKER), text)]
    if not hits:
        sys.exit("ERROR: could not locate the report body in the PDF text")
    body = text[hits[1] if len(hits) > 1 else hits[0]:]

    best: dict[int, str] = {}
    for m in re.finditer(r"False Claim\s*#?\s*(\d{1,2})\s*:", body):
        n = int(m.group(1))
        seg = re.sub(r"\s+", " ", body[m.end():m.end() + 1100]).strip()
        if "...." in seg[:120]:  # a table-of-contents line, not the body
            continue
        if n not in best or len(seg) > len(best[n]):
            best[n] = seg

    def tech(n: int) -> str:
        return "solar" if n <= 14 else ("wind" if n <= 29 else "ev")

    rows = []
    for n in sorted(k for k in best if 1 <= k <= 33):
        seg = best[n]
        mt = re.match(r"(.+?\.)\s*\"", seg)
        claim = (mt.group(1) if mt else seg.split('"')[0]).strip()
        mq = re.search(r"\"(.+?)\"\s*\d{1,4}", seg)
        quote = (mq.group(1) if mq else "").strip()
        if quote:
            rebuttal = seg[seg.find(quote) + len(quote) + 1:].strip()
        else:
            rebuttal = seg[len(claim):].strip()
        rows.append(
            {
                "claim_id": f"SABIN-{n:02d}",
                "tech": tech(n),
                "false_claim": claim,
                "source_quote": quote,
                "rebuttal_excerpt": re.sub(r"^\d+\s*", "", rebuttal)[:450],
            }
        )
    return rows


def main() -> None:
    print("Sabin Center report")
    download(SABIN_URL, SABIN_PDF)

    if CLAIMS_JSON.exists():
        rows = json.loads(CLAIMS_JSON.read_text(encoding="utf-8"))
        print(f"  have sabin_claims.json ({len(rows)} claims)")
    else:
        rows = parse_claims(extract_pdf_text())
        CLAIMS_JSON.parent.mkdir(parents=True, exist_ok=True)
        CLAIMS_JSON.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        with CLAIMS_CSV.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        print(f"  wrote {len(rows)} claims")

    missing = [n for n in range(1, 34) if f"SABIN-{n:02d}" not in {r['claim_id'] for r in rows}]
    no_quote = [r["claim_id"] for r in rows if not r["source_quote"]]

    print("\nFrugalAI claim pool (used by later phases, not the pilot)")
    for name in ("train", "test"):
        download(f"{FRUGAL_BASE}{name}-00000-of-00001.parquet",
                 FRUGAL_DIR / f"{name}.parquet")

    print("\n" + "=" * 46)
    print(f"claims extracted : {len(rows)}/33")
    print(f"with quote       : {len(rows) - len(no_quote)}/{len(rows)}")
    if missing:
        print(f"MISSING          : {missing}")
    print("=" * 46)

    if len(rows) != 33 or missing:
        sys.exit("\nERROR: expected 33 claims. Stop and report this.")
    print("\nData ready. Next: python src/run_pipeline.py --limit 3 --run-name test3")


if __name__ == "__main__":
    main()
