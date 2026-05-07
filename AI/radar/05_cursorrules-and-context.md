# Контекстные инструкции AI IDE: .cursorrules, rules и Skills

## Зачем нужны контекстные инструкции

AI-ассистент по умолчанию знает о проекте ровно то, что попало в его контекстное окно: открытые файлы, результаты поиска, явно прикреплённые документы. Всё остальное модель достраивает из general knowledge — усреднённых практик из обучающих данных.

Без rules AI выдаёт валидный, но generic код: React-компоненты с классовыми состояниями там, где команда использует хуки; REST-обработчики с `express.Router()` в проекте на Fastify; кастомные обработчики ошибок в стиле Go в TypeScript-кодовой базе с Result-типами. Через несколько спринтов накапливается дрейф: разные фрагменты кода выглядят так, как будто их писали разные команды.

Механизм `.cursorrules` и `.cursor/rules/` решает именно эту задачу: фиксирует project-level system prompt, который подмешивается в каждый запрос к модели.

### Экономика инвестиций

Senior-разработчик тратит 1–3 часа на первую версию rules-файла — столько же, сколько на один раунд ревью сложного PR. Измеримые эффекты через полгода:
- Доля PR без правок по стилю и архитектуре растёт с 20–30% до 60–80%
- Onboarding нового разработчика сокращается с 2–3 недель активного менторства до 3–5 дней

**Trade-off:** больше инструкций не означает лучший результат. За пределами примерно 4–6 тысяч токенов правил начинается деградация: модель теряет фокус, игнорирует часть указаний. Оптимальный режим — модульная структура с Auto Attached.

---

## Эволюция .cursorrules

### Хронология

Первая версия появилась в Cursor осенью 2024 года: единственный файл `.cursorrules` в корне репозитория. В него складывали всё: стек, архитектурные паттерны, примеры кода. Файл рос, становился нечитаемым, а содержимое прикреплялось к каждому промпту целиком.

В релизе Cursor 0.45 (23 января 2025) появилась директория `.cursor/rules/` с файлами формата `.mdc` (Markdown + YAML frontmatter) и системой типизированных правил. Это архитектурный сдвиг: rules превратились в набор модулей, каждый из которых применяется по явному условию.

Файл `.cursorrules` по-прежнему читается, но официально помечен как deprecated. Новые проекты строятся на `.cursor/rules/`.

### Четыре типа правил

| Тип | Когда применяется | Использование |
|-----|------------------|---------------|
| **Always** | В каждом запросе | Абсолютные принципы: язык ответов AI, базовые архитектурные инварианты, запрет `any` в TypeScript |
| **Auto Attached** | Когда в контексте есть файлы, совпадающие с glob-паттерном | Основной тип для большинства правил: `src/**/*.ts` → TypeScript-правила |
| **Agent Requested** | AI сам решает подключить, читая поле `description` | Опциональные практики: оптимизация запросов к БД, работа с секретами |
| **Manual** | Явное подключение через `@rulename` в промпте | Разовые задачи: ревью PR под конкретный чек-лист |

**Важно:** перегруженный Always-файл снижает качество вывода. Идеальный размер — 100–300 строк, только абсолютные принципы без примеров и обоснований.

### Аналоги в других IDE

**Windsurf:**
- `.windsurfrules` в корне — аналог устаревшего `.cursorrules`
- `.windsurf/rules/` с мая 2025 (Wave 8) — система типизированных правил
- Глобальные Rules в настройках — аналог Always-правил

**GitHub Copilot:**
- `.github/copilot-instructions.md` — проектные инструкции для всех взаимодействий с Copilot
- Custom Instructions в настройках VS Code — персональные правила поверх проектных

Rules-файл, написанный для Cursor, конвертируется в формат Windsurf или Copilot механически: меняется расположение файла и синтаксис frontmatter, содержание правил переносится без потерь.

---

## Архитектура контекстных инструкций

### Три уровня правил

1. **Глобальные** — `~/.cursor/rules/`. Личные предпочтения разработчика: стиль коммуникации с AI, формат ответов. Не коммитятся в проект. Пример: `отвечай кратко, без объяснений, которые я не просил`.

2. **Проектные** — `.cursor/rules/` внутри репозитория. Технический стек, архитектурные решения, code style. Коммитятся в git, проходят code review.

