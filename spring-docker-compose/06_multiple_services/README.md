# Урок 6. Работа с несколькими сервисами

## Типичный стек микросервиса

Реальное приложение редко работает с одной базой данных. Типичный стек включает несколько инфраструктурных сервисов, каждый со своей ролью:

```
┌────────────────────────────────────────────────────┐
│                Spring Boot Application             │
│                                                    │
│  ┌──────────┐ ┌───────┐ ┌───────┐ ┌────────────┐  │
│  │DataSource│ │ Redis │ │ Kafka │ │ Hazelcast  │  │
│  │  (JDBC)  │ │(Cache)│ │(Msgs) │ │(Dist.Cache)│  │
│  └────┬─────┘ └───┬───┘ └───┬───┘ └─────┬──────┘  │
└───────┼────────────┼─────────┼───────────┼─────────┘
        │            │         │           │
        ▼            ▼         ▼           ▼
   PostgreSQL     Redis      Kafka     Hazelcast
   (compose)    (compose)  (compose)   (compose)
```

Spring Boot Docker Compose обрабатывает все сервисы из одного compose-файла и настраивает подключения для каждого.

## Compose-файл с полным стеком

```yaml
services:

  # --- Реляционная база данных ---
  db:
    image: postgres:18.4
    container_name: demo_postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: demo
      POSTGRES_USER: demo
      POSTGRES_PASSWORD: demo
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U demo"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  # --- Кеш ---
  redis:
    image: redis:8.10
    container_name: demo_redis
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    restart: unless-stopped

  # --- Брокер сообщений (KRaft, один контейнер) ---
  kafka:
    image: apache/kafka:4.3.1
    container_name: demo_kafka
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
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS: 0
    healthcheck:
      test: ["CMD-SHELL", "/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  # --- Распределённый кеш ---
  hz_1:
    image: hazelcast/hazelcast:5.7
    container_name: demo_hazelcast_1
    ports:
      - "5701:5701"
    environment:
      HZ_CLUSTERNAME: demo
      HZ_NETWORK_PUBLICADDRESS: hz_1:5701
      HZ_NETWORK_JOIN_AUTO-DETECTION_ENABLED: false
      HZ_NETWORK_JOIN_TCP-IP_ENABLED: true
      HZ_NETWORK_JOIN_TCP-IP_MEMBERS: hz_1:5701,hz_2:5701

  hz_2:
    image: hazelcast/hazelcast:5.7
    container_name: demo_hazelcast_2
    ports:
      - "5702:5701"
    environment:
      HZ_CLUSTERNAME: demo
      HZ_NETWORK_PUBLICADDRESS: hz_2:5701
      HZ_NETWORK_JOIN_AUTO-DETECTION_ENABLED: false
      HZ_NETWORK_JOIN_TCP-IP_ENABLED: true
      HZ_NETWORK_JOIN_TCP-IP_MEMBERS: hz_1:5701,hz_2:5701
    labels:
      org.springframework.boot.ignore: true

  # --- UI ---
  hazelcast-management:
    image: hazelcast/management-center:5.11.0
    container_name: demo_hazelcast_management
    ports:
      - "5700:8080"
    environment:
      MC_DEFAULT_CLUSTER: demo
      MC_DEFAULT_CLUSTER_MEMBERS: hz_1:5701,hz_2:5701
    labels:
      org.springframework.boot.ignore: true
```

## Зависимости между сервисами

Docker Compose поддерживает `depends_on` для определения порядка запуска:

```yaml
services:
  app-worker:
    depends_on:
      - kafka
```

Это гарантирует, что Kafka запустится перед воркером. Но `depends_on` не означает "готов" — только "запущен". Для реальной готовности используй условие по healthcheck:

```yaml
services:
  app-worker:
    depends_on:
      kafka:
        condition: service_healthy
```

Spring Boot дополнительно ждёт readiness каждого сервиса перед стартом контекста. Но зависимости между самими контейнерами — ответственность Docker Compose.

**Про Kafka:** начиная с Kafka 4.0 ZooKeeper удалён полностью, брокер работает в режиме KRaft и поднимается одним контейнером. Отдельный сервис `zookeeper` в compose-файлах больше не нужен — и в образах Confluent (CP 8.0+) его тоже нет.

## Конфигурация Spring Boot

Для работы с несколькими сервисами подключи соответствующие стартеры:

```groovy
dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-data-jdbc'
    implementation 'org.springframework.boot:spring-boot-starter-data-redis'
    implementation 'org.springframework.boot:spring-boot-starter-kafka'
    implementation 'org.springframework.boot:spring-boot-starter-hazelcast'

    runtimeOnly 'org.postgresql:postgresql'

    testAndDevelopmentOnly 'org.springframework.boot:spring-boot-docker-compose'
}
```

