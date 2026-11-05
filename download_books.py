#!/usr/bin/env python3
"""
Готує вхідний файл для PARCS: input.zip з .txt файлами.

За замовчуванням завантажує ~60 класичних книжок з Project Gutenberg (public domain),
прибирає службовий текст Gutenberg і пакує в архів стільки копій, щоб набрати
~--target-mb мегабайт тексту (більше даних = виразніше прискорення на графіку).

    python3 scripts/download_books.py                 # ~140 MB тексту -> input.zip
    python3 scripts/download_books.py --target-mb 60  # менший архів для швидкої перевірки
    python3 scripts/download_books.py --synthetic     # без інтернету: згенерований текст
"""
import argparse
import itertools
import os
import random
import re
import time
import urllib.request
import zipfile

BOOK_IDS = [
    1342, 84, 11, 2701, 1661, 98, 2600, 1400, 345, 174, 76, 74, 1184, 135, 5200,
    2554, 28054, 4300, 996, 1260, 768, 64317, 100, 10, 219, 43, 120, 36, 35, 1232,
    2591, 158, 161, 1399, 6130, 1727, 8800, 205, 730, 766, 46, 145, 244, 2852, 55,
    16, 1257, 2814, 25344, 215, 910, 3207, 1497, 4363, 1998, 3600, 580, 1259, 4217,
    16328, 2680, 1513,
]
URLS = ["https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt",
        "https://www.gutenberg.org/ebooks/{id}.txt.utf-8"]
START = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK[^\n]*\n", re.I)
END = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", re.I)


def download(book_id):
    err = None
    for url in URLS:
        try:
            req = urllib.request.Request(url.format(id=book_id),
                                         headers={"User-Agent": "parcs-wordcount-lab/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception as e:  # пробуємо наступне дзеркало
            err = e
    raise err


def clean(text):
    """Залишає лише текст книжки (без ліцензії Gutenberg на початку й у кінці)."""
    m = START.search(text)
    if m:
        text = text[m.end():]
    m = END.search(text)
    if m:
        text = text[:m.start()]
    return text.strip() + "\n"


def file_name(book_id, text):
    m = re.search(r"^Title:\s*(.+)$", text, re.M)
    slug = re.sub(r"[^a-z0-9]+", "_", (m.group(1) if m else "book").lower()).strip("_")[:40]
    return "%05d_%s.txt" % (book_id, slug or "book")


def download_books(out):
    for i, book_id in enumerate(BOOK_IDS, 1):
        if any(f.startswith("%05d_" % book_id) for f in os.listdir(out)):
            continue  # уже завантажено раніше
        try:
            raw = download(book_id)
            name = file_name(book_id, raw)
            with open(os.path.join(out, name), "w", encoding="utf-8") as f:
                f.write(clean(raw))
            print("[%2d/%d] ok   %s" % (i, len(BOOK_IDS), name))
        except Exception as e:
            print("[%2d/%d] skip %d (%s)" % (i, len(BOOK_IDS), book_id, e))
        time.sleep(1)  # чемно до серверів Gutenberg


def make_synthetic(out, total_mb, n_files=60):
    """Псевдо-англійський текст із частотами за законом Ципфа (якщо немає інтернету)."""
    rnd = random.Random(42)
    common = ("the and of to a in he that was it his i with her you had as for is she "
              "not at but on him be my have they by all which said so from this were "
              "when one me there would what no their if out we an up into could time "
              "man about then them some more very great over before little who after").split()
    syll = ["ka", "lo", "mi", "ne", "ta", "ri", "so", "va", "de", "an", "er", "in",
            "th", "ou", "st", "ch", "pe", "li", "ar", "or"]
    vocab = common + ["".join(rnd.choice(syll) for _ in range(rnd.randint(2, 4)))
                      for _ in range(50000)]
    cum = list(itertools.accumulate(1.0 / (r + 1) for r in range(len(vocab))))
    per_file = total_mb * 1e6 / n_files
    for k in range(n_files):
        lines, size = [], 0
        while size < per_file:
            line = " ".join(rnd.choices(vocab, cum_weights=cum, k=14)).capitalize() + ".\n"
            lines.append(line)
            size += len(line)
        with open(os.path.join(out, "synthetic_%02d.txt" % k), "w", encoding="utf-8") as f:
            f.write("".join(lines))
    print("generated %d synthetic files" % n_files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="books", help="тека для .txt файлів")
    ap.add_argument("--zip", default="input.zip", help="вихідний архів")
    ap.add_argument("--target-mb", type=float, default=140,
                    help="скільки МБ тексту має бути в архіві (книжки дублюються)")
    ap.add_argument("--synthetic", action="store_true", help="згенерувати текст замість завантаження")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    if args.synthetic:
        make_synthetic(args.out, args.target_mb)
    else:
        download_books(args.out)

    files = sorted(f for f in os.listdir(args.out) if f.endswith(".txt"))
    if not files:
        raise SystemExit("Немає жодного .txt - спробуй ще раз або запусти з --synthetic")
    size = sum(os.path.getsize(os.path.join(args.out, f)) for f in files)
    repeat = max(1, int(round(args.target_mb * 1e6 / size)))

    with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED) as z:
        for k in range(repeat):
            for f in files:
                arc = f if k == 0 else f.replace(".txt", "_copy%d.txt" % (k + 1))
                z.write(os.path.join(args.out, f), arc)
    print("\n%s: %d files (%d unique x %d copies), %.1f MB of text, archive %.1f MB"
          % (args.zip, len(files) * repeat, len(files), repeat,
             size * repeat / 1e6, os.path.getsize(args.zip) / 1e6))


if __name__ == "__main__":
    main()
