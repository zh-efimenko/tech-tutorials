# Урок 21. Транзакции и реактивный стек

## Как @Transactional ложится на драйвер

Стартер поднимает `Neo4jTransactionManager`, и `@Transactional` работает так же, как с JPA: открывает транзакцию, коммитит при нормальном выходе, откатывает при `RuntimeException`.

```
@Transactional
   └─▶ Neo4jTransactionManager
        └─▶ Session драйвера, привязанная к потоку
             └─▶ явная транзакция драйвера (beginTransaction)
```

Важное следствие: под `@Transactional` используется **explicit transaction** драйвера, у которой из урока 17 нет автоматического повтора. Автоматический retry живёт в `executeRead`/`executeWrite`, а Spring туда не заходит.

```java
@Service
public class OrderService {

    private final OrderRepository orders;
    private final Neo4jClient client;

    public OrderService(OrderRepository orders, Neo4jClient client) {
        this.orders = orders;
        this.client = client;
    }

    @Transactional
    public void placeOrder(String email, List<OrderLine> lines) {
        var order = new OrderEntity(nextOrderId(), totalOf(lines), "created", LocalDate.now());
        orders.save(order);
        client.query("MATCH (u:User {email:$e}), (o:Order {orderId:$id}) MERGE (u)-[:PLACED]->(o)")
              .bind(email).to("e")
              .bind(order.getOrderId()).to("id")
              .run();
    }
}
```

Обе операции — репозиторий и `Neo4jClient` — идут в одной транзакции. Это ключевое отличие `Neo4jClient` от голого драйвера.

## Retry на уровне приложения

Раз Spring не повторяет транзакции сам, `TransientException` из урока 15 нужно обрабатывать явно.

Отдельная библиотека для этого больше не нужна: Spring Framework 7, который приходит с Boot 4.1, содержит механизм повторов в `spring-context`. Аннотация живёт в пакете `org.springframework.resilience.annotation` и включается через `@EnableResilientMethods`.

```java
import org.springframework.resilience.annotation.EnableResilientMethods;

@SpringBootApplication
@EnableResilientMethods
public class ShopGraphApplication { /* ... */ }
```

```java
import org.springframework.resilience.annotation.Retryable;
import org.neo4j.driver.exceptions.TransientException;

@Service
public class OrderService {

    @Retryable(
        includes = TransientException.class,
        maxRetries = 4,
        delay = 50,
        multiplier = 2.0,
        jitter = 20)
    @Transactional
    public void placeOrder(String email, List<OrderLine> lines) {
        // ...
    }
}
```

> **Внимание**: это не тот же `@Retryable`, что в статьях под Spring Boot 3. Старый жил в отдельной библиотеке `org.springframework.retry:spring-retry` и имел другие атрибуты — `retryFor`, `maxAttempts`, вложенный `@Backoff`. Boot 4.1 версией этой библиотеки **не управляет**: строка `implementation("org.springframework.retry:spring-retry")` без явной версии падает на `Could not find org.springframework.retry:spring-retry:.`. Новая аннотация задаёт задержку плоскими атрибутами: `delay`, `multiplier`, `maxDelay`, `jitter`, а `maxRetries` считает именно повторы, а не общее число попыток.

> **Важно**: порядок аннотаций имеет значение по существу, а не по стилю. Повтор должен оборачивать транзакцию, а не наоборот, — иначе он произойдёт внутри уже сломанной транзакции. Порядок задаётся атрибутом `order` в `@EnableResilientMethods` и по умолчанию правильный, но при ручной настройке цепочки advice это легко нарушить.

И, как всегда при повторах, метод обязан быть идемпотентным. Правила из уроков 6 и 15 здесь применяются буквально.

## Только чтение

```java
@Transactional(readOnly = true)
public List<ProductView> catalog(String category) {
    return products.findByCategoryProjected(category);
}
```

`readOnly = true` — не косметика: SDN открывает сессию в режиме чтения, и в кластере драйвер направляет её на реплику, разгружая лидера. На одиночном инстансе эффект нулевой, но привычку стоит выработать сразу — при переезде на кластер это даст выигрыш без правок кода.

## Распространение

