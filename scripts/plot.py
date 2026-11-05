#!/usr/bin/env python3
"""
results/results.csv -> results/plot.png + таблиця результатів (Markdown).
Таблиця також автоматично вставляється в README.md між мітками RESULTS.

    python3 -m venv ~/venv && ~/venv/bin/pip install matplotlib && ~/venv/bin/python scripts/plot.py
"""
import csv
import os
import re
import statistics
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

runs = defaultdict(list)
with open("results/results.csv", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["total_s"].strip():
            runs[(row["config"], int(row["workers"]))].append(float(row["total_s"]))
if ("sequential", 0) not in runs or len(runs) < 2:
    raise SystemExit("results/results.csv порожній - спочатку запусти scripts/bench.sh "
                     "або впиши TOTAL з output кожного job вручну")

seq = statistics.mean(runs[("sequential", 0)])
par = sorted((n, statistics.mean(v)) for (cfg, n), v in runs.items() if cfg == "parallel")
n_runs = max(len(v) for v in runs.values())

rows = ["| Конфігурація | Воркерів | Час, с | Прискорення S = T<sub>seq</sub> / T<sub>N</sub> "
        "| Ефективність E = S / N |",
        "|---|:---:|---:|---:|---:|",
        "| послідовно (лише master) | - | %.2f | 1.00 | - |" % seq]
for n, t in par:
    rows.append("| паралельно (PARCS) | %d | %.2f | %.2f | %.2f |" % (n, t, seq / t, seq / t / n))
table = "\n".join(rows) + "\n\n_Час - середнє з %d запуск(ів) кожної конфігурації._\n" % n_runs
print(table)
with open("results/table.md", "w", encoding="utf-8") as f:
    f.write(table)

if os.path.exists("README.md"):  # оновлюємо таблицю в README
    with open("README.md", encoding="utf-8") as f:
        readme = f.read()
    new = re.sub(r"(<!-- RESULTS:START -->\n).*?(<!-- RESULTS:END -->)",
                 lambda m: m.group(1) + table + m.group(2), readme, flags=re.S)
    if new != readme:
        with open("README.md", "w", encoding="utf-8") as f:
            f.write(new)
        print("README.md: таблицю оновлено")

ns, ts = [n for n, _ in par], [t for _, t in par]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
a1.plot(ns, ts, "o-", lw=2, label="PARCS, паралельно")
a1.axhline(seq, ls="--", c="gray", label="послідовно (%.1f с)" % seq)
for n, t in par:
    a1.annotate("%.1f" % t, (n, t), textcoords="offset points", xytext=(0, 8), ha="center")
a1.set(xlabel="кількість воркерів N", ylabel="час, с", title="Час виконання", xticks=ns)
a1.set_ylim(bottom=0, top=max(ts + [seq]) * 1.15)
a1.legend()
a1.grid(alpha=.3)

a2.plot(ns, [seq / t for t in ts], "o-", lw=2, label="фактичне")
a2.plot(ns, ns, ":", c="gray", label="ідеальне (лінійне)")
a2.set(xlabel="кількість воркерів N", ylabel="прискорення S, рази",
       title="Прискорення відносно послідовної версії", xticks=ns)
a2.set_ylim(bottom=0)
a2.legend()
a2.grid(alpha=.3)

fig.tight_layout()
fig.savefig("results/plot.png", dpi=150)
print("Збережено results/plot.png")
