# Урок 8. Интеграция с Spring Boot

## Стек

- Java 25
- Spring Boot 3.x (последняя версия)
- Gradle (wrapper)
- ClickHouse JDBC Driver

## Зависимости (build.gradle.kts)

```kotlin
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-jdbc")
    implementation("com.clickhouse:clickhouse-jdbc:0.8.3:all") {
        // "all" classifier включает HTTP-клиент и все зависимости
    }
}
```

`clickhouse-jdbc` — официальный JDBC-драйвер от ClickHouse. Classifier `all` включает HTTP-транспорт (рекомендуется) без дополнительных зависимостей.

## Конфигурация (application.yml)

```yaml
spring:
  datasource:
    clickhouse:
      url: jdbc:ch://localhost:8123/tutorial
      driver-class-name: com.clickhouse.jdbc.ClickHouseDriver
      # ClickHouse по умолчанию не требует пароля в dev
      username: default
      password: clickhouse
```

### DataSource Bean

```java
@Configuration
public class ClickHouseConfig {

    @Bean
    public DataSource clickHouseDataSource(
            @Value("${spring.datasource.clickhouse.url}") String url,
            @Value("${spring.datasource.clickhouse.username}") String username,
            @Value("${spring.datasource.clickhouse.password}") String password) {

        var dataSource = new com.zaxxer.hikari.HikariDataSource();
        dataSource.setJdbcUrl(url);
        dataSource.setUsername(username);  // default
        dataSource.setPassword(password);  // clickhouse
        dataSource.setDriverClassName("com.clickhouse.jdbc.ClickHouseDriver");
        dataSource.setMaximumPoolSize(10);
        // ClickHouse не поддерживает транзакции — отключаем autocommit проверки
        dataSource.setAutoCommit(true);
        return dataSource;
    }

    @Bean
    public JdbcTemplate clickHouseJdbcTemplate(DataSource clickHouseDataSource) {
        return new JdbcTemplate(clickHouseDataSource);
    }
}
```

**Важно**: если в проекте уже есть PostgreSQL DataSource, используй `@Qualifier("clickHouseDataSource")` для различения.

> Логин и пароль для локальной разработки: `default` / `clickhouse` (заданы в `compose.yml`).

## Чтение данных — JdbcTemplate

### Простые запросы

```java
@Repository
public class PageViewRepository {

    private final JdbcTemplate jdbcTemplate;

    public PageViewRepository(@Qualifier("clickHouseJdbcTemplate") JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public long countViews(LocalDate date) {
        return jdbcTemplate.queryForObject(
                "SELECT count() FROM page_views WHERE event_date = ?",
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
                FROM page_views
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

    public PageViewWriter(@Qualifier("clickHouseDataSource") DataSource dataSource) {
        this.dataSource = dataSource;
    }

    public void insertBatch(List<PageViewEvent> events) {
        String sql = """
                INSERT INTO page_views
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

```java
@Configuration
public class DataSourceConfig {

    @Primary
    @Bean
    @ConfigurationProperties("spring.datasource.postgres")
    public DataSource postgresDataSource() {
        return DataSourceBuilder.create().build();
    }

    @Bean
    public DataSource clickHouseDataSource() {
        var ds = new HikariDataSource();
        ds.setJdbcUrl("jdbc:ch://localhost:8123/tutorial");
        ds.setUsername("default");
        ds.setPassword("clickhouse");
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

```yaml
spring:
  datasource:
    postgres:
      url: jdbc:postgresql://localhost:5432/myapp
      username: postgres
      password: secret
```

## Тестирование с Testcontainers

```kotlin
// build.gradle.kts
testImplementation("org.testcontainers:clickhouse:1.20.6")
testImplementation("org.testcontainers:junit-jupiter:1.20.6")
```

```java
@Testcontainers
@SpringBootTest
class PageViewRepositoryTest {

    @Container
    static ClickHouseContainer clickhouse =
            new ClickHouseContainer("clickhouse/clickhouse-server:25.3.2.39");

    @DynamicPropertySource
    static void properties(DynamicPropertyRegistry registry) {
        registry.add("spring.datasource.clickhouse.url", clickhouse::getJdbcUrl);
        registry.add("spring.datasource.clickhouse.username", clickhouse::getUsername);
        registry.add("spring.datasource.clickhouse.password", clickhouse::getPassword);
    }

    @Autowired
    PageViewRepository repository;

    @Test
    void shouldCountViews() {
        // given: данные вставлены

        // when
        long count = repository.countViews(LocalDate.of(2026, 3, 1));

        // then
        assertThat(count).isGreaterThan(0);
    }
}
```

## Практика

1. Добавить `clickhouse-jdbc` в `build.gradle.kts`
2. Создать `ClickHouseConfig` с DataSource
3. Реализовать `PageViewRepository` с методом `getDailyStats`
4. Реализовать `PageViewWriter` с batch INSERT
5. Создать REST endpoint для получения аналитики
6. Написать тест с Testcontainers

## Итоги урока

- `clickhouse-jdbc:all` — официальный JDBC-драйвер, работает через HTTP
- `JdbcTemplate` — основной инструмент для SELECT-запросов
- Вставка только батчами через `PreparedStatement.executeBatch()`
- Буферизация: копим события в памяти, flush каждую секунду или по достижению BATCH_SIZE
- Два DataSource (PostgreSQL + ClickHouse) — типичная архитектура
- Testcontainers для интеграционных тестов
