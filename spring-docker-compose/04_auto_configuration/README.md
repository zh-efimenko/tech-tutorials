# Урок 4. Автоконфигурация подключений

## Как Spring Boot определяет параметры подключения

Когда Spring Boot запускает Docker Compose, он выполняет `docker compose ps` и получает информацию о каждом сервисе: образ, маппинг портов, переменные окружения. На основе этих данных создаются **ConnectionDetails** — объекты, которые предоставляют параметры подключения другим автоконфигурациям Spring Boot.

```
┌─────────────────────────────────────────────────────────┐
│                    compose.yaml                         │
│                                                         │
│  services:                                              │
│    db:                                                  │
│      image: postgres:18.4        ──┐                    │
│      ports: "5432:5432"          ──┼── Spring Boot      │
│      environment:                ──┘   читает           │
│        POSTGRES_DB: myapp                               │
│        POSTGRES_USER: myapp                             │
│        POSTGRES_PASSWORD: myapp                         │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│              JdbcConnectionDetails                      │
│                                                         │
│  url:      jdbc:postgresql://127.0.0.1:5432/myapp       │
│  username: myapp                                        │
│  password: myapp                                        │
└─────────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────┐
│                    DataSource                           │
│  (HikariCP с автоматическими параметрами)               │
└─────────────────────────────────────────────────────────┘
```

## ConnectionDetails и их приоритет

Spring Boot 3.1+ использует механизм **ConnectionDetails** — интерфейсы, предоставляющие параметры подключения. Docker Compose создаёт реализации этих интерфейсов автоматически.

**Важно:** ConnectionDetails от Docker Compose имеют приоритет выше, чем значения из `application.yml`. Если в compose-файле определён PostgreSQL на порту 5432, а в application.yml указан `spring.datasource.url` с портом 5433 — будет использован порт из compose.

| Источник | Приоритет |
|----------|-----------|
| ConnectionDetails (Docker Compose, Testcontainers, Service Bindings) | Высший |
| application.yml / application.properties | Низший |

Это означает, что при активной Docker Compose интеграции значения `spring.datasource.*` из application.yml **игнорируются**. Если тебе нужно переопределить автоконфигурацию — используй лейблы (урок 5) или отключи Docker Compose для конкретного запуска.

## Автоконфигурация PostgreSQL

Spring Boot распознаёт образы PostgreSQL и извлекает параметры из переменных окружения:

```yaml
services:
  db:
    image: postgres:18.4
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD: myapp
```

Из этого Spring Boot создаёт `JdbcConnectionDetails`:
- URL: `jdbc:postgresql://127.0.0.1:5432/myapp` (порт из `docker compose ps`, хост из docker context, база из `POSTGRES_DB`)
- Username: из `POSTGRES_USER`
- Password: из `POSTGRES_PASSWORD`

Если `POSTGRES_DB` не указан, используется значение `POSTGRES_USER` (поведение самого PostgreSQL).

## Автоконфигурация Redis

```yaml
services:
  redis:
    image: redis:8.10
    ports:
      - "6379:6379"
```

Spring Boot создаёт `DataRedisConnectionDetails` (в Spring Boot 3.x интерфейс назывался `RedisConnectionDetails`):
- Host: `127.0.0.1`
- Port: `6379`

**Только host и port.** В отличие от PostgreSQL, для Redis из compose-файла не извлекается ничего больше: `RedisDockerComposeConnectionDetails` собирается из `service.host()` и `service.ports().get(6379)`, переменные окружения не читаются вовсе. Никакого `REDIS_PASSWORD` интеграция не знает.

Практическое следствие: вот такой сервис из compose-файла не заработает вообще.

```yaml
services:
  redis:
    image: redis:8.10
    ports:
      - "6379:6379"
    command: ["redis-server", "--requirepass", "secret"]
```
 Свойство `spring.data.redis.password` тут не спасает — пока в контексте есть бин `DataRedisConnectionDetails` от Docker Compose, `PropertiesDataRedisConnectionDetails` (тот, что читает `spring.data.redis.*`) не создаётся из-за `@ConditionalOnMissingBean`, и пароль берётся из compose-реализации, то есть `null`. Клиент упадёт при первой же команде:

```
io.lettuce.core.RedisCommandExecutionException: NOAUTH HELLO must be called with the client
already authenticated, otherwise the HELLO <proto> AUTH <user> <pass> option can be used
to authenticate the client and select the RESP protocol version at the same time
```

Варианты, если пароль всё-таки нужен:

| Вариант | Как |
|---|---|
| Не включать пароль локально | Самый частый выбор для dev-окружения |
| Пометить сервис `org.springframework.boot.ignore: true` | ConnectionDetails не создаются, работают обычные `spring.data.redis.*` (урок 5) |
| Объявить свой бин `DataRedisConnectionDetails` | Полный контроль, но это уже код в проекте |

## Kafka: автоконфигурации нет

Kafka — исключение. Docker Compose интеграция **не создаёт** `KafkaConnectionDetails` ни в Spring Boot 3.x, ни в 4.1: в модуле `spring-boot-kafka` есть фабрика только для Testcontainers. Полный список поддерживаемых образов — в уроке 1, Kafka в нём нет.

Что происходит с брокером в compose-файле:

```yaml
services:
  kafka:
    image: apache/kafka:4.3.1
    ports:
      - "9092:9092"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_LISTENERS: PLAINTEXT://:29092,CONTROLLER://:29093,PLAINTEXT_HOST://:9092
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:29093
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
```

**Внимание:** урезать этот набор нельзя. Образ `apache/kafka` работает в режиме KRaft, и без `KAFKA_PROCESS_ROLES` контейнер падает сразу:

```
Exception in thread "main" org.apache.kafka.common.config.ConfigException:
Missing required configuration "process.roles" which has no default value.
```

Дальше Spring Boot две минуты ждёт мёртвый сервис и падает с `ReadinessTimeoutException: Readiness timeout of PT2M reached while waiting for services [my_kafka]`.

1. Spring Boot запускает контейнер вместе с остальными сервисами
2. Ждёт его готовности (healthcheck или TCP-проверка порта 9092)
3. Никаких ConnectionDetails не создаёт — `spring.kafka.*` остаётся за тобой

Поэтому bootstrap-servers указываются явно:

```yaml
spring:
  kafka:
    bootstrap-servers: localhost:9092
```

**Подводный камень:** если порт брокера динамический (`"9092"` вместо `"9092:9092"`), фиксированного адреса не будет — для Kafka всегда пробрасывай конкретный порт.

Лейбл `org.springframework.boot.service-connection: kafka` тут не поможет — значения `kafka` среди поддерживаемых имён нет.

## Динамические порты

Compose-файл может использовать динамические порты — когда Docker сам выбирает свободный порт на хосте:

```yaml
services:
  db:
    image: postgres:18.4
    ports:
      - "5432"  # хост-порт назначается динамически
    environment:
      POSTGRES_DB: myapp
      POSTGRES_USER: myapp
      POSTGRES_PASSWORD: myapp
```

Spring Boot вызывает `docker compose ps`, получает реальный маппинг (например, `0.0.0.0:54321->5432/tcp`) и использует именно этот порт. Это полезно, если стандартный порт 5432 уже занят.

## Несколько сервисов одного типа

Если в compose-файле два PostgreSQL-сервиса, Spring Boot не сможет однозначно определить, какой из них использовать для `DataSource`. В этом случае один сервис нужно пометить лейблом `org.springframework.boot.ignore=true` (подробнее в уроке 5).

## Отладка автоконфигурации

Модуль пишет большую часть диагностики на уровне TRACE, поэтому DEBUG тут недостаточно:

```yaml
logging:
  level:
    org.springframework.boot.docker.compose: TRACE
```

В логах будет видно:
- Какой compose-файл выбран и с какими профилями
- Версии `docker` и `docker compose`, которые нашла интеграция
- Какие команды выполняются и вывод `docker compose ps`

