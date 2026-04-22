import re
html = open('debug_race.html', encoding='utf-8').read()
print(f'HTML size: {len(html)} bytes')
print(f'<table> count: {html.count("<table")}')
print(f'<div role="cell"> count: {html.count(chr(34) + "cell" + chr(34))}')
print(f'"Tyler Reddick" appears: {html.count("Tyler Reddick")}x')
print(f'"Stage 1" appears: {html.count("Stage 1")}x')

# Find the line with Tyler Reddick to see cell structure
for i, line in enumerate(html.split("\n")):
    if "Tyler Reddick" in line:
        print(f"\n--- Line containing Reddick (truncated) ---")
        print(line[:800])
        break

# Find Stage 1 context
for i, line in enumerate(html.split("\n")):
    if "Stage 1" in line:
        print(f"\n--- Line containing Stage 1 (truncated) ---")
        print(line[:500])
        break

# Look for data in JSON-like structures inside the HTML
import re
json_blobs = re.findall(r'(\{[^{}]*"driver"[^{}]*\})', html, re.I)
print(f"\nJSON-like driver objects: {len(json_blobs)}")
if json_blobs:
    print("First one:", json_blobs[0][:300])
