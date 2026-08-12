# Урок 10. Тестирование

## Подходы к тестированию Hazelcast

Hazelcast — инфраструктурная зависимость. Тестирование может быть на разных уровнях:

| Уровень | Что тестируем | Hazelcast |
|---------|--------------|-----------|
| Unit-тесты | Бизнес-логика | Mock-порт (без Hazelcast) |
| Интеграционные тесты адаптеров | Маппинг, Predicates, bulk-операции | Embedded Hazelcast |
| End-to-end тесты | Весь flow | Embedded или внешний кластер |

## Unit-тесты бизнес-логики

Бизнес-логика зависит от порта (интерфейса), а не от Hazelcast. Mock-ай порт:

```java
@ExtendWith(MockitoExtension.class)
class OrderServiceTest {

    @Mock ProductPort productPort;
    @Mock OrderPort orderPort;
    @InjectMocks OrderService orderService;

    @Test
    void shouldRejectOrderIfProductNotFound() {
        when(productPort.findById("prod-1")).thenReturn(Optional.empty());

        assertThrows(ProductNotFoundException.class,
            () -> orderService.createOrder("prod-1", 2));
    }
}
```

> Здесь Hazelcast вообще не участвует. Unit-тесты проверяют логику, а не инфраструктуру.

## Embedded Hazelcast для интеграционных тестов

Для тестирования адаптеров нужен реальный Hazelcast. Embedded-инстанс запускается в том же процессе, что и тест.

### Конфигурация для тестов

```yaml
# src/test/resources/hazelcast.yaml
hazelcast:
  cluster-name: test
  network:
    join:
      multicast:
        enabled: false
      auto-detection:
        enabled: false
  # Без discovery — один узел
```

```yaml
# src/test/resources/hazelcast-client.yaml — не нужен!
# В тестах используем embedded (серверный) инстанс
```

> **Внимание:** одного файла `hazelcast.yaml` в `src/test/resources` мало. В приложении из уроков 3 и 8 в `src/main/resources` лежит клиентская конфигурация, а она в порядке разрешения стоит **выше** серверной (см. список приоритетов в уроке 3: `spring.hazelcast.config` и `hazelcast-client.yaml` идут раньше, чем `hazelcast.yaml`). Поэтому `@SpringBootTest` молча поднимет клиент и полезет в несуществующий кластер: в логе будет `Loading 'hazelcast-client.yaml' from the classpath` и затем `CLIENT_CONNECTED` — если снаружи случайно запущен docker-кластер, тесты «пройдут» на нём, а если нет — тест зависнет **бесконечно**, сыпля в лог `Could not connect to member ...`: `cluster-connect-timeout-millis: -1` из урока 3 означает вечные попытки, поэтому сборку придётся убивать руками. Перебей конфиг явно в тестовом профиле:
>
> ```yaml
> # src/test/resources/application-test.yaml
> spring:
>   hazelcast:
>     config: classpath:hazelcast.yaml
> ```
>
> и пометь тест `@ActiveProfiles("test")`. Так же надёжно — вообще не полагаться на автоконфигурацию и поднимать инстанс руками, как в примере ниже.

### Минимальная Java-конфигурация

Для быстрого старта отключи всё лишнее:

```java
@BeforeAll
static void initHazelcast() {
    Config config = new Config();
    config.setClusterName("test");
    config.setProperty("hazelcast.logging.type", "slf4j");
    config.setProperty("hazelcast.phone.home.enabled", "false");

    // Отключить Jet (не нужен для тестов IMap)
    config.getJetConfig().setEnabled(false);

    // Отключить метрики (ускоряет старт)
    config.getMetricsConfig().setEnabled(false);

    // Отключить discovery
    config.getNetworkConfig().getJoin()
        .getMulticastConfig().setEnabled(false);
    config.getNetworkConfig().getJoin()
        .getTcpIpConfig().setEnabled(false);
    config.getNetworkConfig().getJoin()
        .getAutoDetectionConfig().setEnabled(false);

    hazelcastInstance = Hazelcast.newHazelcastInstance(config);
}

@AfterAll
static void shutdownHazelcast() {
    if (hazelcastInstance != null) {
        hazelcastInstance.shutdown();
    }
}
```

> **Зачем отключать Jet и метрики:** тесты стартуют быстрее. На практике эффект скромнее заявленного — разница в замерах составила 30-150 мс на инстанс, а не секунды; сам старт embedded-инстанса на современном железе укладывается в 300-600 мс, а не в 2-3 секунды. Выигрыш всё равно стоит забирать: при сотнях тестов в CI миллисекунды складываются.

## Spring Boot интеграционные тесты

### Базовый класс для тестов

