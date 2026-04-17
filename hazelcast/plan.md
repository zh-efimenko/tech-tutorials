# Программа обучения: Hazelcast

## Цель

Научиться использовать Hazelcast как распределённый In-Memory Data Grid в Java/Spring Boot приложениях — от локальной настройки до production-эксплуатации в Kubernetes.

## Требования

- Java 17+
- Spring Boot 3.x
- Gradle или Maven
- Docker и Docker Compose (для запуска Hazelcast-сервера локально)
- Базовое понимание распределённых систем
- Опыт работы с Spring Boot

## Запуск окружения

```bash
# Запуск Hazelcast-сервера в Docker
docker run -d --name hazelcast \
  -p 5701:5701 \
  -e HZ_CLUSTERNAME=dev \
  hazelcast/hazelcast:5.6.0

# Проверка работоспособности
curl http://localhost:5701/hazelcast/health/node-state
```

---

## Уроки

| #  | Тема | Папка | Описание |
|----|------|-------|----------|
| 1  | Введение в Hazelcast | `01_introduction/` | Что такое IMDG, зачем нужен, сравнение с альтернативами |
| 2  | Архитектура | `02_architecture/` | Embedded vs Client-Server, партиционирование, топологии |
| 3  | Конфигурация | `03_configuration/` | YAML, Java Config, серверная и клиентская конфигурация, Spring Boot |
| 4  | IMap — основная структура данных | `04_imap/` | Партиции, in-memory format, backup-стратегии, TTL, bulk-операции |
| 5  | Сериализация | `05_serialization/` | Compact Serialization, Java Records, schema evolution |
| 6  | Запросы: Predicates и индексы | `06_queries/` | Типы индексов, Predicates API, SQL-запросы, server-side filtering |
| 7  | Распределённые блокировки | `07_distributed_locks/` | IMap.tryLock, lease time, deadlock prevention, ShedLock |
| 8  | Паттерны интеграции со Spring Boot | `08_spring_integration/` | HazelcastConfigCustomizer, типизированные бины, Hexagonal Architecture |
| 9  | Высокая доступность | `09_high_availability/` | Split-brain protection, merge policies, partition groups, Kubernetes discovery |
| 10 | Тестирование | `10_testing/` | Embedded Hazelcast для тестов, интеграционные тесты, SpyBean |
| 11 | Мониторинг и метрики | `11_monitoring/` | Встроенные метрики, Micrometer, health checks, Management Center |
| 12 | Продвинутые возможности | `12_advanced_features/` | EntryProcessor, Near Cache, ITopic, MapStore, CP Subsystem |

---

## Рекомендуемый порядок

Уроки идут последовательно от базовых концепций к продвинутым. Уроки 1-6 — обязательная база, уроки 7-12 можно проходить в произвольном порядке в зависимости от задач проекта.