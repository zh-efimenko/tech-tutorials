# Урок 38. Spring AI и Neo4j

Предполагается, что пройдены треки 3 (Spring Data Neo4j) и уроки 35–37. Для запуска нужен профиль `rag`:

```bash
docker compose --profile rag up -d
docker exec ollama ollama pull nomic-embed-text
docker exec ollama ollama pull qwen3:4b
```

Если Ollama уже установлена на машине (`brew install ollama`, `ollama serve`), профиль `rag` поднимать не нужно — она слушает тот же порт 11434, а модели тянутся без `docker exec`:

```bash
ollama pull nomic-embed-text
ollama pull qwen3:4b
ollama list
```

Приложение из этого урока запускается на хосте и ходит на `localhost:11434` в обоих случаях, поэтому конфигурация не меняется. Разница появится только если к Ollama потребуется обращаться **изнутри** контейнера Neo4j — тогда вместо `localhost` нужен `host.docker.internal`.

Ещё одно обязательное действие: удалить учебный векторный индекс из урока 37. Он называется так же, `chunk_embedding`, но создан на три измерения, а `nomic-embed-text` выдаёт 768.

```cypher
DROP INDEX chunk_embedding IF EXISTS;
MATCH (c:Chunk) REMOVE c.embedding;
```

Без этого приложение стартует нормально и упадёт только на первой записи документа — как описано ниже.

Всё, что было до этого урока, делалось запросами. Здесь то же самое собирается в приложение.

## Что берёт на себя Spring AI

Три вещи, которые иначе пришлось бы писать руками:

| Задача | Без Spring AI | С Spring AI |
|---|---|---|
| Вызов модели эмбеддингов | HTTP-клиент под каждого провайдера | `EmbeddingModel`, один интерфейс |
| Хранение и поиск векторов | Cypher с `db.index.vector.queryNodes` | `VectorStore.add()` и `similaritySearch()` |
| Сборка RAG-промпта | Конкатенация строк | `RetrievalAugmentationAdvisor` |

Смена провайдера эмбеддингов с Ollama на OpenAI — это замена стартера и свойств, код не меняется. Ради этого абстракция и существует.

Взамен теряется контроль над схемой: `VectorStore` кладёт документы так, как считает нужным. Ниже разбирается, как это совместить с графом, который построен в уроке 36.

## Зависимости

```groovy
plugins {
    id 'java'
    id 'org.springframework.boot' version '4.1.0'
    id 'io.spring.dependency-management' version '1.1.7'
}

dependencyManagement {
    imports { mavenBom "org.springframework.ai:spring-ai-bom:2.0.0" }
}

dependencies {
    implementation 'org.springframework.boot:spring-boot-starter-data-neo4j'
    implementation 'org.springframework.ai:spring-ai-starter-model-ollama'
    implementation 'org.springframework.ai:spring-ai-starter-vector-store-neo4j'
    implementation 'org.springframework.ai:spring-ai-rag'
}
```

Три замечания.

Spring AI управляется собственным BOM, а не Boot-овским: версия ставится один раз в `mavenBom`, у отдельных зависимостей её не указывают.

`spring-ai-starter-vector-store-neo4j` тянет драйвер Neo4j, но не Spring Data Neo4j. Стартер `spring-boot-starter-data-neo4j` нужен отдельно — без него не будет `Neo4jClient`, а именно он делает обходы графа.

`spring-ai-rag` — отдельный артефакт, в стартеры не входит. Без него нет ни `RetrievalAugmentationAdvisor`, ни интерфейса `DocumentRetriever`.

## Конфигурация

```yaml
spring:
  neo4j:
    uri: bolt://localhost:7687
    authentication:
      username: neo4j
      password: graphpassword
  ai:
    ollama:
      base-url: http://localhost:11434
      embedding:
        options:
          model: nomic-embed-text
      chat:
        options:
          model: qwen3:4b
    vectorstore:
      neo4j:
        initialize-schema: true
        embedding-dimension: 768
        label: Chunk
        index-name: chunk_embedding
        id-property: chunkId
        text-property: text
        embedding-property: embedding
        distance-type: COSINE
```

