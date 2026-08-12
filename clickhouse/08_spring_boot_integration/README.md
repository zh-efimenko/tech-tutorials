# Урок 8. Интеграция с Spring Boot

## Стек

- Java 25
- Spring Boot 4.1.0
- Gradle 9.x (Groovy DSL)
- ClickHouse JDBC Driver 0.9.8
- Flyway (миграции)

## Настройка Gradle (build.gradle)

### Версии в gradle.properties

Версии зависимостей выносим в `gradle.properties`, чтобы управлять ими в одном месте:

```properties
clickhouse_jdbc_version=0.9.8
flyway_database_clickhouse_version=10.24.0
```

> **Про версию адаптера.** `flyway-database-clickhouse` — community-модуль, его выпуск остановился на `10.24.0`, хотя сам Flyway уже 13.x. Это не опечатка: модуль работает и с Flyway 12/13 — их плагинный SPI не изменился. Держать адаптер и ядро Flyway в одной версии не нужно и не получится.

### Buildscript — classpath для Flyway-плагина

Gradle-плагин Flyway запускается в compile-time, а не в runtime приложения. Ему нужен собственный classpath с ClickHouse-адаптером:

```groovy
buildscript {
    // Явно, чтобы classpath плагина не зависел от того, какие репозитории
    // подтянет блок plugins {} (он добавляет plugins.gradle.org/m2 сам)
    repositories { mavenCentral() }
    dependencies {
        classpath "org.flywaydb:flyway-database-clickhouse:$flyway_database_clickhouse_version"
    }
}

plugins {
    id 'java'
    id 'org.springframework.boot' version '4.1.0'
    id 'io.spring.dependency-management' version '1.1.7'
    id 'org.flywaydb.flyway' version '13.2.0'
}

// А вот этот блок обязателен: без него ни одна зависимость приложения
// не резолвится — в дереве `gradle dependencies` всё помечено FAILED
repositories { mavenCentral() }

java {
    toolchain { languageVersion = JavaLanguageVersion.of(25) }
}

// Gradle 9 с плагином java по умолчанию ждёт JUnit 4.
// Без этой строки тесты на JUnit 5 просто не находятся:
// "There are test sources present ... but the test task did not discover any tests to execute"
test { useJUnitPlatform() }
```

Рядом с `build.gradle` нужен `settings.gradle` — без него Gradle 9 не считает каталог проектом:

```groovy
rootProject.name = 'clickhouse-analytics'
```

Обёртку (`gradlew`) урок не содержит — сгенерируй её сам, после того как оба файла на месте:

```bash
gradle wrapper --gradle-version 9.5
```

### Dependencies — зависимости приложения

```groovy
dependencies {
    // Spring Boot JDBC (JdbcTemplate, DataSource auto-configuration)
    implementation "org.springframework.boot:spring-boot-starter-jdbc"
    implementation "org.springframework.boot:spring-boot-starter-webmvc"

    // ClickHouse JDBC Driver
    implementation "com.clickhouse:clickhouse-jdbc:$clickhouse_jdbc_version"

    // Flyway: стартер тянет flyway-core + автоконфигурацию
    implementation "org.springframework.boot:spring-boot-starter-flyway"
    // ClickHouse-адаптер для Flyway (только runtime — не нужен при компиляции)
    runtimeOnly "org.flywaydb:flyway-database-clickhouse:$flyway_database_clickhouse_version"

    // Автоматический запуск Docker Compose при старте приложения.
    // Включается самим фактом присутствия в classpath, поэтому в конфиге
    // ниже мы его явно выключаем — почему, разобрано в разделе про application.yml
    developmentOnly "org.springframework.boot:spring-boot-docker-compose"

    // Testcontainers
    testImplementation "org.springframework.boot:spring-boot-starter-test"
    testImplementation "org.testcontainers:testcontainers-clickhouse"
    testImplementation "org.testcontainers:testcontainers-junit-jupiter"
}
```

**Что изменилось в Spring Boot 4:**

| Было (3.x) | Стало (4.1) |
|---|---|
| `spring-boot-starter-web` | `spring-boot-starter-webmvc` (старое имя работает, но deprecated) |
| `org.flywaydb:flyway-core` | `spring-boot-starter-flyway` — автоконфигурация Flyway живёт в отдельном модуле, одного `flyway-core` в classpath уже недостаточно |
| `org.testcontainers:clickhouse` | `org.testcontainers:testcontainers-clickhouse` (Testcontainers 2.x переименовал координаты) |
| `org.testcontainers:junit-jupiter` | `org.testcontainers:testcontainers-junit-jupiter` |

