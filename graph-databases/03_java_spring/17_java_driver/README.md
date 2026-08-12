# Урок 17. Neo4j Java Driver 6

## Зачем разбирать драйвер, если есть Spring Data

Spring Data Neo4j целиком построен поверх драйвера. Всё, что связано с транзакциями, повторами, маршрутизацией и таймаутами, делается на его уровне. Не понимая драйвер, невозможно объяснить, почему `@Transactional` повёл себя не так, откуда взялся `TransientError` и почему запрос ушёл на реплику.

```
┌─────────────────────────────────────┐
│  Репозитории Spring Data Neo4j      │  ← уроки 18-20
├─────────────────────────────────────┤
│  Neo4jTemplate / Neo4jClient        │  ← урок 20
├─────────────────────────────────────┤
│  Neo4j Java Driver 6                │  ← этот урок
├─────────────────────────────────────┤
│  Bolt по сети                       │
└─────────────────────────────────────┘
```

## Подключение

```groovy
// build.gradle.kts
dependencies {
    // BOM согласует версии драйвера и его зависимостей, включая Netty
    implementation(platform("org.neo4j.driver:neo4j-java-driver-bom:6.1.0"))
    implementation("org.neo4j.driver:neo4j-java-driver")
}
```

BOM появился в шестой версии и решает конкретную проблему: драйвер тянет Netty, и при native-транспорте несогласованные версии Netty ломают сборку.

```java
import org.neo4j.driver.AuthTokens;
import org.neo4j.driver.Driver;
import org.neo4j.driver.GraphDatabase;

try (Driver driver = GraphDatabase.driver(
        "bolt://localhost:7687",
        AuthTokens.basic("neo4j", "graphpassword"))) {

    driver.verifyConnectivity();
}
```

> **Важно**: `Driver` — тяжёлый объект с пулом соединений. Он создаётся один раз на приложение и живёт до его остановки. Создавать драйвер на запрос — самая частая ошибка при первом знакомстве.

## executableQuery: основной API

В шестой версии рекомендованный способ выполнить запрос — `executableQuery`. Он сам открывает сессию, сам создаёт транзакцию, сам повторяет её при `TransientError`.

```java
import org.neo4j.driver.QueryConfig;
import org.neo4j.driver.RoutingControl;

var result = driver.executableQuery("""
        MATCH (u:User {email: $email})-[:PLACED]->(o:Order)
        RETURN o.orderId AS orderId, o.total AS total
        ORDER BY o.createdAt DESC
        """)
    .withParameters(Map.of("email", "anna@shop.io"))
    .withConfig(QueryConfig.builder()
        .withDatabase("neo4j")
        .withRouting(RoutingControl.READ)   // отправить на реплику в кластере
        .build())
    .execute();

for (var record : result.records()) {
    System.out.println(record.get("orderId").asLong() + " " + record.get("total").asDouble());
}
```

Дополнительно доступна сводка выполнения:

```java
var summary = result.summary();
System.out.println(summary.counters().nodesCreated());
System.out.println(summary.resultAvailableAfter(TimeUnit.MILLISECONDS));
```

### Маппинг в объекты

Драйвер 6 умеет отображать записи в Java records без ручного разбора.

```java
public record OrderSummary(Long orderId, Double total) {}

List<OrderSummary> orders = driver.executableQuery("""
        MATCH (u:User {email: $email})-[:PLACED]->(o:Order)
        RETURN o.orderId AS orderId, o.total AS total
        """)
    .withParameters(Map.of("email", "anna@shop.io"))
    .execute(Collectors.mapping(r -> r.as(OrderSummary.class), Collectors.toList()));
```

Имена компонентов record должны совпадать с именами колонок в `RETURN`. Это разумный вариант для простых выборок; для доменной модели с графом связей используется Spring Data Neo4j.

## Сессии и транзакции

Когда одной транзакции мало — нужна логика между запросами, чтение результата первого запроса влияет на второй.

```java
import org.neo4j.driver.Session;

try (Session session = driver.session()) {
    // ...
}
```

> **Важно**: сессия — лёгкий объект, но она **не потокобезопасна** и должна закрываться. Одна сессия на единицу работы, а не на приложение. Пул соединений живёт в драйвере, а не в сессии.

### Managed transaction — основной режим

```java
List<String> titles = session.executeRead(tx -> {
    var result = tx.run("""
            MATCH (u:User {email: $email})-[:PLACED]->(:Order)-[:CONTAINS]->(p:Product)
            RETURN DISTINCT p.title AS title
            """, Map.of("email", "anna@shop.io"));
    return result.list(r -> r.get("title").asString());
});
```

