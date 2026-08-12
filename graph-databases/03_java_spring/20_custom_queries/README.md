# Урок 20. Кастомные запросы

## Четыре уровня доступа

Производные запросы из урока 18 покрывают обход глубины 1-2. Всё сложнее пишется вручную, и SDN даёт четыре уровня — от самого высокого к самому низкому.

```
@Query на репозитории       ← Cypher + маппинг в сущность или DTO
Neo4jTemplate               ← Cypher + маппинг, без объявления репозитория
Neo4jClient                 ← Cypher + ручной маппинг строк
Cypher-DSL                  ← построение Cypher кодом вместо строк
```

## @Query

Cypher прямо в аннотации метода репозитория.

```java
public interface UserRepository extends Neo4jRepository<UserEntity, String> {

    @Query("""
           MATCH (u:User {email: $email})-[:PURCHASED]->(:Product)
                 <-[:PURCHASED]-(other:User)-[:PURCHASED]->(rec:Product)
           WHERE other <> u AND NOT (u)-[:PURCHASED]->(rec)
           RETURN rec.sku AS sku, rec.title AS title, count(*) AS score
           ORDER BY score DESC
           LIMIT $limit
           """)
    List<Recommendation> recommend(String email, int limit);
}

public record Recommendation(String sku, String title, Long score) {}
```

Параметры связываются по именам аргументов метода. Если имена в байткоде не сохраняются (сборка без `-parameters`), используется `@Param`:

```java
@Query("MATCH (u:User {city: $city}) RETURN u")
List<UserEntity> findInCity(@Param("city") String city);
```

Spring Boot включает `-parameters` по умолчанию, поэтому в обычном проекте `@Param` не нужен.

### Возврат сущностей

Чтобы SDN собрал полноценную сущность со связями, запрос должен вернуть узел, его связи и связанные узлы:

```java
@Query("""
       MATCH (u:User {email: $email})
       OPTIONAL MATCH (u)-[r:PLACED]->(o:Order)
       RETURN u, collect(r), collect(o)
       """)
Optional<UserEntity> findWithOrders(String email);
```

> **Внимание**: если оставить `OPTIONAL MATCH`, но убрать из `RETURN` только `collect(r), collect(o)`, запрос вернёт по строке на каждый заказ, и метод с `Optional<UserEntity>` упадёт с `IncorrectResultSizeDataAccessException: Expected a result with a single record, but this result contains at least one more`. А вот если сократить запрос до одного `MATCH (u:User {email: $email}) RETURN u`, сущность придёт с пустыми коллекциями связей — и это уже молчаливая ошибка, а не исключение. Для чтения обычно проще вернуть DTO, чем собирать сущность вручную.

### Пагинация и сортировка

```java
@Query(value = """
               MATCH (p:Product)-[:IN_CATEGORY]->(c:Category {name: $category})
               RETURN p
               SKIP $skip LIMIT $limit
               """,
       countQuery = """
                    MATCH (p:Product)-[:IN_CATEGORY]->(c:Category {name: $category})
                    RETURN count(p)
                    """)
Page<ProductEntity> findPageByCategory(String category, Pageable pageable);
```

`$skip` и `$limit` подставляет SDN из `Pageable`. Для `Page` обязателен `countQuery` — иначе SDN не сможет посчитать общее количество.

## Neo4jTemplate

То же самое, но без объявления интерфейса репозитория. Удобно для разовых и динамических запросов.

```java
@Service
public class ReportService {

    private final Neo4jTemplate template;

    public ReportService(Neo4jTemplate template) {
        this.template = template;
    }

    public List<ProductEntity> expensive(double minPrice) {
        return template.findAll("MATCH (p:Product) WHERE p.price > $min RETURN p",
                                Map.of("min", minPrice),
                                ProductEntity.class);
    }

    public Optional<ProductEntity> bySku(String sku) {
        return template.findById(sku, ProductEntity.class);
    }

    public long countProducts() {
        return template.count(ProductEntity.class);
    }
}
```

`Neo4jTemplate` — то, во что делегируют все репозитории. Ничего, чего нет в репозиториях, он не добавляет, кроме возможности обойтись без интерфейса.

## Neo4jClient

Самый низкий уровень внутри Spring: выполняет Cypher и отдаёт строки, маппинг пишется руками. Нужен, когда результат не ложится ни на сущность, ни на DTO — агрегаты, статистика, результаты алгоритмов GDS из трека 4.