В Spring Boot 4 стартер обязателен для каждой технологии: автоконфигурация лежит в отдельном модуле, и одной только клиентской библиотеки (`com.hazelcast:hazelcast`, `org.springframework.kafka:spring-kafka`) уже недостаточно — без `spring-boot-starter-hazelcast` не будет ни `HazelcastConnectionDetails`, ни фабрики Docker Compose для Hazelcast.

В `application.yml` можно не указывать параметры подключения — Spring Boot настроит всё автоматически. Но можно указать настройки уровня приложения, которые не определяются из compose-файла:

```yaml
spring:
  docker:
    compose:
      lifecycle-management: start_and_stop
      stop:
        command: down
        arguments:
          - "--volumes"
        timeout: 10s

  # Пул подключений — это не про хост/порт, compose здесь не поможет
  datasource:
    hikari:
      maximum-pool-size: 10
      minimum-idle: 2

  # Kafka: адрес брокера compose не подставит — задаём вручную
  kafka:
    bootstrap-servers: localhost:9092
    consumer:
      group-id: demo-group
      auto-offset-reset: earliest
```

## Порядок инициализации

При запуске приложения с несколькими сервисами порядок следующий:

1. Spring Boot находит compose-файл
2. Выполняет `docker compose up`
3. Docker Compose запускает сервисы с учётом `depends_on`
4. Spring Boot ждёт readiness каждого сервиса (healthcheck или TCP-порт)
5. Создаёт ConnectionDetails для каждого распознанного сервиса (Kafka в их число не входит)
6. Инициализирует DataSource, RedisConnectionFactory, HazelcastInstance и т.д.
7. Запускает ApplicationContext

Если хотя бы один сервис не станет ready в течение таймаута — приложение не запустится.

## Работа с Kafka

Kafka в compose-файле ведёт себя иначе, чем остальные сервисы: Docker Compose интеграция её не поддерживает и ConnectionDetails не создаёт (урок 4). Практические следствия для стека из нескольких сервисов:

- `spring.kafka.bootstrap-servers` указывается в `application.yml` вручную и должен совпадать с пробрасываемым хост-портом
- порт брокера нельзя делать динамическим — адрес некому подставить
- сервис остаётся под readiness-проверкой Spring Boot, поэтому healthcheck на брокере полезен: приложение не начнёт работу раньше, чем брокер ответит

Если Kafka в конкретном сценарии не нужна, проще не поднимать её вовсе — вынеси брокер в Docker Compose профиль (урок 9), а не помечай лейблом ignore.

## Работа с Hazelcast

Spring Boot Docker Compose поддерживает образ `hazelcast/hazelcast` — при его обнаружении создаётся `HazelcastConnectionDetails`. Автоконфигурация извлекает из compose-файла:
- **Имя кластера** — из переменной `HZ_CLUSTERNAME`
- **Адрес** — из пробрасываемого порта (по умолчанию 5701)

Spring Boot автоматически создаёт `HazelcastInstance` в режиме клиента, подключённого к контейнеру.

**Про лейбл ignore на второй ноде.** Он убирает hz_2 только из обработки Spring Boot. Сам Hazelcast про него всё равно узнает: клиент подключается к hz_1, получает от него список членов кластера и пытается открыть соединение ко второй ноде по адресу из `HZ_NETWORK_PUBLICADDRESS`. Адрес `hz_2:5701` осмыслен только внутри Docker-сети, поэтому в логах примерно раз в секунду появляется сообщение о неудачной попытке — точный текст зависит от того, во что резолвится имя `hz_2` на твоей машине:

```
c.h.c.i.c.ClientConnectionManager : hz.client_1 [demo] [5.5.0] Could not connect to member <uuid>,
reason com.hazelcast.core.HazelcastException: java.io.IOException: Connection refused to address hz_2/...:5701
```

```
c.h.c.i.c.t.TcpClientConnection : hz.client_1 [demo] [5.5.0] ClientConnection{... channel=NioChannel{...->hz_2/127.0.0.1:5701} ...}
closed. Reason: Duplicate connection to same member with uuid : <uuid>
```

Приложение при этом стартует и работает через hz_1 — это шум, а не поломка. Убрать его можно, либо оставив в compose одну ноду, либо задав нодам публичные адреса, доступные с хоста (`localhost:5701` и `localhost:5702`) вместе с проброшенными портами.

**Про версии:** Spring Boot 4.1 управляет версией клиента `com.hazelcast:hazelcast` — это 5.5.0, тогда как образ в compose-файле свежее (5.7). Внутри линейки 5.x клиент и члены кластера протоколом совместимы, но если хочешь версия-в-версию, подними клиент явно: `implementation 'com.hazelcast:hazelcast:5.7.0'`.

