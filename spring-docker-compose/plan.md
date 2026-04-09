# Программа обучения: Spring Boot Docker Compose

## Цель

Освоить зависимость `spring-boot-docker-compose` для автоматического управления локальной инфраструктурой (базы данных, кеши, брокеры сообщений) без ручного запуска контейнеров — как в режиме разработки, так и в тестах.

## Требования

- Java 25
- Spring Boot 3.5+
- Gradle 8.x+
- Docker Desktop / Docker Engine + Docker Compose v2
- IDE с поддержкой Spring Boot (IntelliJ IDEA рекомендуется)

## Запуск окружения

```bash
# Запустить приложение — Docker Compose поднимется автоматически
./gradlew bootRun

# Запустить тесты — тестовый Docker Compose поднимется автоматически
./gradlew test
```

---

## Уроки

| #  | Тема | Папка | Описание |
|----|------|-------|----------|
| 1  | Зачем нужен spring-boot-docker-compose | `01_introduction/` | Проблема ручного управления инфраструктурой и как Spring Boot её решает |
| 2  | Подключение и первый запуск | `02_getting_started/` | Добавление зависимости, создание compose.yaml, первый автоматический старт |
| 3  | Управление жизненным циклом | `03_lifecycle_management/` | Режимы start_and_stop, start_only, параметры остановки и таймауты |
| 4  | Автоконфигурация подключений | `04_auto_configuration/` | Как Spring Boot читает compose-файл и настраивает DataSource, Redis, Kafka без явных properties |
| 5  | Лейблы и управление сервисами | `05_labels_and_service_control/` | Лейблы для игнорирования сервисов, переопределения портов и кастомных connection details |
| 6  | Работа с несколькими сервисами | `06_multiple_services/` | PostgreSQL + Redis + Kafka + Hazelcast в одном compose-файле |
| 7  | Управление properties | `07_properties_management/` | Все spring.docker.compose.* свойства, приоритеты, переопределение через environment |
| 8  | Тестирование с Docker Compose | `08_testing/` | Отдельный compose для тестов, test slices, интеграция с @DataJdbcTest и @DataRedisTest |
| 9  | Профили и окружения | `09_profiles_and_environments/` | Spring-профили для compose, Docker Compose profiles, условный запуск сервисов |
| 10 | Best practices и production | `10_best_practices/` | Что делать в CI/CD, production, типичные ошибки и их решения |

---

## Рекомендуемый порядок

Уроки выстроены последовательно: от понимания проблемы (1) через базовую настройку (2-4) к продвинутым сценариям (5-7) и тестированию (8-9). Завершающий урок (10) — сводка практик для production. Рекомендуется проходить строго по порядку, выполняя практику в каждом уроке.
