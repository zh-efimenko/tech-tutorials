# Урок 5. Лейблы и управление сервисами

## Зачем нужны лейблы

Docker Compose позволяет добавлять произвольные метаданные к сервисам через `labels`. Spring Boot использует лейблы с префиксом `org.springframework.boot.*` для управления тем, как обрабатываются сервисы из compose-файла.

Лейблы решают задачи:
- Исключить сервис из автоконфигурации
- Переопределить параметры подключения
- Указать Spring Boot, как интерпретировать нестандартный образ

## org.springframework.boot.ignore

Самый часто используемый лейбл. Говорит Spring Boot полностью игнорировать сервис:

```yaml
services:
  hz_2:
    image: hazelcast/hazelcast:5.6-jdk21
    ports:
      - "5702:5701"
    labels:
      org.springframework.boot.ignore: true
```

### Когда использовать

**Вспомогательные UI-сервисы.** Management Center, pgAdmin, RedisInsight — это инструменты для разработчика, Spring Boot не должен к ним подключаться:

```yaml
services:
  hazelcast-management:
    image: hazelcast/management-center:5.9
    ports:
      - "5700:8080"
    labels:
      org.springframework.boot.ignore: true

  pgadmin:
    image: dpage/pgadmin4
    ports:
      - "5050:80"
    labels:
      org.springframework.boot.ignore: true
```

**Дублирующие ноды кластера.** Если в compose-файле два экземпляра Hazelcast для кластера, Spring Boot попытается подключиться к обоим. Помечаем вторую ноду как ignore — приложение подключается только к первой, а кластер формируется между нодами внутри Docker-сети:

```yaml
services:
  hz_1:
    image: hazelcast/hazelcast:5.6-jdk21
    ports:
      - "5701:5701"
    environment:
      HZ_CLUSTERNAME: demo
      HZ_NETWORK_JOIN_TCP-IP_MEMBERS: hz_1:5701,hz_2:5701

  hz_2:
    image: hazelcast/hazelcast:5.6-jdk21
    ports:
      - "5702:5701"
    environment:
      HZ_CLUSTERNAME: demo
      HZ_NETWORK_JOIN_TCP-IP_MEMBERS: hz_1:5701,hz_2:5701
    labels:
      # Приложение подключается только к hz_1
      # hz_2 существует для формирования кластера
      org.springframework.boot.ignore: true
```

**Сервисы без поддержки Spring Boot.** Если сервис использует образ, который Spring Boot не распознаёт, он выдаст предупреждение. Лейбл ignore подавляет это предупреждение:

```yaml
services:
  custom-service:
    image: my-company/custom-tool:latest
    labels:
      org.springframework.boot.ignore: true
```

## org.springframework.boot.service-connection

Этот лейбл указывает Spring Boot, какой тип ConnectionDetails создать для сервиса. Полезно, когда используется нестандартный образ, который Spring Boot не распознаёт автоматически.

```yaml
services:
  my-postgres:
    image: myregistry.io/custom-postgres:17
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD: myapp
    labels:
      org.springframework.boot.service-connection: postgres
```

Без этого лейбла Spring Boot не знает, что `myregistry.io/custom-postgres:17` — это PostgreSQL. С лейблом он обработает сервис как стандартный PostgreSQL.

### Доступные значения service-connection

Значение лейбла соответствует имени технологии:

| Значение | ConnectionDetails |
|----------|-------------------|
| `postgres` | JdbcConnectionDetails |
| `mysql` | JdbcConnectionDetails |
| `mongo` | MongoConnectionDetails |
| `redis` | RedisConnectionDetails |
| `kafka` | KafkaConnectionDetails |
| `rabbitmq` | RabbitConnectionDetails |
| `elasticsearch` | ElasticsearchConnectionDetails |
| `zipkin` | ZipkinConnectionDetails |

## org.springframework.boot.readiness-check.tcp.disable

Отключает TCP-проверку готовности для сервиса. Spring Boot по умолчанию проверяет доступность порта перед тем, как считать сервис готовым. Если сервис не пробрасывает порты или проверка мешает:

```yaml
services:
  worker:
    image: my-worker:latest
    labels:
      org.springframework.boot.readiness-check.tcp.disable: true
```

## Комбинирование лейблов

Лейблы можно комбинировать. Например, нестандартный образ PostgreSQL с отключённой проверкой готовности:

```yaml
services:
  db:
    image: myregistry.io/postgres-with-extensions:17
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD: myapp
    labels:
      org.springframework.boot.service-connection: postgres
      org.springframework.boot.readiness-check.tcp.disable: true
```

## Пример из практики: полный compose с лейблами

```yaml
services:
  # Основная база — Spring Boot подключается автоматически
  db:
    image: postgres:17.5
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: sportsbook
      POSTGRES_USER: sportsbook
      POSTGRES_PASSWORD: sportsbook

  # Кеш — Spring Boot подключается автоматически
  redis:
    image: redis:7.4
    ports:
      - "6379:6379"

  # Кастомный образ Kafka — указываем тип подключения явно
  kafka:
    image: myregistry.io/kafka-with-schemas:7.2
    ports:
      - "9092:9092"
    labels:
      org.springframework.boot.service-connection: kafka

  # Hazelcast нода 1 — Spring Boot подключается
  hz_1:
    image: hazelcast/hazelcast:5.6-jdk21
    ports:
      - "5701:5701"

  # Hazelcast нода 2 — только для кластера, Spring Boot игнорирует
  hz_2:
    image: hazelcast/hazelcast:5.6-jdk21
    ports:
      - "5702:5701"
    labels:
      org.springframework.boot.ignore: true

  # UI-инструменты — Spring Boot игнорирует
  pgadmin:
    image: dpage/pgadmin4
    ports:
      - "5050:80"
    labels:
      org.springframework.boot.ignore: true

  hazelcast-management:
    image: hazelcast/management-center:5.9
    ports:
      - "5700:8080"
    labels:
      org.springframework.boot.ignore: true
```

## Практика

1. Добавь pgAdmin в compose.yaml без лейбла ignore — запусти приложение и изучи предупреждение в логах
2. Добавь лейбл `org.springframework.boot.ignore: true` к pgAdmin — предупреждение должно исчезнуть
3. Создай второй PostgreSQL-сервис в compose (для аналитики). Пометь его лейблом ignore, чтобы Spring Boot подключался только к основной базе
4. Замени образ PostgreSQL на нестандартный (например, `postgis/postgis:17-3.5`). Убедись, что Spring Boot не распознаёт его. Добавь лейбл `service-connection: postgres` — подключение должно заработать
5. Добавь два экземпляра Hazelcast, пометь второй как ignore. Проверь через Management Center, что кластер сформирован из двух нод, а приложение подключено к одной
6. Включи DEBUG-логирование и убедись, что игнорируемые сервисы не появляются в списке ConnectionDetails

## Итоги урока

- Лейблы с префиксом `org.springframework.boot.*` управляют поведением Docker Compose интеграции для каждого сервиса
- `org.springframework.boot.ignore: true` полностью исключает сервис из обработки Spring Boot — необходим для UI-инструментов, дублирующих нод кластеров и нераспознаваемых образов
- `org.springframework.boot.service-connection` указывает тип подключения для нестандартных образов — Spring Boot обработает сервис как стандартную технологию
- `org.springframework.boot.readiness-check.tcp.disable` отключает TCP-проверку готовности для сервисов без пробрасываемых портов
- Лейблы комбинируются — можно одновременно указать тип подключения и отключить readiness check
- Без лейбла ignore Spring Boot предупреждает о нераспознанных образах в логах