```java
@SpringBootTest
@Tag("integration")
@ActiveProfiles("test")
abstract class AbstractHazelcastIT {

    @MockitoSpyBean IMap<String, ProductValue> productsMap;
    @MockitoSpyBean IMap<Long, OrderValue> ordersMap;

    @BeforeEach
    void cleanMaps() {
        productsMap.clear();
        ordersMap.clear();
    }
}
```

### Паттерн: SpyBean на IMap

`@MockitoSpyBean` оборачивает **реальный** бин. Это позволяет:

```java
class ProductAdapterIT extends AbstractHazelcastIT {

    @Autowired ProductPort productPort;

    @Test
    void shouldSaveAndFindProduct() {
        // Реальная операция с Hazelcast
        Product product = new Product("Ноутбук", 99900, 1L);
        productPort.save("prod-1", product);

        Optional<Product> found = productPort.findById("prod-1");

        assertThat(found).isPresent();
        assertThat(found.get().getName()).isEqualTo("Ноутбук");
    }

    @Test
    void shouldUseBulkOperations() {
        Map<String, Product> products = Map.of(
            "prod-1", new Product("Ноутбук", 99900, 1L),
            "prod-2", new Product("Телефон", 59900, 1L)
        );
        productPort.saveAll(products);

        // Проверяем, что адаптер вызвал setAll (а не put в цикле)
        verify(productsMap).setAll(anyMap());
    }

    @Test
    void shouldHandleHazelcastFailure() {
        // Подмена поведения для тестирования edge case
        doThrow(new HazelcastInstanceNotActiveException("test"))
            .when(productsMap).get(any());

        assertThrows(StorageUnavailableException.class,
            () -> productPort.findById("prod-1"));
    }
}
```

**Три режима SpyBean:**

| Режим | Код | Назначение |
|-------|-----|-----------|
| Реальная операция | `productPort.save(...)` | Данные реально сохраняются |
| Проверка вызовов | `verify(productsMap).setAll(any())` | Убедиться, что вызван setAll, а не put |
| Подмена поведения | `doThrow(...).when(map).get(any())` | Симуляция сбоев |

## Тестирование Predicates и индексов

```java
@Test
void shouldFindProductsByCategory() {
    // Подготовка: три товара, два в категории 1
    productsMap.set("prod-1", new ProductValue(1L, "Ноутбук", "ACTIVE", ...));
    productsMap.set("prod-2", new ProductValue(1L, "Планшет", "ACTIVE", ...));
    productsMap.set("prod-3", new ProductValue(2L, "Кабель", "ACTIVE", ...));

    Collection<Product> result = productPort.findByCategory(1L);

    assertThat(result).hasSize(2);
    assertThat(result).extracting(Product::getName)
        .containsExactlyInAnyOrder("Ноутбук", "Планшет");
}

@Test
void shouldRemoveAllByCategory() {
    productsMap.set("prod-1", new ProductValue(1L, "Ноутбук", "ACTIVE", ...));
    productsMap.set("prod-2", new ProductValue(1L, "Планшет", "ACTIVE", ...));
    productsMap.set("prod-3", new ProductValue(2L, "Кабель", "ACTIVE", ...));

    productPort.removeByCategory(1L);

    assertThat(productsMap.size()).isEqualTo(1);
    assertThat(productsMap.containsKey("prod-3")).isTrue();
}
```

> **Важно:** Для тестов с Predicates индексы должны быть настроены в тестовой конфигурации. Иначе запросы будут работать (full scan), но тест не проверит реальную производительность.

## Тестирование блокировок

