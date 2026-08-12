# Урок 33. Анализ зависимостей и data lineage

Предполагается, что пройдены треки 1 и 2. Урок работает на отдельном небольшом графе — модель интернет-магазина для этого класса задач не подходит. Граф создаётся ниже и удаляется в конце.

## Общая форма задачи

Два вопроса, которые задают каждый раз перед изменением:

- **Blast radius**: если сломать вот это, что перестанет работать?
- **Lineage**: откуда взялось вот это число в отчёте?

Первый — обход вверх по зависимостям, второй — вниз по потоку данных. Технически это одна и та же операция: транзитивное замыкание в ориентированном графе.

В реляционной модели такой запрос — рекурсивный CTE неизвестной глубины, и на каждом шаге он повторно читает таблицу. В графе это обход по указателям с явно заданной границей глубины. Разница не в синтаксисе, а в том, что графовый вариант остаётся читаемым, когда типов зависимостей становится пять, а глубина — восемь.

Практическая ценность появляется, когда в графе оказываются **разнородные** сущности: сервисы, датасеты, отчёты, команды. Тогда на один запрос отвечает вопрос «какие отчёты сломаются, если упадёт платёжный сервис» — а он пересекает три разных домена.

## Граф для урока

Одиннадцать сервисов, десять датасетов и связи между ними.

```
(:Service)-[:DEPENDS_ON {kind}]->(:Service)     kind: sync | async | batch | compile
(:Service)-[:PRODUCES]->(:Dataset)
(:Dataset)-[:FEEDS]->(:Dataset)
```

```cypher
UNWIND [
  {name: 'api-gateway',     team: 'platform', tier: 'edge'},
  {name: 'order-service',   team: 'orders',   tier: 'core'},
  {name: 'payment-service', team: 'billing',  tier: 'core'},
  {name: 'catalog-service', team: 'catalog',  tier: 'core'},
  {name: 'user-service',    team: 'platform', tier: 'core'},
  {name: 'search-service',  team: 'catalog',  tier: 'core'},
  {name: 'notify-service',  team: 'platform', tier: 'support'},
  {name: 'analytics-etl',   team: 'data',     tier: 'batch'},
  {name: 'report-api',      team: 'data',     tier: 'edge'},
  {name: 'auth-lib',        team: 'platform', tier: 'library'},
  {name: 'common-model',    team: 'platform', tier: 'library'}
] AS s
CREATE (:Service {name: s.name, team: s.team, tier: s.tier});

UNWIND [
  ['api-gateway','order-service','sync'],     ['api-gateway','catalog-service','sync'],
  ['api-gateway','user-service','sync'],      ['api-gateway','search-service','sync'],
  ['order-service','payment-service','sync'], ['order-service','catalog-service','sync'],
  ['order-service','user-service','sync'],    ['order-service','notify-service','async'],
  ['payment-service','user-service','sync'],  ['payment-service','notify-service','async'],
  ['search-service','catalog-service','sync'],['analytics-etl','order-service','batch'],
  ['analytics-etl','catalog-service','batch'],['report-api','analytics-etl','sync'],
  ['order-service','auth-lib','compile'],     ['payment-service','auth-lib','compile'],
  ['user-service','auth-lib','compile'],      ['catalog-service','common-model','compile'],
  ['order-service','common-model','compile'], ['auth-lib','common-model','compile']
] AS d
MATCH (a:Service {name: d[0]}), (b:Service {name: d[1]})
CREATE (a)-[:DEPENDS_ON {kind: d[2]}]->(b);

UNWIND [
  {name: 'orders_raw',     layer: 'raw',     owner: 'orders'},
  {name: 'payments_raw',   layer: 'raw',     owner: 'billing'},
  {name: 'users_raw',      layer: 'raw',     owner: 'platform'},
  {name: 'orders_clean',   layer: 'staging', owner: 'data'},
  {name: 'payments_clean', layer: 'staging', owner: 'data'},
  {name: 'user_dim',       layer: 'staging', owner: 'data'},
  {name: 'revenue_daily',  layer: 'mart',    owner: 'data'},
  {name: 'cohort_ltv',     layer: 'mart',    owner: 'data'},
  {name: 'exec_dashboard', layer: 'report',  owner: 'bi'},
  {name: 'finance_report', layer: 'report',  owner: 'bi'}
] AS t
CREATE (:Dataset {name: t.name, layer: t.layer, owner: t.owner});

UNWIND [
  ['orders_raw','orders_clean'],     ['payments_raw','payments_clean'],
  ['users_raw','user_dim'],          ['orders_clean','revenue_daily'],
  ['payments_clean','revenue_daily'],['orders_clean','cohort_ltv'],
  ['user_dim','cohort_ltv'],         ['revenue_daily','exec_dashboard'],
  ['revenue_daily','finance_report'],['cohort_ltv','exec_dashboard']
] AS l
MATCH (a:Dataset {name: l[0]}), (b:Dataset {name: l[1]})
CREATE (a)-[:FEEDS]->(b);

UNWIND [
  ['order-service','orders_raw'],     ['payment-service','payments_raw'],
  ['user-service','users_raw'],       ['analytics-etl','orders_clean'],
  ['analytics-etl','payments_clean'], ['analytics-etl','user_dim'],
  ['analytics-etl','revenue_daily'],  ['analytics-etl','cohort_ltv'],
  ['report-api','exec_dashboard'],    ['report-api','finance_report']
] AS p
MATCH (s:Service {name: p[0]}), (d:Dataset {name: p[1]})
CREATE (s)-[:PRODUCES]->(d);
```