```java
@Transactional(propagation = Propagation.REQUIRES_NEW)
public void auditLog(String message) { /* ... */ }
```

Поддерживаются те же режимы, что и в JPA. На практике осмысленных случаев два:

| Режим | Когда |
|---|---|
| `REQUIRED` | По умолчанию, почти всегда |
| `REQUIRES_NEW` | Аудит и логирование, которые должны сохраниться даже при откате основной операции |

> **Внимание**: `REQUIRES_NEW` открывает **вторую сессию к базе**. Если внешняя транзакция держит блокировку на узле, который трогает внутренняя, получится самоблокировка — транзакция ждёт саму себя, пока не сработает таймаут. Это не гипотетический риск, а типовая ошибка при добавлении аудита к операции над теми же узлами.

## Транзакции и CALL {} IN TRANSACTIONS

Конструкция из уроков 9 и 14 сама управляет транзакциями и не может выполняться внутри внешней.

```java
// Упадёт: запрос сам открывает транзакции, а @Transactional уже открыл одну
@Transactional
public void bulkUpdate() {
    client.query("MATCH (n:Product) CALL (n) { SET n.checked = true } IN TRANSACTIONS OF 1000 ROWS").run();
}

// Правильно: без @Transactional, в режиме autocommit
public void bulkUpdate() {
    client.query("MATCH (n:Product) CALL (n) { SET n.checked = true } IN TRANSACTIONS OF 1000 ROWS").run();
}
```

Это та же проблема, что в уроке 16 с `transaction-mode` миграций, и решается она одинаково: батчевые операции живут вне управляемых транзакций.

## Таймауты

```java
@Transactional(timeout = 5)
public void slowOperation() { /* ... */ }
```

Таймаут транзакции ограничивает время выполнения на стороне сервера. Без него зависший запрос держит блокировки до срабатывания глобального `db.transaction.timeout`, а это, как правило, куда больше, чем допустимо для веб-запроса.

## Реактивный стек

SDN поддерживает реактивный вариант целиком: репозитории, шаблон и клиент.

```groovy
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-data-neo4j")
    implementation("org.springframework.boot:spring-boot-starter-webflux")
}
```

```java
public interface ReactiveProductRepository extends ReactiveNeo4jRepository<ProductEntity, String> {

    Flux<ProductEntity> findByPriceGreaterThan(Double price);

    @Query("""
           MATCH (p:Product)-[:IN_CATEGORY]->(c:Category {name: $category})
           RETURN p.sku AS sku, p.title AS title, p.price AS price, c.name AS categoryName
           """)
    Flux<ProductView> findViews(String category);
}
```

```java
@RestController
public class ReactiveCatalogController {

    private final ReactiveProductRepository products;

    public ReactiveCatalogController(ReactiveProductRepository products) {
        this.products = products;
    }

    @GetMapping(value = "/api/products", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ProductView> stream(@RequestParam String category) {
        return products.findViews(category);
    }
}
```

Транзакции в реактивном стеке — `ReactiveNeo4jTransactionManager`, а `@Transactional` работает поверх реактивного контекста, а не ThreadLocal.

> **Внимание**: смешивать императивный и реактивный стеки в одном приложении не следует. Два менеджера транзакций в контексте приводят к тому, что `@Transactional` подхватывает не тот, и операции расходятся по разным транзакциям. Если нужны оба, разноси их по разным приложениям.

## Когда реактивный стек оправдан

Честный разбор — потому что реактивность часто берут по инерции.

| Оправдан | Не оправдан |
|---|---|
| Стриминг больших результатов клиенту без материализации | Обычный CRUD с ответом на 20 записей |
| Тысячи одновременных долгих соединений (SSE, WebSocket) | Внутренний сервис с десятками RPS |
| Всё приложение уже на WebFlux | Смешанное приложение с JPA и блокирующими вызовами |

Ключевой аргумент против: **виртуальные потоки Java 21+ закрывают большую часть задач, ради которых брали реактивность**, не ломая стектрейсы, отладку и читаемость.

```yaml
spring:
  threads:
    virtual:
      enabled: true
```

