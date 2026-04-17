# Урок 3. Конфигурация: от локальной разработки до production

## Способы конфигурации Hazelcast

Hazelcast поддерживает три способа конфигурации, которые можно комбинировать:

| Способ | Когда использовать |
|--------|-------------------|
| **YAML/XML файл** | Серверная конфигурация, карты, индексы, бэкапы |
| **Java Config** (программный) | Динамическая конфигурация, Spring Boot кастомизация |
| **Spring Boot автоконфигурация** | Быстрый старт, конвенция над конфигурацией |

## Серверная конфигурация

Серверная конфигурация определяет поведение узлов кластера: имя, сеть, карты, бэкапы, split-brain protection.

### Production-конфигурация (Kubernetes)

```yaml
hazelcast:
  cluster-name: my-cluster
  instance-name: my-app

  properties:
    hazelcast.phone.home.enabled: false           # Отключить телеметрию
    hazelcast.index.copy.behavior: COPY_ON_WRITE  # Быстрые чтения при индексации
    hazelcast.shutdownhook.policy: GRACEFUL        # Корректное завершение
    hazelcast.graceful.shutdown.max.wait: 120      # Ждать до 120 сек при остановке
    hazelcast.cluster.version.auto.upgrade.enabled: true

  network:
    join:
      multicast:
        enabled: false
      kubernetes:
        enabled: true
        service-dns: hazelcast.default.svc.cluster.local

  partition-group:
    enabled: true
    group-type: HOST_AWARE    # Бэкапы на разных физических хостах

  split-brain-protection:
    quorum:
      enabled: true
      minimum-cluster-size: 2

  map:
    products:
      in-memory-format: BINARY
      backup-count: 2
      async-backup-count: 0
      split-brain-protection-ref: quorum
      merge-policy:
        class-name: LatestUpdateMergePolicy
        per-entry-stats-enabled: true
      indexes:
        - type: HASH
          attributes: [ "categoryId" ]

  metrics:
    enabled: true
    collection-frequency-seconds: 15
```

**Разбор ключевых параметров:**

| Параметр | Значение | Зачем |
|----------|----------|-------|
| `phone.home.enabled: false` | Отключает отправку анонимной статистики | Privacy, сетевая безопасность |
| `index.copy.behavior: COPY_ON_WRITE` | Данные копируются при записи | Чтения не блокируются — оптимально для read-heavy нагрузки |
| `shutdownhook.policy: GRACEFUL` | Корректное завершение узла | Данные мигрируют на другие узлы, а не теряются |
| `graceful.shutdown.max.wait: 120` | Максимальное время остановки | Достаточно для миграции партиций при большом объёме данных |

### Локальная конфигурация

Для локальной разработки конфигурация упрощена: один узел, TCP-IP на localhost, REST API для диагностики.

```yaml
hazelcast:
  cluster-name: dev
  network:
    join:
      multicast:
        enabled: false
      tcp-ip:
        enabled: true
        member-list:
          - localhost
  rest-api:
    enabled: true
    endpoint-groups:
      HEALTH_CHECK:
        enabled: true
```

> **Совет:** REST API полезен для быстрой диагностики: `curl http://localhost:5701/hazelcast/health/node-state`

## Клиентская конфигурация

Клиентская конфигурация определяет, как приложение подключается к кластеру.

### Production-конфигурация

```yaml
hazelcast-client:
  cluster-name: my-cluster
  instance-name: my-app

  network:
    auto-detection: false
    cluster-members:
      - hazelcast-headless.default.svc.cluster.local:5701

  connection-strategy:
    async-start: false          # Ждать подключения при старте
    reconnect-mode: ASYNC       # Переподключение в фоне
    connection-retry:
      initial-backoff-millis: 100
      max-backoff-millis: 2000
      multiplier: 2
      cluster-connect-timeout-millis: -1  # Бесконечные повторные попытки
      jitter: 0.3                         # Разброс для избежания thundering herd
```

**Разбор параметров подключения:**

| Параметр | Значение | Зачем |
|----------|----------|-------|
| `async-start: false` | Приложение не стартует без Hazelcast | Fail-fast: лучше не запуститься, чем работать без данных |
| `reconnect-mode: ASYNC` | Переподключение не блокирует потоки | Операции получат исключение, но приложение продолжит работать |
| `cluster-connect-timeout-millis: -1` | Бесконечные попытки | Кластер может быть временно недоступен при rolling update |
| `jitter: 0.3` | 30% случайного разброса | Предотвращает thundering herd — все клиенты не ломятся одновременно |

### Локальная клиентская конфигурация

```yaml
hazelcast-client:
  cluster-name: dev
  network:
    cluster-members:
      - localhost:5701
  connection-strategy:
    async-start: false
    reconnect-mode: ASYNC
```

## Java-конфигурация (программная)

### Серверная (embedded)