Направление связи `DEPENDS_ON` выбрано «от зависящего к зависимости»: `order-service` зависит от `payment-service`, значит стрелка идёт от первого ко второму. Это соглашение важно держать в голове — половина ошибок в таких графах от того, что стрелку читают наоборот.

## Blast radius

Кто пострадает, если сломать `common-model`?

```cypher
MATCH p = SHORTEST 1 (d:Service)-[:DEPENDS_ON]->+(t:Service {name: 'common-model'})
RETURN length(p) AS hops, count(*) AS services, collect(d.name) AS who
ORDER BY hops;
```

```
╒═════════╤═══════════╤═══════════════════════════════════════════════════════════════════════╕
│hops     │services   │who                                                                    │
╞═════════╪═══════════╪═══════════════════════════════════════════════════════════════════════╡
│1        │3          │["order-service","catalog-service","auth-lib"]                         │
│2        │5          │["api-gateway","analytics-etl","search-service","payment-service",     │
│         │           │ "user-service"]                                                       │
│3        │1          │["report-api"]                                                         │
└─────────┴───────────┴───────────────────────────────────────────────────────────────────────┘
```

Девять сервисов из одиннадцати. Разбивка по глубине — это и есть план коммуникации: трое узнают об изменении первыми, пятеро — следующей волной.

`SHORTEST 1` даёт каждому сервису его минимальное расстояние и убирает дубликаты. Без него `order-service` попал бы и в первую строку (прямая зависимость), и во вторую (через `auth-lib`), и итог перестал бы читаться.

Разбивка по командам превращает технический список в список адресатов:

```cypher
MATCH p = SHORTEST 1 (d:Service)-[:DEPENDS_ON]->+(t:Service {name: 'common-model'})
RETURN d.team AS team, count(*) AS services, collect(d.name) AS who
ORDER BY services DESC;
```

```
╒═════════════╤═══════════╤═══════════════════════════════════════════════════╕
│team         │services   │who                                                │
╞═════════════╪═══════════╪═══════════════════════════════════════════════════╡
│"platform"   │3          │["auth-lib","api-gateway","user-service"]          │
│"catalog"    │2          │["catalog-service","search-service"]               │
│"data"       │2          │["analytics-etl","report-api"]                     │
│"orders"     │1          │["order-service"]                                  │
│"billing"    │1          │["payment-service"]                                │
└─────────────┴───────────┴───────────────────────────────────────────────────┘
```

## Тип зависимости решает всё

Все связи выше считались одинаковыми, а они разные. Падение синхронной зависимости роняет вызывающего немедленно; асинхронная деградирует; batch отложит расчёт до утра; compile вообще не имеет отношения к работающей системе.

Фильтр по типу задаётся прямо в шаблоне связи:

```cypher
MATCH p = SHORTEST 1 (d:Service)-[r:DEPENDS_ON WHERE r.kind = 'sync']->+
      (t:Service {name: 'user-service'})
RETURN d.name AS service, length(p) AS hops
ORDER BY hops, service;
```