```java
@Service
public class AnalyticsService {

    private final Neo4jClient client;

    public AnalyticsService(Neo4jClient client) {
        this.client = client;
    }

    public Collection<CategoryRevenue> revenueByCategory(LocalDate from) {
        return client
            .query("""
                   MATCH (c:Category)<-[:IN_CATEGORY]-(:Product)<-[ci:CONTAINS]-(o:Order)
                   WHERE o.createdAt >= $from
                   RETURN c.name AS category,
                          sum(ci.qty * ci.priceAtPurchase) AS revenue,
                          count(DISTINCT o) AS orders
                   ORDER BY revenue DESC
                   """)
            .bind(from).to("from")
            .fetchAs(CategoryRevenue.class)
            .mappedBy((typeSystem, record) -> new CategoryRevenue(
                record.get("category").asString(),
                record.get("revenue").asDouble(),
                record.get("orders").asLong()))
            .all();
    }

    public Optional<Long> totalOrders() {
        return client.query("MATCH (:Order) RETURN count(*) AS c")
                     .fetchAs(Long.class)
                     .mappedBy((ts, record) -> record.get("c").asLong())
                     .one();
    }

    public void markActiveBuyers() {
        client.query("""
                     MATCH (u:User)-[:PLACED]->(:Order {status: 'delivered'})
                     WITH DISTINCT u
                     SET u:ActiveBuyer
                     """)
              .run();
    }
}

public record CategoryRevenue(String category, Double revenue, Long orders) {}
```

| Метод | Что возвращает |
|---|---|
| `.all()` | Все строки |
| `.one()` | `Optional`, ошибка если строк больше одной |
| `.first()` | `Optional` первой строки |
| `.run()` | Ничего, для изменяющих запросов |

`Neo4jClient` участвует в транзакциях Spring наравне с репозиториями — это его главное преимущество перед голым драйвером из урока 17.

### Сравнение уровней

| Уровень | Маппинг | Транзакции Spring | Когда |
|---|---|---|---|
| Производные запросы | Автоматический | Да | CRUD и простые фильтры |
| `@Query` | Автоматический | Да | Графовые обходы, DTO |
| `Neo4jTemplate` | Автоматический | Да | То же без интерфейса репозитория |
| `Neo4jClient` | Ручной | Да | Агрегаты, GDS, нестандартный результат |
| Драйвер | Ручной | Нет | Вне контекста Spring, батчевые загрузки |

## Cypher-DSL

Строить Cypher конкатенацией строк — прямой путь к инъекциям и опечаткам, которые ловятся только в рантайме. Cypher-DSL строит запрос типобезопасно, а SDN использует его внутри себя, поэтому библиотека уже есть в classpath.

```java
import org.neo4j.cypherdsl.core.Cypher;
import org.neo4j.cypherdsl.core.Node;
import org.neo4j.cypherdsl.core.Statement;

public class ProductQueryBuilder {

    public Statement byFilters(String category, Double minPrice, String brand) {
        Node product  = Cypher.node("Product").named("p");
        Node cat      = Cypher.node("Category").named("c");

        var conditions = Cypher.noCondition();
        if (minPrice != null) {
            conditions = conditions.and(product.property("price").gt(Cypher.parameter("minPrice", minPrice)));
        }
        if (brand != null) {
            conditions = conditions.and(product.property("brand").eq(Cypher.parameter("brand", brand)));
        }

        var match = category != null
            ? Cypher.match(product.relationshipTo(cat, "IN_CATEGORY"))
                    .where(cat.property("name").eq(Cypher.parameter("category", category)).and(conditions))
            : Cypher.match(product).where(conditions);

        return match.returning(product).orderBy(product.property("price").descending()).build();
    }
}
```

```java
// Сгенерированный Cypher и параметры доступны отдельно
Statement statement = builder.byFilters("Кофемолки", 2000.0, null);
String cypher = statement.getCypher();
Map<String, Object> params = statement.getCatalog().getParameters();
```

Выполнение через `Neo4jClient`:

```java
client.query(statement.getCypher())
      .bindAll(statement.getCatalog().getParameters())
      .fetchAs(ProductEntity.class)
      .mappedBy(mapper)
      .all();
```

Когда Cypher-DSL оправдан:

