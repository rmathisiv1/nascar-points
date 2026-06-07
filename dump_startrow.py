"""Quick one-off: dump a Jayski STARTROW (starting lineup) PDF so we can see
its layout before writing the real parser. Run from the repo's scripts/ folder.

    python dump_startrow.py
    python dump_startrow.py "<other STARTROW pdf url>"
"""
import io
import sys

import cloudscraper
import pdfplumber

DEFAULT_URL = "https://www.jayski.com/wp-content/uploads/sites/31/2026/6/6/12615_STARTROW.pdf"


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    scraper = cloudscraper.create_scraper()
    resp = scraper.get(url)
    data = resp.content
    print(f"# fetched {len(data)} bytes, HTTP {resp.status_code}", file=sys.stderr)
    if data[:5] != b"%PDF-":
        print("# WARNING: response is not a PDF (Cloudflare block or bad URL?)", file=sys.stderr)

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for i, pg in enumerate(pdf.pages):
            print(f"===== PAGE {i} TEXT =====")
            print(pg.extract_text() or "(no text)")
            tables = pg.extract_tables() or []
            for ti, t in enumerate(tables):
                print(f"----- PAGE {i} TABLE {ti} -----")
                for row in t:
                    print(row)


if __name__ == "__main__":
    main()
