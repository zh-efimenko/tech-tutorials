# Урок 9. Загрузка данных

## Что загружаем

Датасет программы лежит в `graph-databases/dataset/` и смонтирован в контейнер как `/import`. Девять файлов, около 560 строк — модель интернет-магазина с социальным слоем. Датасет намеренно небольшой: его можно целиком просмотреть глазами и сверить с результатом запроса. Объём наращивается в конце урока генератором.

| Файл | Строк | Что описывает |
|---|---|---|
| `categories.csv` | 14 | Иерархия категорий |
| `products.csv` | 24 | Товары с брендом и категорией |
| `users.csv` | 30 | Пользователи, статус и кто кого пригласил |
| `orders.csv` | 72 | Заказы |
| `order_items.csv` | 127 | Позиции заказов |
| `reviews.csv` | 35 | Отзывы |
| `views.csv` | 148 | Просмотры товаров |
| `follows.csv` | 77 | Подписки между пользователями |
| `sessions.csv` | 35 | Входы: устройство, карта, адрес доставки |

Целевая схема после загрузки:

```
 (:Brand)◀── MADE_BY ──(:Product)── IN_CATEGORY ──▶(:Category)──SUBCATEGORY_OF──▶(:Category)
                            ▲   ▲
                    CONTAINS│   │ABOUT
                            │   │
   (:User)──PLACED──▶(:Order)   (:Review)◀──WROTE──(:User)
      │  │  │
      │  │  └── VIEWED ──▶(:Product)
      │  └───── FOLLOWS ──▶(:User)
      └──────── REFERRED ─▶(:User)

   (:User)── LOGGED_IN_FROM ──▶(:Device)
   (:User)── PAID_WITH ───────▶(:PaymentMethod)
   (:User)── SHIPPED_TO ──────▶(:Address)
```

## Подготовка базы

Уроки 4-8 оставили в графе экспериментальные данные: узлы без бизнес-ключей, намеренные дубликаты из практики урока 6, заказы со свойством `id` вместо `orderId`. Они помешают дальше — дубликат по `sku` не даст создать ограничение уникальности, а счётчики после загрузки не сойдутся с таблицей выше.

```cypher
// Учебные данные предыдущих уроков больше не нужны
MATCH (n) DETACH DELETE n;
```

> **Важно**: бизнес-ключ заказа меняется. В уроке 4 заказы создавались вручную со свойством `id`, датасет и все последующие треки используют `orderId`. Дальше в программе заказ ищется только по `orderId`.

## Ограничения создаются до загрузки

Первое, что делается перед любой загрузкой — ограничения уникальности на бизнес-ключи. Причины две:

1. `MERGE` без индекса на свойство сканирует все узлы метки. На каждой строке. Загрузка 127 позиций заказа превратится в 127 полных сканирований.
2. Ограничение уникальности заставляет `MERGE` брать блокировку по ключу, иначе параллельные загрузки создают дубликаты.

```cypher
CREATE CONSTRAINT user_email        IF NOT EXISTS FOR (u:User)          REQUIRE u.email       IS UNIQUE;
CREATE CONSTRAINT product_sku       IF NOT EXISTS FOR (p:Product)       REQUIRE p.sku         IS UNIQUE;
CREATE CONSTRAINT category_id       IF NOT EXISTS FOR (c:Category)      REQUIRE c.categoryId  IS UNIQUE;
CREATE CONSTRAINT brand_name        IF NOT EXISTS FOR (b:Brand)         REQUIRE b.name        IS UNIQUE;
CREATE CONSTRAINT order_id          IF NOT EXISTS FOR (o:Order)         REQUIRE o.orderId     IS UNIQUE;
CREATE CONSTRAINT review_id         IF NOT EXISTS FOR (r:Review)        REQUIRE r.reviewId    IS UNIQUE;
CREATE CONSTRAINT device_id         IF NOT EXISTS FOR (d:Device)        REQUIRE d.deviceId    IS UNIQUE;
CREATE CONSTRAINT card_id           IF NOT EXISTS FOR (c:PaymentMethod) REQUIRE c.cardId      IS UNIQUE;
CREATE CONSTRAINT address_id        IF NOT EXISTS FOR (a:Address)       REQUIRE a.addressId   IS UNIQUE;

SHOW CONSTRAINTS;
```

