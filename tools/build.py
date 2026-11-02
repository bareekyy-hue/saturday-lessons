"""Build the site into _site/. Run by the GitHub job (needs TEACHER_PASSWORD).

- Teacher guide + slides: always locked with the teacher password.
- Student book: open from 08:00 Finland time on its lesson Saturday; locked before that.
First run (no keys yet) creates the repo keys, locked with the teacher password.
Optional env NOW=YYYY-MM-DDTHH:MM (Finland time) for testing.
"""
import base64, datetime as dt, html, json, os, pathlib, shutil, sys
from zoneinfo import ZoneInfo
sys.path.insert(0, os.path.dirname(__file__))
import rcrypto as rc

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
TZ = ZoneInfo("Europe/Helsinki")
OPEN_HOUR = 8
MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]
KINDS = {"guide": "دليل المعلمة", "slides": "عرض الحصة", "student": "كتاب الطالب"}


def ar_date(d):
    return f"السبت {d.day} {MONTHS[d.month - 1]} {d.year}"


def gh_output(k, v):
    p = os.environ.get("GITHUB_OUTPUT")
    if p:
        with open(p, "a") as f:
            f.write(f"{k}={v}\n")


def main():
    pw = os.environ.get("TEACHER_PASSWORD", "")
    if len(pw) < 8:
        sys.exit("TEACHER_PASSWORD secret is missing or shorter than 8 characters.")
    keys = ROOT / "keys"
    keys.mkdir(exist_ok=True)
    if not (keys / "public.pem").exists():
        pub, locked = rc.new_keypair(pw)
        (keys / "public.pem").write_bytes(pub)
        (keys / "private.lock").write_bytes(locked)
        (keys / "site.json").write_text(json.dumps(
            {"salt": base64.b64encode(os.urandom(16)).decode(), "iterations": rc.ITERATIONS}) + "\n")
        print("Created new keys.")
        gh_output("new_keys", "true")
    try:
        priv = rc.open_private((keys / "private.lock").read_bytes(), pw)
    except Exception:
        sys.exit("The TEACHER_PASSWORD secret does not match the password the keys were made with.")
    site = json.loads((keys / "site.json").read_text())
    salt = base64.b64decode(site["salt"])
    page_key = rc.derive(pw, salt, site["iterations"])

    now = dt.datetime.fromisoformat(os.environ["NOW"]).replace(tzinfo=TZ) if os.environ.get("NOW") \
        else dt.datetime.now(TZ)
    lessons = sorted(json.loads((ROOT / "lessons.json").read_text()), key=lambda l: l["date"])
    shell = (ROOT / "web" / "lock.html").read_text()
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    (OUT / ".nojekyll").write_text("")
    # public/ holds files that are open to everyone (e.g. past lessons before 7/11)
    if (ROOT / "public").exists():
        shutil.copytree(ROOT / "public", OUT, dirs_exist_ok=True)

    def lock_shell(title, binname, kind, d):
        if kind == "student":
            icon, heading = "📘", "كتاب الطالب لم يُفتح بعد"
            notice = (f'<p>يُفتح هذا الدرس يوم</p><p class="when">{ar_date(d)} · الساعة 8:00 صباحًا</p>'
                      '<p>بتوقيت فنلندا</p>')
            label = "للمعلمة: كلمة المرور"
        else:
            icon, heading, notice, label = "🔒", title, "<p>هذه الصفحة خاصة بالمعلمة.</p>", "كلمة المرور"
        rep = {"TITLE": html.escape(title), "ICON": icon, "HEADING": html.escape(heading), "NOTICE": notice,
               "FORM_LABEL": label, "SALT": site["salt"], "ITER": str(site["iterations"]), "BIN": binname,
               "HOME": "../index.html"}
        s = shell
        for k, v in rep.items():
            s = s.replace("{{" + k + "}}", v)
        return s

    released = []
    for l in lessons:
        d = dt.date.fromisoformat(l["date"])
        opens = dt.datetime(d.year, d.month, d.day, OPEN_HOUR, tzinfo=TZ)
        l["open"] = now >= opens
        l["d"] = d
        wd = OUT / l["date"]
        wd.mkdir(exist_ok=True)
        for kind, label in KINDS.items():
            src = ROOT / "sources" / l["date"] / f"{kind}.bin"
            if not src.exists():
                l.setdefault("missing", []).append(kind)
                continue
            page = rc.unseal(src.read_bytes(), priv)
            title = f"{label} · {ar_date(d)}"
            if kind == "student" and l["open"]:
                (wd / "student.html").write_bytes(page)
            else:
                (wd / f"{kind}.bin").write_bytes(rc.lock_page(page, page_key))
                (wd / f"{kind}.html").write_text(lock_shell(title, f"{kind}.bin", kind, d))
        if l["open"]:
            released.append(l["date"])

    (OUT / "index.html").write_text(index_page(lessons, now))
    (OUT / "teacher.html").write_text(teacher_page(lessons))
    state = ROOT / "state" / "released.txt"
    state.parent.mkdir(exist_ok=True)
    old = state.read_text() if state.exists() else ""
    new = "\n".join(released) + "\n"
    state.write_text(new)
    gh_output("changed", "true" if old != new else "false")
    print(f"Built {len(lessons)} lessons; open for students: {len(released)}; now={now:%Y-%m-%d %H:%M} Helsinki")
    for l in lessons:
        if l.get("missing"):
            print(f"  note: {l['date']} has no {', '.join(l['missing'])}")