```java
session.executeWriteWithoutResult(tx ->
    tx.run("""
        MERGE (p:Product {sku: $sku})
        ON CREATE SET p.title = $title, p.price = $price
        """, Map.of("sku", "BL-500", "title", "Блендер Turbo Pro", "price", 5490.0)));
```

Два правила, нарушение которых даёт трудноуловимые баги:

**1. Не возвращать `Result` наружу.** Результат привязан к транзакции: после её закрытия он мёртв. Данные нужно вычитать внутри колбэка.

```java
// Ошибка: Result становится недействительным после коммита
var bad = session.executeRead(tx -> tx.run("MATCH (u:User) RETURN u.email"));

// Правильно
var good = session.executeRead(tx ->
    tx.run("MATCH (u:User) RETURN u.email AS email").list(r -> r.get("email").asString()));
```

**2. Колбэк должен быть идемпотентным.** Драйвер повторяет его при `TransientError` — это прямое продолжение урока 15. Инкремент счётчика внутри колбэка при повторе выполнится дважды.

### Explicit transaction

Когда границей транзакции нужно управлять вручную. Автоматического повтора здесь нет.

```java
try (Session session = driver.session();
     var tx = session.beginTransaction()) {

    tx.run("MERGE (b:Brand {name: $name})", Map.of("name", "NewBrand"));
    tx.run("MATCH (p:Product {sku: $sku}) SET p.price = $price",
           Map.of("sku", "CM-100", "price", 5490.0));
    tx.commit();
}
```

### Сравнение режимов

| Режим | Retry | Границы | Когда применять |
|---|---|---|---|
| `executableQuery` | Да | Один запрос | По умолчанию |
| `executeRead` / `executeWrite` | Да | Колбэк | Несколько запросов с логикой между ними |
| `beginTransaction` | Нет | Вручную | Интеграция с внешним менеджером транзакций |

## Что убрали в шестой версии

При переходе с драйвера 5 ломается следующее.

| Было в 5.x | Стало в 6.x |
|---|---|
| `session.readTransaction()` | `session.executeRead()` |
| `session.writeTransaction()` | `session.executeWrite()` |
| `driver.asyncSession()` | `driver.session(AsyncSession.class)` |
| `driver.reactiveSession()` | `driver.session(ReactiveSession.class)` |
| `RxSession`, `RxTransaction` | Удалены, остался только `ReactiveSession` |
| `TrustStrategy.certFile()` | Удалён |
| `Notification.severity()` | Удалён |

Асинхронная и реактивная сессии теперь запрашиваются типом:

```java
import org.neo4j.driver.async.AsyncSession;
import org.neo4j.driver.reactive.ReactiveSession;

var asyncSession    = driver.session(AsyncSession.class);
var reactiveSession = driver.session(ReactiveSession.class);
```

## Батчевая запись

Единственный правильный способ записать много строк — `UNWIND` с параметром-списком. Это прямое применение урока 14.

```java
record ProductRow(String sku, String title, double price) {}

void saveAll(Driver driver, List<ProductRow> rows) {
    var params = rows.stream()
        .map(r -> Map.<String, Object>of("sku", r.sku(), "title", r.title(), "price", r.price()))
        .toList();

    driver.executableQuery("""
            UNWIND $rows AS row
            MERGE (p:Product {sku: row.sku})
            SET p.title = row.title, p.price = row.price
            """)
        .withParameters(Map.of("rows", params))
        .execute();
}
```

Пачками по 1000-10000 строк. Цикл с отдельным запросом на строку медленнее в разы: на локальной машине разрыв получается порядка десяти-двадцати раз, а через сеть с реальной задержкой — на порядки, потому что к каждой записи добавляется round-trip.

## Конфигурация

```java
import org.neo4j.driver.Config;
import java.time.Duration;

var config = Config.builder()
    .withMaxConnectionPoolSize(50)
    .withConnectionAcquisitionTimeout(60, TimeUnit.SECONDS)
    .withMaxConnectionLifetime(1, TimeUnit.HOURS)
    .withMaxTransactionRetryTime(30, TimeUnit.SECONDS)
    .withFetchSize(1000)
    .build();

Driver driver = GraphDatabase.driver(uri, AuthTokens.basic(user, password), config);
```