> **Внимание**: при выполнении файла со скриптом `cypher-shell` останавливается на первой же ошибке и **молча не выполняет остальные команды**. Если одно ограничение не создалось из-за дубликатов в данных, остальные восемь тоже не появятся. Поэтому `SHOW CONSTRAINTS` в конце — не формальность: там должно быть ровно девять строк.

Ограничение уникальности автоматически создаёт индекс — отдельно его заводить не нужно. Подробно про типы индексов — урок 12.

## LOAD CSV

Встроенный механизм чтения CSV. Файл берётся из каталога `import` сервера, поэтому в запросе путь пишется как `file:///имя.csv`.

### Порядок загрузки

Загружать нужно в порядке зависимостей: сначала узлы, потом связи между ними. Иначе `MERGE` связи создаст пустые узлы-заглушки.

**1. Категории и иерархия.** Двумя проходами: сначала все узлы, потом связи между ними — иначе родитель может ещё не существовать.

```cypher
LOAD CSV WITH HEADERS FROM 'file:///categories.csv' AS row
MERGE (c:Category {categoryId: row.categoryId})
SET c.name = row.name;

LOAD CSV WITH HEADERS FROM 'file:///categories.csv' AS row
WITH row WHERE row.parentId IS NOT NULL AND row.parentId <> ''
MATCH (parent:Category {categoryId: row.parentId})
MATCH (c:Category      {categoryId: row.categoryId})
MERGE (c)-[:SUBCATEGORY_OF]->(parent);
```

> **Важно**: пустая ячейка в CSV читается как `null`. Проверить это можно прямо:
>
> ```cypher
> LOAD CSV WITH HEADERS FROM 'file:///categories.csv' AS row
> WITH row WHERE row.categoryId = 'c-root-kitchen'
> RETURN row.parentId IS NULL AS isNull, row.parentId = '' AS isEmptyStr;
> ```
>
> Вернётся `TRUE, null`: значение действительно `null`, а сравнение с пустой строкой само даёт `null` и в `WHERE` работает как «не прошло». Поэтому в фильтре достаточно `IS NOT NULL`, а `<> ''` — избыточная страховка, которая ничего не ломает.
>
> Знать это нужно вот почему: `null` в ключе `MERGE` — не мусорный узел, а ошибка выполнения `22N31: 'MERGE' cannot be used with a graph element property value that is null`. Загрузка упадёт на первой же строке с пустой ячейкой, если фильтр забыт.

> **Внимание**: с CSV, приходящими извне, всё равно проверяй оба варианта. Экспорт из Excel или выгрузка из чужой системы легко даёт ячейку с пробелом или кавычками вместо пустоты — тогда значение будет непустой строкой и фильтр `IS NOT NULL` его пропустит.

**2. Товары, бренды, привязка к категориям.**

```cypher
LOAD CSV WITH HEADERS FROM 'file:///products.csv' AS row
MERGE (p:Product {sku: row.sku})
SET p.title = row.title,
    p.price = toFloat(row.price)          // всё из CSV приходит строкой
MERGE (b:Brand {name: row.brand})
MERGE (p)-[:MADE_BY]->(b)
WITH p, row
MATCH (c:Category {categoryId: row.categoryId})
MERGE (p)-[:IN_CATEGORY]->(c);
```

> **Внимание**: `LOAD CSV` всегда отдаёт строки. Без `toInteger`, `toFloat` или `date` числа и даты попадут в граф текстом, и это ломает запросы **тихо**: сравнение строки с числом в Cypher даёт не ошибку, а `null`, поэтому `WHERE p.price > 3000` вернёт ноль строк вместо ожидаемых товаров. Если же сравнивать со строкой (`p.price > '3000'`), сравнение станет лексикографическим и выдаст бессмыслицу. Приведение типов — обязательный шаг, а не опция.

**3. Пользователи и реферальные связи.**

