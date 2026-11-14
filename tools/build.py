"""Build the site into _site/. Run by the GitHub job (needs TEACHER_PASSWORD).

- Teacher guide + slides: always locked with the teacher password.
- Student book: open from 08:00 Finland time on its lesson Saturday.
  * Regular lessons are published in advance with a JavaScript time gate (the page and the
    student index check the clock themselves), so they open on time even if no job runs.
  * Exam lessons ("exam": true in lessons.json) stay encrypted until a job runs after 08:00.
First run (no keys yet) creates the repo keys, locked with the teacher password.
Optional env NOW=YYYY-MM-DDTHH:MM (Finland time) for testing.
"""
import base64, datetime as dt, html, json, os, pathlib, re, shutil, sys
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
        l["ms"] = int(opens.timestamp() * 1000)
        # end of the lesson Saturday (Sunday 00:00 Finland time): from then on the teacher page
        # moves on to the next lesson
        nxt = d + dt.timedelta(days=1)
        l["end"] = int(dt.datetime(nxt.year, nxt.month, nxt.day, tzinfo=TZ).timestamp() * 1000)
        l["exam"] = bool(l.get("exam"))
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
            elif kind == "student" and not l["exam"]:
                (wd / "student.html").write_bytes(time_gate(page, l["ms"], d))
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


GATE = """<script id="time-gate">(function(){var O=%(ms)d;if(/[?&]preview\\b/.test(location.search)||Date.now()>=O)return;
document.write('<style id="gate-css">body>*:not(#gate){display:none!important}#gate{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;padding:16px;background:#f6f5f0;color:#1f2a24;font:18px/1.9 "Noto Naskh Arabic",serif;direction:rtl;text-align:center;z-index:2147483647}#gate *{background-image:none;text-shadow:none;box-shadow:none;border-bottom:0;-webkit-text-fill-color:currentColor;letter-spacing:normal;animation:none}#gate .gate-c{width:100%%;max-width:440px;background:#fff;border:1px solid #e4e1d7;border-radius:22px;padding:28px 24px}#gate h1{font:700 20px "Noto Kufi Arabic",sans-serif;color:#1f6b45;margin:10px 0 4px}#gate .gate-w{font:700 16px "Noto Kufi Arabic",sans-serif;color:#8a6114;margin:6px 0 2px}#gate p{margin:4px 0;color:#5c665f}#gate a{display:inline-block;margin-top:14px;color:#5c665f;font-size:15px}@media (prefers-color-scheme:dark){#gate{background:#141a17;color:#e9ede9}#gate .gate-c{background:#1c2420;border-color:#2b342f}#gate h1{color:#5fbf8a}#gate .gate-w{color:#d9ae5a}#gate p,#gate a{color:#9aa59e}}</style>');
function show(){if(document.getElementById("gate"))return;var g=document.createElement("div");g.id="gate";g.innerHTML='<div class="gate-c"><div style="font-size:40px;line-height:1">📘</div><h1>كتاب الطالب لم يُفتح بعد</h1><p>يُفتح هذا الدرس يوم</p><p class="gate-w">%(when)s · الساعة 8:00 صباحًا</p><p>بتوقيت فنلندا</p><a href="../index.html">الرجوع إلى قائمة الدروس</a></div>';document.body.insertBefore(g,document.body.firstChild)}
if(document.body)show();else document.addEventListener("DOMContentLoaded",show);
setTimeout(function(){location.reload()},Math.min(O-Date.now()+1500,2147000000));})();</script>"""


def time_gate(page: bytes, ms: int, d) -> bytes:
    """Add a script that hides the student book until `ms` (epoch ms) in the viewer's browser."""
    tag = (GATE % {"ms": ms, "when": ar_date(d)}).encode("utf-8")
    m = re.search(rb"<meta charset=[\"']?utf-8[\"']?\s*/?>", page, re.I) or re.search(rb"<head[^>]*>", page, re.I)
    if not m:
        return tag + page
    return page[:m.end()] + b"\n" + tag + page[m.end():]


