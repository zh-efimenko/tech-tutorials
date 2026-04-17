# Урок 12. Продвинутые возможности

## Обзор

Hazelcast предоставляет набор продвинутых возможностей, которые решают специфические задачи: атомарное обновление данных, локальное кэширование, pub/sub, персистентность, строгие гарантии консистентности. Этот урок — обзор каждой возможности с примерами.

## EntryProcessor — атомарная обработка на сервере

### Проблема: get → modify → put

```java
// ❌ Три сетевых вызова, не атомарно
ProductValue value = map.get(key);                // 1. Чтение
ProductValue updated = new ProductValue(           // 2. Модификация
    value.categoryId(), "Новое имя", value.status(), value.price(), value.description()
);
map.put(key, updated);                             // 3. Запись
// Между get и put другой процесс мог изменить данные!
```

### Решение: EntryProcessor

EntryProcessor выполняется **на стороне сервера**, рядом с данными. Один сетевой вызов, атомарная операция.

```java
public class UpdateStatusProcessor
    implements EntryProcessor<String, ProductValue, Void> {

    private final String newStatus;

    public UpdateStatusProcessor(String newStatus) {
        this.newStatus = newStatus;
    }

    @Override
    public Void process(Map.Entry<String, ProductValue> entry) {
        ProductValue value = entry.getValue();
        if (value != null) {
            entry.setValue(new ProductValue(
                value.categoryId(), value.name(), newStatus,
                value.price(), value.description()
            ));
        }
        return null;
    }
}
```

Использование:

```java
// Одна операция: 1 network call, атомарно
map.executeOnKey("prod-1", new UpdateStatusProcessor("SUSPENDED"));

// Batch: обработать все записи по набору ключей
map.executeOnKeys(Set.of("prod-1", "prod-2", "prod-3"),
    new UpdateStatusProcessor("SUSPENDED"));

// Все записи по предикату
map.executeOnEntries(
    new UpdateStatusProcessor("SUSPENDED"),
    Predicates.equal("categoryId", 42L)
);
```

**Когда использовать:**

- Read-modify-write паттерн (замена get + put)
- Когда значение большое и передача по сети дорогая
- Когда нужна атомарность без distributed lock

> **Важно:** EntryProcessor должен быть сериализуемым (Compact или IdentifiedDataSerializable), так как он передаётся на сервер.

## Near Cache — локальный L1-кэш

Near Cache — кэш на стороне клиента. При повторном чтении того же ключа данные берутся из памяти клиента без сетевого вызова.

```
Без Near Cache:              С Near Cache:
Client ──get──► Server       Client ──get──► Local Cache (hit!)
       ◄─────── response             │
                                     └──miss──► Server
```

### Конфигурация

```yaml
# hazelcast-client.yaml
hazelcast-client:
  near-cache:
    products:
      in-memory-format: OBJECT          # Десериализованный объект
      invalidate-on-change: true        # Инвалидация при изменении на сервере
      time-to-live-seconds: 30
      max-idle-seconds: 10
      eviction:
        size: 10000
        max-size-policy: ENTRY_COUNT
        eviction-policy: LRU
```

### Когда использовать

| Подходит | Не подходит |
|---------|------------|
| Read-heavy данные (каталоги, конфигурации) | Данные, меняющиеся каждую секунду |
| Допустима eventual consistency | Требуется строгая консистентность |
| Много повторных чтений одних ключей | Каждый раз читаются разные ключи |

> **Внимание:** Near Cache = eventual consistency. Между изменением на сервере и инвалидацией кэша на клиенте есть задержка (миллисекунды). Для финансовых данных это может быть неприемлемо.

## ITopic — Pub/Sub

Распределённый pub/sub внутри кластера. Все подписчики на всех инстансах получают сообщение.

```java
ITopic<String> topic = hazelcast.getTopic("config-updates");

// Публикация
topic.publish("margin-changed");

// Подписка (на всех инстансах)
topic.addMessageListener(message -> {
    String event = message.getMessageObject();
    refreshConfig(event);
});
```

### Reliable Topic

Обычный `ITopic` может потерять сообщения при сетевых проблемах. **Reliable Topic** использует Ringbuffer и гарантирует доставку:

```java
ITopic<String> topic = hazelcast.getReliableTopic("config-updates");
```

### Применение

- Инвалидация локальных кэшей при изменении данных
- Broadcast-уведомления всем инстансам ("обновить конфигурацию")
- Замена Kafka для internal-events (без персистентности)

## EntryListener — реакция на изменения карты

Реактивное реагирование на события в IMap:

```java
productsMap.addEntryListener(new EntryAddedListener<String, ProductValue>() {
    @Override
    public void entryAdded(EntryEvent<String, ProductValue> event) {
        log.info("Новый товар: key={}, value={}", event.getKey(), event.getValue());
        notifier.notify(event.getValue());
    }
}, /* includeValue */ true);
```

### Типы событий

| Listener | Событие |
|----------|---------|
| `EntryAddedListener` | Новая запись |
| `EntryUpdatedListener` | Обновление |
| `EntryRemovedListener` | Удаление |
| `EntryExpiredListener` | Истечение TTL |
| `EntryEvictedListener` | Вытеснение по eviction |
| `MapListener` | Все события |

### Применение

- Push-обновления по WebSocket
- Логирование изменений для аудита
- Триггеры бизнес-логики (heartbeat expired → alert)

> **Важно:** `includeValue: true` отправляет значение вместе с событием. Если значения большие и не нужны — используй `false` для экономии трафика.

## MapStore / MapLoader — персистентность

Автоматическая синхронизация IMap с внешним хранилищем (БД, файловая система).

```java
public class ProductMapStore implements MapStore<String, ProductValue> {

    private final JdbcTemplate jdbc;

    @Override
    public ProductValue load(String key) {
        // Read-through: загрузить из БД если нет в кэше
        return jdbc.queryForObject(
            "SELECT * FROM products WHERE id = ?",
            productRowMapper, key
        );
    }

    @Override
    public void store(String key, ProductValue value) {
        // Write-through: сохранить в БД при записи в кэш
        jdbc.update(
            "INSERT INTO products (id, name, price) VALUES (?, ?, ?) " +
            "ON CONFLICT (id) DO UPDATE SET name = ?, price = ?",
            key, value.name(), value.price().amount(),
            value.name(), value.price().amount()
        );
    }

    @Override
    public void delete(String key) {
        jdbc.update("DELETE FROM products WHERE id = ?", key);
    }

    @Override
    public Map<String, ProductValue> loadAll(Collection<String> keys) {
        // Batch load при старте кластера
        // ...
    }

    @Override
    public Iterable<String> loadAllKeys() {
        // Вызывается при старте для предзагрузки всех ключей
        return jdbc.queryForList("SELECT id FROM products", String.class);
    }
}
```

### Конфигурация

```yaml
map:
  products:
    map-store:
      class-name: com.example.ProductMapStore
      write-delay-seconds: 5       # Write-behind: пакетная запись каждые 5 сек
      write-batch-size: 100        # Макс. записей в одном batch
      write-coalescing: true       # Несколько записей одного ключа → одна запись в БД
```

### Режимы

| Режим | Конфигурация | Описание |
|-------|-------------|----------|
| Write-through | `write-delay-seconds: 0` | Сразу пишет в БД при каждой записи в кэш |
| Write-behind | `write-delay-seconds: > 0` | Пакетная запись через указанный интервал |
| Read-through | Автоматически | Загружает из БД при `get()`, если нет в кэше |

> **Write-behind + coalescing**: Если ключ обновлён 10 раз за 5 секунд — в БД запишется только последнее значение. Существенная оптимизация для hot keys.

## CP Subsystem — строгие гарантии (Raft)

Обычные структуры Hazelcast — **AP** (Available, Partition-tolerant) по CAP-теореме. CP Subsystem предоставляет **CP** (Consistent, Partition-tolerant) структуры, основанные на алгоритме Raft.

### Атомарный счётчик

```java
CPSubsystem cpSubsystem = hazelcast.getCPSubsystem();
IAtomicLong counter = cpSubsystem.getAtomicLong("order-counter");
long nextId = counter.incrementAndGet(); // Линеаризуемый!
```

### Fenced Lock

Строже, чем `IMap.tryLock`:

```java
FencedLock lock = cpSubsystem.getLock("critical-operation");
long fence = lock.lockAndGetFence();

try {
    // fence value гарантирует порядок операций
    // Если zombie-процесс держит старый fence — его операции будут отклонены
    processWithFence(fence);
} finally {
    lock.unlock();
}
```

### Semaphore

```java
ISemaphore semaphore = cpSubsystem.getSemaphore("rate-limiter");
// Максимум 5 одновременных операций
semaphore.tryAcquire(5, 10, TimeUnit.SECONDS);
```

### Когда CP вместо IMap

| Критерий | IMap (AP) | CP Subsystem |
|----------|----------|--------------|
| Гарантии | Eventual consistency | Linearizability |
| При split-brain | Обе стороны работают | Только мажорити |
| Скорость | Быстрее | Медленнее (Raft consensus) |
| Когда | Кэш, сессии, heartbeat-ы | Финансовые операции, ID-генерация |

