# Трек 3. Java и Spring Boot

## Цель

Подключить Neo4j к Java-приложению: от голого драйвера до Spring Data Neo4j с маппингом сущностей, кастомными запросами, транзакциями и тестами на Testcontainers. Довести интеграцию до production-состояния — метрики, таймауты, работа с кластером.

## Что нужно до старта

- Треки 1 и 2 — модель данных, Cypher, индексы и профилирование
- Java 25, Gradle 9.x, Spring Boot 4.1.x
- Опыт работы со Spring Boot и Spring Data

## Уроки

| #  | Тема | Папка | Описание |
|----|------|-------|----------|
| 17 | Neo4j Java Driver 6 | `17_java_driver/` | Driver, Session и Transaction, ExecutableQuery, retry, пул соединений, маппинг результатов, driver BOM |
| 18 | Spring Data Neo4j: старт | `18_spring_data_neo4j_start/` | Стартер и конфигурация подключения, @Node, @Id, @Property, @Relationship, репозитории, derived queries |
| 19 | Маппинг и проекции | `19_mapping_projections/` | DTO- и интерфейсные проекции, records, глубина загрузки и циклы, @RelationshipProperties |
| 20 | Кастомные запросы | `20_custom_queries/` | @Query, Neo4jTemplate, Neo4jClient, Cypher-DSL, построение динамических запросов |
| 21 | Транзакции и реактивный стек | `21_transactions_reactive/` | @Transactional и менеджер транзакций SDN, реактивный SDN, когда он оправдан |
| 22 | Тестирование | `22_testing/` | Testcontainers Neo4j, @DataNeo4jTest, фикстуры графа, изоляция и очистка между тестами |
| 23 | Наблюдаемость | `23_observability/` | Метрики драйвера, Micrometer, query log, health-эндпоинты, трассировка через Observation SPI |
| 24 | Production | `24_production/` | Пулы и таймауты, кластер и routing-драйвер, бэкапы, роли и безопасность, чеклист перед выкаткой |

## Порядок

Урок 17 обязателен даже при работе только через Spring Data — без понимания драйвера непонятно поведение транзакций и retry. Уроки 18-20 идут подряд. Уроки 21-24 можно проходить в произвольном порядке под задачи проекта.
