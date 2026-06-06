"""Dump a Jayski EventSchedule PDF's text + tables so we can design the parser.

Usage:
    python dump_schedule.py <pdf_url>

Reuses the existing Cloudflare-aware fetcher (_get) from scrape_jayski_entry,
so run it from the same folder as scrape_jayski_entry.py. It prints, per page:
the raw extracted text, then any detected tables (pipe-separated). Paste the
output back and I'll build parse_schedule() to match the real layout.
"""
import sys
import io

try:
    import pdfplumber
except ImportError:
    print("Missing pdfplumber. Run: pip install pdfplumber")
    sys.exit(1)

try:
    from scrape_jayski_entry import _get
except Exception as e:
    print(f"Couldn't import _get from scrape_jayski_entry.py: {e}")
    print("Make sure this file is in the same folder as scrape_jayski_entry.py")
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    url = sys.argv[1]
    print(f"Fetching: {url}\n")
    data = _get(url, binary=True)
    if not data:
        print("FETCH FAILED — the fetcher returned nothing. "
              "Check the URL, or whether Cloudflare blocked it.")
        sys.exit(1)
    print(f"Fetched {len(data):,} bytes\n")

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        print(f"Pages: {len(pdf.pages)}")
        for pi, page in enumerate(pdf.pages):
            print(f"\n========================= PAGE {pi + 1} =========================")
            print("------------------------- RAW TEXT -------------------------")
            print(page.extract_text() or "(no extractable text)")
            tables = page.extract_tables() or []
            if tables:
                for ti, tbl in enumerate(tables):
                    print(f"\n----------------------- TABLE {ti + 1} -----------------------")
                    for row in tbl:
                        print(" | ".join("" if c is None else str(c).replace("\n", " ") for c in row))
            else:
                print("\n(no tables detected by pdfplumber)")


if __name__ == "__main__":
    main()