| Параметр | Смысл | Ориентир |
|---|---|---|
| `maxConnectionPoolSize` | Размер пула | По числу потоков приложения |
| `connectionAcquisitionTimeout` | Ожидание свободного соединения | 30-60 секунд |
| `maxConnectionLifetime` | Принудительная ротация соединений | 1 час, важно за балансировщиком |
| `maxTransactionRetryTime` | Общее время повторов | 30 секунд |
| `fetchSize` | Размер порции при чтении | 1000 по умолчанию |

`fetchSize` управляет потоковой выдачей: результат не материализуется целиком, а тянется порциями. Для запроса, возвращающего миллион строк, это разница между работой и `OutOfMemory`.

## Таймауты на транзакцию

```java
import org.neo4j.driver.TransactionConfig;

var txConfig = TransactionConfig.builder()
    .withTimeout(Duration.ofSeconds(5))
    .withMetadata(Map.of("app", "shop-api", "operation", "recommendations"))
    .build();

var titles = session.executeRead(tx -> tx.run("...").list(r -> r.get("title").asString()), txConfig);
```

Метаданные транзакции попадают в `SHOW TRANSACTIONS` и в query log — по ним на сервере видно, какой участок приложения породил зависший запрос. При разборе инцидентов это экономит часы.

## Ошибки

Классификация из урока 15 отражена в иерархии исключений.

```java
import org.neo4j.driver.exceptions.*;

try {
    driver.executableQuery("MATCH (u:User) RETURN u").execute();
} catch (TransientException e) {
    // deadlock, потеря лидера — драйвер уже повторял, дальше решает приложение
} catch (ClientException e) {
    // синтаксис, нарушение ограничения — повторять бесполезно
} catch (ServiceUnavailableException e) {
    // база недоступна
}
```

## Наблюдаемость

В шестой версии появился Observation SPI — точка подключения трассировки на уровне драйвера, а не приложения. Подробно в уроке 23.

Там же появилась поддержка `System.Logger`, а старый интерфейс `Logging` объявлен устаревшим:

```java
var config = Config.builder()
    .withLogging(org.neo4j.driver.Logging.javaUtilLogging(java.util.logging.Level.INFO))
    .build();
```

## Практика

1. Создай Gradle-проект на Java 25, подключи BOM драйвера и сам драйвер.
2. Открой драйвер к локальному Neo4j и выполни `verifyConnectivity()`.
3. Выполни через `executableQuery` запрос, возвращающий заказы пользователя, и выведи их в консоль.
4. Опиши record `OrderSummary` и получи результат сразу списком объектов.
5. Выведи из сводки количество созданных узлов после `MERGE` нового товара.
6. Напиши операцию в `executeWrite`, которая читает текущую цену и на её основе ставит новую. Объясни, почему такой код обязан быть идемпотентным.
7. Верни `Result` наружу из колбэка и зафиксируй ошибку при попытке его прочитать.
8. Загрузи 5000 товаров двумя способами: циклом по одному запросу на строку и одним `UNWIND $rows`. Замерь время обоих вариантов.
9. Поставь транзакции таймаут в 1 секунду и выполни заведомо долгий запрос — зафиксируй исключение.
10. Добавь метаданные транзакции и найди свой запрос в `SHOW TRANSACTIONS` из `cypher-shell`, пока он выполняется.

## Итоги урока

- Spring Data Neo4j работает поверх драйвера, поэтому поведение транзакций, повторов и маршрутизации объясняется на его уровне.
- `Driver` — тяжёлый объект с пулом соединений, создаётся один раз на приложение; `Session` — лёгкая, непотокобезопасная, на единицу работы.
- `executableQuery` — рекомендуемый API драйвера 6: сам открывает сессию, создаёт транзакцию и повторяет её при `TransientError`.
- Драйвер 6 умеет отображать записи в Java records по совпадению имён компонентов и колонок `RETURN`.
- Из колбэка транзакции нельзя возвращать `Result` — он мёртв после коммита; данные вычитывают внутри колбэка.
- Колбэк транзакции обязан быть идемпотентным, потому что драйвер повторяет его при временных ошибках.
- В шестой версии удалены `readTransaction`/`writeTransaction`, `asyncSession`/`reactiveSession` и `RxSession`; асинхронная и реактивная сессии запрашиваются через `session(Class)`.
- Батчевая запись делается одним `UNWIND $rows` пачками по 1000-10000 строк, а не циклом с запросом на строку.
- `fetchSize` включает потоковую выдачу и спасает от `OutOfMemory` на больших результатах.
- Метаданные транзакции видны в `SHOW TRANSACTIONS` и query log — это основной способ связать зависший запрос с местом в коде.
