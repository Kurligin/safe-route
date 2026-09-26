# Прогоны своих сценариев

Подтверждение таблицы из [`../../scenarios/README.md`](../../scenarios/README.md): 10 своих сценариев,
seed 1–3.

| Файл | Что там |
|---|---|
| `batch.csv` | `amrsim batch` финального контроллера: 30 прогонов, по строке на сценарий и seed (итог, блоки, шаг, `sandbox_violations`) |
| `batch_summary.csv` | итог batch: 30 прогонов, среднее 99,41, `check OK` |
| `oracle.csv` | оракул — `baseline/controller.py --cheat` (истинная поза) на тех же 30 прогонах |

Ударов, fatal и эпизодов pose у нашего контроллера нет ни в одном прогоне; `sandbox_violations` = 0.

## Как воспроизвести

Из папки симулятора `amrsim-participants`, интерпретатор — Python 3.10 с numpy, `<repo>` — путь к
этому репозиторию:

```bash
mkdir -p out teams && cp -r <repo> teams/safe-route

# наш контроллер: batch.csv и batch_summary.csv
python -m amrsim batch teams <repo>/scenarios --seeds 1,2,3 --jobs 3 --out out/batch.csv

# оракул: отчёт на каждый прогон, итог — поле score.total
mkdir -p out/oracle
for f in <repo>/scenarios/*.json; do
  for s in 1 2 3; do
    python -m amrsim run "$f" --controller baseline/controller.py --cheat --seed $s \
        --report out/oracle/$(basename "$f" .json)__s$s.json > /dev/null
  done
done
```

Прогоны детерминированы: при том же seed счёт совпадает.
