# -*- coding: utf-8 -*-
"""
PARCS-Python | ЛР1 | Тема 4.1 «Паралельна обробка файлів (підрахунок частоти слів)»
ПОСЛІДОВНА версія (baseline для порівняння).

Той самий підрахунок, що й у solver.py, але всі файли обробляє master в одному
потоці, без воркерів. Вхід і формат виходу такі самі, як у solver.py.
Допоміжні функції продубльовано навмисно: PARCS приймає рішення одним файлом.
"""
from __future__ import division, print_function

import heapq
import io
import re
import time
import zipfile

TOP_N = 30

# слово = літери будь-якої мови; апостроф усередині слова дозволено (don't, п'ять)
WORD_RE = re.compile(u"[^\\W\\d_]+(?:'[^\\W\\d_]+)*", re.UNICODE)

STOP_WORDS = set(u"""
a about after all also am an and any are as at be been but by can could did do
does for from had has have he her him his how i if in into is it its just me
more my no not now of on one only or other our out over said she so some than
that the their them then there these they this to up upon us very was we were
what when which who will with would you your
""".split())


def count_words(text, counts):
    """Додає частоти слів тексту до словника counts; повертає кількість слів."""
    if isinstance(text, bytes):
        text = text.decode("utf-8", "ignore")
    # типографський (\u2019) і український (\u02bc) апостроф -> звичайний '
    text = text.lower().replace(u"\u2019", u"'").replace(u"\u02bc", u"'")
    words = WORD_RE.findall(text)
    get = counts.get
    for w in words:
        counts[w] = get(w, 0) + 1
    return len(words)


def read_files(path):
    """Читає всі .txt з ZIP-архіву -> список (ім'я, байти)."""
    if not zipfile.is_zipfile(path):
        raise ValueError("Input file must be a ZIP archive with .txt files")
    with zipfile.ZipFile(path) as z:
        files = [(n, z.read(n)) for n in z.namelist()
                 if n.lower().endswith(".txt")
                 and not n.startswith("__MACOSX/") and "/._" not in "/" + n]
    if not files:
        raise ValueError("No .txt files found in the ZIP archive")
    return files


def top_words(counts, n, skip=()):
    return heapq.nlargest(n, ((c, w) for w, c in counts.items() if w not in skip))


def write_report(path, header, counts, n_bytes, n_words, n_files, timings, extra=()):
    num = "{:,}".format
    lines = [header,
             u"files: %d | text: %.1f MB | words: %s | unique words: %s"
             % (n_files, n_bytes / 1e6, num(n_words), num(len(counts))),
             u"", u"TIME, s"]
    for name, sec in timings:
        lines.append(u"  %-22s %8.3f" % (name, sec))
    lines.append(u"  %-22s %8.3f" % ("TOTAL", sum(s for _, s in timings)))
    lines.extend(extra)
    for title, skip in ((u"TOP-%d WORDS" % TOP_N, ()),
                        (u"TOP-%d WORDS WITHOUT STOP-WORDS" % TOP_N, STOP_WORDS)):
        lines += [u"", title]
        for i, (c, w) in enumerate(top_words(counts, TOP_N, skip), 1):
            lines.append(u"  %2d. %-16s %s" % (i, w, num(c)))
    with io.open(path, "w", encoding="utf-8") as f:
        f.write(u"\n".join(lines) + u"\n")


class Solver:
    def __init__(self, workers=None, input_file_name=None, output_file_name=None):
        self.input_file_name = input_file_name
        self.output_file_name = output_file_name
        self.workers = workers  # не використовуються

    def solve(self):
        print("Sequential job started")
        t0 = time.time()
        files = read_files(self.input_file_name)
        t1 = time.time()

        counts = {}
        n_words = 0
        for name, data in files:
            n_words += count_words(data, counts)
        t2 = time.time()

        write_report(self.output_file_name,
                     u"PARCS word count | SEQUENTIAL (master only)",
                     counts, sum(len(d) for _, d in files), n_words, len(files),
                     [("read (master)", t1 - t0), ("count (master)", t2 - t1)])
        print("Job finished in %.3f s" % (t2 - t0))
