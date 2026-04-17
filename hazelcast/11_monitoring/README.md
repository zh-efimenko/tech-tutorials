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
| `hazelcast.map.ownedEntryCount` | Количество записей на ноде | Равномерное распределение между нодами |
| `hazelcast.map.ownedEntryMemoryCost` | Потребление памяти (байт) | Рост без eviction → OOM |
| `hazelcast.map.backupEntryCount` | Количество бэкап-записей | Должно быть `ownedEntryCount * backup-count` |
| `hazelcast.map.putCount` | Количество put-операций | Аномальные всплески |
| `hazelcast.map.getCount` | Количество get-операций | Ratio get/put показывает read-heaviness |
| `hazelcast.map.totalPutLatency` | Суммарное время put (мс) | Рост = проблемы с сетью или GC |
| `hazelcast.map.totalGetLatency` | Суммарное время get (мс) | Рост = проблемы с десериализацией или сетью |
| `hazelcast.map.lockedEntryCount` | Количество залоченных ключей | Рост = потенциальные deadlock-и |
| `hazelcast.map.hits` | Количество успешных чтений | hits / (hits + misses) = hit rate |
| `hazelcast.map.evictionCount` | Количество вытесненных записей | Если eviction > 0, данные не помещаются |

### Метрики кластера

| Метрика | Описание |
|---------|----------|
| `hazelcast.member.count` | Количество членов кластера |
| `hazelcast.partition.migrationCount` | Количество миграций партиций |
| `hazelcast.connection.activeCount` | Количество активных клиентских подключений |
| `hazelcast.gc.minorCount` / `majorCount` | Количество GC-пауз |
| `hazelcast.gc.minorTime` / `majorTime` | Время GC-пауз |

## Интеграция с Micrometer и Prometheus

### Spring Boot + Micrometer

Spring Boot автоматически экспортирует метрики Hazelcast через Micrometer, если оба в classpath:

```groovy
dependencies {
    implementation 'com.hazelcast:hazelcast:5.6.0'
    implementation 'io.micrometer:micrometer-registry-prometheus'
    implementation 'org.springframework.boot:spring-boot-starter-actuator'
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

Метрики доступны по `/actuator/prometheus`:

```bash
curl http://localhost:8080/actuator/prometheus | grep hazelcast
```

### Кастомные метрики приложения

Помимо встроенных метрик Hazelcast, добавь метрики на уровне адаптера:

```java
@Component
@Timed(value = "cache_port", extraTags = {"port", "ProductPort", "module", "catalog"})
class ProductHazelcastAdapter implements ProductPort {
    // Каждый метод автоматически получает метрику:
    // cache_port_seconds{port="ProductPort", module="catalog", method="findById"}
}
```

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

Если REST API включён в серверной конфигурации:

```bash
# Состояние узла
curl http://localhost:5701/hazelcast/health/node-state
# ACTIVE

# Состояние кластера
curl http://localhost:5701/hazelcast/health/cluster-state
# ACTIVE

# Размер кластера
curl http://localhost:5701/hazelcast/health/cluster-size
# 3
```

### Spring Boot Actuator Health

Hazelcast автоматически регистрирует health indicator в Spring Boot:

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
        "name": "my-cluster",
        "clusterSize": 3
      }
    }
  }
}
```

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
  -p 8080:8080 \
  hazelcast/management-center:5.9.0
```

### Возможности

| Функция | Описание |
|---------|----------|
| Обзор кластера | Узлы, партиции, подключения |
| Мониторинг карт | Размер, hit rate, put/get counts, latency |
| Просмотр данных | Запросы к картам через UI |
| Slow operations | Операции, превысившие порог времени |
| Thread dump | Дампы потоков всех узлов |
| Prometheus exporter | Метрики в формате Prometheus |

### Подключение кластера к Management Center

```yaml
# hazelcast.yaml
hazelcast:
  management-center:
    scripting-enabled: false   # Безопасность: отключить скрипты
    console-enabled: false     # Безопасность: отключить консоль
```

Кластер автоматически обнаруживается Management Center, если оба в одной сети.

## Алерты: что мониторить

### Критичные алерты

| Условие | Алерт | Действие |
|---------|-------|---------|
| `member.count` < ожидаемого | Узел кластера упал | Проверить pod, перезапустить |
| `ownedEntryMemoryCost` > 80% heap | Память заканчивается | Scale up или настроить eviction |
| `lockedEntryCount` растёт | Блокировки не освобождаются | Проверить lease time, thread dump |
| `partition.migrationCount` растёт | Частая перебалансировка | Нестабильный кластер, проверить сеть |
| Health check != ACTIVE | Узел не готов | Проверить логи |

### Предупреждения

| Условие | Алерт |
|---------|-------|
| `totalPutLatency` / `putCount` > 10 мс | Высокая латентность записи |
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

# Hit rate (%)
rate(hazelcast_map_hits[5m]) / (rate(hazelcast_map_hits[5m]) + rate(hazelcast_map_misses[5m])) * 100

# Память карт (MB)
hazelcast_map_ownedEntryMemoryCost / 1024 / 1024

# Размер кластера
hazelcast_member_count
```

## Dynamic Diagnostic Logging (5.6+)

Hazelcast Platform 5.6 добавил возможность включать/выключать диагностическое логирование без рестарта кластера. Ранее для этого требовался рестарт.

Управление через Management Center 5.9+ или Platform Operator 5.16+:

- Включение/выключение diagnostic logging
- Настройка уровня детализации
- Управление через REST API или UI

> Полезно для отладки проблем в production без downtime.

## Практика

1. Включи метрики Hazelcast и проверь их через `/actuator/prometheus`
2. Добавь `@Timed` на адаптер и проверь кастомные метрики
3. Запусти Management Center и подключи к нему кластер
4. Создай нагрузку (10 000 put + get операций) и посмотри метрики в Management Center
5. Настрой Kubernetes liveness и readiness probes для Hazelcast
6. Создай Grafana dashboard с 5 ключевыми метриками (entry count, memory, latency, hit rate, cluster size)
7. Настрой алерт в Prometheus/Grafana на условие `member.count < 3`

## Итоги урока

- Встроенные метрики Hazelcast покрывают карты (entry count, memory, latency), кластер (member count, migrations) и GC
- Spring Boot + Micrometer автоматически экспортирует метрики через `/actuator/prometheus`
- `@Timed` на адаптерах добавляет метрики на уровне бизнес-операций
- Health checks: REST API для серверов, Spring Actuator для приложений, probes для Kubernetes
- Management Center — бесплатный GUI для мониторинга карт, операций и thread dumps
- Критичные алерты: размер кластера, потребление памяти, залоченные записи
- Dynamic Diagnostic Logging (5.6+) позволяет включать отладку без рестарта
- Hit rate < 50% сигнализирует о неэффективном кэше — пересмотри TTL и eviction