# -*- coding: utf-8 -*-
"""
PARCS-Python | ЛР1 | Тема 4.1 «Паралельна обробка файлів (підрахунок частоти слів)»
ПАРАЛЕЛЬНА версія.

Input file : ZIP-архів з .txt файлами (UTF-8).
Output file: обсяг даних, час кожного етапу, навантаження воркерів, топ слів.

Схема map-reduce:
  1. SPLIT  (master)  - читає архів і ділить файли між N воркерами так, щоб обсяг
                        тексту в кожного був майже однаковий (жадібний алгоритм LPT);
  2. MAP    (workers) - кожен воркер паралельно рахує частоти слів у своїх файлах;
  3. REDUCE (master)  - зливає N частотних словників в один і будує топ слів.

Код сумісний з Python 2.7 (саме він у Docker-образі PARCS) і з Python 3.
"""
from __future__ import division, print_function

import base64
import heapq
import io
import re
import time
import zipfile

import Pyro4
from Pyro4 import expose

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


# ---------------------------------------------------------------- допоміжне
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


def merge(total, counts):
    """REDUCE: додає частотний словник одного воркера до загального."""
    get = total.get
    for w, c in counts.items():
        total[w] = get(w, 0) + c


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


def split_files(files, k):
    """SPLIT: ділить файли на k частин з майже однаковим сумарним розміром.
    Жадібний LPT: файли від найбільшого до найменшого, кожен -> найменш
    завантаженому воркеру."""
    parts = [[] for _ in range(k)]
    sizes = [0] * k
    for name, data in sorted(files, key=lambda f: len(f[1]), reverse=True):
        i = sizes.index(min(sizes))
        parts[i].append((name, data))
        sizes[i] += len(data)
    return parts


def result_of(call):
    """Асинхронний виклик Pyro4 повертає future (.value чекає на відповідь)."""
    return call if isinstance(call, (tuple, list)) else call.value


def host_of(proxy):
    uri = getattr(proxy, "_pyroUri", None)
    return getattr(uri, "host", "?")


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


# ---------------------------------------------------------------- PARCS
class Solver:
    def __init__(self, workers=None, input_file_name=None, output_file_name=None):
        self.input_file_name = input_file_name
        self.output_file_name = output_file_name
        self.workers = workers

    def solve(self):
        n = len(self.workers)
        print("Job started, workers: %d" % n)
        t0 = time.time()

        # 1. SPLIT (master)
        files = read_files(self.input_file_name)
        parts = split_files(files, n)
        t1 = time.time()

        # Серіалізатор: marshal замість serpent (за замовчуванням у Pyro4).
        # У Python 2.7 serpent передає bytes як latin-1 unicode (ламає UTF-8)
        # і в рази повільніший на великих текстах і словниках.
        use_marshal = "marshal" in Pyro4.config.SERIALIZERS_ACCEPTED
        if not use_marshal:  # запасний варіант: байти як base64-рядки
            parts = [[(name, base64.b64encode(data).decode("ascii")) for name, data in p]
                     for p in parts]
        old_serializer = Pyro4.config.SERIALIZER
        if use_marshal:
            Pyro4.config.SERIALIZER = "marshal"
        try:
            # 2. MAP (workers): проксі воркерів у PARCS асинхронні -> усі виклики
            #    стартують одночасно, кожен одразу повертає future
            calls = [w.count_files(p, not use_marshal) for w, p in zip(self.workers, parts)]
            results = [result_of(c) for c in calls]  # чекаємо, поки завершать усі
        finally:
            Pyro4.config.SERIALIZER = old_serializer
        t2 = time.time()

        # 3. REDUCE (master)
        total = {}
        for r in results:
            merge(total, r[0])
        t3 = time.time()

        busiest = max(r[4] for r in results)
        extra = [u"", u"WORKERS (serializer: %s)" % ("marshal" if use_marshal else "serpent+base64")]
        for w, r in zip(self.workers, results):
            extra.append(u"  %-15s %4d files %8.1f MB %13s words   compute %7.3f s"
                         % (host_of(w), r[1], r[2] / 1e6, "{:,}".format(r[3]), r[4]))
        extra.append(u"  transfer + RPC overhead ~ %.3f s (map time - busiest worker)"
                     % max(0.0, (t2 - t1) - busiest))

        write_report(self.output_file_name,
                     u"PARCS word count | PARALLEL | workers: %d" % n,
                     total, sum(r[2] for r in results), sum(r[3] for r in results), len(files),
                     [("split (master)", t1 - t0), ("map (workers)", t2 - t1),
                      ("reduce (master)", t3 - t2)], extra)
        print("Job finished in %.3f s" % (t3 - t0))

    @staticmethod
    @expose
    def count_files(files, b64=False):
        """MAP (виконується на воркері): частоти слів у своїй частині файлів."""
        t = time.time()
        counts = {}
        n_words = n_bytes = 0
        for name, data in files:
            if b64:
                data = base64.b64decode(data)
            n_bytes += len(data)
            n_words += count_words(data, counts)
        return counts, len(files), n_bytes, n_words, time.time() - t
