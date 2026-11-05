#!/usr/bin/env bash
# Автоматичний бенчмарк через REST API PARCS (те саме, що кнопки у веб-інтерфейсі):
#   послідовна версія + паралельна на N = 1..W воркерів, кожна конфігурація R разів.
# Результати: results/results.csv (для таблиці й графіка) і results/out/*.txt (виводи job-ів).
#
#   bash scripts/bench.sh <ЗОВНІШНІЙ_IP_MASTER> [input.zip] [повторів, за замовчуванням 3]
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: bash scripts/bench.sh MASTER_EXTERNAL_IP [input.zip] [repeats]"; exit 1; }
M="http://$1:8080"
INPUT="${2:-input.zip}"
R="${3:-3}"
cd "$(dirname "$0")/.."
[ -f "$INPUT" ] || { echo "Немає $INPUT - спочатку: python3 scripts/download_books.py"; exit 1; }
mkdir -p results/out
CSV=results/results.csv

IDS=($(curl -sf "$M/api/worker" | python3 -c 'import sys, json
print(" ".join(str(w["id"]) for w in sorted(json.load(sys.stdin)["workers"], key=lambda w: w["id"])))'))
W=${#IDS[@]}
[ "$W" -ge 1 ] || { echo "На $M не зареєстровано жодного воркера"; exit 1; }
echo "master: $M | workers: $W | input: $INPUT | repeats: $R"

use_workers() {  # залишити увімкненими перші k воркерів, решту вимкнути
  local k=$1 i s
  for i in "${!IDS[@]}"; do
    if [ "$i" -lt "$k" ]; then s=enable; else s=disable; fi
    curl -sf -o /dev/null -X POST "$M/api/worker/${IDS[$i]}/$s"
  done
}

next_job_id() {  # id нового job = кількість уже створених job-ів
  local id=0
  while curl -sf -o /dev/null "$M/api/job/$id/solution"; do id=$((id + 1)); done
  echo "$id"
}

run_job() {  # run_job <name> <solver.py>  -> друкує шлях до output
  local name=$1 solver=$2 id code out
  id=$(next_job_id)
  out="results/out/$name.txt"
  curl -sf -o /dev/null -F "job_name=$name" -F "solution_file=@$solver" \
       -F "input_file=@$INPUT" "$M/api/job"
  while true; do  # 400 = ще виконується, 200 = готово, інше = помилка
    code=$(curl -s -o "$out" -w '%{http_code}' "$M/api/job/$id/output")
    [ "$code" = 200 ] && break
    if [ "$code" != 400 ]; then
      rm -f "$out"; echo "job #$id ($name) завершився з помилкою, деталі: $M/jobs" >&2; return 1
    fi
    sleep 1
  done
  echo "$out"
}

value() { awk -v k="$1" 'index($0, k) { print $NF; exit }' "$2"; }  # value <мітка> <файл>

echo "config,workers,run,total_s,map_s" > "$CSV"
for r in $(seq 1 "$R"); do
  use_workers 1  # PARCS запускає job, лише якщо увімкнено хоча б одного воркера
  out=$(run_job "seq_run$r" solver_seq.py)
  t=$(value TOTAL "$out")
  echo "sequential,0,$r,$t," >> "$CSV"
  echo "run $r/$R: sequential            total $t s"
  for k in $(seq 1 "$W"); do
    use_workers "$k"
    out=$(run_job "par_n${k}_run$r" solver.py)
    t=$(value TOTAL "$out"); mt=$(value "map (workers)" "$out")
    echo "parallel,$k,$r,$t,$mt" >> "$CSV"
    echo "run $r/$R: parallel, $k worker(s)  total $t s (map $mt s)"
  done
done
use_workers "$W"  # повертаємо всіх воркерів
echo "Готово: $CSV. Далі: python3 scripts/plot.py"
