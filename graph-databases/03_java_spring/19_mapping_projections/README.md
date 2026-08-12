# Урок 19. Маппинг и проекции

## Проблема глубины загрузки

Урок 18 закончился на важном факте: каждое поле с `@Relationship` добавляет обход при загрузке сущности. На модели магазина это выглядит так:

```
findByEmail("anna@shop.io")
    └─▶ User
         ├─▶ PLACED   ──▶ Order
         │                 └─▶ CONTAINS ──▶ Product
         │                                   ├─▶ IN_CATEGORY ──▶ Category
         │                                   └─▶ MADE_BY     ──▶ Brand
         └─▶ FOLLOWS  ──▶ User
                          └─▶ PLACED ──▶ Order ...
```

Загрузка одного пользователя тянет его заказы, товары в них, категории и бренды товаров, подписки и заказы подписок. SDN обрывает рекурсию на циклах, но объём всё равно вырастает непредсказуемо.

Три инструмента управления: проекции, `@Query` с явным `RETURN` и разделение доменной модели на классы под разные сценарии.

## Свойства связи

Свойства на связи — например `qty` и `priceAtPurchase` на `CONTAINS` — отображаются отдельным классом.

```java
package shop.graph.domain;

import org.springframework.data.neo4j.core.schema.RelationshipId;
import org.springframework.data.neo4j.core.schema.RelationshipProperties;
import org.springframework.data.neo4j.core.schema.TargetNode;

@RelationshipProperties
public class OrderItem {

    @RelationshipId                       // обязателен: SDN хранит здесь внутренний id связи
    private String id;

    private Integer qty;
    private Double priceAtPurchase;

    @TargetNode                           // куда указывает связь
    private ProductEntity product;

    public OrderItem() {}

    public OrderItem(ProductEntity product, Integer qty, Double priceAtPurchase) {
        this.product = product;
        this.qty = qty;
        this.priceAtPurchase = priceAtPurchase;
    }
    // геттеры опущены
}
```

```java
@Node("Order")
public class OrderEntity {

    @Id private Long orderId;
    private Double total;
    private String status;
    private LocalDate createdAt;

    @Relationship(type = "CONTAINS", direction = Relationship.Direction.OUTGOING)
    private List<OrderItem> items = new ArrayList<>();
}
```

Правила класса `@RelationshipProperties`:

- ровно одно поле с `@TargetNode`;
- обязательное поле с `@RelationshipId` — без него SDN падает при старте контекста;
- сам класс **не** помечается `@Node`.

> **Важно**: поле `@RelationshipId` нужно SDN, чтобы при сохранении понять, какую связь перезаписать, а не создать новую. Без него каждое сохранение заказа создавало бы дубликаты связей `CONTAINS`.

Тип поля — `String`, потому что современные идентификаторы Neo4j строковые (`elementId` из урока 4). В старых примерах встречается `Long` с `@Id @GeneratedValue` — это унаследованная форма.

## Интерфейсные проекции

Самый дешёвый способ ограничить объём: описать интерфейс с нужными геттерами.

```java
public interface ProductSummary {
    String getSku();
    String getTitle();
    Double getPrice();
}
```

```java
public interface ProductRepository extends Neo4jRepository<ProductEntity, String> {
    List<ProductSummary> findProjectedByPriceGreaterThan(Double price);
}
```

SDN сгенерирует `RETURN` только с тремя свойствами и не пойдёт по связям. На узле с вектором эмбеддинга из трека 6 это разница между килобайтом и мегабайтом трафика.

Проекция умеет и вложенность:

```java
public interface ProductWithCategory {
    String getSku();
    String getTitle();
    CategoryInfo getCategory();

    interface CategoryInfo {
        String getName();
    }
}
```

## DTO-проекции на records

Более выразительный вариант — записать нужную форму классом.

```java
public record ProductView(String sku, String title, Double price, String categoryName) {}
```

```java
public interface ProductRepository extends Neo4jRepository<ProductEntity, String> {

    @Query("""
           MATCH (p:Product)-[:IN_CATEGORY]->(c:Category)
           WHERE p.price > $minPrice
           RETURN p.sku AS sku, p.title AS title, p.price AS price, c.name AS categoryName
           ORDER BY p.price DESC
           """)
    List<ProductView> findViewsAbove(Double minPrice);
}
```

Имена в `RETURN ... AS` обязаны совпадать с именами компонентов record. Это тот же принцип, что у маппинга драйвера из урока 17.

> **Внимание**: map-проекция Cypher на верхнем уровне для DTO **не работает так, как ожидается**. Запрос
>
> ```java
> @Query("""
>        MATCH (p:Product)-[:IN_CATEGORY]->(c:Category {name: $category})
>        RETURN p {.sku, .title, .price, categoryName: c.name} AS productView
>        """)
> List<ProductView> findByCategoryProjected(String category);
> ```
>
> вернёт объекты, у которых `sku`, `title` и `price` заполнены, а `categoryName` равен `null` — хотя сам Cypher возвращает этот ключ. Причина в том, что для репозитория сущности `ProductEntity` SDN трактует `ProductView` как проекцию **этой сущности** и разрешает компоненты record по её свойствам, а не по ключам возвращённой map. Компонента `categoryName` среди свойств `Product` нет, поэтому она остаётся пустой.
>
> Правило: **каждое поле DTO возвращается отдельной колонкой через `AS`**. Форма выше пригодна только когда все поля принадлежат одному узлу.

