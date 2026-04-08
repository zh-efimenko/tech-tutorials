# Программа обучения ClickHouse

## Цель

Освоить ClickHouse на уровне, достаточном для внедрения в проект: проектирование схемы данных для аналитики, написание эффективных запросов, интеграция со Spring Boot 3 + Java 25 + Gradle.

## Требования

- Docker Desktop (compose.yml в корне проекта)
- Java 25, Spring Boot 3.x, Gradle (wrapper)
- Базовые знания SQL

## Запуск окружения

```bash
docker compose up -d
# HTTP-интерфейс: http://localhost:8123
# Подключение через CLI:
docker exec -it clickhouse-local clickhouse-client --user default --password clickhouse
```

---

## Уроки

| #  | Тема | Папка | Описание |
|----|------|-------|----------|
| 1  | Архитектура и основы | `01_architecture_basics/` | Колоночное хранение, архитектура ClickHouse, первое подключение |
| 2  | Типы данных и создание таблиц | `02_data_types_tables/` | Система типов, MergeTree, создание первых таблиц |
| 3  | Загрузка данных | `03_data_loading/` | INSERT, форматы данных (CSV, JSON, TSV), batch-вставка |
| 4  | SELECT и агрегации | `04_select_aggregations/` | Фильтрация, GROUP BY, агрегатные функции, ORDER BY |
| 5  | Движки таблиц (MergeTree family) | `05_mergetree_engines/` | ReplacingMergeTree, AggregatingMergeTree, SummingMergeTree |
| 6  | Материализованные представления | `06_materialized_views/` | Автоматическая агрегация, пайплайны данных |
| 7  | Оптимизация производительности | `07_performance_optimization/` | Партиционирование, индексы, проекции, EXPLAIN |
| 8  | Интеграция с Spring Boot | `08_spring_boot_integration/` | JDBC-драйвер, Spring Data, конфигурация, репозитории |
| 9  | Аналитические функции | `09_analytical_functions/` | Оконные функции, массивы, словари, аппроксимации |
| 10 | Дашборды и production | `10_dashboards_production/` | Grafana, мониторинг, бэкапы, best practices |
| 11 | Кластер: репликация, миграции и Spring Boot | `11_cluster_replication/` | Настройка кластера, ClickHouse Keeper, ReplicatedMergeTree, Flyway для кластера, конфигурация Gradle и Spring Boot |

---

## Рекомендуемый порядок

Уроки выстроены последовательно — каждый следующий опирается на знания предыдущего. Рекомендуется проходить строго по порядку и выполнять все практические задания в `clickhouse-client`.