```java
@Configuration
class HazelcastServerConfig {

    @Bean
    Config hazelcastConfig() {
        Config config = new Config();
        config.setClusterName("my-cluster");

        // Сеть
        config.getNetworkConfig().getJoin()
            .getMulticastConfig().setEnabled(false);
        config.getNetworkConfig().getJoin()
            .getTcpIpConfig().setEnabled(true)
            .addMember("localhost");

        // Конфигурация карты
        MapConfig productsMap = new MapConfig("products");
        productsMap.setInMemoryFormat(InMemoryFormat.BINARY);
        productsMap.setBackupCount(2);
        productsMap.addIndexConfig(
            new IndexConfig(IndexType.HASH, "categoryId")
        );
        config.addMapConfig(productsMap);

        return config;
    }
}
```

### Клиентская

```java
@Configuration
class HazelcastClientConfig {

    @Bean
    ClientConfig hazelcastClientConfig() {
        ClientConfig config = new ClientConfig();
        config.setClusterName("my-cluster");
        config.getNetworkConfig()
            .addAddress("localhost:5701");
        return config;
    }
}
```

## Spring Boot автоконфигурация

Spring Boot автоматически создаёт `HazelcastInstance`, если Hazelcast есть в classpath. Порядок поиска конфигурации:

1. Бин `ClientConfig` → создаёт клиентский инстанс
2. Свойство `spring.hazelcast.config` → загружает указанный файл
3. Системное свойство `hazelcast.client.config`
4. Файл `hazelcast-client.yaml` в classpath
5. Бин `Config` → создаёт embedded-инстанс
6. Файл `hazelcast.yaml` в classpath

### Указание файла конфигурации

```yaml
# application.yaml
spring:
  hazelcast:
    config: classpath:hazelcast-client.yaml
```

### Профили для разных окружений

```yaml
# application.yaml (общие настройки)
spring:
  hazelcast:
    config: classpath:hazelcast-client.yaml

---
# application-local.yaml
spring:
  hazelcast:
    config: classpath:hazelcast-client-local.yaml
```

### HazelcastConfigCustomizer

Если нужно добавить настройки поверх файла конфигурации (например, зарегистрировать сериализаторы), используй `HazelcastConfigCustomizer`:

```java
@Configuration
class HazelcastCustomization {

    @Bean
    HazelcastConfigCustomizer hazelcastConfigCustomizer() {
        return config -> {
            // Регистрация классов для Compact Serialization
            config.getSerializationConfig()
                .getCompactSerializationConfig()
                .addClass(ProductValue.class)
                .addClass(OrderValue.class);
        };
    }
}
```

> **Важно:** `HazelcastConfigCustomizer` применяется **до** создания `HazelcastInstance`. Это правильный способ программно дополнить YAML-конфигурацию в Spring Boot.

## Типизированные бины для IMap

Хорошая практика — создавать отдельный Spring Bean для каждой карты с типизацией:

```java
@Configuration
class HazelcastMapsConfig {

    @Bean
    IMap<String, ProductValue> productsMap(HazelcastInstance hazelcast) {
        return hazelcast.getMap("products");
    }

    @Bean
    IMap<Long, OrderValue> ordersMap(HazelcastInstance hazelcast) {
        return hazelcast.getMap("orders");
    }

    @Bean
    IMap<String, String> sessionsMap(HazelcastInstance hazelcast) {
        return hazelcast.getMap("sessions");
    }
}
```

**Что это даёт:**

- Compile-time безопасность типов — невозможно положить `String` вместо `ProductValue`
- Явные зависимости — адаптер в конструкторе получает конкретную типизированную карту
- Удобство тестирования — можно подменить конкретную карту через `@MockitoSpyBean`

```java
// Адаптер с явной зависимостью
@Component
class ProductCacheAdapter {
    private final IMap<String, ProductValue> productsMap;

    ProductCacheAdapter(IMap<String, ProductValue> productsMap) {
        this.productsMap = productsMap;
    }
}
```

## Практика

1. Создай Spring Boot проект с зависимостью `hazelcast` и `hazelcast-spring`
2. Создай файл `hazelcast-client-local.yaml` для подключения к локальному серверу
3. Настрой `spring.hazelcast.config` в `application-local.yaml`
4. Создай `HazelcastConfigCustomizer`, который регистрирует Compact Serialization для одного класса
5. Создай типизированный бин `IMap<String, String>` и напиши REST-контроллер, который кладёт и читает данные
6. Добавь второй профиль с embedded-конфигурацией и проверь, что приложение работает в обоих режимах
7. Создай серверную конфигурацию с двумя картами, разными `backup-count` и индексом на одной из карт

## Итоги урока

- Hazelcast конфигурируется через YAML/XML, Java Config или Spring Boot автоконфигурацию
- Серверная конфигурация определяет кластер, карты, бэкапы, индексы; клиентская — подключение и стратегию reconnect
- `COPY_ON_WRITE` для индексов оптимален при read-heavy нагрузке
- `async-start: false` + `reconnect-mode: ASYNC` — рекомендуемая стратегия подключения для production
- `HazelcastConfigCustomizer` — правильный способ программно дополнить YAML-конфигурацию в Spring Boot
- Типизированные бины `IMap<K, V>` обеспечивают compile-time безопасность и удобство тестирования
- Для разных окружений используй Spring-профили с разными файлами конфигурации