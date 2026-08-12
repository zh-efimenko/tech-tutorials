# Урок 1. Введение в Hazelcast

## Зачем нужен In-Memory Data Grid

Представь типичную высоконагруженную систему: тысячи запросов в секунду, требования к латентности менее 1 мс, данные должны быть доступны даже при падении отдельных серверов. Классическая база данных (PostgreSQL, MySQL) здесь не справится — даже с пулом соединений и индексами время ответа измеряется миллисекундами, а при высокой нагрузке — десятками миллисекунд.

**In-Memory Data Grid (IMDG)** решает эту проблему: данные хранятся в оперативной памяти, распределены по кластеру серверов и реплицированы для отказоустойчивости. Доступ к данным — микросекунды вместо миллисекунд.

Hazelcast — одна из ведущих реализаций IMDG для JVM-экосистемы. Текущая актуальная версия — **Hazelcast Platform 5.7** (май 2026).

## Что такое Hazelcast

Hazelcast — это распределённое хранилище данных в оперативной памяти с открытым исходным кодом. Ключевые характеристики:

- **Распределённость** — данные автоматически разделяются (партиционируются) между узлами кластера
- **Репликация** — каждая запись имеет настраиваемое количество копий на других узлах
- **Отказоустойчивость** — при падении узла его данные доступны с реплик, кластер автоматически перебалансируется
- **Масштабируемость** — добавление узлов увеличивает объём доступной памяти и пропускную способность
- **Java API** — нативная интеграция с Java, Spring Boot, Kubernetes

## Какие задачи решает Hazelcast

| Задача | Пример | Почему не БД |
|--------|--------|-------------|
| Кэширование горячих данных | Каталог товаров, профили пользователей | Частые чтения, допустима eventual consistency |
| Хранение ephemeral-данных | Сессии, heartbeat-ы, временные токены | Не нужно долговременное хранение |
| Распределённые блокировки | Координация между инстансами | `synchronized` работает только в одной JVM |
| Real-time аналитика | Счётчики, агрегации в реальном времени | Латентность БД неприемлема |
| Pub/Sub между инстансами | Инвалидация кэшей, broadcast-события | Не нужен отдельный message broker |

## Hazelcast vs альтернативы

| Характеристика | Hazelcast | Redis | Apache Ignite | Memcached |
|---------------|-----------|-------|---------------|-----------|
| Язык | Java (JVM-native) | C | Java | C |
| Встраивание в JVM | Да (embedded mode) | Нет | Да | Нет |
| Распределённые структуры данных | IMap, IQueue, ITopic, ISet, IList | Strings, Hashes, Lists, Sets | Cache, SQL Tables | Key-Value |
| SQL-запросы | Да (Hazelcast SQL) | Нет | Да (полноценный SQL) | Нет |
| Партиционирование | Автоматическое (271 партиция) | Ручное (Redis Cluster) | Автоматическое | Нет (клиентский шардинг) |
| Транзакции | Да | Lua-скрипты | Да (ACID) | Нет |
| Персистентность | Опциональная (MapStore) | RDB/AOF | Да (native persistence) | Нет |
| Spring Boot интеграция | Автоконфигурация из коробки | Через Spring Data Redis | Через Spring Data | Нет |

**Когда выбирать Hazelcast:**

- Проект на Java/Spring Boot — нативная интеграция без сериализации в строки
- Нужны распределённые структуры данных (не только key-value)
- Важна embedded-модель — Hazelcast работает в том же процессе, что и приложение
- Требуется server-side вычисление — EntryProcessor, агрегации выполняются рядом с данными

**Когда НЕ выбирать Hazelcast:**

- Нужна полноценная персистентная БД — Hazelcast в первую очередь in-memory
- Polyglot-стек (Python, Node.js, Go) — Redis имеет лучшую поддержку клиентов
- Простое кэширование без распределённых структур — Redis проще в эксплуатации

## Архитектура на высоком уровне

