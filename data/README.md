# Corpus — The Unofficial Guide (ASU CS required courses)

**Domain:** Student experiences with the courses ASU Computer Science (BS)
majors are *required* to take — CSE core + the math, stats, logic, and
lab-science requirements (MAT 265/266/243/343, CSE 259, IEE 380, PHY).

**Focus is the course, not the professor.** We collect by *course*: what the
class is actually like to take — workload, exams, projects, whether it's a
weed-out. Professor mentions inside those threads are a bonus signal, not the
organizing principle. (We still keep some professor-level reviews in `rmp/`
for cross-reference, but the corpus is course-centric.)

Raw collected documents live here, organized by source type. The ingestion
pipeline reads from these subfolders. **Save documents by hand** (browser →
save file) so the corpus is reproducible and offline — live pages can change
or get deleted before the evaluation step.

## Folder layout

| Folder | What goes here | Save as | Why this format |
|--------|----------------|---------|-----------------|
| `reddit/`    | r/ASU threads about profs/courses | `.json` (the `.json` trick) | clean structured data + free metadata (author, score, date) |
| `rmp/`       | Rate My Professors — one file per **professor** | `.txt` / `.md` | answers "which prof is best/clearest/worth retaking" |
| `pdf/`       | Natively-PDF docs (degree checksheet) | `.pdf` | parsed later with **pdfplumber** |

### The Reddit `.json` trick
Append `.json` to any public thread URL, open in browser, save the page:
```
https://www.reddit.com/r/ASU/comments/<id>/<slug>/   →   …/<slug>/.json
```
You get the post + all comments as structured data — no nav/ads/vote-button
cleanup, and you keep `author`, `score`, and `created_utc` (useful for the
metadata-filtering / "reviews from the past year" stretch features).

## Naming convention
Keep the source + an identifier in the filename so attribution is easy:
- `reddit/`    → `reddit_asu_<course>.json`       e.g. `reddit_asu_cse240.json`
                 (multiple threads for one course: add a suffix, e.g.
                 `reddit_asu_cse240_b.json`)
- `rmp/`       → `rmp_<lastname>_<dept>.txt`       e.g. `rmp_richa_cse.txt`
- `pdf/`       → descriptive name                  e.g. `asu_cs_degree_checksheet.pdf`

---

## Collection checklist

Goal: **≥10 documents**, varied enough to answer different questions
(best teacher · hardest course · worth-taking-again · which calc prof).

### Reddit — r/ASU (you collect these manually; aim for 10+)
Search r/ASU **by course code** — that surfaces the long experience threads.
Save the best ones via the `.json` trick. One file per thread.
- [ ] reddit_asu_cse110.json
- [ ] reddit_asu_cse205.json
- [ ] reddit_asu_cse240.json
- [ ] reddit_asu_cse310.json
- [ ] reddit_asu_cse259.json
- [ ] reddit_asu_mat243.json
- [ ] reddit_asu_mat265.json
- [ ] reddit_asu_mat266.json
- [ ] reddit_asu_mat343.json
- [ ] reddit_asu_iee380.json
- [ ] reddit_asu_____________.json (add more as you find good threads)

### Rate My Professors — `rmp/` (professor-level)
CS:
- [ ] Andrea Richa — https://www.ratemyprofessors.com/professor/1288646
- [ ] Phillip Miller — https://www.ratemyprofessors.com/professor/1834878
- [ ] Connor Nelson — https://www.ratemyprofessors.com/professor/2849863
- [ ] Chris Bryan — https://www.ratemyprofessors.com/professor/2463568
- [ ] Adil Ahmad — https://www.ratemyprofessors.com/professor/2810322
- [ ] Hasan Davulcu — https://www.ratemyprofessors.com/professor/573489
- [ ] Stephen Yau — https://www.ratemyprofessors.com/professor/636627
- [ ] James Gordon — https://www.ratemyprofessors.com/professor/2844149

Math / stats (required MAT + IEE courses):
- [ ] Franklin Yu (MAT 265) — https://www.ratemyprofessors.com/professor/2392152
- [ ] Joe Rody (MAT 265) — https://www.ratemyprofessors.com/professor/617326
- [ ] Hedvig Mohacsy (MAT 265) — https://www.ratemyprofessors.com/professor/477524
- [ ] Linda Chattin (IEE 380) — https://www.ratemyprofessors.com/professor/304028

### PDF — `pdf/` (native PDF, parsed with pdfplumber)
- [ ] ASU CS BS degree requirements / checksheet —
      https://scai.engineering.asu.edu/computer-science-bs/degree-requirements/
      (use this to confirm which courses/profs are in scope; the checksheet
      itself is a real PDF you can include)
