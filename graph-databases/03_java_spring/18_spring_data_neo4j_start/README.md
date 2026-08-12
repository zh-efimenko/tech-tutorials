# Урок 18. Spring Data Neo4j: старт

## Что даёт SDN поверх драйвера

Драйвер из урока 17 возвращает записи и значения. Spring Data Neo4j добавляет отображение графа на доменные классы, репозитории с производными запросами и интеграцию с транзакциями Spring.

| Задача | Драйвер | SDN |
|---|---|---|
| Выполнить Cypher | Да | Да, через `Neo4jClient` |
| Отобразить узел в объект | Вручную | Автоматически по `@Node` |
| Загрузить связанные объекты | Вручную | Автоматически по `@Relationship` |
| Сохранить объект вместе со связями | Вручную | `repository.save()` |
| `@Transactional` | Нет | Да |

## Подключение

```groovy
// settings.gradle.kts
rootProject.name = "shop-graph"
```

```groovy
// build.gradle.kts
plugins {
    java
    id("org.springframework.boot") version "4.1.0"
    id("io.spring.dependency-management") version "1.1.7"
}

group = "shop.graph"
version = "0.0.1"

repositories { mavenCentral() }

java { toolchain { languageVersion = JavaLanguageVersion.of(25) } }

dependencies {
    implementation("org.springframework.boot:spring-boot-starter-data-neo4j")
}
```

Версии драйвера и SDN задаёт Spring Boot — вручную их пинить не нужно и вредно. Spring Boot 4.1.x приносит Spring Data Neo4j 8.1 и Neo4j Java Driver 6.1.

```yaml
# application.yml
spring:
  neo4j:
    uri: bolt://localhost:7687
    authentication:
      username: neo4j
      password: graphpassword
  data:
    neo4j:
      database: neo4j
```

> **Внимание**: настройки подключения живут в `spring.neo4j.*`, а настройки маппинга — в `spring.data.neo4j.*`. Их регулярно путают: `spring.data.neo4j.uri` молча игнорируется, и приложение уходит на `bolt://localhost:7687` по умолчанию.

## Доменные классы

```java
package shop.graph.domain;

import org.springframework.data.neo4j.core.schema.Id;
import org.springframework.data.neo4j.core.schema.Node;
import org.springframework.data.neo4j.core.schema.Property;
import org.springframework.data.neo4j.core.schema.Relationship;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

@Node("User")                                    // метка в графе
public class UserEntity {

    @Id                                          // бизнес-ключ, не сгенерированный
    private String email;

    private String name;
    private String city;
    private String status;

    @Property("registeredAt")                    // если имя поля и свойства расходятся
    private LocalDate registeredAt;

    @Relationship(type = "PLACED", direction = Relationship.Direction.OUTGOING)
    private List<OrderEntity> orders = new ArrayList<>();

    @Relationship(type = "FOLLOWS", direction = Relationship.Direction.OUTGOING)
    private List<UserEntity> following = new ArrayList<>();

    // конструкторы, геттеры и сеттеры опущены
}
```

Класс заказа, на который ссылается `UserEntity`. Свойства связи `CONTAINS` тут пока не отображаются — это тема урока 19.

```java
@Node("Order")
public class OrderEntity {

    @Id
    private Long orderId;                            // бизнес-ключ из датасета урока 9

    private Double total;
    private String status;
    private LocalDate createdAt;

    // конструкторы, геттеры и сеттеры опущены
}
```

```java
@Node("Product")
public class ProductEntity {

    @Id
    private String sku;

    private String title;
    private Double price;

    @Relationship(type = "IN_CATEGORY", direction = Relationship.Direction.OUTGOING)
    private CategoryEntity category;

    @Relationship(type = "MADE_BY", direction = Relationship.Direction.OUTGOING)
    private BrandEntity brand;
}
```

### Идентификаторы

Три варианта, и выбор влияет на всю модель.

```java
// 1. Бизнес-ключ — предпочтительно
@Id private String email;

// 2. Сгенерированный UUID
@Id @GeneratedValue(UUIDGenerator.class) private UUID id;

// 3. Внутренний идентификатор базы — не использовать
@Id @GeneratedValue private Long id;
```

> **Важно**: третий вариант опирается на `elementId` из урока 4 — идентификатор, который не переносится между инстансами и переиспользуется после удаления. Для доменной сущности это ловушка. Он остаётся допустимым только в `@RelationshipProperties`, где SDN требует его технически.

Бизнес-ключ работает и с ограничением уникальности из урока 12: `MERGE` по нему идемпотентен, и SDN сам делает `MERGE`, а не `CREATE`, когда у сущности заполнен `@Id`.

### Направление связи