Для базового случая (одна нода, стандартный образ) никакой дополнительной конфигурации не нужно — достаточно compose-файла и стартера `spring-boot-starter-hazelcast`.

Когда нужна `@Configuration`:
- Кластер из нескольких нод (нужно перечислить все адреса членов)
- Кастомные `IMap`, `IQueue` и другие распределённые структуры данных
- Нестандартные настройки сериализации, near cache и т.д.

```java
@Configuration
public class HazelcastConfig {

    // IMap не создаётся автоконфигурацией — объявляем явно
    @Bean
    public IMap<String, String> demoMessages(HazelcastInstance hazelcastInstance) {
        return hazelcastInstance.getMap("demo-messages");
    }
}
```

Для кластера из нескольких нод, где первая нода обрабатывается автоконфигурацией, а остальные помечены `ignore`, адреса всех членов задаются через `ClientConfig`:

```java
@Configuration
public class HazelcastConfig {

    // Переопределяем автоконфигурированный HazelcastInstance,
    // чтобы добавить адреса второй ноды для failover
    @Bean
    public HazelcastInstance hazelcastInstance() {
        ClientConfig config = new ClientConfig();
        config.setClusterName("demo");
        // обе ноды — для отказоустойчивости клиент знает о каждой
        config.getNetworkConfig()
              .addAddress("localhost:5701")
              .addAddress("localhost:5702");
        return HazelcastClient.newHazelcastClient(config);
    }

    @Bean
    public IMap<String, String> demoMessages(HazelcastInstance hazelcastInstance) {
        return hazelcastInstance.getMap("demo-messages");
    }
}
```

## Время старта

Чем больше сервисов, тем дольше старт. Примерные времена cold start (первый запуск, образы уже скачаны):

| Сервис | Время старта |
|--------|-------------|
| PostgreSQL | 2-3 сек |
| Redis | 1-2 сек |
| Kafka (KRaft) | 8-15 сек |
| Hazelcast | 5-10 сек |
| **Всё вместе** | **20-35 сек** (зависит от загрузки машины) |

Для ускорения при разработке используй `lifecycle-management: start_only` — контейнеры запускаются один раз и живут между перезапусками приложения.

## Практика

1. Создай compose.yaml с PostgreSQL и Redis. Запусти приложение и убедись, что оба подключения настроены
2. Добавь Kafka в режиме KRaft. Проверь, что Spring Boot ждёт её healthcheck перед стартом, и добавь `spring.kafka.bootstrap-servers` вручную
3. Добавь два экземпляра Hazelcast. Пометь второй как ignore. Запусти без дополнительной конфигурации — убедись, что `HazelcastInstance` создаётся автоматически. Затем добавь `@Configuration` с `IMap`-бином
4. Добавь Hazelcast Management Center с лейблом ignore. Открой http://localhost:5700 и убедись, что кластер из двух нод виден
5. Измени `lifecycle-management` на `start_only` и замерь время повторного старта приложения — оно должно быть значительно меньше
6. Объяви бин `NewTopic` (урок 4, практика 5) — без обращения к брокеру «не находит Kafka» никак не проявится, приложение стартует молча. Затем убери `spring.kafka.bootstrap-servers` из application.yml и смени хост-порт брокера на 9093: `KafkaAdmin` пойдёт на дефолтный `localhost:9092`, лог заполнится `Connection to node -1 ... could not be established`, старт затянется на минуту и закончится `ERROR KafkaAdmin : Could not configure topics`. Убери этот бин перед уроком 8 — иначе он будет тормозить тесты

## Итоги урока

- Один compose-файл может содержать все инфраструктурные сервисы проекта — Spring Boot обработает каждый
- `depends_on` управляет порядком запуска контейнеров, но для реальной готовности нужен healthcheck
- Для Kafka healthcheck критически важен — без него Spring Boot закончит readiness-проверку по открытому порту и приложение начнёт работу с ещё не готовым брокером
- UI-инструменты (Management Center) и Kafka не создают ConnectionDetails — для Kafka адрес брокера задаётся вручную
- Hazelcast поддерживается Docker Compose интеграцией — Spring Boot создаёт `HazelcastConnectionDetails` и `HazelcastInstance`-клиент автоматически; кастомная `@Configuration` нужна только для `IMap`-бинов и кластерных настроек
- Для быстрой разработки с тяжёлым стеком используй `start_only` — контейнеры живут между перезапусками приложения
- Вторые ноды кластеров и UI-инструменты помечаются лейблом `org.springframework.boot.ignore: true`
