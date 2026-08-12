# Урок 22. Тестирование

## Почему не embedded-база

У Neo4j есть test harness — встраиваемый сервер для тестов. Соблазн понятен: быстрее контейнера, не требует Docker. Но он приносит в classpath само ядро Neo4j, из-за чего версия базы в тестах и в продакшне расходятся, а поведение процедур APOC и GDS отличается.

Рабочий вариант — Testcontainers: тот же образ, что в `compose.yml`, те же плагины, та же версия.

## Подключение

```groovy
dependencies {
    testImplementation("org.springframework.boot:spring-boot-starter-test")
    testImplementation("org.springframework.boot:spring-boot-testcontainers")
    testImplementation(platform("org.testcontainers:testcontainers-bom:1.21.3"))
    testImplementation("org.testcontainers:neo4j")
    testImplementation("org.testcontainers:junit-jupiter")

    // В Spring Boot 4 слайс-тесты вынесены в отдельные модули
    testImplementation("org.springframework.boot:spring-boot-data-neo4j-test")
}
```

> **Внимание**: Spring Boot 4.1 не управляет версиями модулей Testcontainers. Ядро `org.testcontainers:testcontainers` приезжает транзитивно вместе со `spring-boot-testcontainers`, а вот отдельные модули — нет: без явного импорта `testcontainers-bom` сборка падает на `Could not find org.testcontainers:neo4j:.` — без номера версии в сообщении, что сбивает с толку. BOM нужно подключать вручную, и версию в нём стоит сверить с той, что пришла транзитивно.

> **Внимание**: в Spring Boot 4 аннотация `@DataNeo4jTest` больше не входит в `spring-boot-starter-test` и сменила пакет. Было `org.springframework.boot.test.autoconfigure.data.neo4j.DataNeo4jTest`, стало `org.springframework.boot.data.neo4j.test.autoconfigure.DataNeo4jTest`, и живёт она в отдельном артефакте `spring-boot-data-neo4j-test`. Примеры из статей под Boot 3 не соберутся.

## @ServiceConnection

Современный способ связать контейнер с настройками Spring — без `@DynamicPropertySource` и ручного проброса URI.

```java
package shop.graph;

import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.testcontainers.containers.Neo4jContainer;
import org.testcontainers.utility.DockerImageName;

@TestConfiguration(proxyBeanMethods = false)
public class Neo4jTestConfig {

    @Bean
    @ServiceConnection
    Neo4jContainer<?> neo4jContainer() {
        return new Neo4jContainer<>(DockerImageName.parse("neo4j:2026.07.1-community"))
            .withoutAuthentication()
            .withPlugins("apoc", "graph-data-science")
            .withReuse(true);
    }
}
```

`@ServiceConnection` сам пропишет `spring.neo4j.uri` и учётные данные. Ради этой одной аннотации нужен `spring-boot-testcontainers`.

`withReuse(true)` оставляет контейнер жить между запусками тестов — экономит десятки секунд на каждом прогоне. Требует `testcontainers.reuse.enable=true` в `~/.testcontainers.properties`.

## Слайс-тест @DataNeo4jTest

Поднимает только слой доступа к данным: репозитории, `Neo4jTemplate`, `Neo4jClient`, конвертеры. Веб-слой, безопасность и остальные бины не создаются.

```java
package shop.graph;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.data.neo4j.test.autoconfigure.DataNeo4jTest;
import org.springframework.context.annotation.Import;
import org.springframework.data.neo4j.core.Neo4jClient;
import shop.graph.repository.UserRepository;

import static org.assertj.core.api.Assertions.assertThat;

@DataNeo4jTest
@Import(Neo4jTestConfig.class)
class UserRepositoryTest {

    @Autowired UserRepository users;
    @Autowired Neo4jClient client;

    @BeforeEach
    void setUp() {
        client.query("MATCH (n) DETACH DELETE n").run();
        client.query("""
                     CREATE (a:User {email:'anna@shop.io', name:'Анна', city:'Минск', status:'active'})
                     CREATE (i:User {email:'ivan@shop.io', name:'Иван', city:'Минск', status:'active'})
                     CREATE (o:Order {orderId: 1, total: 4990.0, status:'delivered'})
                     CREATE (a)-[:PLACED]->(o)
                     """)
              .run();
    }

    @Test
    void findsUserWithOrders() {
        var anna = users.findByEmail("anna@shop.io").orElseThrow();
        assertThat(anna.getName()).isEqualTo("Анна");
        assertThat(anna.getOrders()).hasSize(1);
    }

    @Test
    void findsByCity() {
        assertThat(users.findByCity("Минск")).hasSize(2);
    }
}
```

