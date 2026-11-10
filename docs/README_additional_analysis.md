# Дополнительный анализ Red Wings

Из корня репозитория, с Python 3.10+ и стандартной библиотекой:

```bash
python -B calc/robustness_plus.py
python -B calc/economics_dashboard.py
```

| Что открывать в `out/` | Содержимое |
|---|---|
| [robustness_dashboard.html](../out/robustness_dashboard.html) | График частот топ-3 по 1 000 прогонам |
| [monte_carlo_summary.csv](../out/monte_carlo_summary.csv) | Частота топ-3, среднее место и число попаданий на каждое из 12 мест |
| [missing_sensitivity.csv](../out/missing_sensitivity.csv) | Места и их изменения при трёх нормализованных оценках пропусков для каждого набора весов |
| [robustness_plus.md](../out/robustness_plus.md) | Тройки лидеров и места городов с пропусками |
| [economics_dashboard.html](../out/economics_dashboard.html) | Сравнение хаба и прямых рейсов по трём показателям за 2027–2028 годы |
| [economics_summary.csv](../out/economics_summary.csv) | Агрегаты по двум гипотезам, двум годам и двум сценариям |

Скачайте HTML и откройте в браузере. Сервер, интернет и дополнительные
библиотеки для просмотра не нужны. Для повторной генерации рейтинга
используются `data/processed/longlist.csv` и `calc/weights*.yaml`.
Для дашборда используются `out/economics_results.csv` и маршрутные ключи
из `data/processed/route_inputs.csv`. После согласованного изменения
экономических входов сначала запустите `python calc/economics.py`,
чтобы обновить исходный CSV модели, затем генератор дашборда.

Формулы и допущения разобраны в [методологии](model_methodology.md).

## Уточнение кейса T1

- [Стратегия к цели №2](strategy_t1.md) — масштаб разрыва, маршрутный пилот,
  цифровой сервис и условия расширения.
- [Офлайн-демо](../out/strategy_t1.html) — калькулятор мощности, результаты
  маршрутной модели и демонстрация экрана «Моя поездка».

После обновления исходных результатов экономики пересоберите демо командой
`python -B calc/strategy_t1.py`.
