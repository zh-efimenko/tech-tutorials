# Урок 8. Интеграция с Spring Boot

## Стек

- Java 25
- Spring Boot 3.x (последняя версия)
- Gradle (Groovy DSL)
- ClickHouse JDBC Driver
- Flyway (миграции)

## Настройка Gradle (build.gradle)

### Версии в gradle.properties

Версии зависимостей выносим в `gradle.properties`, чтобы управлять ими в одном месте:

```properties
clickhouse_jdbc_version=0.9.8
flyway_database_clickhouse_version=10.24.0
```

### Buildscript — classpath для Flyway-плагина

Gradle-плагин Flyway запускается в compile-time, а не в runtime приложения. Ему нужен собственный classpath с ClickHouse-адаптером:

```groovy
buildscript {
    dependencies {
        classpath "org.flywaydb:flyway-database-clickhouse:$flyway_database_clickhouse_version"
    }
}

plugins {
    id 'org.springframework.boot' version '3.x.x'
    id 'org.flywaydb.flyway' version '10.24.0'
}
```

### Dependencies — зависимости приложения

```groovy
dependencies {
    // Spring Boot JDBC (JdbcTemplate, DataSource auto-configuration)
    implementation "org.springframework.boot:spring-boot-starter-jdbc"
    implementation "org.springframework.boot:spring-boot-starter-web"

    // ClickHouse JDBC Driver
    implementation "com.clickhouse:clickhouse-jdbc:$clickhouse_jdbc_version"

    // Flyway Core (миграции при старте приложения)
    implementation "org.flywaydb:flyway-core"
    // ClickHouse-адаптер для Flyway (только runtime — не нужен при компиляции)
    runtimeOnly "org.flywaydb:flyway-database-clickhouse:$flyway_database_clickhouse_version"

    // DevTools — автоматический запуск Docker Compose
    developmentOnly "org.springframework.boot:spring-boot-docker-compose"

    // Testcontainers
    testImplementation "org.testcontainers:clickhouse"
    testImplementation "org.testcontainers:junit-jupiter"
}
```

**Почему два места для `flyway-database-clickhouse`?**

| Место | Зачем |
|-------|-------|
| `buildscript { classpath }` | Для Gradle-плагина `flywayMigrate` (запуск из CLI: `gradle flywayMigrate`) |
| `runtimeOnly` | Для автоматических миграций при старте Spring Boot приложения |

> Если Kafka используется в том же проекте, нужно исключить `lz4-java` из ClickHouse-драйвера — подробнее в уроке 11.

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
```

### Локальный конфиг — application-local.yml

Для разработки с Docker Compose:

```yaml
spring:
  datasource:
    driver-class-name: com.clickhouse.jdbc.ClickHouseDriver
    url: jdbc:clickhouse://localhost:8123/tutorial
    username: default
    password: clickhouse
  docker:
    compose:
      enabled: true
      lifecycle-management: start_only  # запускает, но не останавливает при shutdown
```

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
testImplementation "org.testcontainers:clickhouse"
testImplementation "org.testcontainers:junit-jupiter"
```

```java
@Testcontainers
@SpringBootTest
class PageViewRepositoryTest {

    @Container
    static ClickHouseContainer clickhouse =
            new ClickHouseContainer("clickhouse/clickhouse-server:25.8.8.26");

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.url", clickhouse::getJdbcUrl);
        registry.add("spring.datasource.username", clickhouse::getUsername);
        registry.add("spring.datasource.password", clickhouse::getPassword);
    }

    @Autowired
    PageViewRepository repository;

    @Test
    void shouldCountViews() {
        // given: данные вставлены через Flyway-миграцию

        // when
        long count = repository.countViews(LocalDate.of(2026, 3, 1));

        // then
        assertThat(count).isGreaterThanOrEqualTo(0);
    }
}
```

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
- Flyway-миграции: `V{YYYYMMDD}_{N}__{name}.sql` в `src/main/resources/db/migration/`
- `JdbcTemplate` — основной инструмент для SELECT-запросов
- Вставка только батчами через `PreparedStatement.executeBatch()`
- Буферизация: копим события в памяти, flush каждую секунду или по достижению BATCH_SIZE
- Два DataSource (PostgreSQL + ClickHouse): `@Primary` на PostgreSQL, `@Qualifier` для ClickHouse
- Testcontainers + `@DynamicPropertySource` для интеграционных тестов