> **Внимание**: слайс поднимает только слой данных, но бины из главного класса приложения — в том числе `ApplicationRunner` со smoke-тестом из урока 18 — в контекст всё равно попадают. Пока такой бин зависит только от репозиториев, всё работает: они в слайсе есть. Но стоит ему потребовать `@Service` из урока 20 или 21, и контекст рухнет с `NoSuchBeanDefinitionException` ещё до первого запроса, потому что сервисные бины в слайс не входят. Самый простой выход — убрать runner из главного класса, когда он отслужил своё. Вариант с профилем работает только если профиль реально активирован: `@Profile("!test")` на бине **и** `@ActiveProfiles("test")` на тесте, потому что сам по себе слайс профиль `test` не включает.

> **Важно**: `@DataNeo4jTest` **не откатывает** транзакции после теста, в отличие от `@DataJpaTest`. Причина в том, что у Neo4j нет вложенных транзакций, а тестовый и прикладной код в SDN работают в разных сессиях. Изоляцию приходится обеспечивать явно — очисткой в `@BeforeEach`.

## Стратегии изоляции

| Стратегия | Скорость | Надёжность | Когда |
|---|---|---|---|
| `DETACH DELETE` всего графа в `@BeforeEach` | Быстро на малых данных | Полная | По умолчанию |
| Отдельный контейнер на класс тестов | Медленно | Полная | Тесты, ломающие схему |
| Уникальные данные на тест без очистки | Быстро | Хрупко | Только чтение |
| Снапшот и восстановление тома | Сложно | Полная | Большой эталонный датасет |

Первая стратегия покрывает почти всё. При этом важно чистить и схему, если тест её меняет:

```java
@BeforeEach
void clean() {
    client.query("MATCH (n) DETACH DELETE n").run();
    client.query("SHOW CONSTRAINTS YIELD name").fetchAs(String.class)
          .mappedBy((ts, r) -> r.get("name").asString())
          .all()
          .forEach(name -> client.query("DROP CONSTRAINT " + name).run());
}
```

## Фикстуры

Наполнять граф удобнее готовым Cypher-файлом, а не строками в коде.

```java
@TestConfiguration(proxyBeanMethods = false)
public class FixtureLoader {

    static void load(Neo4jClient client, String resource) throws IOException {
        var cypher = new ClassPathResource(resource).getContentAsString(StandardCharsets.UTF_8);
        for (String statement : cypher.split(";")) {
            if (!statement.isBlank()) {
                client.query(statement).run();
            }
        }
    }
}
```

```java
@BeforeEach
void setUp() throws IOException {
    client.query("MATCH (n) DETACH DELETE n").run();
    FixtureLoader.load(client, "fixtures/shop-small.cypher");
}
```

Второй вариант — загрузить контейнер настоящим датасетом курса:

```java
@Bean
@ServiceConnection
Neo4jContainer<?> neo4jContainer() {
    return new Neo4jContainer<>(DockerImageName.parse("neo4j:2026.07.1-community"))
        .withoutAuthentication()
        .withPlugins("apoc", "graph-data-science")
        .withCopyFileToContainer(
            MountableFile.forHostPath("../dataset/products.csv"), "/import/products.csv");
}
```

Так тесты работают на тех же данных, что и практика в `cypher-shell`, — расхождения между тестом и реальностью исчезают.

## Полный интеграционный тест

Когда нужно проверить сервисный слой и контроллеры целиком.

```java
@SpringBootTest
@Import(Neo4jTestConfig.class)
@AutoConfigureMockMvc
class CatalogIntegrationTest {

    @Autowired MockMvc mockMvc;
    @Autowired Neo4jClient client;

    @Test
    void returnsCatalogPage() throws Exception {
        mockMvc.perform(get("/api/products").param("category", "Кофемолки"))
               .andExpect(status().isOk())
               .andExpect(jsonPath("$.length()").value(3));
    }
}
```

## Миграции в тестах

Если проект использует Neo4j-Migrations из урока 16, тесты должны прогонять их — иначе тестируется схема, которой в продакшне не будет.

```yaml
# src/test/resources/application.yml
org:
  neo4j:
    migrations:
      enabled: true
      transaction-mode: PER_STATEMENT
```

Отдельный тест, проверяющий сами миграции на чистой базе:

```java
@SpringBootTest
@Import(Neo4jTestConfig.class)
class MigrationsTest {

    @Autowired Neo4jClient client;

    @Test
    void allMigrationsApplied() {
        var count = client.query("MATCH (m:__Neo4jMigration) RETURN count(m) AS c")
                          .fetchAs(Long.class)
                          .mappedBy((ts, r) -> r.get("c").asLong())
                          .one().orElseThrow();
        assertThat(count).isGreaterThan(0);
    }

    @Test
    void constraintsExist() {
        var names = client.query("SHOW CONSTRAINTS YIELD name RETURN name")
                          .fetchAs(String.class)
                          .mappedBy((ts, r) -> r.get("name").asString())
                          .all();
        assertThat(names).contains("user_email", "product_sku");
    }
}
```

