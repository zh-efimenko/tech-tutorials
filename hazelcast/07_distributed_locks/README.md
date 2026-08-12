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
boolean acquired;
try {
    acquired = lockMap.tryLock(
        key,
        5, TimeUnit.SECONDS,     // Сколько ждать захвата
        120, TimeUnit.SECONDS    // Автоосвобождение (lease time)
    );
} catch (InterruptedException e) {
    Thread.currentThread().interrupt();
    throw new IllegalStateException("Прервано ожидание блокировки: " + key, e);
}

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

> **Важно:** версия `tryLock` с таймаутом объявляет checked `InterruptedException` — без `try/catch` код не компилируется (`unreported exception InterruptedException; must be caught or declared to be thrown`). Перехватив его, обязательно восстанавливай флаг прерывания через `Thread.currentThread().interrupt()`.

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

Сначала — собственные типы, которых нет ни в JDK, ни в Hazelcast. `Lock` здесь — **не** `java.util.concurrent.locks.Lock`, а функциональный интерфейс с одним методом, чтобы блокировку можно было отдавать в try-with-resources:

```java
@FunctionalInterface
public interface Lock extends AutoCloseable {
    @Override
    void close();   // Переопределяем без throws Exception — иначе try-with-resources заставит ловить checked
}

public class LockException extends RuntimeException {
    public LockException(String message) { super(message); }
    public LockException(String message, Throwable cause) { super(message, cause); }
}
```

```java
public interface LockProvider {
    Lock lock(String namespace, Object id, Duration timeout);
    Lock lockAll(String namespace, Collection<?> ids, Duration timeout);
}
```

> **Важно:** если по привычке импортировать `java.util.concurrent.locks.Lock`, код не соберётся — `error: incompatible types: Lock is not a functional interface`: у стандартного `Lock` шесть методов, лямбдой его не вернуть.

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
implementation 'net.javacrumbs.shedlock:shedlock-spring:7.7.0'
implementation 'net.javacrumbs.shedlock:shedlock-provider-hazelcast4:7.7.0'
```

### Конфигурация

> **Внимание:** `LockProvider` и `HazelcastLockProvider` из ShedLock — это **другие** классы, а не те, что ты написал выше в этом уроке. Имена совпадают, поэтому импорты обязательны, а свой провайдер лучше назвать иначе (например, `KeyLockProvider`).

```java
import net.javacrumbs.shedlock.core.LockProvider;
import net.javacrumbs.shedlock.provider.hazelcast4.HazelcastLockProvider;

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
@SchedulerLock(
    name = "processExpiredSessions",
    lockAtMostFor = "PT1m",
    lockAtLeastFor = "PT10S"   // Обязательно для быстрых задач — см. предупреждение ниже
)
void processExpiredSessions() {
    // Выполняется только на одном инстансе
    sessionService.cleanExpired();
}
```

| Параметр | Описание |
|----------|----------|
| `lockAtMostFor` | Максимальное время удержания блокировки (защита от падения) |
| `lockAtLeastFor` | Минимальное время удержания (предотвращает повторный запуск на другом узле) |

> **Побочный эффект:** `lockAtLeastFor` задаёт нижнюю границу и для интервала запусков. В примере выше объявлено `fixedRate = 5000`, но фактически задача пойдёт раз в 10 секунд: пока блокировка удерживается, тики других инстансов проходят вхолостую. Замер на двух инстансах даёт шаг около 10 с (обычно 9997-10011 мс, изредка тик проскакивает и шаг становится ~15 с). Учитывай это, подбирая пару `fixedRate` / `lockAtLeastFor`.

> **Важно:** без `lockAtLeastFor` ShedLock снимает блокировку сразу по завершении задачи. Если задача отрабатывает за миллисекунды, второй инстанс на своём тике застаёт блокировку уже освобождённой и выполняет задачу повторно. Проверено на двух инстансах с `fixedRate = 3000`: только с `lockAtMostFor` дублируется практически каждый тик — за 70 секунд по 23 запуска на каждом инстансе, парами с разницей в десятки миллисекунд; с `lockAtLeastFor = "PT10S"` дубликаты исчезают. Правило: для коротких задач всегда задавай `lockAtLeastFor`, сравнимый с периодом запуска.

## Метрики блокировок

Для мониторинга блокировок полезно отслеживать время захвата и удержания:

```java
public Lock lock(String namespace, Object id, Duration timeout) {
    String key = namespace + ":" + id;
    long startTime = System.nanoTime();

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
7. Проверь lease time: захвати блокировку с коротким lease (3 секунды), не вызывай `unlock()` и **оставь процесс живым** — второй поток получит блокировку примерно через 3 секунды. Убивать процесс для этой проверки нельзя: при обрыве клиентского соединения кластер снимает его блокировки сам, не дожидаясь lease time (замер: ~4,7 секунды при lease 120 секунд)

## Итоги урока

- `synchronized` и `ReentrantLock` бесполезны в кластерном окружении — нужны распределённые блокировки
- `IMap.tryLock(key, timeout, leaseTime)` — основной механизм распределённых блокировок в Hazelcast
- Всегда используй `tryLock` с timeout, никогда `lock()` без таймаута
- Lease time автоматически освобождает блокировку при падении процесса
- Для multi-lock сортируй ключи перед захватом — это предотвращает deadlock
- Namespace в ключе блокировки предотвращает коллизии между модулями
- ShedLock + Hazelcast гарантирует выполнение `@Scheduled`-задачи на одном инстансе в кластере
- Метрики времени захвата и удержания позволяют выявлять проблемы с блокировками