3. **Модульные** — те же проектные правила, но с glob-паттернами Auto Attached, работающие только в пределах своей области.

Практический совет: глобальных правил должно быть минимум. Основной объём — проектные и модульные.

### Декомпозиция по доменам

Рабочая структура для среднего проекта:

```
.cursor/rules/
├── 00-always.mdc       # базовые принципы
├── 01-tech-stack.mdc   # стек и версии
├── 02-architecture.mdc # паттерны, DDD, слои
├── 03-code-style.mdc   # форматирование, naming
├── 04-testing.mdc      # стратегия тестирования
├── 05-api-design.mdc   # REST/GraphQL конвенции
├── 06-security.mdc     # правила безопасности
└── 07-review.mdc       # чек-лист для code review
```

Разные роли в команде владеют разными файлами: security engineer ведёт `06-security.mdc`, tech lead — `02-architecture.mdc`, QA — `04-testing.mdc`.

### Стратегии для монорепо

```
.cursor/rules/              # общие для монорепо
├── 00-always.mdc
└── 01-tech-stack.mdc

packages/auth/
└── .cursor/rules/          # специфичные для auth
    ├── 00-auth-domain.mdc
    └── 01-security.mdc
```

Рекомендация: не более двух уровней вложенности. Глубже логика разрешения становится непрозрачной.

---

## Создание эффективных инструкций

### Анатомия .mdc файла

```yaml
---
description: >
  Правила TypeScript для сервисного слоя.
  Применяй при изменении файлов сервисов —
  валидация входных данных через Zod,
  возврат Result-типов, логирование через pino.
globs: ["src/services/**/*.ts"]
alwaysApply: false
---

# TypeScript Service Layer Rules

Use Result<T, E> instead of throwing.
Avoid `any`. Prefer `unknown` + narrowing.
```

- **description** — ключевое поле для Agent Requested. Плохое описание делает правило мёртвым.
- **globs** — массив glob-паттернов для Auto Attached.
- **alwaysApply** — если `true`, правило становится Always независимо от других полей.

### Пять техник написания инструкций

**1. Imperatives вместо описаний**

```
# Слабая формулировка:
Обычно мы используем Result-типы для обработки ошибок в сервисах.

# Сильная формулировка:
Use Result<T, E> in all service methods.
Do not throw in service layer. Propagate errors via .err() —
throwing breaks the contract with callers.
```

**2. Few-shot примеры**

```markdown
## Naming

Good:
  export class CreateUserHandler { ... }
  const activeUsers = users.filter(...)

Bad:
  export class userCreator { ... }
  const au = users.filter(...)
```

**3. Обоснование (Why)**

```
Do not use `any` in public API signatures.
Why: any disables type checking at the call site, and callers cannot rely
on refactoring tools. Use `unknown` + type guards instead.
```

**4. Явные антипаттерны**

Перечисляй запрещённое прямо, без расчёта на умолчания.

**5. Ссылки на документы проекта**

```
@ARCHITECTURE.md
@openapi.yaml
@memory-bank/systemPatterns.md
```

При загрузке правила Cursor подставляет актуальное содержимое файлов.

### Архитектурные паттерны в инструкциях

Пример правила для Hexagonal Architecture:

```
Domain layer (src/domain/**):
- No imports from application, infrastructure.
- No framework imports (Express, NestJS).
- No I/O (fetch, fs, database).

Forbidden in domain:
  - import { PrismaClient } from '@prisma/client'
  - import express from 'express'

Allowed in domain:
  - import { DomainError } from './errors'
  - import { UserId } from './value-objects'
```

---

## Стандарты кода в rules-файлах

### Code style и форматирование

Первый принцип: не дублировать автоформатер. Если настроены Prettier, Black, gofmt — сослаться на конфиг одной строкой:

```
Code style is enforced by Prettier 3.3 with config in `.prettierrc`.
Do not override formatting decisions — run `prettier --write` before commit.
```

Описывать в rules только то, что автоформатер не покрывает: порядок импортов, порядок деклараций в файле, стиль комментариев.

### Обработка ошибок

Стратегия фиксируется однозначно — исключения или Result/Either:

```
Error handling — Result<T, E> pattern:

- All service methods return Result<T, E>.
- Infrastructure errors: DatabaseError, NetworkError — never leak to callers.
- Log errors via pino with { err, context }.
- Forbidden:
  - Empty catch blocks.
  - Swallowing errors without context.
```