CSS = """:root{--bg:#f6f5f0;--ink:#1f2a24;--muted:#5c665f;--line:#e4e1d7;--green:#1f6b45;--card:#fff;--gold:#8a6114;--soft:#f1ede2;--new:#e1f4e7;--btn-ink:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#141a17;--ink:#e9ede9;--muted:#9aa59e;--line:#2b342f;--green:#5fbf8a;--card:#1c2420;--gold:#d9ae5a;--soft:#26302b;--new:#1f3a2b;--btn-ink:#0f1a14}}
*{box-sizing:border-box}
[hidden]{display:none!important}
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


INDEX_JS = """<script>(function(){
// Regular lessons are listed in advance (hidden) and shown here once their time comes,
// so the list updates at 08:00 even if no build runs. Exams appear only after a build opens them.
var now=Date.now(),first=null,next=null;
document.querySelectorAll(".week[data-open]").forEach(function(w){
  if(now>=+w.getAttribute("data-open"))w.hidden=false;
  if(!w.hidden&&!first)first=w;
});
if(first){
  first.classList.add("hl");
  var t=document.createElement("span");t.className="tag";t.textContent="جديد";
  first.querySelector(".d").appendChild(document.createTextNode(" "));first.querySelector(".d").appendChild(t);
  var p=document.createElement("p");p.textContent="واجب هذا الأسبوع في «كتاب الطالب» ← تبويب «واجبي».";
  first.querySelector("h2").after(p);
}
document.querySelectorAll("[data-next]").forEach(function(n){
  if(!next&&now<+n.getAttribute("data-next"))next=n;
});
if(next){var c=document.getElementById("next");c.querySelector(".d").textContent=next.getAttribute("data-when");c.hidden=false;
  setTimeout(function(){location.reload()},Math.min(+next.getAttribute("data-next")-now+1500,2147000000));}
})();</script>
"""


def index_page(lessons, now):
    out = [HEAD.format(title="دروس السبت · مدرسة الرابطة", css=CSS),
           "<h1>دروس السبت</h1>\n<p class=\"sub\">مدرسة الرابطة الإسلامية · الدرس الجديد في الأعلى دائمًا</p>\n"]
    # all opening times, oldest first, for the "next lesson" card
    out.append("".join(f'<i hidden data-next="{l["ms"]}" data-when="{ar_date(l["d"])}"></i>' for l in lessons) + "\n")
    out.append('<div class="week" id="next" hidden><div class="d"></div>'
               '<h2>الدرس القادم</h2><p>يُفتح كتاب الطالب يوم السبت الساعة 8:00 صباحًا بتوقيت فنلندا.</p></div>\n')
    for l in reversed(lessons):
        if "student" in l.get("missing", []) or (l["exam"] and not l["open"]):
            continue
        hidden = "" if l["open"] else " hidden"
        out.append(f'<div class="week" data-open="{l["ms"]}"{hidden}><div class="d">{ar_date(l["d"])}</div>'
                   f'<h2>{html.escape(l["title"])}</h2>'
                   f'<div class="btns"><a class="st" href="{l["date"]}/student.html">📘 كتاب الطالب والواجب</a></div></div>\n')
    out.append(INDEX_JS)
    past = ROOT / "web" / "past_section.html"
    if past.exists():
        out.append(past.read_text())
    out.append('<p class="foot"><a href="teacher.html">صفحة المعلمة</a></p>\n</div></body></html>\n')
    return "".join(out)


TEACHER_JS = """<h3 id="h-past" hidden>الدروس السابقة</h3><div id="past"></div>
<h3 id="h-later" hidden>الدروس اللاحقة</h3><div id="later"></div>
<script>(function(){
// Order by the clock, so it changes by itself without a build: the lesson of the coming
// Saturday first (it stays first through its Saturday; from Sunday the next one takes over),
// then past lessons (newest first), then the later ones.
var now=Date.now(),cur=null,past=[],later=[];
document.querySelectorAll(".tag[data-open]").forEach(function(t){if(now>=+t.getAttribute("data-open"))t.hidden=false});
document.querySelectorAll(".week[data-end]").forEach(function(w){
  var end=+w.getAttribute("data-end");
  if(now>=end)past.push(w);else if(!cur)cur=w;else later.push(w);
});
var top=document.getElementById("now");
if(cur){
  cur.classList.add("hl");
  var today=now>=+cur.getAttribute("data-end")-864e5;
  document.getElementById("h-now").textContent=today?"درس اليوم":"درس الحصة القادمة";
  document.getElementById("h-now").hidden=false;top.appendChild(cur);
  setTimeout(function(){location.reload()},Math.min(+cur.getAttribute("data-end")-now+1500,2147000000));
}
past.reverse().forEach(function(w){document.getElementById("past").appendChild(w)});
later.forEach(function(w){document.getElementById("later").appendChild(w)});
document.getElementById("h-past").hidden=!past.length;
document.getElementById("h-later").hidden=!later.length;
})();</script>
"""


def teacher_page(lessons):
    out = [HEAD.format(title="صفحة المعلمة · دروس السبت", css=CSS),
           "<h1>صفحة المعلمة</h1>\n<p class=\"sub\">الدليل والعرض مقفلان بكلمة المرور دائمًا، "
           "وكتاب الطالب يُفتح للطلاب الساعة 8:00 صباح يوم درسه (الاختبارات مشفّرة حتى ذلك الوقت).</p>\n"
           '<h3 id="h-now" style="color:var(--green);font-size:18px" hidden></h3><div id="now"></div>\n']
    for l in lessons:
        if l["open"]:
            tag = ' <span class="tag">مفتوح للطلاب</span>'
        elif not l["exam"]:  # opens by itself in the browser
            tag = f' <span class="tag" data-open="{l["ms"]}" hidden>مفتوح للطلاب</span>'
        else:
            tag = ' <span class="tag">اختبار · يُفتح بعد تشغيل النشر</span>'
        btn = []
        for kind, label, cls in (("slides", "🖥 عرض الحصة", "st"), ("guide", "📗 دليل المعلمة", "pr"),
                                 ("student", "📘 كتاب الطالب", "pr")):
            if kind not in l.get("missing", []):
                q = "?preview" if kind == "student" and not l["open"] and not l["exam"] else ""
                btn.append(f'<a class="{cls}" href="{l["date"]}/{kind}.html{q}">{label}</a>')
        out.append(f'<div class="week" data-end="{l["end"]}"><div class="d">{ar_date(l["d"])}{tag}</div>'
                   f'<h2>{html.escape(l["title"])}</h2><div class="btns">{"".join(btn)}</div></div>\n')
    out.append(TEACHER_JS)
    out.append('<p class="foot"><a href="index.html">صفحة الطلاب</a> · '
               '<button type="button" onclick="try{sessionStorage.removeItem(\'rabita-key\');'
               'localStorage.removeItem(\'rabita-key\')}catch(e){};this.textContent=\'تم. نُسيت كلمة المرور على هذا الجهاز\'">'
               'انسي كلمة المرور على هذا الجهاز</button></p>\n</div></body></html>\n')
    return "".join(out)


if __name__ == "__main__":
    main()
