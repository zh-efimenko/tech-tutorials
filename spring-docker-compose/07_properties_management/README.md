# Урок 7. Управление properties

## Все свойства spring.docker.compose.*

Spring Boot предоставляет набор свойств для настройки Docker Compose интеграции. Все они находятся под префиксом `spring.docker.compose`.

| Свойство | Тип | По умолчанию | Описание |
|----------|-----|-------------|----------|
| `spring.docker.compose.enabled` | boolean | `true` | Включить/выключить интеграцию |
| `spring.docker.compose.file` | String | автоопределение | Путь к compose-файлу |
| `spring.docker.compose.lifecycle-management` | enum | `start_and_stop` | Режим управления жизненным циклом |
| `spring.docker.compose.host` | String | `localhost` | Хост для подключения к сервисам |
| `spring.docker.compose.start.command` | enum | `up` | Команда запуска |
| `spring.docker.compose.start.arguments` | String | — | Аргументы для команды запуска |
| `spring.docker.compose.start.log-level` | enum | `info` | Уровень логирования при запуске |
| `spring.docker.compose.stop.command` | enum | `stop` | Команда остановки (`stop` или `down`) |
| `spring.docker.compose.stop.arguments` | String | — | Аргументы для команды остановки |
| `spring.docker.compose.stop.timeout` | Duration | `10s` | Таймаут остановки |
| `spring.docker.compose.skip.in-tests` | boolean | `true` | Пропускать в тестах |
| `spring.docker.compose.profiles.active` | List | — | Активные Docker Compose профили |
| `spring.docker.compose.readiness.tcp.connect-timeout` | Duration | `200ms` | Таймаут TCP-проверки готовности |
| `spring.docker.compose.readiness.tcp.read-timeout` | Duration | `200ms` | Таймаут чтения TCP-проверки |
| `spring.docker.compose.readiness.timeout` | Duration | `2m` | Общий таймаут ожидания готовности |
| `spring.docker.compose.readiness.wait` | enum | `always` | Когда ждать готовности |

## Отключение интеграции

Полное отключение Docker Compose интеграции:

```yaml
spring:
  docker:
    compose:
      enabled: false
```

Это полезно, когда:
- Запускаешь приложение в среде без Docker (production, CI с предзапущенными сервисами)
- Временно хочешь использовать внешние сервисы вместо контейнеров

Можно отключить через переменную окружения без изменения application.yml:

```bash
SPRING_DOCKER_COMPOSE_ENABLED=false ./gradlew bootRun
```

## Путь к compose-файлу

По умолчанию Spring Boot ищет файл с именами `compose.yaml`, `compose.yml`, `docker-compose.yaml`, `docker-compose.yml` в рабочей директории. Если файл называется иначе или лежит в другой папке:

```yaml
spring:
  docker:
    compose:
      file: infrastructure/docker/compose.yaml
```

Путь может быть абсолютным или относительным (от рабочей директории).

## Настройка команды запуска

По умолчанию Spring Boot выполняет `docker compose up`. Можно добавить аргументы:

```yaml
spring:
  docker:
    compose:
      start:
        command: up
        arguments: --build --force-recreate
        log-level: info
```

Доступные значения `log-level`:

| Значение | Описание |
|----------|----------|
| `info` | Стандартный вывод (по умолчанию) |
| `debug` | Подробный вывод Docker Compose |
| `warn` | Только предупреждения |
| `error` | Только ошибки |

**Внимание:** аргумент `--build` пересобирает образы при каждом запуске. Используй его, только если compose-файл содержит сервисы с `build` (локальные Dockerfile).

## Настройка хоста

По умолчанию Spring Boot считает, что сервисы доступны на `localhost`. Если Docker запущен на удалённой машине или в VM:

```yaml
spring:
  docker:
    compose:
      host: 192.168.1.100
```

Это значение используется во всех ConnectionDetails вместо `localhost`.

## Настройка readiness

Spring Boot ждёт готовности каждого сервиса перед подключением. Параметры ожидания:

```yaml
spring:
  docker:
    compose:
      readiness:
        timeout: 3m
        wait: always
        tcp:
          connect-timeout: 500ms
          read-timeout: 500ms
```