```
┌──────────────────────────────────────────────┐
│              Hazelcast Cluster                │
│                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │  Node 1  │  │  Node 2  │  │  Node 3  │   │
│  │          │  │          │  │          │   │
│  │ Part 0-90│  │Part 91-180│ │Part 181-270│  │
│  │ (owner)  │  │ (owner)  │  │ (owner)  │   │
│  │          │  │          │  │          │   │
│  │ Backups  │  │ Backups  │  │ Backups  │   │
│  │from 2,3  │  │from 1,3  │  │from 1,2  │   │
│  └──────────┘  └──────────┘  └──────────┘   │
│                                              │
└──────────────────────────────────────────────┘
         ▲              ▲              ▲
         │              │              │
    ┌────┴────┐   ┌────┴────┐   ┌────┴────┐
    │  App 1  │   │  App 2  │   │  App 3  │
    │(client) │   │(client) │   │(client) │
    └─────────┘   └─────────┘   └─────────┘
```

Hazelcast разделяет все данные на **271 партицию** (по умолчанию). Каждая партиция имеет владельца (owner) и настраиваемое количество реплик (backups). Ключ определяет, в какую партицию попадёт запись: `partitionId = hash(key) % partitionCount`.

## Основные структуры данных

| Структура | Java-аналог | Описание |
|-----------|-------------|----------|
| `IMap<K, V>` | `ConcurrentMap` | Распределённая карта — основная структура |
| `IQueue<E>` | `BlockingQueue` | Распределённая очередь |
| `ITopic<E>` | — | Pub/Sub механизм |
| `ISet<E>` | `Set` | Распределённое множество |
| `IList<E>` | `List` | Распределённый список |
| `IAtomicLong` | `AtomicLong` | Распределённый атомарный счётчик (CP Subsystem, Enterprise) |
| `FencedLock` | `ReentrantLock` | Распределённая блокировка (CP Subsystem, Enterprise) |
| `Ringbuffer<E>` | — | Кольцевой буфер для reliable messaging |

> **IMap** — это 90% использования Hazelcast на практике. Остальные структуры данных рассматриваются в уроке 12.

## Быстрый старт

### Запуск сервера

```bash
docker run -d --name hazelcast \
  -p 5701:5701 \
  -e HZ_CLUSTERNAME=dev \
  hazelcast/hazelcast:5.7.0
```

### Подключение из Java

```java
import com.hazelcast.client.HazelcastClient;
import com.hazelcast.client.config.ClientConfig;
import com.hazelcast.core.HazelcastInstance;
import com.hazelcast.map.IMap;

public class QuickStart {
    public static void main(String[] args) {
        ClientConfig config = new ClientConfig();
        config.setClusterName("dev");

        HazelcastInstance client = HazelcastClient.newHazelcastClient(config);
        
        // Получить или создать распределённую карту
        IMap<String, String> map = client.getMap("my-map");
        
        // Операции как с обычной ConcurrentMap
        map.put("key-1", "value-1");
        String value = map.get("key-1");
        System.out.println(value); // value-1
        
        // Но данные доступны с любого клиента кластера!
        
        client.shutdown();
    }
}
```

### Зависимости (Gradle)

```groovy
dependencies {
    implementation 'com.hazelcast:hazelcast:5.7.0'
    // Для Spring Boot — автоконфигурация включена
    implementation 'com.hazelcast:hazelcast-spring:5.7.0'
    // Spring Boot 4: автоконфигурация вынесена в отдельный модуль
    implementation 'org.springframework.boot:spring-boot-starter-hazelcast'
}
```

> **Важно:** у стартера версия не указана — её подставляет BOM Spring Boot. Без плагина `org.springframework.boot` (или без `implementation platform('org.springframework.boot:spring-boot-dependencies:4.1.0')`) сборка упадёт с `Could not find org.springframework.boot:spring-boot-starter-hazelcast:.`

## Версии и поддержка

Hazelcast выпускается в двух редакциях:

| Редакция | Что включает |
|----------|-------------|
| **Community Edition** | Открытый исходный код, IMap, Serialization, Predicates, Indexes, Split-Brain Protection, K8s Discovery |
| **Enterprise Edition** | Всё из Community + CP Subsystem (с 5.5), HD Memory, WAN Replication, Hot Restart, Security, Blue-Green Deployments, Vector Search |

> Для большинства задач Community Edition достаточно. Enterprise нужен для WAN-репликации между дата-центрами, off-heap памяти, hot restart и CP Subsystem (`IAtomicLong`, `FencedLock`, `ISemaphore` — начиная с 5.5 только по лицензии).