```
╒═══════════════════╤═════════╕
│service            │hops     │
╞═══════════════════╪═════════╡
│"api-gateway"      │1        │
│"order-service"    │1        │
│"payment-service"  │1        │
└───────────────────┴─────────┘
```

Три сервиса вместо пяти: `analytics-etl` ходит в `user-service` пакетно, а `report-api` — только через него. При падении `user-service` отчёты не сломаются, они просто обновятся позже.

`WHERE` внутри скобок связи — синтаксис Cypher 25, фильтр применяется на каждом шаге обхода, а не после построения пути. Это принципиально для производительности: путь, у которого уже второй шаг не подходит, дальше не разворачивается.

Эквивалентная запись через проверку всего пути читается хуже и работает медленнее:

```cypher
MATCH p = SHORTEST 1 (d:Service)-[r:DEPENDS_ON]->+(t:Service {name: 'user-service'})
WHERE all(x IN relationships(p) WHERE x.kind = 'sync')
RETURN d.name AS service, length(p) AS hops;
```

## Критичность сервисов

Ранжирование по числу зависящих — первый подход к вопросу «что нельзя ронять».

```cypher
MATCH (s:Service)
OPTIONAL MATCH (d:Service)-[:DEPENDS_ON]->+(s)
WITH s, count(DISTINCT d) AS dependents
RETURN s.name AS service, s.tier AS tier, dependents
ORDER BY dependents DESC LIMIT 6;
```

```
╒═══════════════════╤═══════════╤═════════════╕
│service            │tier       │dependents   │
╞═══════════════════╪═══════════╪═════════════╡
│"common-model"     │"library"  │9            │
│"auth-lib"         │"library"  │6            │
│"notify-service"   │"support"  │5            │
│"user-service"     │"core"     │5            │
│"catalog-service"  │"core"     │5            │
│"payment-service"  │"core"     │4            │
└───────────────────┴───────────┴─────────────┘
```

Список правдоподобен и вводит в заблуждение. `notify-service` стоит наравне с `user-service`, хотя все входящие в него зависимости асинхронные — его падение не роняет никого. Учтём тип:

```cypher
MATCH (s:Service)
OPTIONAL MATCH p = (d:Service)-[:DEPENDS_ON]->+(s)
WHERE all(r IN relationships(p) WHERE r.kind = 'sync')
WITH s, count(DISTINCT d) AS syncDependents
RETURN s.name AS service, syncDependents
ORDER BY syncDependents DESC LIMIT 6;
```

```
╒═══════════════════╤═════════════════╕
│service            │syncDependents   │
╞═══════════════════╪═════════════════╡
│"catalog-service"  │3                │
│"user-service"     │3                │
│"payment-service"  │2                │
│"search-service"   │1                │
│"order-service"    │1                │
│"analytics-etl"    │1                │
└───────────────────┴─────────────────┘
```

Картина другая: `common-model` и `auth-lib` исчезли (зависимости compile-time — вопрос релиза, а не аптайма), `notify-service` тоже. Наверху остались настоящие точки отказа рантайма.

Вывод общий: метрика без учёта типа связи в графе зависимостей всегда врёт. То же наблюдение было в уроке 26 про центральности — там разные метрики давали разные топы, здесь то же делает один фильтр.

## Data lineage

Направление обхода тут обратное: не «кто от меня зависит», а «откуда пришли данные».

Вниз по потоку — что затронет изменение в источнике:

```cypher
MATCH p = SHORTEST 1 (src:Dataset {name: 'orders_raw'})-[:FEEDS]->+(d:Dataset)
RETURN length(p) AS hops, d.name AS dataset, d.layer AS layer
ORDER BY hops, dataset;
```

```
╒═════════╤═══════════════════╤═════════════╕
│hops     │dataset            │layer        │
╞═════════╪═══════════════════╪═════════════╡
│1        │"orders_clean"     │"staging"    │
│2        │"cohort_ltv"       │"mart"       │
│2        │"revenue_daily"    │"mart"       │
│3        │"exec_dashboard"   │"report"     │
│3        │"finance_report"   │"report"     │
└─────────┴───────────────────┴─────────────┘
```

Вверх по потоку — откуда взялось число в отчёте:

```cypher
MATCH p = SHORTEST 1 (src:Dataset)-[:FEEDS]->+(d:Dataset {name: 'exec_dashboard'})
RETURN length(p) AS hops, src.name AS source, src.layer AS layer
ORDER BY hops DESC, source;
```