```cypher
LOAD CSV WITH HEADERS FROM 'file:///users.csv' AS row
MERGE (u:User {email: row.email})
SET u.name         = row.name,
    u.city         = row.city,
    u.status       = row.status,
    u.registeredAt = date(row.registeredAt);

LOAD CSV WITH HEADERS FROM 'file:///users.csv' AS row
WITH row WHERE row.referredBy IS NOT NULL AND row.referredBy <> ''
MATCH (invited:User {email: row.email})
MATCH (inviter:User {email: row.referredBy})
MERGE (inviter)-[:REFERRED]->(invited);
```

**4. Заказы и позиции.**

```cypher
LOAD CSV WITH HEADERS FROM 'file:///orders.csv' AS row
MATCH (u:User {email: row.email})
MERGE (o:Order {orderId: toInteger(row.orderId)})
SET o.total     = toFloat(row.total),
    o.status    = row.status,
    o.createdAt = date(row.createdAt)
MERGE (u)-[r:PLACED]->(o)
SET r.channel = row.channel, r.createdAt = date(row.createdAt);

LOAD CSV WITH HEADERS FROM 'file:///order_items.csv' AS row
MATCH (o:Order   {orderId: toInteger(row.orderId)})
MATCH (p:Product {sku: row.sku})
MERGE (o)-[c:CONTAINS]->(p)
SET c.qty = toInteger(row.qty), c.priceAtPurchase = toFloat(row.priceAtPurchase);
```

**5. Отзывы, просмотры, подписки.**

```cypher
LOAD CSV WITH HEADERS FROM 'file:///reviews.csv' AS row
MATCH (u:User    {email: row.email})
MATCH (p:Product {sku: row.sku})
MERGE (rev:Review {reviewId: row.reviewId})
SET rev.rating = toInteger(row.rating), rev.createdAt = date(row.createdAt)
MERGE (u)-[:WROTE]->(rev)
MERGE (rev)-[:ABOUT]->(p);

LOAD CSV WITH HEADERS FROM 'file:///views.csv' AS row
MATCH (u:User    {email: row.email})
MATCH (p:Product {sku: row.sku})
MERGE (u)-[v:VIEWED]->(p)
SET v.views = toInteger(row.views);

LOAD CSV WITH HEADERS FROM 'file:///follows.csv' AS row
MATCH (a:User {email: row.fromEmail})
MATCH (b:User {email: row.toEmail})
MERGE (a)-[:FOLLOWS]->(b);
```

**6. Сессии: устройства, карты, адреса.** Здесь узлы намеренно общие для нескольких пользователей — на этом строится антифрод в уроке 31.

```cypher
LOAD CSV WITH HEADERS FROM 'file:///sessions.csv' AS row
MATCH (u:User {email: row.email})
MERGE (d:Device        {deviceId: row.deviceId})
MERGE (c:PaymentMethod {cardId: row.cardId})
MERGE (a:Address       {addressId: row.addressId})
MERGE (u)-[l:LOGGED_IN_FROM]->(d)
  SET l.loggedInAt = date(row.loggedInAt)
MERGE (u)-[:PAID_WITH]->(c)
MERGE (u)-[:SHIPPED_TO]->(a);
```

## Проверка загрузки

```cypher
// Счётчики по меткам
MATCH (n) RETURN labels(n) AS label, count(*) AS cnt ORDER BY cnt DESC;

// Счётчики по типам связей
MATCH ()-[r]->() RETURN type(r) AS relType, count(*) AS cnt ORDER BY cnt DESC;

// Узлы без единой связи — почти всегда признак ошибки загрузки
MATCH (n) WHERE NOT (n)--() RETURN labels(n) AS label, count(*) AS orphans;

// Свойства узлов, оставшиеся строками там, где ожидались числа
CALL db.schema.nodeTypeProperties()
YIELD nodeLabels, propertyName, propertyTypes
WHERE propertyName IN ['price', 'total', 'rating']
RETURN nodeLabels, propertyName, propertyTypes;

// То же для свойств связей: qty и priceAtPurchase живут на CONTAINS,
// в nodeTypeProperties их не будет вообще
CALL db.schema.relTypeProperties()
YIELD relType, propertyName, propertyTypes
WHERE propertyName IN ['qty', 'priceAtPurchase']
RETURN relType, propertyName, propertyTypes;
```