## Вложенные структуры

Внутри `collect` map-проекция работает штатно — там элементы списка отображаются как обычные map.

```java
public record OrderView(Long orderId, Double total, String status, List<ItemView> items) {}
public record ItemView(String sku, String title, Integer qty, Double priceAtPurchase) {}
```

```java
@Query("""
       MATCH (u:User {email: $email})-[:PLACED]->(o:Order)
       OPTIONAL MATCH (o)-[c:CONTAINS]->(p:Product)
       WITH o, collect(p {sku: p.sku, title: p.title,
                          qty: c.qty, priceAtPurchase: c.priceAtPurchase}) AS items
       ORDER BY o.createdAt DESC
       RETURN o.orderId AS orderId, o.total AS total, o.status AS status, items
       """)
List<OrderView> findOrderViews(String email);
```

Так формируется ровно тот ответ, который нужен API, — без загрузки доменного графа и без отдельного слоя преобразования. Обрати внимание: `qty` и `priceAtPurchase` берутся со связи `c`, и внутри `collect` это отображается корректно.

> **Внимание**: сортировка вынесена в `WITH ... ORDER BY` **до** `RETURN`. В этом запросе так делать не обязательно — агрегация закончилась в `WITH`, и `o` дальше доступна. Правило срабатывает, когда агрегат стоит в самом `RETURN`: тогда после него доступны только результаты агрегации, и `ORDER BY o.createdAt` даёт `42N44`:
>
> ```cypher
> // Упадёт: o уже недоступна после агрегирующего RETURN
> MATCH (u:User {email: $email})-[:PLACED]->(o:Order)
> RETURN o.status AS status, count(*) AS orders
> ORDER BY o.createdAt;
> ```
>
> Привычка выносить сортировку в `WITH` избавляет от необходимости каждый раз проверять, какой это случай.

## Когда что применять

| Инструмент | Когда | Плюсы | Минусы |
|---|---|---|---|
| Полная сущность | Нужно изменять и сохранять | `save()` работает как ожидается | Тянет все связи |
| Интерфейсная проекция | Простое чтение части полей | Ноль кода | Только свойства и простая вложенность |
| DTO-record с `@Query` и колонками `AS` | Чтение сложной формы | Полный контроль над Cypher | Нельзя сохранять |
| Map-проекция `p {...}` внутри `collect` | Вложенные списки | Читаемо, собирается одним запросом | На верхнем уровне для DTO не работает |

Практическое правило: **сущности для записи, проекции для чтения**. Это снимает почти все проблемы производительности SDN.

## Ограничение глубины на уровне модели

Радикальный, но часто правильный приём — не объявлять связь, которая нужна редко.

```java
// Вариант для чтения списка пользователей: связей нет вообще
@Node("User")
public class UserSummaryEntity {
    @Id private String email;
    private String name;
    private String city;
}
```

> **Внимание**: второй `@Node("User")` в том же контексте **не заведётся**. SDN 8 требует, чтобы у метки было ровно одно описание сущности, и падает на старте:
>
> ```
> MappingException: The schema already contains a node description under the primary label User
> ```
>
> Поэтому урезать модель приходится иначе: либо интерфейсной проекцией, либо DTO с `@Query` — то есть инструментами, разобранными выше. Приём «два класса на одну метку» встречается в статьях под SDN 6 и там работал; на текущей версии он неприменим.

Если урезанная сущность всё же нужна как отдельный класс, метку ей задают свою — например, техническую, проставленную миграцией. И в любом случае сохранять такой класс опасно: `save()` увидит пустые коллекции связей и может удалить существующие связи в графе.

## Циклы и сериализация

Модель магазина содержит цикл: пользователь ссылается на заказы, подписки ссылаются на пользователей. При чтении SDN справляется, при сериализации в JSON — нет.

```
UserEntity → orders → OrderEntity → ... 
UserEntity → following → UserEntity → following → ... StackOverflowError
```

Правильное решение — не отдавать сущность наружу вообще:

```java
@RestController
@RequestMapping("/api/users")
public class UserController {

    private final UserRepository users;

    public UserController(UserRepository users) {
        this.users = users;
    }

    @GetMapping("/{email}/orders")
    public List<OrderView> orders(@PathVariable String email) {
        return users.findOrderViews(email);     // DTO, а не сущность
    }
}
```

## Типы данных