```
╒═════════╤═══════════════════╤═════════════╕
│hops     │source             │layer        │
╞═════════╪═══════════════════╪═════════════╡
│3        │"orders_raw"       │"raw"        │
│3        │"payments_raw"     │"raw"        │
│3        │"users_raw"        │"raw"        │
│2        │"orders_clean"     │"staging"    │
│2        │"payments_clean"   │"staging"    │
│2        │"user_dim"         │"staging"    │
│1        │"cohort_ltv"       │"mart"       │
│1        │"revenue_daily"    │"mart"       │
└─────────┴───────────────────┴─────────────┘
```

Это готовый ответ аудитору: дашборд собран из трёх сырых источников через два слоя. Ровно того же требует GDPR-запрос «где хранятся мои данные» — только вместо датасетов там таблицы и поля.

## Через границу доменов

Самое ценное — запрос, пересекающий сервисы и данные. Инцидент в сервисе, а вопрос про отчёты.

```cypher
MATCH (s:Service {name: 'payment-service'})-[:PRODUCES]->(d:Dataset)
MATCH (d)-[:FEEDS]->*(affected:Dataset)
WHERE affected.layer = 'report'
RETURN DISTINCT affected.name AS report, affected.owner AS owner;
```

```
╒═══════════════════╤═════════╕
│report             │owner    │
╞═══════════════════╪═════════╡
│"exec_dashboard"   │"bi"     │
│"finance_report"   │"bi"     │
└───────────────────┴─────────┘
```

`->*` вместо `->+` включает нулевую длину: сам датасет тоже считается затронутым, если он уже отчёт.

Полная картина последствий одного инцидента:

```cypher
MATCH (s:Service {name: 'payment-service'})
OPTIONAL MATCH (dep:Service)-[:DEPENDS_ON]->+(s)
WITH s, collect(DISTINCT dep.name) AS services
OPTIONAL MATCH (s)-[:PRODUCES]->(ds:Dataset)-[:FEEDS]->*(down:Dataset)
RETURN services, collect(DISTINCT down.name) AS datasets;
```

```
╒═══════════════════════════════════════════════════════════════╤══════════════════════════════════════════════════════════════════════════════════════╕
│services                                                       │datasets                                                                              │
╞═══════════════════════════════════════════════════════════════╪══════════════════════════════════════════════════════════════════════════════════════╡
│["order-service","api-gateway","analytics-etl","report-api"]   │["payments_raw","payments_clean","revenue_daily","finance_report","exec_dashboard"]   │
└───────────────────────────────────────────────────────────────┴──────────────────────────────────────────────────────────────────────────────────────┘
```

Четыре сервиса и пять датасетов от одного узла. Такой запрос вешают на кнопку в дежурной панели — он отвечает на вопрос «кого звать» быстрее, чем это сделает человек по вики.

## Циклы

Циклическая зависимость между сервисами — почти всегда дефект архитектуры. Ищется одним запросом:

```cypher
MATCH p = (s:Service)-[:DEPENDS_ON]->+(s)
RETURN [n IN nodes(p) | n.name] AS cycle
LIMIT 5;
```

На нашем графе результат пуст — он ациклический. Добавь связь `catalog-service → api-gateway`, и цикл появится.

> **Важно**: без режима `TRAIL`, действующего в Cypher 25 по умолчанию, такой запрос на графе с циклом не завершится — обход бесконечно ходил бы по кругу. `TRAIL` запрещает повторное использование связи, поэтому цикл проходится один раз и обход останавливается. На старых версиях Cypher то же самое требовало явного ограничения глубины.

Для поиска всех циклов сразу лучше подходит SCC из урока 27: сильно связная компонента размером больше единицы — это и есть группа сервисов, замкнутых друг на друге.

## Практическая сторона

**Откуда берутся данные.** Граф зависимостей не заполняют вручную. Источники: манифесты сборки (`build.gradle`, `pom.xml`), спецификации API, конфигурация оркестратора ETL, OpenTelemetry-трейсы. Загрузка — периодический импорт, как в уроке 09.

**Историчность.** «Что зависело от этого сервиса три месяца назад» требует версионирования связей: свойства `validFrom` и `validTo` вместо удаления. Приём разбирался в уроке 11.

