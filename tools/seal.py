"""Add or update a lesson. Seals the files with keys/public.pem (no password needed).

python tools/seal.py 2026-11-14 --title "..." --guide G.html --slides S.html --student B.html
Any of the three files can be left out (e.g. a past lesson with only a student book).
"""
import argparse, json, os, pathlib, sys
sys.path.insert(0, os.path.dirname(__file__))
import rcrypto as rc

ROOT = pathlib.Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser()
ap.add_argument("date")
ap.add_argument("--title")
for k in ("guide", "slides", "student"):
    ap.add_argument("--" + k)
a = ap.parse_args()

pub = (ROOT / "keys" / "public.pem").read_bytes()
d = ROOT / "sources" / a.date
d.mkdir(parents=True, exist_ok=True)
for k in ("guide", "slides", "student"):
    f = getattr(a, k)
    if f:
        (d / f"{k}.bin").write_bytes(rc.seal(pathlib.Path(f).read_bytes(), pub))
        print("sealed", a.date, k)

lp = ROOT / "lessons.json"
lessons = json.loads(lp.read_text()) if lp.exists() else []
cur = next((l for l in lessons if l["date"] == a.date), None)
if cur is None:
    cur = {"date": a.date, "title": a.title or ""}
    lessons.append(cur)
elif a.title:
    cur["title"] = a.title
lessons.sort(key=lambda l: l["date"])
lp.write_text(json.dumps(lessons, ensure_ascii=False, indent=1) + "\n")