Финальная проверка — осмысленный запрос через весь граф:

```cypher
MATCH (u:User)-[:PLACED]->(o:Order)-[:CONTAINS]->(p:Product)-[:IN_CATEGORY]->(c:Category)
RETURN c.name AS category, count(DISTINCT o) AS orders, round(sum(o.total)) AS revenue
ORDER BY revenue DESC LIMIT 5;
```

## Батчевая загрузка больших файлов

Один `LOAD CSV` — одна транзакция. На файле в миллион строк она не поместится в heap. Решение — разбить на батчи через `CALL {} IN TRANSACTIONS`.

```cypher
LOAD CSV WITH HEADERS FROM 'file:///order_items.csv' AS row
CALL (row) {
  MATCH (o:Order   {orderId: toInteger(row.orderId)})
  MATCH (p:Product {sku: row.sku})
  MERGE (o)-[c:CONTAINS]->(p)
  SET c.qty = toInteger(row.qty)
} IN TRANSACTIONS OF 10000 ROWS;
```

| Размер файла | Подход |
|---|---|
| До ~100 тысяч строк | Обычный `LOAD CSV` |
| От ~100 тысяч до десятков миллионов | `LOAD CSV` + `CALL {} IN TRANSACTIONS` |
| Первичная загрузка сотен миллионов | `neo4j-admin database import` |

> **Внимание**: у `CALL {} IN TRANSACTIONS` нет общей транзакции. Сбой на середине оставит часть данных загруженной — откатится только текущий батч. Поэтому загрузка обязана быть идемпотентной: только `MERGE`, никаких `CREATE`, и повторный запуск должен доводить дело до конца.

Управление поведением при ошибке:

```cypher
LOAD CSV WITH HEADERS FROM 'file:///order_items.csv' AS row
CALL (row) {
  MATCH (o:Order {orderId: toInteger(row.orderId)})
  MATCH (p:Product {sku: row.sku})
  MERGE (o)-[:CONTAINS]->(p)
} IN TRANSACTIONS OF 10000 ROWS
  ON ERROR CONTINUE            // альтернативы: ON ERROR FAIL (по умолчанию), ON ERROR BREAK
  REPORT STATUS AS status
// count(*) считает строки исходного CSV, а не батчи: REPORT STATUS отдаёт
// по строке на каждую входную запись, повторяя в ней статус её батча
RETURN status.errorMessage, count(*) AS rows;
```

## neo4j-admin import

Для первичной загрузки очень больших объёмов есть отдельный инструмент, который пишет файлы хранилища напрямую, минуя транзакционный слой. Быстрее `LOAD CSV` на порядки.

```bash
docker exec -it neo4j neo4j-admin database import full \
  --nodes=User=/import/users_header.csv,/import/users.csv \
  --nodes=Product=/import/products_header.csv,/import/products.csv \
  --relationships=PLACED=/import/placed_header.csv,/import/placed.csv \
  --overwrite-destination \
  neo4j
```

Цена скорости:

- База должна быть **остановлена**, а целевая база — пустой. Это инструмент первичной загрузки, а не догрузки.
- Свой формат заголовков с типами: `email:ID(User)`, `name:string`, `:START_ID(User)`, `:END_ID(Order)`, `:TYPE`.
- Никаких `MERGE` и дедупликации — данные должны быть чистыми заранее.

Для датасета этой программы он избыточен, но знать о нём нужно: когда потребуется залить в граф 500 миллионов связей, `LOAD CSV` будет работать сутки, а `neo4j-admin import` — минуты.

## Загрузка через APOC

APOC читает то, что `LOAD CSV` не умеет: JSON, XML, данные по HTTP, другую СУБД по JDBC.

```cypher
// JSON из файла или по URL.
// Файла products.json в датасете курса нет — пример показывает форму вызова.
// Чтобы выполнить его, сначала положи любой JSON-массив в dataset/
CALL apoc.load.json('file:///products.json') YIELD value
MERGE (p:Product {sku: value.sku})
SET p.title = value.title, p.price = toFloat(value.price);

// Батчинг средствами APOC: первый запрос порождает строки, второй выполняется пачками
CALL apoc.periodic.iterate(
  "LOAD CSV WITH HEADERS FROM 'file:///order_items.csv' AS row RETURN row",
  "MATCH (o:Order {orderId: toInteger(row.orderId)})
   MATCH (p:Product {sku: row.sku})
   MERGE (o)-[c:CONTAINS]->(p) SET c.qty = toInteger(row.qty)",
  {batchSize: 10000, parallel: false}
);
```