| Оправдан | Не оправдан |
|---|---|
| Фильтры собираются из необязательных параметров | Запрос фиксирован |
| Форма запроса зависит от прав пользователя | Простой обход |
| Нужна проверка синтаксиса на этапе компиляции | Читаемость важнее гибкости |

> **Важно**: у Cypher-DSL заметная цена — читаемость. Обход на пять шагов, записанный DSL, понять сложнее, чем тот же Cypher строкой. Правило: фиксированные запросы — строкой в `@Query`, динамические — через DSL.

## Работа с параметрами-списками

Массовые операции из урока 14 работают и через SDN.

```java
public interface ProductRepository extends Neo4jRepository<ProductEntity, String> {

    @Query("""
           UNWIND $rows AS row
           MERGE (p:Product {sku: row.sku})
           SET p.title = row.title, p.price = row.price
           RETURN count(*)
           """)
    long upsertAll(List<Map<String, Object>> rows);
}
```

Такой метод на порядки быстрее, чем `saveAll()` со списком сущностей, потому что `saveAll` выполняет отдельный запрос на каждый объект вместе с его связями.

## Вызов процедур

Процедуры APOC и GDS вызываются обычным Cypher через `Neo4jClient`.

```java
public Collection<PageRankScore> pageRank() {
    return client.query("""
                        CALL gds.pageRank.stream('userGraph')
                        YIELD nodeId, score
                        RETURN gds.util.asNode(nodeId).email AS email, score
                        ORDER BY score DESC
                        LIMIT 20
                        """)
                 .fetchAs(PageRankScore.class)
                 .mappedBy((ts, r) -> new PageRankScore(r.get("email").asString(), r.get("score").asDouble()))
                 .all();
}
```

Это основной способ вызывать алгоритмы из трека 4 в приложении.

## Практика

1. Напиши в репозитории метод `recommend` с `@Query` для коллаборативной рекомендации и верни DTO.
2. Проверь, что запрос отрабатывает на пользователе `anna@shop.io`, предварительно построив связи `PURCHASED` из урока 11.
3. Напиши `@Query`, возвращающий сущность `UserEntity` вместе с заказами через `collect`.
4. Убери из запроса `collect(r), collect(o)`, оставив `OPTIONAL MATCH`, и зафиксируй `IncorrectResultSizeDataAccessException`. Затем сократи запрос до `MATCH (u:User {email: $email}) RETURN u` и убедись, что теперь коллекция заказов приходит пустой без всякой ошибки.
5. Добавь метод с `Page<ProductEntity>` и `countQuery`, проверь работу пагинации.
6. Перепиши один из запросов на `Neo4jTemplate` без объявления репозитория.
7. Напиши через `Neo4jClient` отчёт по выручке в разрезе категорий с ручным маппингом.
8. Напиши через `Neo4jClient` изменяющий запрос с `.run()`, который проставляет метку `:ActiveBuyer`.
9. Собери через Cypher-DSL запрос с тремя необязательными фильтрами и выведи сгенерированный Cypher в консоль.
10. Реализуй `upsertAll` через `UNWIND $rows` и сравни время загрузки 1000 товаров с `saveAll()`.

## Итоги урока

- SDN даёт четыре уровня доступа: производные запросы, `@Query`, `Neo4jTemplate` и `Neo4jClient`; ниже находится только драйвер.
- Параметры `@Query` связываются по именам аргументов, потому что Spring Boot компилирует с `-parameters`; `@Param` нужен только без него.
- Чтобы `@Query` вернул сущность со связями, запрос обязан вернуть узел, связи и связанные узлы; иначе коллекции придут пустыми молча.
- Для `Page` требуется отдельный `countQuery`, а `$skip` и `$limit` подставляются из `Pageable`.
- `Neo4jTemplate` — то, во что делегируют репозитории; он полезен, когда интерфейс репозитория заводить не хочется.
- `Neo4jClient` выполняет произвольный Cypher с ручным маппингом и участвует в транзакциях Spring — это его отличие от голого драйвера.
- `Neo4jClient` — основной способ вызывать процедуры APOC и алгоритмы GDS из приложения.
- Cypher-DSL строит запрос типобезопасно и нужен для динамических фильтров; для фиксированных запросов он проигрывает обычной строке по читаемости.
- Массовая запись делается через `@Query` с `UNWIND $rows`, а не через `saveAll()`, который выполняет запрос на каждый объект.
