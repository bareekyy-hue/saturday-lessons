# دروس السبت · مدرسة الرابطة

Static lesson site published with GitHub Pages by the **Publish lessons** workflow.

- **Teacher guide and slides** are always encrypted (AES-256-GCM, key from the teacher password with PBKDF2-SHA256, 600k rounds) and open in the browser after the password is typed.
- **Student books** open at **08:00 Finland time** on their lesson Saturday. Past lessons are open.
  - **Regular lessons** are published in advance with a JavaScript time gate: the student book and the student index check the clock in the browser, so they open on time even if GitHub skips the scheduled run. (A curious student could see them early by changing the device clock or reading the page source; this was accepted.)
  - **Exams** (`"exam": true` in `lessons.json`) stay encrypted the same way as the teacher pages until a run after 08:00 publishes them. On exam Saturdays, check that the run happened, or start **Publish lessons** by hand (Actions → Run workflow).
  - The teacher page links regular lessons with `?preview`, which skips the time gate.
- Lesson files in `sources/` are sealed with `keys/public.pem`. Only the workflow can open them: its private key (`keys/private.lock`) is locked with the teacher password.
- The password lives only in the repository secret `TEACHER_PASSWORD`. It is never stored in the files.

Files in `public/` (the past lessons before 7/11) are copied to the site as they are, open to everyone, and `web/past_section.html` is added to the bottom of the student page.

## Add or update a lesson

```
pip install cryptography
python tools/seal.py 2026-11-14 --title "..." --guide guide.html --slides slides.html --student student.html
git add sources lessons.json && git commit -m "Add lesson" && git push
```

## Changing the password

The keys are locked with the current password, so changing the `TEACHER_PASSWORD` secret alone breaks the build. To change it, delete `keys/`, set the new secret, run the workflow once (it makes new keys), then seal all lessons again.