> Если оставить `flyway-core` вместо стартера, приложение стартует **без единой ошибки**, а миграции просто не выполнятся — первое падение будет уже на запросе к несуществующей таблице.

**Почему два места для `flyway-database-clickhouse`?**

| Место | Зачем |
|-------|-------|
| `buildscript { classpath }` | Для Gradle-плагина `flywayMigrate` (запуск из CLI: `gradle flywayMigrate`) |
| `runtimeOnly` | Для автоматических миграций при старте Spring Boot приложения |

> Про `lz4-java`, который тянут и ClickHouse-драйвер, и Kafka: исключать его не нужно — почему, разобрано в уроке 11.

### Точка входа

Без класса с `main` `bootJar`/`bootRun` падает: `Main class name has not been configured and it could not be resolved from classpath`. Все классы ниже кладём в подпакеты этого пакета — иначе component scan их не увидит:

```java
package com.example.analytics;

@SpringBootApplication
@EnableScheduling  // нужен для @Scheduled-флаша буфера, см. ниже
public class AnalyticsApplication {

    public static void main(String[] args) {
        SpringApplication.run(AnalyticsApplication.class, args);
    }
}
```

Дальше в примерах `package` и `import` опущены — подставляй свои.

## Конфигурация (application.yml)

### Основной конфиг — application.yml

Переменные окружения с дефолтами для production:

```yaml
spring:
  datasource:
    driver-class-name: com.clickhouse.jdbc.ClickHouseDriver
    url: jdbc:clickhouse://${CLICKHOUSE_DB_HOST:localhost}:${CLICKHOUSE_DB_PORT:8123}/${CLICKHOUSE_DB_NAME:tutorial}
    username: ${CLICKHOUSE_DB_USER:default}
    password: ${CLICKHOUSE_DB_PASS:clickhouse}
  flyway:
    out-of-order: true
    validate-migration-naming: true
    baseline-on-migrate: true
  docker:
    compose:
      enabled: false   # см. пояснение ниже
```

**Про `spring.docker.compose.enabled: false`.** Модуль `spring-boot-docker-compose` включается сам, как только оказывается в classpath, и ищет `compose.yml` **в рабочем каталоге приложения**. У нас его там нет — compose курса лежит в корне курса, а не в каталоге Gradle-проекта. Без этой строки приложение не стартует вообще:

```
java.lang.IllegalStateException: No Docker Compose file found in directory '<project>/.'
```

Подсунуть ему чужой файл через `spring.docker.compose.file` — не решение, и почему именно, разобрано ниже, в конфиге профиля `local`.

`baseline-on-migrate: true` нужен, потому что база `tutorial` уже не пустая — в ней таблицы из уроков 2–7. Без этой настройки первый же запуск падает:

```
FlywayException: Found non-empty schema(s) "tutorial" but no schema history table.
Use baseline() or set baselineOnMigrate to true to initialize the schema history table.
```

Flyway создаст `flyway_schema_history`, пометит текущее состояние как baseline и применит миграции поверх.

### Локальный конфиг — application-local.yml

Для разработки с Docker Compose:

```yaml
spring:
  datasource:
    driver-class-name: com.clickhouse.jdbc.ClickHouseDriver
    url: jdbc:clickhouse://localhost:8123/tutorial
    username: default
    password: clickhouse
```

Docker Compose-интеграция и здесь остаётся выключённой (`enabled: false` наследуется из `application.yml`) — окружение курса ты поднимаешь сам командой `docker compose up -d`.

**Почему её не включаем.** Модуль `spring-boot-docker-compose` не «дополняет» конфигурацию, а подменяет её: он строит `ConnectionDetails` по найденному в compose контейнеру, и эти значения **перебивают** `spring.datasource.url`. Имя базы он берёт из переменной `CLICKHOUSE_DB` контейнера, а в `compose.yml` курса её нет — получается `default` вместо `tutorial`, и в логе видно чужой URL:

```
Database: jdbc:clickhouse://127.0.0.1:8123/default
```