`embedding-dimension: 768` — это размерность `nomic-embed-text`. Проверить её можно напрямую:

```bash
curl -s http://localhost:11434/api/embed \
  -d '{"model":"nomic-embed-text","input":"кофеварка"}' \
  | python3 -c "import json,sys; print(len(json.load(sys.stdin)['embeddings'][0]))"
```

```
768
```

> **Внимание**: `initialize-schema: true` создаёт индекс и ограничение только если их нет. Существующий индекс с другой размерностью он не трогает и не предупреждает — падение произойдёт на первой записи:
>
> ```
> Vector index 'chunk_embedding' has a configured dimensionality of 3,
> but the provided vector has dimension 768.
> ```
>
> Смена модели эмбеддингов требует ручного `DROP INDEX` и пересчёта всех векторов. Это то же ограничение, что в уроке 35, только проявляется оно уже в рантайме приложения.

Имя модели в Ollama должно совпадать точно, включая тег. Если `ollama list` показывает `nomic-embed-text:latest`, то и в конфигурации допустимо и короткое имя, и полное — но модель обязана быть скачана заранее, иначе будет `HTTP 404 - model not found, try pulling it first`.

## Программная конфигурация хранилища

Свойств хватает для типовых случаев. Когда нужен полный контроль — бин:

```java
@Bean
VectorStore customVectorStore(Driver driver, EmbeddingModel embeddingModel) {
    return Neo4jVectorStore.builder(driver, embeddingModel)
            .databaseName("neo4j")
            .distanceType(Neo4jVectorStore.Neo4jDistanceType.COSINE)
            .embeddingDimension(768)
            .label("Chunk")
            .embeddingProperty("embedding")
            .indexName("chunk_embedding")
            .idProperty("chunkId")
            .textProperty("text")
            .initializeSchema(true)
            .build();
}
```

`Neo4jDistanceType` — вложенный enum самого `Neo4jVectorStore`, а не отдельный класс.

## Загрузка документов

```java
@Service
class IngestService {

    private final VectorStore vectorStore;

    IngestService(VectorStore vectorStore) {
        this.vectorStore = vectorStore;
    }

    void ingest(String docId, List<String> chunks) {
        List<Document> docs = IntStream.range(0, chunks.size())
                // Первый аргумент — идентификатор документа. Он попадёт в свойство
                // chunkId и должен быть детерминированным: docId + позиция, как в уроке 36
                .mapToObj(i -> new Document(docId + "-" + i, chunks.get(i),
                                            Map.of("docId", docId)))
                .toList();
        vectorStore.add(docs);
    }

    List<Document> search(String query, int k) {
        return vectorStore.similaritySearch(
                SearchRequest.builder()
                        .query(query)
                        .topK(k)
                        .similarityThreshold(0.5)
                        .build());
    }
}
```

`vectorStore.add()` делает три вещи одним вызовом: считает эмбеддинги через `EmbeddingModel`, создаёт узлы, пишет векторы. `similaritySearch` считает эмбеддинг запроса и обращается к индексу.

> **Важно**: конструктор `new Document(text, metadata)` без идентификатора генерирует случайный UUID. Он же попадает в `chunkId`, и узлы получаются новыми — не теми, что построил урок 36, и без единой связи `MENTIONS`. Для GraphRAG-ретривера ниже это фатально: он ищет чанки по идентификаторам из векторной выдачи и не находит ничего. Идентификатор обязан совпадать с `chunkId` из пайплайна извлечения — отсюда явный `docId + '-' + позиция`, тот же формат, что в уроке 36.

Проверка на живой базе — два чанка и запрос «кофеварка протекает»:

```
RESULT> 0.8752 :: Протечка воды — известная проблема Aroma Mini. Причина в уплотнителе резервуара.
RESULT> 0.8028 :: Наушники Echo Light выпускает компания Echo.
```

Настоящие эмбеддинги, настоящая семантика: про кофеварку в запросе слова «протечка» не было, а чанк нашёлся первым.

