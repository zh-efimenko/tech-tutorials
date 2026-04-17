# Урок 4. IMap — основная структура данных

## Что такое IMap

`IMap<K, V>` — распределённая реализация `java.util.concurrent.ConcurrentMap`. Это основная и наиболее используемая структура данных в Hazelcast. Данные **партиционированы** по ключу — каждая запись хранится на одном узле (owner) с репликами (backups) на других.

```
Cluster: [Node1] [Node2] [Node3]

IMap "products":
  key "prod-1" → Node1 (owner), Node2 (backup)
  key "prod-2" → Node2 (owner), Node3 (backup)
  key "prod-3" → Node3 (owner), Node1 (backup)
```

Если ты знаком с `ConcurrentHashMap` — `IMap` работает аналогично, но данные распределены по кластеру вместо одной JVM.

## Базовые операции

```java
IMap<String, Product> map = hazelcast.getMap("products");

// Запись
map.put("prod-1", new Product("Ноутбук", 99900));

// Чтение
Product product = map.get("prod-1");

// Удаление
map.remove("prod-1");

// Проверка наличия
boolean exists = map.containsKey("prod-1");

// Размер (sum по всем партициям — дорогая операция)
int size = map.size();
```

### put vs set

```java
// put — возвращает предыдущее значение (дополнительная десериализация)
Product old = map.put("prod-1", newProduct);

// set — не возвращает предыдущее значение (быстрее)
map.set("prod-1", newProduct);
```

> **Правило:** Если предыдущее значение не нужно — используй `set()` вместо `put()`. Это экономит сетевой трафик и десериализацию.

## Bulk-операции

Одиночные операции `get`/`put` в цикле — одна из самых частых ошибок при работе с Hazelcast. Каждый вызов — это сетевой round-trip (в client-server топологии).

```java
// ❌ Неправильно: N сетевых вызовов
for (String id : ids) {
    Product p = map.get(id);  // Каждый вызов = network round-trip
}

// ✅ Правильно: один сетевой вызов для N ключей
Map<String, Product> results = map.getAll(ids);
```

Доступные bulk-операции:

| Операция | Описание |
|----------|----------|
| `getAll(Set<K>)` | Чтение нескольких ключей одним вызовом |
| `putAll(Map<K,V>)` | Запись нескольких записей (триггерит события) |
| `setAll(Map<K,V>)` | Запись нескольких записей (не триггерит события, быстрее) |
| `removeAll(Predicate)` | Удаление по условию без загрузки на клиент |

> **Разница в производительности:** Для 100 записей bulk-операция может быть **10-100x** быстрее, чем цикл из одиночных вызовов.

### Пример batch-чтения и записи

```java
@Component
class ProductCacheAdapter {

    private final IMap<String, ProductValue> productsMap;
    private final ProductMapper mapper;

    // Batch-чтение
    Map<String, Product> findByIds(Set<String> ids) {
        return productsMap.getAll(ids).entrySet().stream()
            .collect(toMap(Map.Entry::getKey, e -> mapper.toDomain(e.getValue())));
    }

    // Batch-запись
    void saveAll(Map<String, Product> products) {
        Map<String, ProductValue> hzEntries = products.entrySet().stream()
            .collect(toMap(Map.Entry::getKey, e -> mapper.toHZ(e.getValue())));
        productsMap.setAll(hzEntries); // setAll — без возвращения старых значений
    }
}
```

## In-Memory Format

Формат хранения данных в памяти определяет баланс между скоростью доступа и потреблением памяти.

| Формат | Описание | Когда использовать |
|--------|----------|-------------------|
| `BINARY` | Хранится в сериализованном виде (byte[]) | По умолчанию. Минимум памяти, нет десериализации при репликации |
| `OBJECT` | Хранится как Java-объект | Много EntryProcessor/in-place обработки |
| `NATIVE` | Off-heap память (Enterprise) | Огромные объёмы данных, чтобы избежать GC |

```yaml
map:
  products:
    in-memory-format: BINARY
```

> **Рекомендация:** Для client-server топологии всегда используй `BINARY`. Серверы в основном хранят и реплицируют данные — им не нужно десериализовать объекты.

## cache-deserialized-values

```yaml
map:
  products:
    cache-deserialized-values: INDEX_ONLY
```

Контролирует, кешируются ли десериализованные объекты на сервере:

| Значение | Поведение | Потребление памяти |
|----------|-----------|-------------------|
| `NEVER` | Каждый доступ = десериализация | Минимальное |
| `INDEX_ONLY` | Кеширует только для построения индексов | Среднее |
| `ALWAYS` | Кеширует всегда | Максимальное, но быстрее доступ |

> `INDEX_ONLY` — оптимальный баланс для карт с индексами: индексы работают быстро, обычные операции не потребляют лишнюю память.

## Backup-стратегии

Hazelcast поддерживает два типа бэкапов для каждой карты:

- **Синхронный** (`backup-count`) — запись подтверждена только после репликации на backup-узлы
- **Асинхронный** (`async-backup-count`) — запись подтверждена сразу, реплика "догонит" (eventual consistency)

```yaml
map:
  # Критичные данные: строгая консистентность
  orders:
    backup-count: 2
    async-backup-count: 0

  # Read-heavy данные: достаточно одной гарантированной копии
  product-catalog:
    backup-count: 1
    async-backup-count: 1

  # Некритичные данные: максимальная скорость записи
  user-sessions:
    backup-count: 0
    async-backup-count: 2
```

**Как выбрать стратегию:**

| Тип данных | sync | async | Обоснование |
|-----------|------|-------|-------------|
| Финансовые (заказы, платежи) | 2 | 0 | Потеря данных недопустима |
| Каталоги, справочники | 1 | 1 | Баланс: одна гарантированная копия + одна eventual |
| Heartbeat-ы, сессии | 0 | 2 | Некритичны: быстро восстанавливаются |
| Временные данные с TTL | 1 | 0 | Минимальная защита, данные и так временные |

> **Ограничение:** `backup-count + async-backup-count` <= `количество узлов - 1`. На кластере из 3 узлов максимум 2 бэкапа.

## TTL — время жизни записи

TTL можно задать на уровне карты или отдельной записи.

### TTL на уровне карты

```yaml
map:
  sessions:
    time-to-live-seconds: 1800    # 30 минут
    max-idle-seconds: 600         # Удалить, если не читали 10 минут
```

### TTL на уровне записи

```java
// Запись с TTL 60 секунд — автоматическое удаление
map.put("session:abc", sessionData, 60, TimeUnit.SECONDS);

// Запись с TTL и max-idle
map.put("token:xyz", token,
    300, TimeUnit.SECONDS,    // TTL: 5 минут
    60, TimeUnit.SECONDS      // Max-idle: 1 минута без доступа
);
```

> Per-entry TTL переопределяет TTL карты. Это позволяет хранить записи с разным временем жизни в одной карте.

### Max-idle vs TTL

| Параметр | Поведение |
|----------|-----------|
| `time-to-live-seconds` | Удалить запись через N секунд **после создания** |
| `max-idle-seconds` | Удалить запись через N секунд **после последнего доступа** (get/put) |

## Eviction — вытеснение при нехватке памяти

Без eviction-политики карта будет расти до `OutOfMemoryError`. Настрой eviction для карт с неограниченным ростом данных.

```yaml
map:
  products:
    eviction:
      max-size-policy: USED_HEAP_PERCENTAGE
      max-size: 70          # Не более 70% heap
      eviction-policy: LRU  # Удалять наименее используемые
```

**Политики размера:**

| Политика | Описание |
|----------|----------|
| `PER_NODE` | Максимум записей на узел |
| `PER_PARTITION` | Максимум записей на партицию |
| `USED_HEAP_SIZE` | Максимум MB heap-памяти |
| `USED_HEAP_PERCENTAGE` | Максимум % от heap |
| `FREE_HEAP_SIZE` | Eviction когда свободной heap меньше N MB |
| `FREE_HEAP_PERCENTAGE` | Eviction когда свободной heap меньше N% |

**Политики вытеснения:**

| Политика | Описание |
|----------|----------|
| `LRU` | Least Recently Used — удаляет давно не использованные |
| `LFU` | Least Frequently Used — удаляет редко используемые |
| `RANDOM` | Случайный выбор |
| `NONE` | Без вытеснения (по умолчанию) |

## Практика

1. Создай IMap и сравни производительность `put` в цикле vs `putAll` для 1000 записей — замерь время
2. Создай карту с `backup-count: 1`, положи данные, останови один узел — убедись что данные доступны
3. Настрой TTL на уровне карты (10 секунд), положи запись и через 15 секунд проверь, что она удалена
4. Настрой per-entry TTL: положи две записи с TTL 5 и 30 секунд, проверь что первая удаляется раньше
5. Настрой eviction с `PER_NODE: 100` и `LRU`, положи 200 записей, проверь что осталось не более 100
6. Сравни `put` vs `set` для 10 000 записей — измерь разницу во времени
7. Создай две карты с разными backup-стратегиями и проверь поведение при падении узла

## Итоги урока

- `IMap<K, V>` — распределённая `ConcurrentMap`, основная структура данных Hazelcast
- Bulk-операции (`getAll`, `putAll`, `setAll`) в 10-100 раз быстрее одиночных вызовов в цикле
- `set()` быстрее `put()`, если предыдущее значение не нужно
- `BINARY` — рекомендуемый формат хранения для client-server топологии
- `cache-deserialized-values: INDEX_ONLY` — оптимальный баланс для карт с индексами
- Sync-бэкапы обеспечивают строгую консистентность, async — скорость записи
- TTL задаётся на уровне карты или записи; `max-idle-seconds` удаляет неиспользуемые записи
- Без eviction-политики карта растёт до OOM — настраивай eviction для карт с неограниченным ростом