`apoc.periodic.iterate` появился раньше, чем `CALL {} IN TRANSACTIONS`, и до сих пор встречается в чужих скриптах. Для нового кода предпочтителен встроенный синтаксис: он часть языка, лучше оптимизируется планировщиком и не требует плагина.

> **Внимание**: `parallel: true` в `apoc.periodic.iterate` выглядит соблазнительно, но при записи в пересекающиеся узлы даёт взаимные блокировки. Включать его можно, только если батчи гарантированно не трогают одни и те же узлы.

## Увеличение объёма графа

Загруженного датасета достаточно для изучения Cypher, но мало для урока 13 про профилирование и для графовых алгоритмов трека 4: на таком графе любой запрос выполняется мгновенно и разница между планами не видна.

Скрипт генерирует синтетических пользователей, заказы и связи, доводя граф до сотен тысяч связей. Запускать после основной загрузки.

```cypher
// 20 000 синтетических пользователей
UNWIND range(1, 20000) AS i
CALL (i) {
  MERGE (u:User:Synthetic {email: 'synth' + i + '@shop.io'})
  SET u.name         = 'Synthetic ' + i,
      u.city         = ['Минск','Гомель','Брест','Витебск','Гродно','Могилёв'][i % 6],
      u.registeredAt = date('2025-01-01') + duration({days: i % 500})
} IN TRANSACTIONS OF 5000 ROWS;

// По 1-6 заказов на пользователя со случайными товарами.
// Номер заказа собирается из номера пользователя — своего целочисленного
// идентификатора у узла в Cypher 25 нет, а elementId для арифметики не годится
MATCH (u:User:Synthetic)
CALL (u) {
  WITH u, toInteger(replace(replace(u.email, 'synth', ''), '@shop.io', '')) AS idx
  UNWIND range(1, toInteger(rand() * 6) + 1) AS n
  MERGE (o:Order:Synthetic {orderId: 100000 + idx * 10 + n})
  SET o.total     = round(rand() * 20000),
      o.status    = ['delivered','delivered','shipped','cancelled'][toInteger(rand() * 4)],
      o.createdAt = date('2026-01-01') + duration({days: toInteger(rand() * 90)})
  MERGE (u)-[:PLACED]->(o)
  // Вложенный CALL нужен, чтобы LIMIT 3 применялся к каждому заказу,
  // а не к общему результату по пользователю
  CALL (o) {
    MATCH (p:Product)
    WITH p ORDER BY rand() LIMIT 3
    MERGE (o)-[c:CONTAINS]->(p)
    SET c.qty = toInteger(rand() * 2) + 1, c.priceAtPurchase = p.price
  }
} IN TRANSACTIONS OF 1000 ROWS;

// Плотный социальный граф — нужен для алгоритмов сообществ в уроке 27
MATCH (u:User:Synthetic)
CALL (u) {
  MATCH (other:User:Synthetic)
  WHERE other <> u
  WITH u, other ORDER BY rand() LIMIT 8
  MERGE (u)-[:FOLLOWS]->(other)
} IN TRANSACTIONS OF 1000 ROWS;

// Проверка масштаба
MATCH ()-[r]->() RETURN count(r) AS relationships;
```

Метка `:Synthetic` позволяет в любой момент отличить сгенерированные данные от исходных и удалить их:

```cypher
MATCH (n:Synthetic)
CALL (n) { DETACH DELETE n } IN TRANSACTIONS OF 10000 ROWS;
```

На конфигурации из `compose.yml` генерация занимает около минуты суммарно: примерно по 40 секунд на пользователей и по 15-20 на заказы и подписки. Граф вырастает до 90 тысяч узлов и 440 тысяч связей. Точные числа от запуска к запуску отличаются: количество заказов и товаров в них выбирается через `rand()`.

