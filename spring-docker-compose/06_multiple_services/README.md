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
    image: postgres:17.5
    container_name: demo_postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_DB: demo
      POSTGRES_USER: demo
      POSTGRES_PASSWORD: demo
    restart: unless-stopped

  # --- Кеш ---
  redis:
    image: redis:7.4
    container_name: demo_redis
    ports:
      - "6379:6379"
    restart: unless-stopped

  # --- Брокер сообщений ---
  zookeeper:
    image: confluentinc/cp-zookeeper:7.2.1
    container_name: demo_zookeeper
    ports:
      - "2181:2181"
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    restart: unless-stopped

  kafka:
    image: confluentinc/cp-kafka:7.2.1
    container_name: demo_kafka
    ports:
      - "9092:9092"
    depends_on:
      - zookeeper
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:29092,PLAINTEXT_HOST://localhost:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT,PLAINTEXT_HOST:PLAINTEXT
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "29092"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  # --- Распределённый кеш ---
  hz_1:
    image: hazelcast/hazelcast:5.6-jdk21
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
    image: hazelcast/hazelcast:5.6-jdk21
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
    image: hazelcast/management-center:5.9
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
  kafka:
    depends_on:
      - zookeeper
```

Это гарантирует, что Zookeeper запустится перед Kafka. Но `depends_on` не означает "готов" — только "запущен". Для реальной готовности используй healthcheck:

```yaml
services:
  kafka:
    depends_on:
      zookeeper:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "nc", "-z", "localhost", "29092"]
      interval: 10s
      timeout: 5s
      retries: 10
```

Spring Boot дополнительно ждёт readiness каждого сервиса перед подключением. Но для зависимостей между контейнерами (Kafka -> Zookeeper) это ответственность Docker Compose.

## Конфигурация Spring Boot

Для работы с несколькими сервисами подключи соответствующие стартеры:

```groovy
dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-data-jdbc'
    implementation 'org.springframework.boot:spring-boot-starter-data-redis'
    implementation 'org.springframework.boot:spring-boot-starter-kafka' // для Kafka (опционально)

    runtimeOnly 'org.postgresql:postgresql'
    implementation 'com.hazelcast:hazelcast:5.6.0'

    testAndDevelopmentOnly 'org.springframework.boot:spring-boot-docker-compose'
}
```

В `application.yml` можно не указывать параметры подключения — Spring Boot настроит всё автоматически. Но можно указать настройки уровня приложения, которые не определяются из compose-файла:

```yaml
spring:
  docker:
    compose:
      lifecycle-management: start_and_stop
      stop:
        command: down
        arguments: -v
        timeout: 10s

  # Пул подключений — это не про хост/порт, compose здесь не поможет
  datasource:
    hikari:
      maximum-pool-size: 10
      minimum-idle: 2

  # Настройки Kafka-потребителя — это бизнес-логика, не подключение
  kafka:
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
5. Создаёт ConnectionDetails для каждого распознанного сервиса
6. Инициализирует DataSource, RedisConnectionFactory, KafkaTemplate и т.д.
7. Запускает ApplicationContext

Если хотя бы один сервис не станет ready в течение таймаута — приложение не запустится.

## Работа с Zookeeper

Zookeeper — вспомогательный сервис для Kafka. Spring Boot не создаёт для него ConnectionDetails (нет стартера Zookeeper). Но Zookeeper необходим для работы Kafka, поэтому он присутствует в compose-файле.

Spring Boot не выдаёт предупреждение для Zookeeper — он распознаёт этот образ как вспомогательный.

## Работа с Hazelcast

Spring Boot Docker Compose поддерживает образ `hazelcast/hazelcast` — при его обнаружении создаётся `HazelcastConnectionDetails`. Автоконфигурация извлекает из compose-файла:
- **Имя кластера** — из переменной `HZ_CLUSTERNAME`
- **Адрес** — из пробрасываемого порта (по умолчанию 5701)

Spring Boot автоматически создаёт `HazelcastInstance` в режиме клиента, подключённого к контейнеру.

Для базового случая (одна нода, стандартный образ) никакой дополнительной конфигурации не нужно — достаточно compose-файла и зависимости `com.hazelcast:hazelcast`.

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
| Zookeeper | 3-5 сек |
| Kafka | 10-20 сек |
| Hazelcast | 5-10 сек |
| **Всё вместе** | **15-30 сек** |

Для ускорения при разработке используй `lifecycle-management: start_only` — контейнеры запускаются один раз и живут между перезапусками приложения.

## Практика

1. Создай compose.yaml с PostgreSQL и Redis. Запусти приложение и убедись, что оба подключения настроены
2. Добавь Kafka (с Zookeeper). Проверь, что Spring Boot ждёт healthcheck Kafka перед стартом
3. Добавь два экземпляра Hazelcast. Пометь второй как ignore. Запусти без дополнительной конфигурации — убедись, что `HazelcastInstance` создаётся автоматически. Затем добавь `@Configuration` с `IMap`-бином
4. Добавь Hazelcast Management Center с лейблом ignore. Открой http://localhost:5700 и убедись, что кластер из двух нод виден
5. Измени `lifecycle-management` на `start_only` и замерь время повторного старта приложения — оно должно быть значительно меньше
6. Удали `depends_on` у Kafka и перезапусти — наблюдай, как Kafka падает из-за недоступного Zookeeper

## Итоги урока

- Один compose-файл может содержать все инфраструктурные сервисы проекта — Spring Boot обработает каждый
- `depends_on` управляет порядком запуска контейнеров, но для реальной готовности нужен healthcheck
- Для Kafka healthcheck критически важен — без него Spring Boot может попытаться подключиться к не готовому брокеру
- Вспомогательные сервисы (Zookeeper) и UI (Management Center) не создают ConnectionDetails
- Hazelcast поддерживается Docker Compose интеграцией — Spring Boot создаёт `HazelcastConnectionDetails` и `HazelcastInstance`-клиент автоматически; кастомная `@Configuration` нужна только для `IMap`-бинов и кластерных настроек
- Для быстрой разработки с тяжёлым стеком используй `start_only` — контейнеры живут между перезапусками приложения
- Вторые ноды кластеров и UI-инструменты помечаются лейблом `org.springframework.boot.ignore: true`