`similarityThreshold` отсекает результаты ниже порога. На примере выше видно, почему он нужен: наушники получили 0.80 при полной нерелевантности. Косинусная близость на текстовых эмбеддингах редко опускается ниже 0.7 даже для несвязанных текстов, поэтому порог подбирают замером на своих данных, а не берут из головы.

### Что реально записывается

```cypher
MATCH (n:Chunk) RETURN keys(n) AS keys, size(n.embedding) AS dim LIMIT 1;
```

```
╒══════════════════════════════════════════════════╤═══════╕
│keys                                              │dim    │
╞══════════════════════════════════════════════════╪═══════╡
│["chunkId","text","embedding","metadata.docId"]   │768    │
└──────────────────────────────────────────────────┴───────┘
```

Метаданные раскладываются в плоские свойства с точкой в имени: `metadata.docId`. Обращаться к ним в Cypher нужно через обратные кавычки — `` n.`metadata.docId` ``.

> **Внимание**: идентификатор лежит в свойстве, названном в `id-property`, — здесь это `chunkId`. Свойства `id` у узла **нет**, и запрос `MATCH (c:Chunk) WHERE c.id IN $ids` вернёт ноль строк. В ретривере ниже это особенно опасно: там на пустой результат стоит фолбэк на векторную выдачу, поэтому GraphRAG молча выродится в обычный векторный поиск — без ошибок и без единой строки в логах. Если поменяешь `id-property` в конфигурации, поменяй имя свойства и во всех Cypher-запросах.

> **Важно**: это не та схема, которую строил урок 36. Там были `Document`, `Chunk` с `chunkId`, связи `HAS_CHUNK` и `MENTIONS`. Spring AI знает только про плоские узлы. Совместить их можно двумя способами: настроить `label` и `id-property` так, чтобы `VectorStore` писал в те же узлы, что и пайплайн извлечения, — либо оставить два слоя и связать их отдельным запросом. Первый вариант проще, но требует, чтобы `id` документов Spring AI совпадал с `chunkId`; второй надёжнее, но добавляет шаг в пайплайн.

## RAG-адвайзор

`RetrievalAugmentationAdvisor` — готовый RAG-конвейер: берёт вопрос, идёт в ретривер, подставляет найденное в промпт.

```java
@Service
class PlainRagService {

    private final ChatClient chatClient;

    PlainRagService(ChatClient.Builder builder, VectorStore vectorStore) {
        this.chatClient = builder
                .defaultAdvisors(RetrievalAugmentationAdvisor.builder()
                        .documentRetriever(VectorStoreDocumentRetriever.builder()
                                .vectorStore(vectorStore)
                                .topK(3)
                                .similarityThreshold(0.5)
                                .build())
                        .build())
                .build();
    }

    String ask(String question) {
        return chatClient.prompt().user(question).call().content();
    }
}
```

Это наивный RAG из урока 37 — ровно то, чего недостаточно. Графа здесь нет.

## GraphRAG через собственный ретривер

`DocumentRetriever` — интерфейс с одним методом. Реализация может делать что угодно, лишь бы вернула список документов.

```java
@Component
class GraphExpandingRetriever implements DocumentRetriever {

    private final VectorStore vectorStore;
    private final Neo4jClient client;

    GraphExpandingRetriever(VectorStore vectorStore, Neo4jClient client) {
        this.vectorStore = vectorStore;
        this.client = client;
    }

    @Override
    public List<Document> retrieve(Query query) {
        List<Document> seeds = vectorStore.similaritySearch(
                SearchRequest.builder().query(query.text()).topK(3).build());

        List<String> ids = seeds.stream().map(Document::getId).toList();

        List<String> facts = client.query("""
                        MATCH (c:Chunk) WHERE c.chunkId IN $ids
                        MATCH (c)-[:MENTIONS]->(e:Entity)-[r:RELATES_TO]-(n:Entity)
                        RETURN DISTINCT e.name + ' -[' + r.type + ']- ' + n.name AS fact
                        LIMIT 30
                        """)
                .bind(ids).to("ids")
                .fetchAs(String.class)
                .mappedBy((types, record) -> record.get("fact").asString())
                .all()
                .stream().toList();

        if (facts.isEmpty()) {
            return seeds;
        }

        Document graphContext = new Document(
                "Факты графа:\n" + String.join("\n", facts),
                Map.of("source", "graph"));

        return Stream.concat(seeds.stream(), Stream.of(graphContext)).toList();
    }
}
```

