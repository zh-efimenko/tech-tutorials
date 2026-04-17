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

> **Зачем отключать Jet и метрики:** Тесты стартуют быстрее на 2-3 секунды. В CI это экономит минуты.

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
    void shouldFailOnTimeout() {
        // Захватить блокировку в основном потоке
        IMap<String, String> lockMap = hazelcastInstance.getMap("LOCKS");
        lockMap.lock("ORDER:42");

        try {
            // Попытка захватить из lockProvider — таймаут
            assertThrows(LockException.class,
                () -> lockProvider.lock("ORDER", 42, Duration.ofMillis(100)));
        } finally {
            lockMap.unlock("ORDER:42");
        }
    }

    @Test
    void shouldPreventDeadlockWithSortedKeys() throws Exception {
        // Два потока лочат [1,2] и [2,1] — без сортировки будет deadlock
        ExecutorService executor = Executors.newFixedThreadPool(2);

        Future<?> f1 = executor.submit(() ->
            lockProvider.lockAll("ORDER", List.of(1, 2), Duration.ofSeconds(5)));
        Future<?> f2 = executor.submit(() ->
            lockProvider.lockAll("ORDER", List.of(2, 1), Duration.ofSeconds(5)));

        // Оба должны завершиться без deadlock (таймаут теста 10 сек)
        assertTimeoutPreemptively(Duration.ofSeconds(10), () -> {
            f1.get();
            f2.get();
        });

        executor.shutdown();
    }
}
```

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
| Один embedded-инстанс на весь тестовый набор | Старт Hazelcast занимает 2-3 секунды |
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
- Тесты блокировок проверяют таймаут, deadlock prevention (сортировка ключей) и reentrancy
- `@Tag("integration")` разделяет unit и интеграционные тесты для CI/CD