Hazelcast Platform 5.7 (май 2026) — текущая стабильная версия. Ключевые изменения:
- Поддержка Java 25 (LTS); Java 17 и 21 продолжают работать
- CP Leader Auto Step-Down (Enterprise) — запрет лидерства CP-групп на выбранных узлах
- Улучшения Jet: User Code Namespaces, метрики backpressure, автовосстановление джоб при rolling update
- Dynamic Diagnostic Logging — GA в Management Center 5.11, переключение диагностики без рестарта
- Минимальная версия JDK: **17** (начиная с Hazelcast 5.5)

> **Внимание:** образ `hazelcast/hazelcast:5.7.0` собран на Java 25. Если тебе нужен другой JDK, бери тег с суффиксом: `hazelcast/hazelcast:5.7.0-jdk17` или `5.7.0-jdk21`.

## Практика

1. Запусти Hazelcast-сервер через Docker (команда выше)
2. Проверь его состояние через REST API: `curl http://localhost:5701/hazelcast/health/node-state`
3. Создай Java-проект с зависимостью `com.hazelcast:hazelcast:5.7.0`
4. Напиши программу, которая подключается к кластеру, кладёт 100 записей в IMap и читает их обратно
5. Запусти второй экземпляр Hazelcast и убедись, что данные доступны с обоих узлов. Оба узла должны быть в одной пользовательской сети Docker и знать адреса друг друга:

```bash
docker network create hz-net

# IP хоста в локальной сети (macOS; на Linux: hostname -I | awk '{print $1}')
HOST_IP=$(ipconfig getifaddr en0)

for n in 1 2; do
  docker run -d --name hz-$n --network hz-net -p 570$n:5701 \
    -e HZ_CLUSTERNAME=dev \
    -e HZ_NETWORK_JOIN_MULTICAST_ENABLED=false \
    -e HZ_NETWORK_JOIN_TCPIP_ENABLED=true \
    -e HZ_NETWORK_JOIN_TCPIP_MEMBERLIST_0=$HOST_IP:5701 \
    -e HZ_NETWORK_JOIN_TCPIP_MEMBERLIST_1=$HOST_IP:5702 \
    -e HZ_NETWORK_PUBLICADDRESS=$HOST_IP:570$n \
    hazelcast/hazelcast:5.7.0
done

docker logs hz-2 | grep "Members {"   # Members {size:2, ver:2}
```

Клиент с хоста подключай по тем же адресам:

```java
config.getNetworkConfig().addAddress(HOST_IP + ":5701", HOST_IP + ":5702");
```

> **Внимание:** `--network host` для этого шага не подходит. На Docker Desktop (macOS, Windows) контейнер с `--network host` не получает сетевое пространство хоста, и второй узел не увидит первый — кластер соберётся из одного участника.

> **Почему именно IP хоста, а не имена контейнеров.** Узлы анонсируют друг другу и клиентам адрес из `HZ_NETWORK_PUBLICADDRESS`. Если поставить туда имена контейнеров (`hz-1`, `hz-2`), кластер соберётся, но клиент **с хоста** работать не будет: smart-клиент получает список членов и пытается ходить к каждому напрямую, а имена контейнеров с хоста не резолвятся — в лог бесконечно сыплется `Could not connect to member ..., reason ... UnknownHostException: hz-2`, и `map.put` просто не завершается. IP хоста резолвится и снаружи, и изнутри контейнеров, поэтому работает и кластеризация, и клиент из IDE. Альтернатива — запускать клиент контейнером в той же сети `hz-net`.
6. Останови первый узел и проверь, что данные сохранились на втором

## Итоги урока

- Hazelcast — In-Memory Data Grid для JVM, хранящий данные в оперативной памяти распределённого кластера
- Данные автоматически партиционируются по 271 партиции и реплицируются между узлами
- Основная структура данных — `IMap<K, V>`, распределённая реализация `ConcurrentMap`
- Hazelcast решает задачи кэширования, распределённых блокировок, pub/sub и real-time аналитики
- По сравнению с Redis, Hazelcast нативнее интегрируется с Java и поддерживает embedded-режим
- Community Edition покрывает большинство задач, Enterprise нужен для WAN-репликации и off-heap памяти
- Актуальная версия — Hazelcast Platform 5.7, минимальная версия JDK — 17