> **Внимание**: третий блок для каждого пользователя сканирует всех остальных синтетических — на 20 000 узлов это работает за секунды, но только если Neo4j хватает page cache. Если параллельно подняты другие тяжёлые контейнеры (например, забытый Testcontainers-инстанс из урока 22), контейнер может уйти в crash-loop по памяти. Перед генерацией стоит проверить `docker stats` и остановить лишнее. Если контейнеру не хватает памяти, уменьши количество пользователей до 5000 — для учебных целей этого достаточно.

## Практика

1. Очисти базу от учебных данных предыдущих уроков, затем создай все ограничения уникальности и проверь через `SHOW CONSTRAINTS`, что их девять. Если меньше — найди, на какой команде скрипт остановился.
2. Загрузи файлы в правильном порядке: категории, товары, пользователи, заказы, позиции, отзывы, просмотры, подписки, сессии.
3. Проверь счётчики по меткам и типам связей, сверь с числами из таблицы в начале урока.
4. Найди узлы без связей. Если такие есть — разберись, на каком шаге они появились.
5. Убери из запроса загрузки категорий всю проверку `WITH row WHERE row.parentId IS NOT NULL AND row.parentId <> ''`, запусти повторно и сверь счётчики `Category` и `SUBCATEGORY_OF` — они не изменятся: `MATCH` по `null` ничего не находит и строка просто отсеивается. Теперь замени в том же запросе `MATCH (parent:Category {categoryId: row.parentId})` на `MERGE` и убедись, что загрузка падает с `22N31`. Верни фильтр на место.
6. Загрузи товары без `toFloat(row.price)`, затем выполни `MATCH (p:Product) WHERE p.price > 3000 RETURN count(*)` и объясни, почему получился ноль. Сравни с `WHERE p.price > '3000'` и проверь `RETURN '4990.00' > 3000` отдельно. Исправь типы через `SET p.price = toFloat(p.price)`.
7. Запусти любую загрузку повторно и убедись через счётчики, что дубликатов не появилось.
8. Перепиши загрузку позиций заказов на `CALL {} IN TRANSACTIONS OF 50 ROWS` и убедись, что результат тот же.
9. Найди устройство, с которого заходило больше одного пользователя — это заготовка для урока 31.
10. Запусти скрипт генерации синтетических данных и зафиксируй итоговое количество связей.

## Итоги урока

- Перед загрузкой базу очищают от учебных данных: дубликаты из практики прошлых уроков не дадут создать ограничения уникальности, а скрипт в `cypher-shell` останавливается на первой ошибке и остальные команды молча пропускает.
- Ограничения уникальности создаются до загрузки: без индекса каждый `MERGE` сканирует все узлы метки, а без ограничения параллельные загрузки создают дубликаты.
- Свойства связей не видны в `db.schema.nodeTypeProperties()` — для них есть `db.schema.relTypeProperties()`.
- Загружать нужно в порядке зависимостей — сначала узлы, потом связи; иначе `MERGE` связи создаст пустые узлы-заглушки.
- `LOAD CSV` отдаёт все значения строками: без `toInteger`, `toFloat` и `date` сравнения и сортировки начинают работать лексикографически.
- Пустая ячейка CSV читается как `null`, и `null` в ключе `MERGE` роняет загрузку ошибкой `22N31`, поэтому фильтр по пустым значениям обязателен.
- Самоссылающиеся данные вроде иерархии категорий загружаются двумя проходами по одному файлу: сначала узлы, потом связи.
- `CALL {} IN TRANSACTIONS` разбивает загрузку на транзакции по N строк и снимает ограничение по heap, но лишает загрузку атомарности — она обязана быть идемпотентной.
- `neo4j-admin database import` пишет хранилище напрямую и на порядки быстрее, но требует остановленной пустой базы и чистых данных без дедупликации.
- APOC читает JSON, XML, HTTP и JDBC; `apoc.periodic.iterate` — предшественник `CALL {} IN TRANSACTIONS`, для нового кода предпочтителен встроенный синтаксис.
- Учебный датасет мал для профилирования и алгоритмов, поэтому граф достраивается синтетическими данными с меткой `:Synthetic`, которую потом легко отделить.