Отдельного лога «созданы такие-то ConnectionDetails» интеграция не пишет. Для DataSource выручает HikariCP — он печатает итоговый JDBC URL при старте пула:

```yaml
logging:
  level:
    com.zaxxer.hikari.HikariConfig: DEBUG
```

С Redis так не получится: Lettuce подключается лениво, при старте контекста соединение не открывается, и `logging.level.io.lettuce.core: DEBUG` даёт только строки вида `Starting without optional epoll library`. Адрес придётся спросить у самого приложения:

```java
// в классе с @SpringBootApplication
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.data.redis.connection.RedisConnectionFactory;
import org.springframework.jdbc.core.JdbcTemplate;

@Bean
CommandLineRunner probe(JdbcTemplate jdbc, RedisConnectionFactory redis) {
    return args -> {
        System.out.println("JDBC: " + jdbc.queryForObject("select current_database()", String.class));
        try (var conn = redis.getConnection()) {
            System.out.println("REDIS PING: " + conn.ping());
        }
    };
}
```

## Практика

1. Создай compose.yaml с PostgreSQL и Redis, добавь в build.gradle `implementation 'org.springframework.boot:spring-boot-starter-data-redis'` (без стартера Redis-подключения не будет вовсе). Добавь бин `probe` из раздела «Отладка автоконфигурации» — без него в проекте нет ни одного обращения к базе и кешу, и проверять нечего. Запусти приложение без `spring.datasource.*` и `spring.data.redis.*` в application.yml — в консоли должны появиться имя базы и `REDIS PING: PONG`
2. Добавь `spring.datasource.url: jdbc:postgresql://localhost:9999/wrong` в application.yml — проверь, что Spring Boot всё равно подключается к правильному порту из compose
3. Измени порт PostgreSQL на динамический (`"5432"` вместо `"5432:5432"`) — убедись, что приложение подключается к порту, назначенному Docker
4. Включи TRACE-логирование для `org.springframework.boot.docker.compose` и изучи, какой compose-файл выбран и какие команды выполняются
5. Добавь Kafka в compose-файл целиком, со всем набором `KAFKA_*` из примера выше, и подключи `implementation 'org.springframework.boot:spring-boot-starter-kafka'` — без клиента наблюдать нечего. Объяви бин топика (`import org.apache.kafka.clients.admin.NewTopic;`) — `KafkaAdmin` обращается к брокеру при старте:

   ```java
   @Bean
   NewTopic demo() {
       return new NewTopic("demo", 1, (short) 1);
   }
   ```

   Убедись, что `spring.kafka.bootstrap-servers` **не** настраивается автоматически: без явного значения приложение идёт на дефолтный `localhost:9092`. Смени хост-порт брокера на 9093 — приложение всё равно стартует, но лог заполнится строками `Connection to node -1 (localhost/127.0.0.1:9092) could not be established` и закончится `ERROR KafkaAdmin : Could not configure topics` / `TimeoutException: Timed out waiting for a node assignment`. Старт при этом растягивается на десятки секунд, а лог — на десятки тысяч строк
6. Попробуй добавить два PostgreSQL-сервиса в compose и запусти приложение — изучи ошибку

## Итоги урока

- Spring Boot создаёт ConnectionDetails на основе образов, портов и переменных окружения из compose-файла
- ConnectionDetails имеют приоритет выше, чем значения из application.yml — это намеренное поведение, не баг
- Для PostgreSQL параметры извлекаются из `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- Динамические порты поддерживаются — Spring Boot получает реальный маппинг через `docker compose ps`
- Два сервиса одного типа вызывают конфликт — один нужно пометить лейблом ignore
- Для Kafka ConnectionDetails не создаются — `spring.kafka.bootstrap-servers` задаётся вручную
- TRACE-логирование пакета `org.springframework.boot.docker.compose` показывает выбранный compose-файл и выполняемые команды; итоговые параметры подключения видны в логах клиентов (HikariCP, Lettuce)