> CP Subsystem требует минимум 3 CP-членов и работает медленнее (каждая операция проходит через Raft consensus). Используй только когда AP-гарантий недостаточно.

## Aggregations — серверные агрегации

Агрегации выполняются на сервере без загрузки данных на клиент:

```java
// Количество активных товаров
long count = productsMap.aggregate(
    Aggregators.count(),
    Predicates.equal("status", "ACTIVE")
);

// Средняя цена в категории
double avgPrice = productsMap.aggregate(
    Aggregators.doubleAvg("price.amount"),
    Predicates.equal("categoryId", 42L)
);

// Максимальная цена
long maxPrice = productsMap.aggregate(
    Aggregators.longMax("price.amount")
);

// Уникальные значения
Set<String> statuses = productsMap.aggregate(
    Aggregators.distinct("status")
);
```

## Projection — частичное чтение

Загрузка только нужных полей (аналог SQL SELECT):

```java
// Вместо загрузки всего ProductValue — только статус
Collection<String> statuses = productsMap.project(
    Projections.singleAttribute("status"),
    Predicates.equal("categoryId", 42L)
);

// Несколько полей
Collection<Object[]> nameAndPrice = productsMap.project(
    Projections.multiAttribute("name", "price.amount"),
    Predicates.equal("status", "ACTIVE")
);
```

> **Экономит трафик** когда из большого объекта нужно только одно-два поля.

## Executor Service — задачи на сервере

Выполнение задач **на стороне сервера**, рядом с данными (data locality):

```java
IExecutorService executor = hazelcast.getExecutorService("default");

// Выполнить на ноде, где лежит ключ (data locality)
executor.executeOnKeyOwner(
    new RecalculatePriceTask(productId),
    productId
);

// Выполнить на всех нодах
executor.executeOnAllMembers(new RefreshConfigTask());
```

## JSON Storage (HazelcastJsonValue)

Хранение и запросы по JSON без десериализации:

```java
IMap<String, HazelcastJsonValue> eventsMap = hazelcast.getMap("events");

eventsMap.put("event-1",
    new HazelcastJsonValue("{\"type\":\"purchase\",\"amount\":42}")
);

// SQL по JSON-полям
SqlResult result = hazelcast.getSql().execute(
    "SELECT * FROM events WHERE JSON_VALUE(this, '$.type') = 'purchase'"
);
```

> Полезно для schema-less данных или когда нужно хранить JSON "как есть".

## Сводная таблица

| Возможность | Задача | Сложность внедрения |
|-------------|--------|-------------------|
| **EntryProcessor** | Атомарное обновление без lock | Низкая |
| **Near Cache** | Ускорение read-heavy карт | Низкая (конфигурация) |
| **EntryListener** | Реакция на изменения | Низкая |
| **Aggregations** | Серверные COUNT, AVG, MAX | Низкая |
| **Projection** | Чтение отдельных полей | Низкая |
| **ITopic** | Pub/Sub между инстансами | Средняя |
| **MapStore** | Персистентность в БД | Средняя |
| **CP Subsystem** | Строгая консистентность | Высокая |
| **Executor Service** | Задачи на стороне сервера | Средняя |

## Практика

1. Реализуй EntryProcessor, который обновляет статус товара — сравни производительность с get+put
2. Настрой Near Cache для карты с read-heavy нагрузкой — замерь latency до и после
3. Добавь EntryListener, который логирует все добавления и обновления в карте
4. Реализуй MapStore с write-behind в PostgreSQL — положи данные в IMap и проверь, что они появились в БД
5. Используй Aggregations: посчитай количество, среднюю и максимальную цену товаров
6. Используй Projection: загрузи только имена товаров без остальных полей
7. Создай ITopic и отправь сообщение — убедись, что все подписчики получили его
8. Настрой CP Subsystem с 3 членами и создай атомарный счётчик

## Итоги урока

- EntryProcessor выполняет атомарное обновление на сервере за один сетевой вызов — замена get+modify+put
- Near Cache — L1-кэш на клиенте для read-heavy данных, но обеспечивает только eventual consistency
- ITopic и Reliable Topic — pub/sub внутри кластера для broadcast-событий и инвалидации кэшей
- EntryListener реактивно реагирует на добавление, обновление, удаление и expiry записей
- MapStore обеспечивает read-through и write-behind персистентность в БД без изменения клиентского кода
- CP Subsystem (Raft) даёт линеаризуемые операции — атомарные счётчики, fenced locks, semaphores
- Aggregations и Projection экономят трафик, выполняя вычисления на сервере
- Выбор между AP (IMap) и CP (CP Subsystem) зависит от требований к консистентности и допустимой латентности