| Cypher | Java |
|---|---|
| `INTEGER` | `Long`, `Integer` |
| `FLOAT` | `Double` |
| `STRING` | `String` |
| `BOOLEAN` | `Boolean` |
| `DATE` | `java.time.LocalDate` |
| `LOCAL_DATETIME` | `java.time.LocalDateTime` |
| `ZONED_DATETIME` | `java.time.ZonedDateTime`, `OffsetDateTime` |
| `DURATION` | `java.time.Duration`, `Period` |
| `POINT` | `org.springframework.data.neo4j.types.GeographicPoint2d` |
| `LIST` примитивов | `List<T>`, массив |

Enum отображается на строку автоматически:

```java
public enum OrderStatus { DELIVERED, SHIPPED, CANCELLED }

@Node("Order")
public class OrderEntity {
    private OrderStatus status;    // в графе хранится "DELIVERED"
}
```

> **Внимание**: в датасете курса статусы записаны в нижнем регистре (`delivered`), а имена констант enum — в верхнем. Прямое отображение не сработает: SDN сравнивает строку с `name()` константы. Либо приводи данные к именам констант миграцией из урока 16, либо оставляй `String`.

## Конвертеры

Для типов, которых нет в таблице, пишется конвертер.

```java
import org.springframework.data.neo4j.core.convert.Neo4jConversions;
import org.springframework.core.convert.converter.Converter;
import org.neo4j.driver.Value;
import org.neo4j.driver.Values;

@Configuration
public class Neo4jConfig {

    @Bean
    Neo4jConversions neo4jConversions() {
        return new Neo4jConversions(Set.of(new MoneyToValue(), new ValueToMoney()));
    }

    static class MoneyToValue implements Converter<Money, Value> {
        @Override public Value convert(Money source) {
            return Values.value(source.amount().toPlainString());
        }
    }

    static class ValueToMoney implements Converter<Value, Money> {
        @Override public Money convert(Value source) {
            return new Money(new BigDecimal(source.asString()));
        }
    }
}
```

Типичный случай — денежные суммы: `Double` для денег не годится, а `BigDecimal` в графе нативно не хранится.

## Практика

1. Опиши класс `OrderItem` с `@RelationshipProperties` и подключи его к `OrderEntity` через `@Relationship`.
2. Убери поле `@RelationshipId` и зафиксируй ошибку при старте контекста.
3. Загрузи пользователя `anna@shop.io` и убедись, что `qty` и `priceAtPurchase` со связи доехали до объекта.
4. Опиши интерфейсную проекцию `ProductSummary` и метод репозитория, который её возвращает.
5. Включи DEBUG-логирование Cypher и сравни запросы для полной сущности и для проекции.
6. Опиши record `ProductView` и метод с `@Query`, где имена в `RETURN ... AS` совпадают с компонентами record.
7. Намеренно переименуй одну колонку в `RETURN` и посмотри, что произойдёт: исключения не будет, соответствующее поле DTO молча окажется `null`. Найди в логах предупреждение SDN об этом — оно единственный признак опечатки.
8. Собери вложенный `OrderView` со списком `ItemView` одним запросом через `collect`.
9. Опиши второй класс `@Node("User")` без связей и зафиксируй `MappingException` при старте контекста. Затем добейся того же результата интерфейсной проекцией и сравни объём загружаемых данных.
10. Отдай сущность `UserEntity` из REST-контроллера и зафиксируй, что происходит при сериализации. Замени на DTO.

## Итоги урока

- Каждое объявленное поле с `@Relationship` расширяет граф загрузки; на связной модели объём растёт непредсказуемо.
- Свойства связи отображаются классом с `@RelationshipProperties`, ровно одним `@TargetNode` и обязательным `@RelationshipId`.
- `@RelationshipId` нужен, чтобы при сохранении перезаписать связь, а не создать дубликат; тип поля — `String`, потому что идентификаторы Neo4j строковые.
- Интерфейсные проекции ограничивают `RETURN` свойствами и не идут по связям — нулевой код и заметный выигрыш.
- DTO-record с `@Query` даёт полный контроль над Cypher; имена в `RETURN ... AS` обязаны совпадать с компонентами record.
- Map-проекция `p {...}` на верхнем уровне не годится для DTO: SDN разрешает компоненты record по свойствам сущности, и поля из соседних узлов остаются `null`; каждое поле возвращается отдельной колонкой через `AS`.
- Внутри `collect` map-проекция работает штатно, в том числе для свойств связи, — так собираются вложенные списки одним запросом.
- После агрегирующего `RETURN` переменные до него недоступны: сортировку выносят в `WITH ... ORDER BY` перед `RETURN`, иначе запрос падает с `42N44`.
- Практическое правило: сущности для записи, проекции для чтения.
- Отобразить две сущности на одну метку SDN 8 не позволяет: контекст падает с `MappingException`, поэтому урезанные формы делаются проекциями и DTO, а не вторым `@Node`.
- Циклы в модели ломают сериализацию в JSON; решение — отдавать наружу DTO, а не сущности.
- Enum отображается на строку по имени константы, поэтому данные в графе должны совпадать с `name()` — иначе нужен `String` или миграция.