### Требования к тестам

Rules по тестам — отдельный файл с Auto Attached на `**/*test*`:
- Пирамида: соотношение unit : integration : e2e (типично 70/25/5 для backend)
- Naming: `should [do X] when [condition Y]`
- Моки только на границах I/O — HTTP, БД, файловая система

---

## Управление проектным контекстом

### Memory Bank паттерн

Memory Bank — набор markdown-файлов, описывающих проект, которые обновляются параллельно с кодом и подключаются через rules.

Структура:
```
memory-bank/
├── projectBrief.md     # цель, бизнес-контекст
├── activeContext.md    # текущие задачи, спринт
├── techStack.md        # детали стека, версии
├── progress.md         # сделано / в работе
└── systemPatterns.md   # архитектурные паттерны
```

В rules-файле:
```yaml
---
alwaysApply: true
---

# Project Context

Current state: @memory-bank/activeContext.md
Architecture patterns: @memory-bank/systemPatterns.md
```

**Важное ограничение:** Memory Bank разрастается. Лучший баланс — ставить в Always только компактные файлы (`projectBrief.md`, `techStack.md`), объёмные подключать Agent Requested.

### .cursorignore

Что исключать обязательно:
- `node_modules/`, `vendor/`, `.venv/` — внешние зависимости
- `build/`, `dist/`, `.next/` — сгенерированные артефакты
- Автогенерированный код: `*_pb.go`, протобуферы
- Файлы с секретами: `.env*`, `*.key`, `*.pem` — даже если они в `.gitignore`

---

## Командные практики

### Rules как часть кодовой базы

- `.cursor/rules/` коммитится в репозиторий и проходит code review
- PR с изменением rules — новый инвариант в команде, заслуживает ревью не меньше, чем изменение архитектуры
- Changelog в коммитах: дата, причина изменения, ссылка на обсуждение

Практически: добавить rules в `CODEOWNERS`, чтобы PR с изменением `.cursor/rules/` автоматически уходили на ревью tech lead.

### Governance: кто владеет rules

- Tech lead — общий владелец `.cursor/rules/`
- Владельцы отдельных файлов по доменам: security engineer → `06-security.mdc`, QA lead → `04-testing.mdc`
- Регулярный аудит: раз в квартал, совместно с ретроспективой. Задача аудита — найти устаревшие и противоречивые правила, не добавить новые

---

## Skills как эволюция rules

**Rules** — это system prompt: фиксированный контекст (стек, архитектура, code style). **Skills** — пакетированные процедуры (`SKILL.md` + скрипты + ресурсы), которые модель подгружает только когда видит релевантную задачу.

Пример:
- Rules говорят, что в проекте используется Flyway
- Skill `creating-migration` знает как именно создать миграцию: пошаговая процедура, шаблон, проверки перед коммитом

Структура в репозитории (апрель 2026):
```
.cursor/rules/              # фиксированный контекст
├── 00-always.mdc
└── 01-tech-stack.mdc

.cursor/skills/             # процедурные знания
├── creating-migration/
│   ├── SKILL.md
│   └── scripts/validate.sh
└── release-checklist/
    └── SKILL.md
```

С 18.12.2025 Skills — открытый стандарт, поддерживается в 26+ инструментах (Cursor, Windsurf, Copilot, Gemini CLI, AWS Kiro и другие). Инвестиция в Skills защищает от vendor lock-in, который остаётся у rules.

---

## Trade-offs и ограничения

- **Rules не заменяют linter:** ESLint, golangci-lint проверяют детерминированно. Rules несут архитектурные и доменные соглашения, которые статический анализ не понимает.
- **Длинные rules снижают качество:** граница деградации — около 4–6 тысяч токенов в одном промпте.
- **Конфликтующие правила игнорируются:** если два правила противоречат, модель выберет случайное. Регулярный аудит находит конфликты.
- **Дрейф — главный операционный риск:** rules устаревают, если не обновлять вместе с кодом. Лечится квартальным аудитом и добавлением изменения rules в definition of done для крупных архитектурных изменений.
- **Vendor lock-in:** формат `.cursor/rules/` специфичен для Cursor. Skills как открытый стандарт частично решают эту проблему.
