# Урок 7. Распределённые блокировки

## Зачем нужны распределённые блокировки

В кластере из нескольких инстансов приложения `synchronized` и `ReentrantLock` бесполезны — они работают только в рамках одной JVM. Если два инстанса одновременно обрабатывают один и тот же заказ, возникнет гонка (race condition).

```
Без распределённой блокировки:

App Instance 1                 App Instance 2
     │                              │
     ├── read order #42 ──┐         │
     │                    │    ├── read order #42
     ├── modify ──────────┤    ├── modify
     ├── save ────────────┘    ├── save  ← затирает изменения Instance 1
     │                         │
```

Распределённая блокировка гарантирует, что только один инстанс одновременно работает с ресурсом.

## IMap.tryLock — блокировка на уровне ключа

Hazelcast позволяет блокировать **отдельные ключи** IMap. Это не отдельная структура данных, а механизм, встроенный в IMap.

```java
IMap<String, LockValue> lockMap = hazelcast.getMap("LOCKS");

String key = "ORDER:42";
boolean acquired = lockMap.tryLock(
    key,
    5, TimeUnit.SECONDS,     // Сколько ждать захвата
    120, TimeUnit.SECONDS    // Автоосвобождение (lease time)
);

if (acquired) {
    try {
        // Критическая секция — гарантированно один инстанс
        processOrder(42);
    } finally {
        lockMap.unlock(key);
    }
} else {
    throw new RuntimeException("Не удалось захватить блокировку: " + key);
}
```

### tryLock vs lock

```java
// ✅ Правильно: ожидание с таймаутом
lockMap.tryLock(key, 5, TimeUnit.SECONDS, 120, TimeUnit.SECONDS);

// ❌ Неправильно: бесконечное ожидание, риск deadlock
lockMap.lock(key);
```

> **Правило:** Всегда используй `tryLock` с timeout. `lock()` без таймаута — путь к deadlock-ам при сбоях.

### Lease Time (автоосвобождение)

Lease time — критически важный параметр. Если процесс упал, не успев вызвать `unlock()`, блокировка автоматически снимется через указанное время.

```java
lockMap.tryLock(key,
    5, TimeUnit.SECONDS,     // Сколько ждать
    120, TimeUnit.SECONDS    // Lease time: автоосвобождение через 120 сек
);
```

Без lease time блокировка висела бы вечно после падения процесса. Выбирай lease time больше максимального ожидаемого времени операции, но не слишком большой.

## Реализация LockProvider

Типичный паттерн — абстрагировать блокировки за интерфейсом:

```java
public interface LockProvider {
    Lock lock(String namespace, Object id, Duration timeout);
    Lock lockAll(String namespace, Collection<?> ids, Duration timeout);
}
```

```java
public class HazelcastLockProvider implements LockProvider {

    private static final Duration LEASE_TIME = Duration.ofSeconds(120);
    private final IMap<String, String> lockMap;

    public HazelcastLockProvider(HazelcastInstance hazelcast) {
        this.lockMap = hazelcast.getMap("LOCKS");
    }

    @Override
    public Lock lock(String namespace, Object id, Duration timeout) {
        String key = namespace + ":" + id;

        boolean acquired;
        try {
            acquired = lockMap.tryLock(
                key,
                timeout.toMillis(), TimeUnit.MILLISECONDS,
                LEASE_TIME.toMillis(), TimeUnit.MILLISECONDS
            );
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new LockException("Прервано ожидание блокировки: " + key, e);
        }

        if (!acquired) {
            throw new LockException("Не удалось захватить блокировку: " + key);
        }

        // AutoCloseable для try-with-resources
        return () -> lockMap.unlock(key);
    }
}
```

Использование:

```java
// try-with-resources: блокировка автоматически освобождается
try (Lock lock = lockProvider.lock("ORDER", orderId, Duration.ofSeconds(5))) {
    processOrder(orderId);
}
```

## Multi-lock с защитой от deadlock

Когда нужно заблокировать несколько ключей одновременно, порядок захвата критически важен.

```
Без сортировки — deadlock:

Thread A: lock("ORDER:1") → lock("ORDER:2")  ← ждёт Thread B
Thread B: lock("ORDER:2") → lock("ORDER:1")  ← ждёт Thread A
```

Решение: **всегда сортируй ключи** перед захватом.

```java
@Override
public Lock lockAll(String namespace, Collection<?> ids, Duration timeout) {
    // Сортировка предотвращает deadlock
    List<String> sortedKeys = ids.stream()
        .map(id -> namespace + ":" + id)
        .sorted()
        .toList();

    List<String> acquiredKeys = new ArrayList<>();

    for (String key : sortedKeys) {
        boolean acquired;
        try {
            acquired = lockMap.tryLock(
                key,
                timeout.toMillis(), TimeUnit.MILLISECONDS,
                LEASE_TIME.toMillis(), TimeUnit.MILLISECONDS
            );
        } catch (InterruptedException e) {
            // Rollback: освободить все уже захваченные
            releaseAll(acquiredKeys);
            Thread.currentThread().interrupt();
            throw new LockException("Прервано ожидание блокировки", e);
        }

        if (!acquired) {
            // Rollback: освободить все уже захваченные
            releaseAll(acquiredKeys);
            throw new LockException("Не удалось захватить блокировку: " + key);
        }

        acquiredKeys.add(key);
    }

    return () -> releaseAll(acquiredKeys);
}

private void releaseAll(List<String> keys) {
    // Освобождаем в обратном порядке
    for (int i = keys.size() - 1; i >= 0; i--) {
        lockMap.unlock(keys.get(i));
    }
}
```