> **Внимание**: очистка `MATCH (n) DETACH DELETE n` в `@BeforeEach` удалит и узлы `__Neo4jMigration`. При следующем старте контекста миграции применятся заново — на малых данных это незаметно, но на больших миграциях тесты начинают тормозить. Решение — исключить служебную метку из очистки:

```java
client.query("MATCH (n) WHERE NOT n:__Neo4jMigration DETACH DELETE n").run();
```

## Тестирование запросов, а не маппинга

Отдельный класс тестов, который проверяет не Java-код, а Cypher: правильно ли запрос отвечает на бизнес-вопрос.

```java
@Test
void recommendsProductsBoughtBySimilarUsers() {
    // Анна и Иван купили один товар, у Ивана есть ещё один
    client.query("""
                 CREATE (a:User {email:'a@x'}), (i:User {email:'i@x'})
                 CREATE (p1:Product {sku:'P1'}), (p2:Product {sku:'P2'})
                 CREATE (a)-[:PURCHASED]->(p1)
                 CREATE (i)-[:PURCHASED]->(p1)
                 CREATE (i)-[:PURCHASED]->(p2)
                 """).run();

    var recs = repository.recommend("a@x", 10);

    assertThat(recs).extracting(Recommendation::sku).containsExactly("P2");
}
```

Такие тесты — единственный способ поймать регрессию в графовой логике: рекомендация, антифрод или обход прав ломаются молча, без исключений.

## Практика

1. Подключи Testcontainers с BOM и убедись, что без него сборка падает с сообщением без номера версии.
2. Подключи `spring-boot-data-neo4j-test` и проверь, что без него `@DataNeo4jTest` не резолвится.
3. Опиши `Neo4jTestConfig` с `@ServiceConnection` на образе `neo4j:2026.07.1-community` с плагинами.
4. Напиши слайс-тест `@DataNeo4jTest`, проверяющий производный запрос по городу.
5. Убери очистку из `@BeforeEach`, запусти два теста подряд и зафиксируй, что данные первого утекли во второй.
6. Включи `withReuse(true)` и `testcontainers.reuse.enable=true`, сравни время двух прогонов.
7. Вынеси фикстуру в Cypher-файл и загрузи её через `Neo4jClient`.
8. Пробрось в контейнер CSV из `dataset/` и загрузи через `LOAD CSV` в тесте.
9. Включи миграции в тестовом профиле и напиши тест, проверяющий наличие ограничений.
10. Воспроизведи проблему с удалением узлов `__Neo4jMigration` и почини очистку.
11. Напиши тест на бизнес-логику рекомендаций: минимальный граф, ожидаемый список товаров.

## Итоги урока

- Testcontainers предпочтительнее embedded test harness: тот же образ и те же плагины, что в продакшне, вместо ядра в classpath.
- Spring Boot 4.1 не управляет версиями Testcontainers — BOM подключается вручную, иначе сборка падает с сообщением без номера версии.
- В Spring Boot 4 `@DataNeo4jTest` вынесена в модуль `spring-boot-data-neo4j-test` и переехала в пакет `org.springframework.boot.data.neo4j.test.autoconfigure`; примеры под Boot 3 не компилируются.
- `@ServiceConnection` из `spring-boot-testcontainers` сам прописывает URI и учётные данные, заменяя `@DynamicPropertySource`.
- `@DataNeo4jTest` поднимает только слой данных, но не откатывает транзакции после теста — изоляцию обеспечивает явная очистка в `@BeforeEach`.
- Бины главного класса попадают и в слайс: пока они зависят только от репозиториев, тест проходит, но зависимость от сервисного бина роняет контекст — такой runner убирают или закрывают профилем, не забыв активировать его через `@ActiveProfiles`.
- Стратегия по умолчанию — `DETACH DELETE` всего графа перед каждым тестом; при изменении схемы нужно чистить и ограничения.
- `withReuse(true)` вместе с настройкой в `~/.testcontainers.properties` оставляет контейнер между прогонами и экономит десятки секунд.
- Фикстуры удобнее хранить Cypher-файлами, а для полного соответствия практике — пробрасывать в контейнер настоящие CSV датасета.
- Миграции должны прогоняться и в тестах, иначе проверяется схема, которой не будет в продакшне.
- Очистка графа удаляет узлы `__Neo4jMigration` и заставляет миграции применяться заново — служебную метку исключают из удаления.
- Тесты на графовую логику обязательны: рекомендации и антифрод ломаются молча, без исключений.