Подключается заменой одной строки:

```java
@Service
class GraphRagService {

    private final ChatClient chatClient;

    GraphRagService(ChatClient.Builder builder, GraphExpandingRetriever retriever) {
        this.chatClient = builder
                .defaultAdvisors(RetrievalAugmentationAdvisor.builder()
                        .documentRetriever(retriever)
                        .build())
                .build();
    }

    String ask(String question) {
        return chatClient.prompt().user(question).call().content();
    }
}
```

Устройство важнее кода: **векторный поиск и обход графа живут в одном методе и в одной базе**. Между ними нет сетевого вызова, нет второго хранилища и нет рассинхронизации. Это и есть техническая причина использовать Neo4j как vector store, а не отдельный Qdrant рядом.

Метка `Map.of("source", "graph")` на документе с фактами — не украшение. Она позволяет в промпте и в логах отличать «взято из текста» от «выведено из графа», что критично при разборе неверных ответов (урок 39).

`LIMIT 30` внутри запроса — защита от хабов из урока 37: одна популярная сущность иначе притащит сотни фактов и вытеснит из контекста сами тексты.

## Полный контроль над промптом

Адвайзор удобен, но собирает промпт по своему шаблону. Когда нужны три подписанных блока из урока 37, промпт собирается вручную.

```java
@Service
class ManualGraphRagService {

    private final VectorStore vectorStore;
    private final Neo4jClient neo4jClient;
    private final ChatClient chatClient;

    ManualGraphRagService(VectorStore vectorStore, Neo4jClient neo4jClient, ChatClient.Builder builder) {
        this.vectorStore = vectorStore;
        this.neo4jClient = neo4jClient;
        this.chatClient = builder.build();
    }

    String answer(String question) {
        List<Document> seeds = vectorStore.similaritySearch(
                SearchRequest.builder().query(question).topK(3).build());
        List<String> ids = seeds.stream().map(Document::getId).toList();

        String facts = neo4jClient.query("""
                        MATCH (c:Chunk) WHERE c.chunkId IN $ids
                        MATCH (c)-[:MENTIONS]->(e:Entity)-[r:RELATES_TO]-(n:Entity)
                        RETURN DISTINCT e.name + ' -[' + r.type + ']- ' + n.name AS fact
                        LIMIT 30
                        """)
                .bind(ids).to("ids")
                .fetchAs(String.class)
                .mappedBy((types, record) -> record.get("fact").asString())
                .all()
                .stream()
                .collect(Collectors.joining("\n"));

        String texts = seeds.stream().map(Document::getText).collect(Collectors.joining("\n"));

        return chatClient.prompt()
                .system("Отвечай только по контексту. Если данных нет, скажи об этом.")
                .user("""
                      Вопрос: %s

                      Тексты документов:
                      %s

                      Факты графа:
                      %s
                      """.formatted(question, texts, facts))
                .call()
                .content();
    }
}
```

Выбор между адвайзором и ручной сборкой: адвайзор — когда конвейер стандартный и важна переносимость, ручная сборка — когда структура контекста сама по себе часть решения. Для GraphRAG чаще нужен второй вариант.

## Эксплуатация

**Транзакции.** `vectorStore.add()` вызывает внешний HTTP-сервис для расчёта эмбеддингов. Держать вокруг него `@Transactional` нельзя: транзакция Neo4j будет открыта всё время работы модели. Загрузка документов делается пакетами вне транзакции.

**Пакетирование.** `BatchingStrategy` в Spring AI режет список документов на порции, укладывающиеся в лимит токенов модели. Значение по умолчанию разумно; менять его нужно, только если модель отвергает батчи.

