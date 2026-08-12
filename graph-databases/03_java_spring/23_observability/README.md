# Урок 23. Наблюдаемость

## Что нужно видеть

Три слоя, и каждый отвечает на свой вопрос.

| Слой | Вопрос | Инструмент |
|---|---|---|
| Приложение | Сколько времени заняло обращение к графу | Micrometer, Observation SPI |
| Драйвер | Хватает ли соединений в пуле | Метрики драйвера |
| Сервер | Какой запрос тормозит и почему | `SHOW TRANSACTIONS`, `PROFILE`, query log (Enterprise) |

Разбирать инцидент, имея только один слой, обычно не получается: медленный ответ API может означать и пустой пул соединений, и плохой план запроса.

## Health-эндпоинт

```groovy
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-actuator")
}
```

```yaml
management:
  endpoints:
    web:
      exposure:
        include: health, metrics, prometheus
  endpoint:
    health:
      show-details: always
```

Стартер Neo4j регистрирует индикатор здоровья автоматически:

```json
{
  "status": "UP",
  "components": {
    "neo4j": {
      "status": "UP",
      "details": {
        "server": "2026.07.1@localhost:7687",
        "edition": "community",
        "database": "neo4j"
      }
    }
  }
}
```

Версия ядра приезжает внутри поля `server` вместе с адресом — отдельного ключа `version` в ответе нет.

> **Важно**: индикатор выполняет реальный запрос к базе. На частом опросе из Kubernetes это заметная нагрузка. Для liveness-пробы его лучше исключить, оставив только в readiness — liveness должна отвечать на вопрос «жив ли процесс», а не «доступна ли база».

## Состояние пула соединений

В драйвере 5 у пула был собственный набор метрик: `Config.withDriverMetrics()` и `driver.metrics()`. **В шестой версии их удалили** — вместе с `RxSession` и остальным, перечисленным в уроке 17. Попытка вызвать `withDriverMetrics()` на драйвере 6.1 не компилируется:

```
cannot find symbol: method withDriverMetrics()
```

Вместо них появился Observation SPI — `Config.withObservationProvider(...)`, разбираемый ниже. Он даёт не счётчики пула, а span на каждый запрос, из которых видно время ожидания и время выполнения.

Признаки проблем с пулом теперь ищут по-другому:

| Признак | О чём говорит | Где смотреть |
|---|---|---|
| `ServiceUnavailableException` с текстом про acquisition timeout | Пул исчерпан — прямой признак аварии | Логи приложения |
| Рост времени span'а до начала запроса | Ожидание свободного соединения | Трассировка |
| Разрыв между временем HTTP-запроса и суммой span'ов Neo4j | Потоки стоят в очереди за соединением | Трассировка |
| Долгие транзакции в `SHOW TRANSACTIONS` | Соединения удерживаются дольше, чем нужно | Сервер |

Ненулевые таймауты получения соединения означают одно из двух: либо `maxConnectionPoolSize` из урока 17 меньше реальной конкурентности, либо запросы держат соединение дольше, чем должны.

## Observation SPI

Главное нововведение драйвера 6 для наблюдаемости: точка подключения трассировки на уровне самого драйвера, а не поверх него. Каждый запрос становится span в трассе.

```groovy
dependencies {
    implementation("org.springframework.boot:spring-boot-starter-actuator")
    implementation("io.micrometer:micrometer-tracing-bridge-otel")
    implementation("io.opentelemetry:opentelemetry-exporter-otlp")
}
```

```yaml
management:
  tracing:
    sampling:
      probability: 0.1     # 10% запросов, на проде 100% — дорого
  otlp:
    tracing:
      endpoint: http://localhost:4318/v1/traces
```

Что даёт: в трассе HTTP-запроса видны вложенные span обращений к Neo4j с текстом Cypher и длительностью. Ответ на вопрос «почему этот эндпоинт отвечает 800 мс» становится очевиден — либо три последовательных обращения к графу, либо одно медленное.

## Логирование Cypher

```yaml
logging:
  level:
    org.springframework.data.neo4j.cypher: DEBUG          # сгенерированный Cypher
    org.springframework.data.neo4j.cypher.unwind: DEBUG   # запросы с UNWIND
    org.neo4j.driver: INFO
```