```java
class LockProviderTest {

    private static HazelcastInstance hazelcastInstance;
    private HazelcastLockProvider lockProvider;

    @BeforeAll
    static void init() {
        // ... минимальная конфигурация (см. выше)
        hazelcastInstance = Hazelcast.newHazelcastInstance(config);
    }

    @BeforeEach
    void setup() {
        lockProvider = new HazelcastLockProvider(hazelcastInstance);
    }

    @Test
    void shouldAcquireAndReleaseLock() {
        try (Lock lock = lockProvider.lock("ORDER", 42, Duration.ofSeconds(5))) {
            // Блокировка захвачена
            assertThat(lock).isNotNull();
        }
        // Блокировка освобождена — можно захватить снова
        try (Lock lock = lockProvider.lock("ORDER", 42, Duration.ofSeconds(1))) {
            assertThat(lock).isNotNull();
        }
    }

    @Test
    void shouldFailOnTimeout() throws Exception {
        // Захватить блокировку из ДРУГОГО потока — IMap.lock реентерабелен
        // в рамках одного потока, поэтому из основного потока lockProvider
        // получил бы блокировку без проблем и тест ничего бы не проверил
        IMap<String, String> lockMap = hazelcastInstance.getMap("LOCKS");
        ExecutorService holder = Executors.newSingleThreadExecutor();
        holder.submit(() -> lockMap.lock("ORDER:42")).get();

        try {
            // Попытка захватить из lockProvider — таймаут
            assertThrows(LockException.class,
                () -> lockProvider.lock("ORDER", 42, Duration.ofMillis(100)));
        } finally {
            holder.submit(() -> lockMap.unlock("ORDER:42")).get();
            holder.shutdown();
        }
    }

    @Test
    void shouldPreventDeadlockWithSortedKeys() throws Exception {
        // Два потока лочат [1,2] и [2,1] — без сортировки будет deadlock
        ExecutorService executor = Executors.newFixedThreadPool(2);

        Future<?> f1 = executor.submit(() -> {
            try (Lock lock = lockProvider.lockAll("ORDER", List.of(1, 2), Duration.ofSeconds(5))) {
                // Критическая секция
            }
        });
        Future<?> f2 = executor.submit(() -> {
            try (Lock lock = lockProvider.lockAll("ORDER", List.of(2, 1), Duration.ofSeconds(5))) {
                // Критическая секция
            }
        });

        // Оба должны завершиться без deadlock (таймаут теста 10 сек)
        assertTimeoutPreemptively(Duration.ofSeconds(10), () -> {
            f1.get();
            f2.get();
        });

        executor.shutdown();
    }
}
```

> **Внимание:** обе задачи в тексте выше нерабочие в своём первоначальном виде. `shouldFailOnTimeout` захватывал `lockMap.lock` в основном потоке и тут же пытался взять его через `lockProvider` — блокировки Hazelcast реентерабельны в рамках одного потока, поэтому второй захват молча проходил, и `assertThrows` падал с `Expected LockException to be thrown, but nothing was thrown`. Нужен отдельный поток-держатель. `shouldPreventDeadlockWithSortedKeys` захватывал блокировки через `lockAll` и никогда их не освобождал — второй поток честно ждал 5 секунд и падал с `LockException: Не удалось захватить блокировку`. Возврат `Lock` нужно закрывать через try-with-resources, как и в проде.

## Тестирование TTL

```java
@Test
void shouldExpireEntryAfterTTL() throws InterruptedException {
    IMap<String, String> map = hazelcastInstance.getMap("sessions");

    map.put("session:1", "data", 1, TimeUnit.SECONDS);

    assertThat(map.get("session:1")).isEqualTo("data");

    // Подождать истечения TTL
    Thread.sleep(1500);

    assertThat(map.get("session:1")).isNull();
}
```

> **Внимание:** `Thread.sleep` в тестах — антипаттерн, но для TTL это неизбежно. Держи TTL в тестах минимальным (1-2 секунды).

## Общие рекомендации

| Рекомендация | Обоснование |
|-------------|-------------|
| Один embedded-инстанс на весь тестовый набор | Старт Hazelcast занимает сотни миллисекунд — на десятках тестов складывается в заметное время |
| `clear()` в `@BeforeEach` | Каждый тест работает с чистой картой |
| Отключить Jet, метрики, discovery | Ускоряет старт |
| SpyBean вместо MockBean | Реальные операции + проверка вызовов |
| Отдельный тег `@Tag("integration")` | Можно запускать unit и интеграционные тесты отдельно |
| Индексы в тестовой конфигурации | Тесты Predicates проверяют реальную конфигурацию |

## Практика

1. Настрой embedded Hazelcast для тестов с минимальной конфигурацией
2. Напиши интеграционный тест адаптера: save, findById, findByIds — проверь реальные данные
3. Используй `@MockitoSpyBean` для проверки, что адаптер вызывает `setAll` вместо `put` в цикле
4. Напиши тест, симулирующий сбой Hazelcast через `doThrow().when(map).get(any())`
5. Напиши тест Predicates: положи 5 записей с разными categoryId, проверь фильтрацию
6. Напиши тест блокировки: два потока конкурируют за один ключ — только один получает доступ
7. Напиши тест TTL: запись исчезает через заданное время

## Итоги урока

- Unit-тесты бизнес-логики mock-ят порт, а не Hazelcast — полная изоляция от инфраструктуры
- Embedded Hazelcast в тестах: один инстанс, отключены Jet, метрики и discovery для быстрого старта
- `@MockitoSpyBean` на IMap позволяет одновременно использовать реальные операции и проверять вызовы
- Каждый тест начинает с `clear()` — изоляция между тестами
- Тесты Predicates требуют настроенных индексов в тестовой конфигурации
- Тесты блокировок проверяют таймаут (из отдельного потока — `IMap.lock` реентерабелен в своём потоке) и deadlock prevention (сортировка ключей)
- `@Tag("integration")` разделяет unit и интеграционные тесты для CI/CD