# Урок 11. Мониторинг и метрики

## Зачем мониторить Hazelcast

Hazelcast хранит данные в оперативной памяти. Без мониторинга ты не узнаешь о проблемах, пока не станет поздно:

- Память заканчивается → OOM → потеря данных
- Латентность растёт → деградация приложения
- Бэкапы не реплицируются → потеря отказоустойчивости
- Блокировки держатся слишком долго → deadlock-подобное поведение

## Встроенные метрики Hazelcast

### Включение метрик

```yaml
# hazelcast.yaml (серверная конфигурация)
hazelcast:
  metrics:
    enabled: true
    collection-frequency-seconds: 15
    management-center:
      enabled: true
    jmx:
      enabled: true
```

### Ключевые метрики карт

| Метрика | Описание | На что обращать внимание |
|---------|----------|------------------------|
| `map.ownedEntryCount` | Количество записей на ноде | Равномерное распределение между нодами |
| `map.ownedEntryMemoryCost` | Потребление памяти (байт) | Рост без eviction → OOM |
| `map.backupEntryCount` | Количество бэкап-записей | Должно быть `ownedEntryCount * backup-count` |
| `map.putCount` / `map.setCount` | Количество put- / set-операций | Аномальные всплески. Урок 8 рекомендует `set()` вместо `put()` — если адаптер написан по этой рекомендации, смотри `setCount`, не `putCount` |
| `map.getCount` | Количество get-операций | Ratio get/put показывает read-heaviness |
| `map.totalPutLatency` / `map.totalSetLatency` | Суммарное время put- / set-операций (мс) | Рост = проблемы с сетью или GC |
| `map.totalGetLatency` | Суммарное время get (мс) | Рост = проблемы с десериализацией или сетью |
| `map.lockedEntryCount` | Количество залоченных ключей | Рост = потенциальные deadlock-и |
| `map.hits` | Количество успешных чтений | Сравнивай с `getCount`: `hits / getCount` = hit rate |
| `map.evictionCount` | Количество вытесненных записей | Если eviction > 0, данные не помещаются |

> **Внимание:** префикс метрики — это `map`, `cluster`, `gc`, без `hazelcast.` впереди (имена берутся из `MetricDescriptorConstants`: `MAP_PREFIX = "map"`, `CLUSTER_PREFIX = "cluster"`). И у IMap **нет** метрики `misses` — есть только `hits`, поэтому hit rate считай как `hits / getCount`. Метрика `misses` существует у Near Cache (`map.nearcache.misses`) и у JCache (`cacheMisses`), но не у самой карты.

### Метрики кластера

| Метрика | Описание |
|---------|----------|
| `cluster.size` | Количество членов кластера |
| `partitions.completedMigrations` / `partitions.plannedMigrations` | Миграции партиций (префикс `partitions`, не `partition`) |
| `tcp.connection.activeCount` / `client.endpoint.count` | Активные соединения и подключённые клиенты |
| `gc.minorCount` / `majorCount` | Количество GC-пауз |
| `gc.minorTime` / `majorTime` | Время GC-пауз |

## Интеграция с Micrometer и Prometheus

### Spring Boot + Micrometer

Само по себе наличие Hazelcast в classpath метрик не даёт: Spring Boot автоматически биндит только кэши, которыми управляет абстракция Spring Cache (`@Cacheable` + `HazelcastCacheManager`). Если ты работаешь с `IMap` напрямую — как во всём этом курсе, — карту нужно зарегистрировать в реестре руками через биндер `HazelcastCacheMetrics` из `micrometer-core`.

```groovy
dependencies {
    implementation 'com.hazelcast:hazelcast:5.7.0'
    implementation 'io.micrometer:micrometer-registry-prometheus'
    implementation 'org.springframework.boot:spring-boot-starter-actuator'
}
```