```java
// Товар знает свою категорию
@Relationship(type = "IN_CATEGORY", direction = Relationship.Direction.OUTGOING)
private CategoryEntity category;

// Категория знает свои товары — та же связь, вид с другой стороны
@Node("Category")
public class CategoryEntity {
    @Id private String categoryId;
    private String name;

    @Relationship(type = "IN_CATEGORY", direction = Relationship.Direction.INCOMING)
    private List<ProductEntity> products = new ArrayList<>();
}
```

Одна связь в графе может быть отображена с обеих сторон. Это удобно для чтения, но опасно для записи: сохранение объекта с обеих сторон способно создать связь дважды или перезаписать её. Практическое правило — **владелец связи один**, обратная сторона используется только для чтения.

## Репозитории

```java
package shop.graph.repository;

import org.springframework.data.neo4j.repository.Neo4jRepository;
import shop.graph.domain.UserEntity;
import java.util.List;
import java.util.Optional;

public interface UserRepository extends Neo4jRepository<UserEntity, String> {

    Optional<UserEntity> findByEmail(String email);

    List<UserEntity> findByCity(String city);

    List<UserEntity> findByCityAndStatus(String city, String status);

    List<UserEntity> findByNameContainingIgnoreCase(String fragment);

    List<UserEntity> findByRegisteredAtAfter(LocalDate date);

    long countByStatus(String status);

    boolean existsByEmail(String email);
}
```

`Neo4jRepository<T, ID>` даёт стандартный набор: `save`, `saveAll`, `findById`, `findAll`, `deleteById`, `count`. Производные запросы строятся по имени метода так же, как в Spring Data JPA.

### Производные запросы по связям

```java
public interface ProductRepository extends Neo4jRepository<ProductEntity, String> {

    // Обход одной связи по имени метода
    List<ProductEntity> findByCategoryName(String categoryName);

    List<ProductEntity> findByBrandNameAndPriceGreaterThan(String brand, Double price);

    List<ProductEntity> findByPriceBetweenOrderByPriceDesc(Double from, Double to);
}
```

> **Внимание**: производные запросы покрывают обход глубины 1-2. Всё, что сложнее — рекомендации, обходы переменной длины, агрегации — пишется на Cypher через `@Query`. Попытка выразить графовый обход именем метода упирается в предел быстро, и это нормально: сила Neo4j в Cypher, а не в генерации по именам.

## Сохранение

```java
@Service
public class CatalogService {

    private final ProductRepository productRepository;

    public CatalogService(ProductRepository productRepository) {
        this.productRepository = productRepository;
    }

    @Transactional
    public ProductEntity addProduct(String sku, String title, Double price, CategoryEntity category) {
        var product = new ProductEntity(sku, title, price);
        product.setCategory(category);
        return productRepository.save(product);   // сохранит и товар, и связь IN_CATEGORY
    }
}
```

`save()` сохраняет объект **вместе со связанными объектами**, которые видит в полях с `@Relationship`. Это удобно и опасно одновременно: сохранение пользователя с загруженным списком из тысячи заказов запишет все тысячу.

Именно поэтому глубина загрузки и проекции — тема отдельного урока 19.

## Как SDN видит граф

Понимать генерируемый Cypher важно: без этого невозможно объяснить производительность.

```java
userRepository.findByEmail("anna@shop.io");
```

превращается **не в один запрос**. SDN 8 сначала собирает идентификаторы узлов и связей, а потом отдельными запросами догружает каждый уровень:

```cypher
// 1. Найти корневой узел
MATCH (userEntity:`User`) WHERE userEntity.email = $email
WITH collect(elementId(userEntity)) AS __sn__ RETURN __sn__

// 2. Собрать идентификаторы связанных узлов — по запросу на каждый тип связи
MATCH (userEntity:`User`) WHERE userEntity.email = $email
OPTIONAL MATCH (userEntity)-[__sr__:`FOLLOWS`]->(__srn__:`User`)
WITH collect(elementId(userEntity)) AS __sn__,
     collect(elementId(__srn__)) AS __srn__,
     collect(elementId(__sr__)) AS __sr__
RETURN __sn__, __srn__, __sr__

// 3. То же самое для найденных на шаге 2 узлов — и так вглубь, пока есть что разворачивать
MATCH (userEntity:`User`) WHERE elementId(userEntity) IN $__ids__
OPTIONAL MATCH (userEntity)-[__sr__:`FOLLOWS`]->(__srn__:`User`)
...

// 4. В конце — сборка результата по накопленным идентификаторам
MATCH (rootNodeIds:`User`) WHERE elementId(rootNodeIds) IN $rootNodeIds
...
```

Это принципиально важно для понимания производительности. Каждое поле с `@Relationship` — не «плюс один `OPTIONAL MATCH` в общем запросе», а **отдельная серия запросов**, причём рекурсивная: связь `FOLLOWS` ведёт от пользователя к пользователю, у которого тоже есть `FOLLOWS`, и SDN разворачивает уровень за уровнем. Поиск одного пользователя по email в модели из двух связей на датасете курса порождает больше десятка запросов к базе.