**Ограничение глубины.** В графе зависимостей крупной компании от любого узла достижимо почти всё. Верхняя граница `{1,4}` в запросе обязательна, иначе ответ «затронуто 4000 сервисов» технически верен и бесполезен.

**Проверка в CI.** Запрос «сколько сервисов зависит от изменяемого» встраивается в пайплайн: пороговое значение блокирует мердж или требует дополнительного ревью.

```java
@Service
public class ImpactAnalysisService {

    private final Neo4jClient client;

    public ImpactAnalysisService(Neo4jClient client) {
        this.client = client;
    }

    public List<String> syncDependents(String service, int maxHops) {
        return client.query("""
                MATCH p = SHORTEST 1 (d:Service)-[r:DEPENDS_ON WHERE r.kind = 'sync']->{1,%d}
                      (t:Service {name: $service})
                RETURN d.name AS name
                ORDER BY length(p), name
                """.formatted(maxHops))
            .bind(service).to("service")
            .fetchAs(String.class)
            .mappedBy((types, record) -> record.get("name").asString())
            .all()
            .stream().toList();
    }
}
```

> **Внимание**: граница глубины подставляется в текст запроса, а не биндится параметром — квантификатор `{1,n}` параметром не задаётся. Значит, `maxHops` обязан быть из контролируемого набора, а не приходить из HTTP-запроса. Иначе это инъекция в Cypher.

## Практика

1. Создай граф сервисов и датасетов.
2. Найди всех, кто зависит от `common-model`, с разбивкой по глубине. Убери `SHORTEST 1` и объясни, что изменилось.
3. Сгруппируй тот же результат по командам.
4. Отфильтруй зависимости от `user-service` только по типу `sync` и объясни, почему `report-api` выпал.
5. Перепиши тот же запрос через `all(... WHERE ...)` по связям пути и сравни планы через `PROFILE`.
6. Посчитай критичность всех сервисов по числу зависящих, затем только по синхронным. Объясни, почему `common-model` пропал из второго списка.
7. Построй downstream-lineage от `orders_raw` и upstream-lineage для `exec_dashboard`.
8. Найди отчёты, затронутые падением `payment-service`, пройдя через `PRODUCES` и `FEEDS`.
9. Замени `->*` на `->+` в этом запросе и объясни разницу.
10. Собери полную картину последствий инцидента в `order-service`: сервисы и датасеты одним запросом.
11. Проверь граф на циклы. Добавь связь `catalog-service → api-gateway` и найди цикл. Затем удали её.
12. Найди все циклы через SCC из урока 27 и сравни с результатом обхода.
13. Ограничь глубину обхода до `{1,2}` и посмотри, как изменился blast radius `common-model`.
14. Удали граф урока: `MATCH (n) WHERE n:Service OR n:Dataset DETACH DELETE n`.

## Итоги урока

- Blast radius и lineage — одна и та же операция транзитивного замыкания, отличающаяся направлением обхода.
- Ценность появляется, когда в графе лежат разнородные сущности: один запрос пересекает сервисы, датасеты и отчёты.
- Направление `DEPENDS_ON` выбирается один раз и держится строго: половина ошибок в таких графах — от чтения стрелки наоборот.
- `SHORTEST 1` даёт каждому узлу минимальное расстояние и убирает дубликаты, без него один сервис попадает в несколько строк.
- Тип зависимости меняет ответ: синхронная роняет немедленно, асинхронная деградирует, batch откладывает, compile-time к аптайму не относится вовсе.
- `WHERE` внутри скобок связи фильтрует на каждом шаге обхода и потому дешевле проверки `all(...)` по готовому пути.
- Критичность сервиса, посчитанная без учёта типа связи, ставит наравне библиотеку времени компиляции и сервис в проде.
- `->*` включает путь нулевой длины, `->+` требует хотя бы одного шага — на границе доменов эта разница меняет ответ.
- Режим `TRAIL` в Cypher 25 делает поиск циклов конечным без явного ограничения глубины; для перечисления всех циклов удобнее SCC.
- Граф зависимостей наполняется импортом из манифестов сборки, спецификаций API и трейсов, а не руками.
- Верхняя граница глубины обязательна: без неё ответ «затронуто всё» верен и бесполезен.
- Квантификатор `{1,n}` не биндится параметром, поэтому подстановка глубины в текст запроса допустима только из контролируемого набора значений.