## Пространства имён (Namespaces)

Ключ блокировки формируется как `NAMESPACE:ID`. Namespace предотвращает коллизии между разными модулями:

```java
// Разные модули используют разные namespace
lockProvider.lock("ORDER", 42, timeout);    // Ключ: "ORDER:42"
lockProvider.lock("PAYMENT", 42, timeout);  // Ключ: "PAYMENT:42"
lockProvider.lock("USER", 42, timeout);     // Ключ: "USER:42"
```

Рекомендуется оформить namespace как enum:

```java
public enum LockNamespace {
    ORDER, PAYMENT, USER, PRODUCT
}

// Использование
lockProvider.lock(LockNamespace.ORDER.name(), orderId, timeout);
```

## ShedLock для scheduled-задач

В кластерном окружении `@Scheduled`-задача выполняется на **каждом** инстансе. Если задача не идемпотентна (рассылка email, начисление бонусов), это приведёт к дублированию.

**ShedLock** гарантирует выполнение scheduled-задачи только на одном инстансе, используя Hazelcast как хранилище блокировок.

### Зависимость

```groovy
implementation 'net.javacrumbs.shedlock:shedlock-spring:6.2.0'
implementation 'net.javacrumbs.shedlock:shedlock-provider-hazelcast4:6.2.0'
```

### Конфигурация

```java
@EnableSchedulerLock(defaultLockAtMostFor = "PT1m")
@Configuration
class ShedLockConfig {

    @Bean
    LockProvider shedLockProvider(HazelcastInstance hazelcast) {
        return new HazelcastLockProvider(hazelcast, "SHEDLOCK");
    }
}
```

### Использование

```java
@Scheduled(fixedRate = 5000)
@SchedulerLock(name = "processExpiredSessions", lockAtMostFor = "PT1m")
void processExpiredSessions() {
    // Гарантированно выполняется только на одном инстансе
    sessionService.cleanExpired();
}
```

| Параметр | Описание |
|----------|----------|
| `lockAtMostFor` | Максимальное время удержания блокировки (защита от падения) |
| `lockAtLeastFor` | Минимальное время удержания (предотвращает повторный запуск на другом узле) |

## Метрики блокировок

Для мониторинга блокировок полезно отслеживать время захвата и удержания:

```java
public Lock lock(String namespace, Object id, Duration timeout) {
    String key = namespace + ":" + id;
    long startTime = System.nanoTime();

    boolean acquired = lockMap.tryLock(key, timeout, unit, leaseTime, unit);

    // Время ожидания захвата
    long acquisitionTime = System.nanoTime() - startTime;
    meterRegistry.timer("lock_acquisition_time",
        "namespace", namespace).record(acquisitionTime, TimeUnit.NANOSECONDS);

    if (!acquired) {
        meterRegistry.counter("lock_acquisition_failed",
            "namespace", namespace).increment();
        throw new LockException("Не удалось захватить: " + key);
    }

    // Время удержания
    long holdStart = System.nanoTime();
    return () -> {
        lockMap.unlock(key);
        meterRegistry.timer("lock_hold_time",
            "namespace", namespace)
            .record(System.nanoTime() - holdStart, TimeUnit.NANOSECONDS);
    };
}
```

> Эти метрики позволяют ответить на вопросы: "Долго ли мы ждём блокировку?" и "Не держим ли слишком долго?"

## Практика

1. Создай IMap для блокировок и реализуй `tryLock` с lease time 30 секунд
2. Запусти два потока, которые конкурируют за одну блокировку — убедись, что только один получает доступ
3. Реализуй `LockProvider` с `try-with-resources` (AutoCloseable Lock)
4. Реализуй multi-lock с сортировкой ключей — проверь, что при конкурентном захвате [1,2] и [2,1] deadlock не возникает
5. Настрой ShedLock с Hazelcast и создай `@Scheduled`-задачу — запусти два инстанса и убедись, что задача выполняется только на одном
6. Добавь метрики (Micrometer) на время захвата и удержания блокировки
7. Проверь lease time: захвати блокировку, убей процесс (без `unlock()`), убедись что блокировка освободилась через lease time

## Итоги урока

- `synchronized` и `ReentrantLock` бесполезны в кластерном окружении — нужны распределённые блокировки
- `IMap.tryLock(key, timeout, leaseTime)` — основной механизм распределённых блокировок в Hazelcast
- Всегда используй `tryLock` с timeout, никогда `lock()` без таймаута
- Lease time автоматически освобождает блокировку при падении процесса
- Для multi-lock сортируй ключи перед захватом — это предотвращает deadlock
- Namespace в ключе блокировки предотвращает коллизии между модулями
- ShedLock + Hazelcast гарантирует выполнение `@Scheduled`-задачи на одном инстансе в кластере
- Метрики времени захвата и удержания позволяют выявлять проблемы с блокировками