Свойство `readiness.wait` принимает значения:

| Значение | Поведение |
|----------|-----------|
| `always` | Всегда ждать готовности (по умолчанию) |
| `only-if-started` | Ждать только если контейнеры были запущены Spring Boot |
| `never` | Не ждать готовности |

`only-if-started` полезен с `lifecycle-management: start_only` — при повторных запусках приложения контейнеры уже готовы, нет смысла проверять повторно.

## Приоритет источников конфигурации

Spring Boot применяет properties из нескольких источников. Приоритет (от высшего к низшему):

```
1. Аргументы командной строки       --spring.docker.compose.enabled=false
2. Переменные окружения              SPRING_DOCKER_COMPOSE_ENABLED=false
3. application-{profile}.yml         spring.docker.compose.file: test.yaml
4. application.yml                   spring.docker.compose.lifecycle-management: start_only
5. Значения по умолчанию             (встроенные в Spring Boot)
```

Это стандартный порядок Spring Boot. Используй его для переключения поведения между окружениями без изменения кода.

## Переключение через переменные окружения

Переменные окружения — удобный способ переопределить compose-настройки без правки файлов:

```bash
# Отключить интеграцию
SPRING_DOCKER_COMPOSE_ENABLED=false ./gradlew bootRun

# Указать другой файл
SPRING_DOCKER_COMPOSE_FILE=compose-full.yaml ./gradlew bootRun

# Только запуск, без остановки
SPRING_DOCKER_COMPOSE_LIFECYCLE_MANAGEMENT=start_only ./gradlew bootRun
```

## Переключение через аргументы командной строки

```bash
./gradlew bootRun --args='--spring.docker.compose.enabled=false'

./gradlew bootRun --args='--spring.docker.compose.file=compose-minimal.yaml'
```

## Пример: разные конфигурации для разных задач

### Для ежедневной разработки

```yaml
# application.yml
spring:
  docker:
    compose:
      lifecycle-management: start_only
      readiness:
        wait: only-if-started
```

Контейнеры запускаются один раз, при повторных запусках приложения readiness-проверка пропускается.

### Для демонстрации с чистыми данными

```yaml
# application-demo.yml
spring:
  docker:
    compose:
      lifecycle-management: start_and_stop
      stop:
        command: down
        arguments: -v
```

```bash
./gradlew bootRun --args='--spring.profiles.active=demo'
```

### Для работы с удалённым Docker

```yaml
# application-remote.yml
spring:
  docker:
    compose:
      host: dev-server.internal
      lifecycle-management: none
```

## Практика

1. Создай `application.yml` с `lifecycle-management: start_only` и запусти приложение дважды — второй раз должен быть быстрее
2. Переопредели `lifecycle-management` через переменную окружения на `start_and_stop` без изменения yml-файла
3. Настрой `readiness.timeout: 5s` и попробуй запустить приложение с Kafka без healthcheck — наблюдай таймаут
4. Увеличь `readiness.timeout: 3m` — теперь Spring Boot дождётся Kafka
5. Создай `application-clean.yml` с `stop.command: down` и `stop.arguments: -v`. Запусти с профилем `clean` — убедись, что данные не сохраняются
6. Отключи интеграцию через `SPRING_DOCKER_COMPOSE_ENABLED=false`, предварительно запустив контейнеры вручную — убедись, что приложение подключается к ним, но не управляет жизненным циклом
7. Переименуй compose-файл и укажи путь через `spring.docker.compose.file`

## Итоги урока

- Все настройки Docker Compose интеграции находятся под префиксом `spring.docker.compose.*`
- `enabled: false` полностью отключает интеграцию — полезно для production и CI
- `readiness.wait: only-if-started` пропускает проверку готовности для уже запущенных контейнеров — ускоряет повторные запуски
- `readiness.timeout` определяет, сколько Spring Boot ждёт готовности сервисов — для Kafka и Elasticsearch стоит увеличить
- Переменные окружения и аргументы командной строки позволяют переключать поведение без изменения файлов
- Spring-профили (`application-{profile}.yml`) — удобный способ хранить разные compose-конфигурации для разных сценариев
- `start.arguments` позволяет добавить `--build` или `--force-recreate` к команде запуска