> **Внимание**: `DEBUG` на Cypher — инструмент разработки, а не продакшна. Он логирует каждый запрос вместе с параметрами, а в параметрах лежат персональные данные. В продакшне для этого есть query log на сервере, где логирование управляется политикой базы, а не приложения.

Практическое применение из уроков 18 и 19: включить DEBUG и посмотреть, во что превращается загрузка сущности. Класс с восемью связями порождает восемь `OPTIONAL MATCH` — увидеть это можно только так.

## Query log на сервере

> **Внимание**: query log — возможность Enterprise. В Community настройки `db.logs.query.*` видны в `dbms.listConfig` и выглядят рабочими, но файл `/logs/query.log` остаётся пустым независимо от них. На окружении этой программы посмотреть содержимое лога не получится — раздел нужен, чтобы понимать инструмент, который встретится на production-инстансе Enterprise. В Community его роль частично закрывает DEBUG-логирование Cypher из приложения, разобранное выше.

```cypher
CALL dbms.listConfig() YIELD name, value
WHERE name STARTS WITH 'db.logs.query'
RETURN name, value;
```

| Настройка | Значение по умолчанию | Назначение |
|---|---|---|
| `db.logs.query.enabled` | `VERBOSE` | Уровень логирования, а не булево значение |
| `db.logs.query.threshold` | `0s` | Логировать только запросы дольше порога |
| `db.logs.query.parameter_logging_enabled` | `true` | Логировать параметры |
| `db.logs.query.plan_description_enabled` | `false` | Логировать план |
| `db.logs.query.obfuscate_literals` | `false` | Скрывать литералы в логе |

Порог — ключевая настройка. По умолчанию он равен нулю, то есть логируется **каждый** запрос: на нагруженной системе это заметный объём диска. Осмысленное значение — 500 мс и выше.

> **Внимание**: `db.logs.query.parameter_logging_enabled` включён по умолчанию, а в параметрах лежат почты, идентификаторы и всё остальное, что приложение передаёт в запросы. Если на базу распространяются требования к персональным данным, этот флаг нужно осознанно выключить или включить `obfuscate_literals`.

```bash
docker exec -it neo4j tail -f /logs/query.log
```

В Cypher 25 в query log появилось поле `queryLang`, показывающее версию языка. При миграции с Cypher 5 это единственный способ увидеть, какие запросы ещё идут на старой версии.

## Метаданные транзакций

Приём из урока 17, который окупается именно здесь.

```java
var txConfig = TransactionConfig.builder()
    .withMetadata(Map.of("app", "shop-api", "operation", "recommendations", "userId", email))
    .build();
```

В Spring метаданные проставляются кастомизатором:

```java
@Bean
Neo4jTransactionManager transactionManager(Driver driver, DatabaseSelectionProvider provider) {
    return new Neo4jTransactionManager(driver, provider);
}
```

Метаданные видны в `SHOW TRANSACTIONS` и в query log. Без них зависший запрос в логе сервера — это анонимный Cypher, который нужно вручную сопоставлять с местом в коде.

```cypher
SHOW TRANSACTIONS YIELD transactionId, metaData, elapsedTime, currentQuery
WHERE elapsedTime > duration('PT5S')
RETURN transactionId, metaData, elapsedTime, currentQuery;
```

## Собственные метрики

Micrometer позволяет мерить бизнес-операции, а не только технические.

```java
@Service
public class RecommendationService {

    private final Timer timer;
    private final UserRepository users;

    public RecommendationService(MeterRegistry registry, UserRepository users) {
        this.timer = Timer.builder("shop.recommendations")
                          .description("Время построения рекомендаций")
                          .publishPercentiles(0.5, 0.95, 0.99)
                          .register(registry);
        this.users = users;
    }

    public List<Recommendation> recommend(String email) {
        return timer.record(() -> users.recommend(email, 10));
    }
}
```

Для графовых обходов процентили важнее среднего: время сильно зависит от плотности связей конкретного узла. Средний ответ 20 мс при p99 в 4 секунды означает, что часть пользователей упирается в supernode из урока 11 — и увидеть это можно только по процентилям.

## Notifications

Сервер возвращает предупреждения о потенциально проблемных запросах: отсутствующая метка, неиспользуемый индекс, картезианское произведение.

```java
var result = driver.executableQuery("MATCH (u:Users) RETURN u").execute();
result.summary().notifications().forEach(n ->
    log.warn("Neo4j: {} — {}", n.code(), n.description()));
```