**Идемпотентность.** `VectorStore.add()` перезаписывает документ с тем же `id` — при условии, что `id` задан явно. Сгенерированный случайно `id` означает дубли при повторной загрузке. Идентификатор должен быть детерминированным: хеш текста или `docId + позиция`, как в уроке 36.

**Стоимость.** Один вызов модели эмбеддингов на документ при загрузке и один на каждый вопрос. Эмбеддинг вопроса кешируется по тексту — на популярных запросах это заметная экономия.

**Локальные модели.** Ollama на CPU считает эмбеддинги медленно: сотни миллисекунд на документ. Для загрузки корпуса это часы. На проде — либо GPU, либо облачный провайдер; локальная модель нужна для разработки и для данных, которые нельзя отдавать наружу.

**Наблюдаемость.** Spring AI отдаёт метрики через Micrometer: латентность вызовов модели, число токенов, время поиска в хранилище. Настройка — как в уроке 23.

## Практика

1. Собери проект с четырьмя зависимостями и убедись, что он компилируется.
2. Проверь размерность `nomic-embed-text` запросом к `/api/embed` и пропиши её в конфигурации.
3. Загрузи два-три чанка через `vectorStore.add()` и найди их семантическим запросом, не содержащим слов из текста.
4. Посмотри в Cypher, какие свойства появились у созданных узлов, и обратись к `metadata.docId` через обратные кавычки.
5. Создай векторный индекс с размерностью 3, запусти загрузку и разбери текст ошибки.
6. Замени конфигурацию свойствами на бин `Neo4jVectorStore.builder(...)` и добейся того же поведения.
7. Подбери `similarityThreshold`, при котором нерелевантный чанк перестаёт попадать в выдачу.
8. Собери наивный RAG на `VectorStoreDocumentRetriever` и задай вопрос, требующий фактов из двух документов.
9. Реализуй `GraphExpandingRetriever`, подключи его в адвайзор и сравни ответ на тот же вопрос.
10. Убери `LIMIT 30` из запроса фактов и оцени, насколько вырос контекст.
11. Собери промпт вручную тремя подписанными блоками и сравни ответы с адвайзорной версией.
12. Задай документам детерминированные `id`, загрузи их дважды и убедись, что дублей нет.
13. Оберни загрузку в `@Transactional` и объясни, почему так делать нельзя.

## Итоги урока

- Spring AI даёт три абстракции: `EmbeddingModel`, `VectorStore` и RAG-адвайзоры; смена провайдера эмбеддингов сводится к замене стартера и свойств.
- Версии Spring AI управляются собственным BOM, а `spring-ai-rag` — отдельный артефакт, в стартеры не входящий.
- Стартер векторного хранилища тянет драйвер Neo4j, но не Spring Data Neo4j: `Neo4jClient` для обходов графа подключается отдельно.
- `embedding-dimension` обязан совпадать с моделью; у `nomic-embed-text` это 768.
- `initialize-schema` создаёт индекс, только если его нет, и молча пропускает существующий с другой размерностью — падение случится на первой записи.
- `Neo4jVectorStore` пишет плоские узлы со свойствами `id`, `text`, `embedding` и `metadata.<ключ>` — это не та схема, что строит пайплайн извлечения из урока 36.
- Совместить слои можно настройкой `label` и `id-property` либо отдельным шагом связывания; первое проще, второе надёжнее.
- `RetrievalAugmentationAdvisor` с `VectorStoreDocumentRetriever` даёт наивный RAG; GraphRAG получается заменой ретривера на собственный.
- Собственный `DocumentRetriever` — это векторный поиск плюс обход графа в одном методе и в одной базе, без сетевого вызова между ними.
- Факты графа возвращаются отдельным документом с меткой источника, чтобы отличать их от текста при отладке и в промпте.
- Обход внутри ретривера ограничивается `LIMIT`, иначе одна сущность-хаб вытесняет из контекста сами тексты.
- `vectorStore.add()` ходит по HTTP во внешнюю модель, поэтому не оборачивается в транзакцию Neo4j.
- Идентификаторы документов должны быть детерминированными, иначе повторная загрузка создаёт дубли вместо перезаписи.