```java
@Bean
IMap<String, ProductValue> productsMap(HazelcastInstance hazelcast, MeterRegistry registry) {
    IMap<String, ProductValue> map = hazelcast.getMap("products");
    // Биндер снимает LocalMapStats карты и публикует их как метрики cache_*
    HazelcastCacheMetrics.monitor(registry, map, "cache", "products");
    return map;
}
```

```yaml
# application.yaml
management:
  endpoints:
    web:
      exposure:
        include: health, prometheus, metrics
  metrics:
    tags:
      application: my-app
```

Метрики доступны по `/actuator/prometheus` с префиксом `cache_` и тегом `cache="products"`:

```bash
curl -s http://localhost:8080/actuator/prometheus | grep '^cache_'
# cache_size{cache="products"} ...
# cache_gets_total{cache="products",result="hit"} ...
# cache_puts_total{cache="products"} ...
# cache_entries{cache="products",ownership="owned"} ...
# cache_gets_latency_seconds_count{cache="products"} ...
```

> **Внимание:** `grep hazelcast` по `/actuator/prometheus` не найдёт ничего — имена метрик начинаются с `cache_`.

> **Внимание:** на **клиентском** инстансе эти метрики всегда нулевые. Не «неполные», а ровно нули: после 10 000 `put` и 10 000 `get` через клиент `cache_size`, `cache_puts_total`, `cache_gets_total`, `cache_entries` остаются `0.0`, потому что `LocalMapStats` у клиента считает только то, что хранится локально, а не хранится ничего. На embedded-члене те же метрики дают `10000.0`. Поскольку курс с урока 1 работает через `HazelcastClient`, не жди здесь цифр — для клиентской стороны меряй свои метрики на адаптере (`@Timed`, урок 8), а статистику карт снимай на узлах.

### Кастомные метрики приложения

Помимо встроенных метрик Hazelcast, добавь метрики на уровне адаптера:

```java
@Component
@Timed(value = "cache_port", extraTags = {"port", "ProductPort", "module", "catalog"})
class ProductHazelcastAdapter implements ProductPort {
    // Каждый метод получает метрику:
    // cache_port_seconds{port="ProductPort", module="catalog", method="findById"}
}
```

> **Внимание:** «автоматически» тут не работает. Аннотацию обрабатывает аспект `TimedAspect`, которого в Spring Boot 4 по умолчанию нет, — с одним лишь `@Timed` метрик `cache_port*` не появится вовсе, молча. Нужен AOP на classpath (`org.springframework.boot:spring-boot-starter-aspectj`) плюс либо бин `TimedAspect`, либо свойство `management.observations.annotations.enabled=true` (по нему условна автоконфигурация `MetricsAspectsAutoConfiguration`). Подробности и код бина — в уроке 8.

### Метрики блокировок

```java
// Время захвата блокировки
meterRegistry.timer("lock_acquisition_time",
    "namespace", namespace.name(),
    "impl", "hazelcast"
).record(acquisitionDuration);

// Время удержания блокировки
meterRegistry.timer("lock_hold_time",
    "namespace", namespace.name(),
    "impl", "hazelcast"
).record(holdDuration);

// Счётчик неудачных захватов
meterRegistry.counter("lock_acquisition_failed",
    "namespace", namespace.name()
).increment();
```

## Health Checks

### REST API (локальная разработка)

В стоковом образе `hazelcast/hazelcast:5.7.0` REST уже включён — его `hazelcast-docker.xml` содержит `<rest-api enabled="true">` с группой `HEALTH_CHECK`, поэтому curl ниже работает сразу после `docker run`. А вот в чистом `Config` и в собственном YAML REST **выключен**: подсунув узлу свой конфиг (урок 3), ты потеряешь эти эндпоинты, и первый же curl оставит в логе `IllegalStateException: REST API is not enabled`. В своём YAML включай явно:

```yaml
hazelcast:
  network:
    rest-api:
      enabled: true
      endpoint-groups:
        HEALTH_CHECK:
          enabled: true
```

После этого:

```bash
# Состояние узла
curl http://localhost:5701/hazelcast/health/node-state
# "ACTIVE"

# Состояние кластера
curl http://localhost:5701/hazelcast/health/cluster-state
# "ACTIVE"

# Размер кластера
curl http://localhost:5701/hazelcast/health/cluster-size
# 3
```

### Spring Boot Actuator Health

Spring Boot регистрирует health indicator для Hazelcast автоматически — в Boot 3 достаточно Hazelcast в classpath, в Boot 4 нужен `spring-boot-starter-hazelcast` (автоконфигурация вынесена в отдельный модуль, см. урок 3). Детали компонентов видны только с `show-details`:

```yaml
management:
  endpoint:
    health:
      show-details: always
```

```bash
curl http://localhost:8080/actuator/health
```

```json
{
  "status": "UP",
  "components": {
    "hazelcast": {
      "status": "UP",
      "details": {
        "name": "hz.client_1",
        "uuid": "11ab3b2e-1012-47a5-81e6-e62257aac5e9"
      }
    }
  }
}
```

> Индикатор отдаёт только имя и UUID инстанса — размера кластера в нём нет. Он проверяет факт живого соединения: если инстанс остановлен, статус станет `DOWN`. Размер кластера бери из REST API (`/hazelcast/health/cluster-size`) или из метрик.

### Kubernetes probes

```yaml
# StatefulSet для Hazelcast-серверов
containers:
  - name: hazelcast
    livenessProbe:
      httpGet:
        path: /hazelcast/health/node-state
        port: 5701
      initialDelaySeconds: 30
      periodSeconds: 10
    readinessProbe:
      httpGet:
        path: /hazelcast/health/ready
        port: 5701
      initialDelaySeconds: 15
      periodSeconds: 5
```

## Management Center

**Hazelcast Management Center** — бесплатный GUI для мониторинга и управления кластером.

### Запуск

```bash
docker run -d --name hazelcast-mc \
  --network hz-net \
  -p 8080:8080 \
  -e MC_DEFAULT_CLUSTER=dev \
  -e MC_DEFAULT_CLUSTER_MEMBERS=hz-1 \
  hazelcast/management-center:5.11.0
```

В логе должно появиться `MC Client connected to cluster dev`.

### Возможности

| Функция | Описание |
|---------|----------|
| Обзор кластера | Узлы, партиции, подключения |
| Мониторинг карт | Размер, hit rate, put/get counts, latency |
| Просмотр данных | Запросы к картам через UI |
| Slow operations | Операции, превысившие порог времени |
| Thread dump | Дампы потоков всех узлов |
| Prometheus exporter | Метрики в формате Prometheus — **только Enterprise**, без лицензии `/metrics` отдаёт HTTP 402 `LICENSE_REQUIRED` |

### Подключение кластера к Management Center

```yaml
# hazelcast.yaml
hazelcast:
  management-center:
    scripting-enabled: false   # Безопасность: отключить скрипты
    console-enabled: false     # Безопасность: отключить консоль
```

> **Внимание:** сам по себе кластер в Management Center не появится, даже если оба контейнера в одной сети. При старте без настройки в логе будет `Connecting to 0 enabled cluster(s) on startup` и пустой UI. Указывай кластер явно — переменными `MC_DEFAULT_CLUSTER` / `MC_DEFAULT_CLUSTER_MEMBERS` (как выше) либо руками через «Add Cluster Config» в UI.

## Алерты: что мониторить

### Критичные алерты

| Условие | Алерт | Действие |
|---------|-------|---------|
| `cluster.size` < ожидаемого | Узел кластера упал | Проверить pod, перезапустить |
| `ownedEntryMemoryCost` > 80% heap | Память заканчивается | Scale up или настроить eviction |
| `lockedEntryCount` растёт | Блокировки не освобождаются | Проверить lease time, thread dump |
| `partitions.completedMigrations` растёт | Частая перебалансировка | Нестабильный кластер, проверить сеть |
| Health check != ACTIVE | Узел не готов | Проверить логи |

### Предупреждения