На Java 25 с виртуальными потоками блокирующий стек держит высокую конкурентность без реактивного кода. Реактивность остаётся оправданной там, где нужен именно backpressure — потоковая выдача, которую потребитель не успевает читать.

## Стриминг в императивном стеке

Если нужна именно потоковая обработка большого результата, реактивность не обязательна:

```java
public interface ProductRepository extends Neo4jRepository<ProductEntity, String> {
    Stream<ProductEntity> findAllByPriceGreaterThan(Double price);
}
```

```java
@Transactional(readOnly = true)
public void export(Double price, Writer out) {
    try (Stream<ProductEntity> stream = products.findAllByPriceGreaterThan(price)) {
        stream.forEach(p -> write(out, p));
    }
}
```

`Stream` обязан закрываться и потребляться внутри транзакции. Формально SDN 8 отдаёт наружу уже материализованный результат, поэтому обращение к стриму после выхода из метода на датасете курса обычно проходит без исключения — но полагаться на это нельзя: гарантий, что результат не окажется привязанным к закрытому соединению, нет, и на больших выборках такой код ломается. Вместе с `fetchSize` драйвера из урока 17 конструкция даёт потоковое чтение без реактивного стека.

## Практика

1. Напиши сервисный метод с `@Transactional`, который сохраняет заказ репозиторием и создаёт связь через `Neo4jClient`. Убедись, что при исключении откатываются обе операции.
2. Проверь, что `Neo4jClient` действительно попал в ту же транзакцию: брось исключение после `.run()` и посмотри, осталась ли связь в графе.
3. Включи `@EnableResilientMethods` и повесь `@Retryable(includes = TransientException.class)` с экспоненциальной задержкой. Отдельно проверь, что зависимость `org.springframework.retry:spring-retry` без версии не резолвится — так выглядят примеры под Boot 3.
4. Пометь метод чтения `@Transactional(readOnly = true)` и найди в DEBUG-логах режим доступа сессии.
5. Вызови из метода с `@Transactional` запрос с `CALL {} IN TRANSACTIONS` и зафиксируй ошибку. Убери аннотацию и убедись, что запрос прошёл.
6. Поставь `@Transactional(timeout = 1)` и выполни заведомо долгий запрос — зафиксируй исключение.
7. Добавь метод аудита с `REQUIRES_NEW`, который пишет в тот же узел, что и внешняя транзакция, и воспроизведи самоблокировку.
8. Собери отдельное приложение на WebFlux с `ReactiveNeo4jRepository` и отдай `Flux<ProductView>` как SSE-поток.
9. Включи виртуальные потоки в императивном приложении и сравни поведение под нагрузкой с реактивным вариантом.
10. Реализуй экспорт каталога через `Stream<ProductEntity>` внутри `@Transactional(readOnly = true)` и проверь, что происходит при обращении к стриму после выхода из метода.

## Итоги урока

- `@Transactional` использует explicit transaction драйвера, у которой нет автоматического повтора: retry в `executeRead`/`executeWrite` Spring не задействует.
- Репозитории и `Neo4jClient` работают в одной транзакции Spring — это главное отличие клиента от голого драйвера.
- Повторы при `TransientException` подключаются встроенным механизмом Spring Framework 7 (`@EnableResilientMethods` и `@Retryable` из `org.springframework.resilience.annotation`), а не библиотекой `spring-retry`; повтор обязан оборачивать транзакцию, а не наоборот.
- `@Transactional(readOnly = true)` открывает сессию в режиме чтения, и в кластере драйвер направит её на реплику без изменений в коде.
- `REQUIRES_NEW` открывает вторую сессию: если обе транзакции трогают одни узлы, возникает самоблокировка до срабатывания таймаута.
- Запрос с `CALL {} IN TRANSACTIONS` не может выполняться внутри управляемой транзакции и запускается без `@Transactional`.
- Реактивный стек поддержан полностью, но смешивать его с императивным в одном приложении нельзя — два менеджера транзакций расходятся.
- Виртуальные потоки Java 21+ закрывают большую часть задач, ради которых брали реактивность; она остаётся оправданной там, где нужен backpressure.
- Потоковое чтение доступно и в императивном стеке через `Stream<T>` внутри транзакции вместе с `fetchSize` драйвера.