Дальше падает Flyway — на чистом томе `Code: 81 ... Database tutorial does not exist`, на непустом `Code: 57 ... Table tutorial.page_views already exists` (историю миграций он ведёт уже в `default`). Включать интеграцию имеет смысл, когда compose-файл лежит в корне самого проекта и объявляет `CLICKHOUSE_DB` — как в кластерном compose из урока 11.

### Spring Boot auto-configuration

Spring Boot автоматически создаёт `DataSource` и `JdbcTemplate` из `spring.datasource.*` — дополнительных бинов не нужно:

```java
@Repository
public class PageViewRepository {

    private final JdbcTemplate jdbcTemplate;

    // Spring Boot инжектит auto-configured JdbcTemplate
    public PageViewRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }
}
```

> Логин и пароль для локальной разработки: `default` / `clickhouse` (заданы в `compose.yml`).

### JDBC URL параметры

| Параметр | Описание |
|----------|----------|
| `jdbc:clickhouse://host:port/db` | Стандартный формат подключения |
| `?jdbc_ignore_unsupported_values=true` | Игнорирует неподдерживаемые JDBC-операции (полезно для Flyway) |
| `?socket_timeout=300000` | Таймаут сокета в мс (для долгих запросов) |
| `?compress=true` | Сжатие трафика между клиентом и сервером |

## Flyway-миграции

### Структура файлов

```
src/main/resources/db/migration/
├── V20260401_1__page_views_table.sql
├── V20260401_2__users_table.sql
└── V20260401_3__countries_table.sql
```

Паттерн: `V{YYYYMMDD}_{порядковый_номер}__{описание}.sql`

### Пример миграции

```sql
-- V20260401_1__page_views_table.sql
CREATE TABLE tutorial.page_views
(
    event_date Date,
    event_time DateTime,
    user_id    UInt64,
    page_url   String,
    duration   UInt32,
    country    LowCardinality(String),
    device     LowCardinality(String)
) ENGINE = MergeTree()
      PARTITION BY toYYYYMM(event_date)
      ORDER BY (user_id, event_time);
```

### Запуск миграций из Gradle CLI

Для этого нужны параметры подключения в `gradle.properties`:

```properties
flyway.url=jdbc:clickhouse://localhost:8123/tutorial?jdbc_ignore_unsupported_values=true
flyway.user=default
flyway.password=clickhouse
flyway.outOfOrder=true
flyway.validateOnMigrate=false
flyway.baselineOnMigrate=true
```

```bash
# Запуск миграций вручную
./gradlew flywayMigrate

# Проверка статуса
./gradlew flywayInfo
```

При старте Spring Boot приложения миграции выполняются автоматически — ручной запуск нужен только для разработки.

## Чтение данных — JdbcTemplate

### Простые запросы

```java
@Repository
public class PageViewRepository {

    private final JdbcTemplate jdbcTemplate;

    public PageViewRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public long countViews(LocalDate date) {
        return jdbcTemplate.queryForObject(
                "SELECT count() FROM tutorial.page_views WHERE event_date = ?",
                Long.class,
                date
        );
    }

    public List<PageViewStats> getDailyStats(LocalDate from, LocalDate to) {
        return jdbcTemplate.query(
                """
                SELECT
                    event_date,
                    count()        AS views,
                    uniq(user_id)  AS unique_users,
                    avg(duration)  AS avg_duration
                FROM tutorial.page_views
                WHERE event_date BETWEEN ? AND ?
                GROUP BY event_date
                ORDER BY event_date
                """,
                (rs, rowNum) -> new PageViewStats(
                        rs.getDate("event_date").toLocalDate(),
                        rs.getLong("views"),
                        rs.getLong("unique_users"),
                        rs.getDouble("avg_duration")
                ),
                from, to
        );
    }
}
```

### DTO

```java
public record PageViewStats(
        LocalDate date,
        long views,
        long uniqueUsers,
        double avgDuration
) {}
```

## Вставка данных — батчи

### Batch INSERT через PreparedStatement