Отсюда правило, которое разбирается в уроке 19: **сущности со связями — только там, где нужно сохранять; для чтения используются проекции**.

Посмотреть фактический Cypher можно включив логирование:

```yaml
logging:
  level:
    org.springframework.data.neo4j.cypher: DEBUG
```

## Циклы в модели

Пользователь ссылается на заказы, заказ — на пользователя. SDN обрывает цикл при загрузке, поэтому до `StackOverflowError` при сериализации обычно не доходит — вместо этого клиенту уезжает ответ с многоуровневой вложенностью на десятки килобайт вместо нужных трёх полей. Это тише, чем ошибка, и потому опаснее: проблема всплывает не в тестах, а под нагрузкой.

Три решения, по возрастанию правильности:

1. `@JsonIgnore` на обратной ссылке — работает, но смешивает слои.
2. Не объявлять обратную связь в классе вообще — чаще всего достаточно.
3. Отдавать наружу DTO, а не сущность — правильный вариант, разбирается в уроке 19.

## Проверка на старте

```java
@SpringBootApplication
public class ShopGraphApplication {

    public static void main(String[] args) {
        SpringApplication.run(ShopGraphApplication.class, args);
    }

    @Bean
    ApplicationRunner smokeTest(UserRepository users, ProductRepository products) {
        return args -> {
            System.out.println("Пользователей: " + users.count());
            System.out.println("Товаров: " + products.count());
            users.findByEmail("anna@shop.io")
                 .ifPresent(u -> System.out.println("Заказов у Анны: " + u.getOrders().size()));
        };
    }
}
```

## Практика

1. Создай Spring Boot 4.1 проект на Java 25 со стартером `spring-boot-starter-data-neo4j`.
2. Пропиши подключение в `application.yml` и запусти приложение на загруженном датасете из урока 9.
3. Опиши сущности `UserEntity`, `ProductEntity`, `CategoryEntity` с бизнес-ключами в `@Id`.
4. Создай репозитории и выведи в `ApplicationRunner` количество пользователей и товаров.
5. Напиши производные запросы: поиск по городу, по фрагменту имени, по диапазону цены с сортировкой. Если в базе уже лежат синтетические данные из урока 9, поиск по городу вернёт тысячи пользователей и уронит приложение по heap — сначала удали синтетику (`MATCH (n:Synthetic) CALL (n) { DETACH DELETE n } IN TRANSACTIONS`) или ограничь выборку через `Pageable`. Это не дефект задания, а прямое следствие того, что сущность тянет за собой связи.
6. Напиши производный запрос с обходом связи — товары по названию категории.
7. Включи `DEBUG`-логирование Cypher и посмотри, какой запрос генерируется для `findByEmail`.
8. Добавь в `UserEntity` ещё две связи и посчитай в логах, сколько запросов к базе порождает один `findByEmail` до и после.
9. Сохрани новый товар вместе с категорией одним `save()` и проверь в `cypher-shell`, что связь создалась.
10. Опиши обратную связь от категории к товарам, отдай сущность из REST-контроллера и посмотри, что вернётся. SDN обрывает цикл при загрузке, поэтому вместо ошибки, скорее всего, придёт ответ на десятки килобайт с глубокой вложенностью — оцени, сколько лишнего уехало клиенту.

## Итоги урока

- SDN добавляет к драйверу отображение графа на классы, репозитории и интеграцию с транзакциями Spring; сам Cypher по-прежнему выполняет драйвер.
- Версии драйвера и SDN задаёт Spring Boot: 4.1.x приносит SDN 8.1 и драйвер 6.1, пинить их вручную не нужно.
- Настройки подключения находятся в `spring.neo4j.*`, а маппинга — в `spring.data.neo4j.*`; перепутанный префикс молча игнорируется.
- В `@Id` предпочтителен бизнес-ключ с ограничением уникальности: SDN делает по нему `MERGE`, и сохранение становится идемпотентным.
- `@GeneratedValue` без параметров опирается на внутренний идентификатор базы, который не переносим и переиспользуется, — для доменных сущностей это ловушка.
- Одна связь может быть отображена с обеих сторон, но владелец должен быть один: сохранение с обеих сторон дублирует или перезаписывает связь.
- Производные запросы покрывают обход глубины 1-2; всё сложнее пишется на Cypher через `@Query`.
- `save()` записывает объект вместе со всеми загруженными связями — сохранение сущности с тысячей заказов запишет тысячу связей.
- Загрузка сущности со связями — это не один запрос, а серия: SDN собирает идентификаторы узлов и связей и разворачивает уровни отдельными запросами, поэтому каждое поле с `@Relationship` стоит дороже, чем выглядит.
- Циклические ссылки в модели раздувают JSON до многоуровневой вложенности вместо явной ошибки; правильное решение — отдавать DTO, а не сущность.