Типичное предупреждение — обращение к несуществующей метке:

```
Neo.ClientNotification.Statement.UnknownLabelWarning
One of the labels in your query is not available in the database,
make sure you didn't misspell it or that the label is available when you run this statement
in your application (the missing label name is: Users)
```

Опечатка в метке не вызывает ошибку — запрос просто вернёт пустой результат. Логирование notifications превращает молчаливый баг в видимое предупреждение, и это одна из самых окупаемых практик при работе с Neo4j.

## Что мониторить в продакшне

| Метрика | Тревожный порог |
|---|---|
| Таймауты получения соединения | Больше нуля |
| p99 времени запроса к графу | Рост в 2 раза от базовой линии |
| Количество `TransientException` | Рост — признак конкуренции за узлы |
| Записи в query log дольше порога | Появление новых шаблонов запросов |
| Page cache hit ratio на сервере | Падение ниже 90% |
| Размер графа: узлы и связи | Резкий рост — признак дублирования при загрузке |

Последняя строка часто выпадает из внимания: неидемпотентная загрузка из урока 6 не вызывает ошибок, она просто удваивает данные, и заметить это можно только по счётчикам.

```cypher
// Счётчики из count store — дёшево, годится для регулярного опроса
MATCH (n) RETURN count(n) AS nodes;
MATCH ()-[r]->() RETURN count(r) AS relationships;
```

## Практика

1. Подключи actuator и проверь `/actuator/health` — найди в деталях версию и редакцию Neo4j.
2. Останови контейнер Neo4j и посмотри, как изменится статус health.
3. Убедись, что `withDriverMetrics()` из драйвера 5 больше не компилируется, и найди в `Config.ConfigBuilder` пришедший ему на смену `withObservationProvider`.
4. Уменьши `maxConnectionPoolSize` до 1, дай нагрузку в несколько потоков и зафиксируй исключение об истечении времени ожидания соединения.
5. Включи DEBUG-логирование Cypher и посмотри запрос, генерируемый загрузкой сущности с несколькими связями.
6. Выведи настройки `db.logs.query.*` через `dbms.listConfig`, затем проверь `/logs/query.log` в контейнере и зафиксируй, что он пуст — это ограничение Community.
7. Добейся того же результата средствами приложения: включи DEBUG-логирование Cypher, выполни медленный запрос и найди его в логах сервиса.
8. Добавь метаданные транзакции и найди свой запрос в `SHOW TRANSACTIONS` во время выполнения.
9. Заведи `Timer` с процентилями на операцию рекомендаций и сравни среднее с p99 на разных пользователях.
10. Выполни запрос с опечаткой в метке, залогируй notifications и найди предупреждение `UnknownLabelWarning`.

## Итоги урока

- Наблюдаемость складывается из трёх слоёв: приложение, драйвер и сервер; по одному слою инцидент обычно не разбирается.
- Health-индикатор Neo4j выполняет реальный запрос, поэтому его исключают из liveness-пробы и оставляют в readiness.
- Собственные метрики пула удалены в драйвере 6 вместе с `withDriverMetrics()`; их роль перешла к Observation SPI, а исчерпание пула видно по исключениям и по времени ожидания в трассировке.
- Observation SPI драйвера 6 даёт span на каждый запрос к базе внутри трассы HTTP-запроса.
- DEBUG-логирование Cypher — инструмент разработки: оно пишет параметры, а в них персональные данные; в продакшне используется query log сервера.
- Query log доступен только в Enterprise: в Community файл остаётся пустым при любых значениях `db.logs.query.*`.
- В Enterprise порог по умолчанию нулевой, то есть пишется каждый запрос; логирование параметров тоже включено по умолчанию и требует внимания к персональным данным.
- Поле `queryLang` в query log показывает версию Cypher — единственный способ увидеть незамигрированные запросы.
- Метаданные транзакции связывают зависший запрос на сервере с местом в коде приложения.
- Для графовых обходов нужны процентили, а не среднее: разброс времени определяется плотностью связей конкретного узла.
- Логирование notifications превращает молчаливые баги вроде опечатки в метке в видимые предупреждения.
- Счётчики узлов и связей стоит мониторить регулярно: неидемпотентная загрузка удваивает данные без единой ошибки.