```java
@Repository
public class PageViewWriter {

    private final DataSource dataSource;

    public PageViewWriter(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    public void insertBatch(List<PageViewEvent> events) {
        String sql = """
                INSERT INTO tutorial.page_views
                (event_date, event_time, user_id, page_url, duration, country, device)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """;

        try (var conn = dataSource.getConnection();
             var ps = conn.prepareStatement(sql)) {

            for (var event : events) {
                ps.setDate(1, Date.valueOf(event.date()));
                ps.setTimestamp(2, Timestamp.valueOf(event.time()));
                ps.setLong(3, event.userId());
                ps.setString(4, event.pageUrl());
                ps.setInt(5, event.duration());
                ps.setString(6, event.country());
                ps.setString(7, event.device());
                ps.addBatch();
            }

            ps.executeBatch();
        } catch (SQLException e) {
            throw new RuntimeException("Failed to insert page views batch", e);
        }
    }
}
```

### DTO для вставки

```java
public record PageViewEvent(
        LocalDate date,
        LocalDateTime time,
        long userId,
        String pageUrl,
        int duration,
        String country,
        String device
) {}
```

## Буферизация вставок

В production нельзя вставлять по одному событию. Нужен буфер:

> **Внимание.** `@Scheduled` работает только при `@EnableScheduling` на конфигурации (см. точку входа выше). Без него отказ тихий: `POST /api/analytics/events` отвечает 200, буфер копится в памяти и не флашится никогда, а в ClickHouse пусто.

```java
@Service
public class PageViewBuffer {

    private final PageViewWriter writer;
    private final List<PageViewEvent> buffer = new ArrayList<>();
    private static final int BATCH_SIZE = 10_000;

    public PageViewBuffer(PageViewWriter writer) {
        this.writer = writer;
    }

    public synchronized void add(PageViewEvent event) {
        buffer.add(event);
        if (buffer.size() >= BATCH_SIZE) {
            flush();
        }
    }

    @Scheduled(fixedRate = 1000)  // каждую секунду
    public synchronized void flush() {
        if (buffer.isEmpty()) return;

        var batch = new ArrayList<>(buffer);
        buffer.clear();
        writer.insertBatch(batch);
    }
}
```

## REST Controller

```java
@RestController
@RequestMapping("/api/analytics")
public class AnalyticsController {

    private final PageViewRepository repository;
    private final PageViewBuffer buffer;

    public AnalyticsController(PageViewRepository repository, PageViewBuffer buffer) {
        this.repository = repository;
        this.buffer = buffer;
    }

    @GetMapping("/daily")
    public List<PageViewStats> getDailyStats(
            @RequestParam LocalDate from,
            @RequestParam LocalDate to) {
        return repository.getDailyStats(from, to);
    }

    @PostMapping("/events")
    public void trackEvent(@RequestBody PageViewEvent event) {
        buffer.add(event);
    }
}
```

## Работа с двумя DataSource (PostgreSQL + ClickHouse)

Типичная архитектура: PostgreSQL для OLTP, ClickHouse для аналитики.

### application.yml

```yaml
spring:
  datasource:
    # Основной DataSource — PostgreSQL (авто-конфигурация Spring Boot)
    url: jdbc:postgresql://localhost:5432/myapp
    username: postgres
    password: secret

  # ClickHouse — кастомный DataSource
  clickhouse:
    url: jdbc:clickhouse://localhost:8123/tutorial
    username: default
    password: clickhouse
```

### Конфигурация двух DataSource

```java
@Configuration
public class DataSourceConfig {

    @Primary
    @Bean
    @ConfigurationProperties("spring.datasource")
    public DataSource postgresDataSource() {
        return DataSourceBuilder.create().build();
    }

    @Bean
    public DataSource clickHouseDataSource(
            @Value("${spring.clickhouse.url}") String url,
            @Value("${spring.clickhouse.username}") String username,
            @Value("${spring.clickhouse.password}") String password) {
        var ds = new HikariDataSource();
        ds.setJdbcUrl(url);
        ds.setUsername(username);
        ds.setPassword(password);
        ds.setDriverClassName("com.clickhouse.jdbc.ClickHouseDriver");
        ds.setMaximumPoolSize(10);
        ds.setAutoCommit(true);
        return ds;
    }

    @Bean
    public JdbcTemplate clickHouseJdbcTemplate(
            @Qualifier("clickHouseDataSource") DataSource ds) {
        return new JdbcTemplate(ds);
    }
}
```

При двух DataSource репозитории используют `@Qualifier` для выбора нужного:

```java
@Repository
public class PageViewRepository {

    private final JdbcTemplate jdbcTemplate;

    public PageViewRepository(@Qualifier("clickHouseJdbcTemplate") JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }
}
```