| Условие | Алерт |
|---------|-------|
| `totalPutLatency` / `putCount` > 10 мс (или `totalSetLatency` / `setCount`, если адаптер пишет через `set()`) | Высокая латентность записи |
| `evictionCount` > 0 | Данные вытесняются |
| `gc.majorTime` > 1000 мс | Длинные GC-паузы |
| `backupEntryCount` != ожидаемому | Бэкапы не реплицируются |
| hit rate < 50% | Кэш неэффективен |

### Grafana Dashboard (пример PromQL)

```
# Количество записей по картам
hazelcast_map_ownedEntryCount{map="products"}

# Средняя латентность get (мс)
rate(hazelcast_map_totalGetLatency[5m]) / rate(hazelcast_map_getCount[5m])

# Hit rate (%) — метрики misses у IMap нет, знаменатель это getCount
rate(hazelcast_map_hits[5m]) / rate(hazelcast_map_getCount[5m]) * 100

# Память карт (MB)
hazelcast_map_ownedEntryMemoryCost / 1024 / 1024

# Размер кластера
hazelcast_cluster_size
```

> **Внимание:** имена выше — это метрики **серверного** экспорта Hazelcast, а не те `cache_*`, что отдаёт Micrometer из твоего приложения (см. выше). Получить их из Community-редакции неоткуда: Prometheus exporter Management Center закрыт лицензией — `GET :8080/metrics` отвечает `HTTP 402` с телом `{"error":{"type":"LICENSE_REQUIRED","message":"License is not configured!"}}`. Без Enterprise-лицензии строй дашборд на метриках `cache_*` из приложения или снимай метрики узлов через JMX.

## Dynamic Diagnostic Logging (5.6+)

Hazelcast Platform 5.6 добавил возможность включать/выключать диагностическое логирование без рестарта кластера. Ранее для этого требовался рестарт.

Управление через Management Center 5.9+ (бета; GA — начиная с Management Center 5.11) или Platform Operator 5.16+:

- Включение/выключение diagnostic logging
- Настройка уровня детализации
- Управление через REST API или UI

> Полезно для отладки проблем в production без downtime.

> **Внимание:** в Docker и Kubernetes включить динамическую диагностику с выводом в файл не получится — каталог логов по умолчанию read-only. Направляй вывод в STDOUT либо заранее монтируй writable-том.

## Практика

1. Зарегистрируй карту через `HazelcastCacheMetrics.monitor(...)` и найди метрики `cache_*` в `/actuator/prometheus`
2. Добавь `@Timed` на адаптер и проверь кастомные метрики
3. Запусти Management Center и подключи к нему кластер
4. Создай нагрузку (10 000 put + get операций) и посмотри метрики в Management Center. В `/actuator/prometheus` своего приложения при этом будут нули, если оно подключается клиентом — см. предупреждение выше
5. Настрой Kubernetes liveness и readiness probes для Hazelcast
6. Создай Grafana dashboard с 5 ключевыми метриками (entry count, memory, latency, hit rate, cluster size)
7. Настрой алерт в Prometheus/Grafana на условие `cluster.size < 3`

## Итоги урока

- Встроенные метрики Hazelcast покрывают карты (`map.*`), кластер (`cluster.*`) и GC (`gc.*`) — без префикса `hazelcast.`
- Метрики `IMap` в Micrometer не появляются сами — карту регистрируют биндером `HazelcastCacheMetrics.monitor(...)`, метрики выходят с префиксом `cache_`
- `@Timed` на адаптерах добавляет метрики на уровне бизнес-операций
- Health checks: REST API для серверов, Spring Actuator для приложений, probes для Kubernetes
- Management Center — бесплатный GUI для мониторинга карт, операций и thread dumps; его Prometheus exporter требует Enterprise-лицензии
- Критичные алерты: размер кластера, потребление памяти, залоченные записи
- Dynamic Diagnostic Logging (5.6+) позволяет включать отладку без рестарта
- Hit rate < 50% сигнализирует о неэффективном кэше — пересмотри TTL и eviction