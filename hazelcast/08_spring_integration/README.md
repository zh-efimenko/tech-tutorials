# Урок 8. Паттерны интеграции со Spring Boot

## Зачем нужны паттерны интеграции

Hazelcast — это инфраструктурная зависимость. Бизнес-логика не должна знать, что данные хранятся именно в Hazelcast. Правильная интеграция позволяет:

- Заменить хранилище без изменения бизнес-логики
- Тестировать бизнес-логику в изоляции от инфраструктуры
- Разделить ответственность: маппинг, сериализация, доступ к данным

## Hexagonal Architecture (Ports & Adapters)

Рекомендуемый подход — **Hexagonal Architecture**. Доменная логика зависит от абстрактного порта (интерфейса), а Hazelcast-адаптер реализует этот порт.

```
Domain (Core)                    Infrastructure
┌─────────────────┐             ┌──────────────────────────────┐
│ ProductPort      ◄─────────────► ProductHazelcastAdapter       │
│ (interface)      │             │ (implements ProductPort)      │
│                  │             │ uses: IMap<String, HZValue>   │
└─────────────────┘             └──────────────────────────────┘
```

### Порт (интерфейс)

```java
// Доменный интерфейс — не знает о Hazelcast
public interface ProductPort {
    Optional<Product> findById(String id);
    Map<String, Product> findByIds(Set<String> ids);
    void save(String id, Product product);
    void saveAll(Map<String, Product> products);
    void removeByCategory(long categoryId);
}
```

### Адаптер (реализация)

```java
@Component
class ProductHazelcastAdapter implements ProductPort {

    private final IMap<String, ProductValue> productsMap;
    private final ProductMapper mapper;

    ProductHazelcastAdapter(
        IMap<String, ProductValue> productsMap,
        ProductMapper mapper
    ) {
        this.productsMap = productsMap;
        this.mapper = mapper;
    }

    @Override
    public Optional<Product> findById(String id) {
        ProductValue value = productsMap.get(id);
        return Optional.ofNullable(value).map(v -> mapper.toDomain(id, v));
    }

    @Override
    public Map<String, Product> findByIds(Set<String> ids) {
        return productsMap.getAll(ids).entrySet().stream()
            .collect(toMap(
                Map.Entry::getKey,
                e -> mapper.toDomain(e.getKey(), e.getValue())
            ));
    }

    @Override
    public void save(String id, Product product) {
        productsMap.set(id, mapper.toHZ(product));
    }

    @Override
    public void saveAll(Map<String, Product> products) {
        Map<String, ProductValue> hzEntries = products.entrySet().stream()
            .collect(toMap(
                Map.Entry::getKey,
                e -> mapper.toHZ(e.getValue())
            ));
        productsMap.setAll(hzEntries);
    }

    @Override
    public void removeByCategory(long categoryId) {
        productsMap.removeAll(Predicates.equal("categoryId", categoryId));
    }
}
```

**Ключевые решения:**

- `set()` вместо `put()` — не нужно возвращаемое значение
- `setAll()` вместо `putAll()` — не триггерит EntryListener (быстрее)
- `getAll()` вместо цикла `get()` — один сетевой вызов
- `removeAll(predicate)` — server-side удаление

## Конфигурация карт как Spring Beans

Типизированные бины IMap создаются в отдельном конфигурационном классе:

```java
@Configuration
class HazelcastMapsConfig {

    @Bean
    HazelcastConfigCustomizer serializationCustomizer() {
        return config -> {
            config.getSerializationConfig()
                .getCompactSerializationConfig()
                .addClass(ProductValue.class)
                .addClass(OrderValue.class)
                .addClass(SessionValue.class);
        };
    }

    @Bean
    IMap<String, ProductValue> productsMap(HazelcastInstance hazelcast) {
        return hazelcast.getMap("products");
    }

    @Bean
    IMap<Long, OrderValue> ordersMap(HazelcastInstance hazelcast) {
        return hazelcast.getMap("orders");
    }

    @Bean
    IMap<String, SessionValue> sessionsMap(HazelcastInstance hazelcast) {
        return hazelcast.getMap("sessions");
    }
}
```

**Что это даёт:**

| Преимущество | Пояснение |
|-------------|----------|
| Type safety | `IMap<String, ProductValue>` — невозможно перепутать типы |
| Явные зависимости | Конструктор адаптера явно показывает, какая карта нужна |
| Тестируемость | `@MockitoSpyBean IMap<String, ProductValue>` — легко подменить |
| Единая точка конфигурации | Все карты в одном месте |

## Паттерн: TTL на уровне записи

Для данных с временным характером (сессии, кэш, отложенные сообщения) TTL задаётся при записи:

```java
@Component
class SessionHazelcastAdapter implements SessionPort {

    private final IMap<String, SessionValue> sessionsMap;
    private final Duration sessionTtl;

    SessionHazelcastAdapter(
        IMap<String, SessionValue> sessionsMap,
        @Value("${app.session.ttl:PT30M}") Duration sessionTtl
    ) {
        this.sessionsMap = sessionsMap;
        this.sessionTtl = sessionTtl;
    }

    @Override
    public void save(String sessionId, Session session) {
        sessionsMap.put(
            sessionId,
            mapper.toHZ(session),
            sessionTtl.toMillis(), TimeUnit.MILLISECONDS
        );
    }
}
```

> TTL конфигурируется через Spring properties — разные окружения могут иметь разное время жизни сессий.

## Паттерн: Get-and-Erase

Для однократной обработки данных (отложенные сообщения, задачи из очереди):

```java
@Override
public Map<String, Message> getAndErase(Collection<String> keys) {
    Map<String, MessageValue> entries = messagesMap.getAll(new HashSet<>(keys));

    // Удаление уже прочитанных
    entries.keySet().forEach(messagesMap::remove);

    return entries.entrySet().stream()
        .collect(toMap(
            Map.Entry::getKey,
            e -> mapper.toDomain(e.getValue())
        ));
}
```

> **Внимание:** Между `getAll` и `remove` есть окно, когда другой процесс может прочитать те же данные. Этот паттерн подходит только для идемпотентных операций. Для строгой однократной обработки используй `IMap.tryLock` или EntryProcessor.

## Метрики на адаптере

Добавь `@Timed` для автоматического сбора метрик каждого метода адаптера:

```java
@Component
@Timed(value = "cache_port", extraTags = {"port", "ProductPort"})
class ProductHazelcastAdapter implements ProductPort {
    // ...
}
```

Это даёт метрики:
- `cache_port_seconds_count{port="ProductPort", method="findById"}` — количество вызовов
- `cache_port_seconds_sum{port="ProductPort", method="findById"}` — суммарное время
- `cache_port_seconds_max{port="ProductPort", method="findById"}` — максимальное время

## Обработка ошибок

Адаптер должен транслировать Hazelcast-специфичные исключения в доменные:

```java
@Component
class ProductHazelcastAdapter implements ProductPort {

    @Override
    public Optional<Product> findById(String id) {
        try {
            ProductValue value = productsMap.get(id);
            return Optional.ofNullable(value).map(v -> mapper.toDomain(id, v));
        } catch (HazelcastInstanceNotActiveException e) {
            throw new StorageUnavailableException("Hazelcast недоступен", e);
        }
    }
}
```

Альтернатива — Spring AOP для всех адаптеров:

```java
@Aspect
@Component
class HazelcastExceptionTranslator {

    @Around("@within(org.springframework.stereotype.Component) " +
            "&& execution(* *..adapter.hazelcast..*(..))")
    Object translate(ProceedingJoinPoint pjp) throws Throwable {
        try {
            return pjp.proceed();
        } catch (HazelcastInstanceNotActiveException e) {
            throw new StorageUnavailableException("Hazelcast недоступен", e);
        }
    }
}
```

## Структура пакетов

```
com.example.myapp/
├── domain/
│   ├── model/
│   │   └── Product.java              # Доменная модель
│   └── port/
│       └── ProductPort.java           # Порт (интерфейс)
│
├── adapter/
│   └── hazelcast/
│       ├── config/
│       │   └── HazelcastMapsConfig.java   # Конфигурация карт и сериализации
│       ├── dto/
│       │   └── ProductValue.java          # HZ DTO (Java Record)
│       ├── mapper/
│       │   └── ProductMapper.java         # Маппер Domain <-> HZ DTO
│       └── ProductHazelcastAdapter.java   # Адаптер (реализация порта)
│
└── application/
    └── ProductService.java            # Бизнес-логика (зависит от порта)
```

## Практика

1. Создай доменную модель `Product` и порт `ProductPort` с методами `findById`, `findByIds`, `save`, `saveAll`
2. Создай HZ DTO `ProductValue` (Java Record) и маппер
3. Реализуй `ProductHazelcastAdapter`, используя bulk-операции
4. Создай `HazelcastMapsConfig` с типизированным бином `IMap` и регистрацией Compact Serialization
5. Добавь `@Timed` на адаптер и проверь метрики через Actuator
6. Реализуй паттерн get-and-erase для карты сообщений с TTL
7. Добавь обработку `HazelcastInstanceNotActiveException` через AOP

## Итоги урока

- Hexagonal Architecture изолирует бизнес-логику от Hazelcast через порты и адаптеры
- Адаптер отвечает за маппинг Domain <-> HZ DTO, bulk-операции и обработку ошибок
- Типизированные бины `IMap<K, V>` обеспечивают compile-time safety и тестируемость
- `HazelcastConfigCustomizer` — единая точка регистрации сериализации в Spring Boot
- `@Timed` на адаптере автоматически собирает метрики каждого метода
- Hazelcast-специфичные исключения транслируются в доменные через AOP или try/catch
- Структура пакетов: `domain/port`, `adapter/hazelcast/dto`, `adapter/hazelcast/mapper`, `adapter/hazelcast`
- Паттерн get-and-erase подходит только для идемпотентных операций