CSS = """:root{--bg:#f6f5f0;--ink:#1f2a24;--muted:#5c665f;--line:#e4e1d7;--green:#1f6b45;--card:#fff;--gold:#8a6114;--soft:#f1ede2;--new:#e1f4e7;--btn-ink:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#141a17;--ink:#e9ede9;--muted:#9aa59e;--line:#2b342f;--green:#5fbf8a;--card:#1c2420;--gold:#d9ae5a;--soft:#26302b;--new:#1f3a2b;--btn-ink:#0f1a14}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:"Noto Naskh Arabic",serif;font-size:18px;line-height:1.9}
.wrap{max-width:760px;margin:0 auto;padding:40px 16px 60px}
h1{font-family:"Noto Kufi Arabic";color:var(--green);font-size:28px;margin:0}
.sub{color:var(--muted);margin:4px 0 26px}
h3{font-family:"Noto Kufi Arabic";font-size:16px;color:var(--muted);margin:30px 0 6px}
.week{background:var(--card);border:1px solid var(--line);border-radius:20px;padding:18px 20px;margin:14px 0;box-shadow:0 6px 20px rgba(40,30,10,.05)}
.week.hl{border-color:var(--green)}
.week .d{font-family:"Noto Kufi Arabic";font-size:14px;color:var(--gold);font-weight:700}
.week h2{font-family:"Noto Kufi Arabic";font-size:19px;margin:4px 0 10px;line-height:1.7}
.week p{margin:0 0 12px;color:var(--muted)}
.btns{display:flex;gap:10px;flex-wrap:wrap}
.btns a{text-decoration:none;font-family:"Noto Kufi Arabic";font-size:15px;border-radius:999px;padding:8px 18px}
.st{background:var(--green);color:var(--btn-ink)}
.pr{background:var(--soft);color:var(--ink)}
.tag{display:inline-block;background:var(--new);color:var(--green);border-radius:999px;padding:0 10px;font-size:12px;margin-inline-start:6px}
.foot{margin-top:40px;text-align:center;font-size:14px}
.foot a,.foot button{color:var(--muted);font:inherit;background:none;border:0;cursor:pointer;text-decoration:underline}"""

HEAD = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Kufi+Arabic:wght@500;700;800&family=Noto+Naskh+Arabic:wght@400;600&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body><div class="wrap">
"""


def index_page(lessons, now):
    opened = [l for l in lessons if l["open"]]
    upcoming = [l for l in lessons if not l["open"]]
    out = [HEAD.format(title="دروس السبت · مدرسة الرابطة", css=CSS),
           "<h1>دروس السبت</h1>\n<p class=\"sub\">مدرسة الرابطة الإسلامية · الدرس الجديد في الأعلى دائمًا</p>\n"]
    if upcoming:
        n = upcoming[0]
        out.append(f'<div class="week"><div class="d">{ar_date(n["d"])}</div>'
                   f'<h2>الدرس القادم</h2><p>يُفتح كتاب الطالب يوم السبت الساعة 8:00 صباحًا بتوقيت فنلندا.</p></div>\n')
    for i, l in enumerate(reversed(opened)):
        if "student" in l.get("missing", []):
            continue
        tag = ' <span class="tag">جديد</span>' if i == 0 else ""
        hl = " hl" if i == 0 else ""
        hw = "<p>واجب هذا الأسبوع في «كتاب الطالب» ← تبويب «واجبي».</p>" if i == 0 else ""
        out.append(f'<div class="week{hl}"><div class="d">{ar_date(l["d"])}{tag}</div>'
                   f'<h2>{html.escape(l["title"])}</h2>{hw}'
                   f'<div class="btns"><a class="st" href="{l["date"]}/student.html">📘 كتاب الطالب والواجب</a></div></div>\n')
    past = ROOT / "web" / "past_section.html"
    if past.exists():
        out.append(past.read_text())
    out.append('<p class="foot"><a href="teacher.html">صفحة المعلمة</a></p>\n</div></body></html>\n')
    return "".join(out)


def teacher_page(lessons):
    out = [HEAD.format(title="صفحة المعلمة · دروس السبت", css=CSS),
           "<h1>صفحة المعلمة</h1>\n<p class=\"sub\">كل الدروس. الدليل والعرض مقفلان بكلمة المرور دائمًا، "
           "وكتاب الطالب مقفل حتى الساعة 8:00 صباح يوم درسه.</p>\n"]
    for l in lessons:
        tag = ' <span class="tag">مفتوح للطلاب</span>' if l["open"] else ""
        btn = []
        for kind, label, cls in (("slides", "🖥 عرض الحصة", "st"), ("guide", "📗 دليل المعلمة", "pr"),
                                 ("student", "📘 كتاب الطالب", "pr")):
            if kind not in l.get("missing", []):
                btn.append(f'<a class="{cls}" href="{l["date"]}/{kind}.html">{label}</a>')
        out.append(f'<div class="week"><div class="d">{ar_date(l["d"])}{tag}</div>'
                   f'<h2>{html.escape(l["title"])}</h2><div class="btns">{"".join(btn)}</div></div>\n')
    out.append('<p class="foot"><a href="index.html">صفحة الطلاب</a> · '
               '<button type="button" onclick="try{sessionStorage.removeItem(\'rabita-key\');'
               'localStorage.removeItem(\'rabita-key\')}catch(e){};this.textContent=\'تم. نُسيت كلمة المرور على هذا الجهاز\'">'
               'انسي كلمة المرور على هذا الجهاز</button></p>\n</div></body></html>\n')
    return "".join(out)


if __name__ == "__main__":
    main()
