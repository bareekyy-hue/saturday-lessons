"""Seal every lesson from /mnt/project-files into a clone of the lessons repo.
Usage: python3 seal_all.py /path/to/clone   (the clone must already have keys/public.pem)
Titles come from /mnt/project-files/site/index.html."""
import re, subprocess, sys, pathlib
R = pathlib.Path(sys.argv[1]); P = pathlib.Path("/mnt/project-files")
idx = (P / "site/index.html").read_text()
titles = {}
for m in re.finditer(r'<div class="week">(.*?)</div>\s*</div>', idx, re.S):
    h = re.search(r'href="([0-9-]+)/', m.group(1)); t = re.search(r'<h2>([^<]*)', m.group(1))
    if h and t and re.match(r"\d{4}-", h.group(1)): titles[h.group(1)] = t.group(1)
odd = {"2026-11-07": ("7-11", "-7-11"), "2026-11-14": ("14-11", "-14-11")}
for date, title in sorted(titles.items()):
    folder, suf = odd.get(date, (date, ""))
    d = P / folder
    args = ["python3", str(R / "tools/seal.py"), date, "--title", title]
    for k, n in (("guide", "دليل-المعلمة"), ("slides", "عرض-الحصة"), ("student", "كتاب-الطالب")):
        f = d / f"{n}{suf}.html"
        if f.exists(): args += ["--" + k, str(f)]
    subprocess.run(args, check=True)