> Если ClickHouse — единственная база, `@Qualifier` не нужен — Spring Boot создаст `JdbcTemplate` автоматически.

## Тестирование с Testcontainers

```groovy
// build.gradle
testImplementation "org.testcontainers:testcontainers-clickhouse"
testImplementation "org.testcontainers:testcontainers-junit-jupiter"
```

Версиями Testcontainers управляет BOM Spring Boot — для 4.1.0 это 2.0.5. Класс контейнера лежит в пакете `org.testcontainers.clickhouse`:

```java
import org.testcontainers.clickhouse.ClickHouseContainer;
```

```java
@Testcontainers
@SpringBootTest
class PageViewRepositoryTest {

    @Container
    static ClickHouseContainer clickhouse =
            new ClickHouseContainer("clickhouse/clickhouse-server:26.3.17.110")
                    .withDatabaseName("tutorial")   // иначе БД будет default
                    .withUsername("default")
                    .withPassword("clickhouse");

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", clickhouse::getJdbcUrl);
        registry.add("spring.datasource.username", clickhouse::getUsername);
        registry.add("spring.datasource.password", clickhouse::getPassword);
    }

    @Autowired
    PageViewRepository repository;

    @Autowired
    PageViewWriter writer;

    @Test
    void shouldCountViews() {
        // given: Flyway создал пустую таблицу — данные вставляем сами
        var date = LocalDate.of(2026, 3, 1);
        writer.insertBatch(List.of(
                new PageViewEvent(date, date.atTime(10, 0), 1L, "/home", 42, "RU", "desktop"),
                new PageViewEvent(date, date.atTime(10, 5), 2L, "/pricing", 17, "DE", "mobile")
        ));

        // when
        long count = repository.countViews(date);

        // then
        assertThat(count).isEqualTo(2);
    }
}
```

> Миграция `V20260401_1` только создаёт таблицу и не вставляет ни строки. Ассерт вида `isGreaterThanOrEqualTo(0)` в таком тесте зелёный всегда — он не проверяет ничего.

> **Почему `withDatabaseName`.** По умолчанию контейнер поднимается с БД `default` и учёткой `test`/`test`, а `getJdbcUrl()` возвращает `jdbc:clickhouse://localhost:<port>/default`. Миграция при этом создаёт `tutorial.page_views` — и тест падает с `Code: 81. DB::Exception: Database tutorial does not exist. (UNKNOWN_DATABASE)`. Имя БД в контейнере и префикс в миграциях должны совпадать.

## Практика

1. Создать `gradle.properties` с версиями `clickhouse_jdbc_version` и `flyway_database_clickhouse_version`
2. Настроить `build.gradle` с `buildscript`, Flyway-плагином и зависимостями
3. Написать `application.yml` и `application-local.yml` с конфигурацией DataSource
4. Создать Flyway-миграцию `V20260401_1__page_views_table.sql`
5. Реализовать `PageViewRepository` с методом `getDailyStats`
6. Реализовать `PageViewWriter` с batch INSERT
7. Создать REST endpoint для получения аналитики
8. Написать тест с Testcontainers

## Итоги урока

- `com.clickhouse:clickhouse-jdbc` — официальный JDBC-драйвер, подключается через `jdbc:clickhouse://host:port/db`
- Spring Boot auto-configuration создаёт `DataSource` и `JdbcTemplate` из `spring.datasource.*` — ручной бин не нужен
- `application.yml` — env-переменные для production, `application-local.yml` — фиксированные значения для dev
- Gradle: версии в `gradle.properties`, Flyway-адаптер и в `buildscript` (для CLI), и в `runtimeOnly` (для приложения)
- В Spring Boot 4 автоконфигурация Flyway приходит только со стартером `spring-boot-starter-flyway`, а `flyway-database-clickhouse` остаётся на `10.24.0` и работает с любым Flyway 12/13
- Flyway-миграции: `V{YYYYMMDD}_{N}__{name}.sql` в `src/main/resources/db/migration/`
- `JdbcTemplate` — основной инструмент для SELECT-запросов
- Вставка только батчами через `PreparedStatement.executeBatch()`
- Буферизация: копим события в памяти, flush каждую секунду или по достижению BATCH_SIZE
- Два DataSource (PostgreSQL + ClickHouse): `@Primary` на PostgreSQL, `@Qualifier` для ClickHouse
- Testcontainers + `@DynamicPropertySource` для интеграционных тестов