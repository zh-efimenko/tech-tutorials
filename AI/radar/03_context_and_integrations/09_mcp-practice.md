# Практика: разработка MCP-сервера на Python и TypeScript

## Выбор SDK

Anthropic поддерживает два основных SDK:
- `python-sdk` — с высокоуровневым API FastMCP
- `typescript-sdk` — с валидацией через Zod

Оба реализуют полную спецификацию протокола, отличаясь экосистемой библиотек и паттернами deployment.

| Критерий | Python | TypeScript |
|----------|--------|-----------|
| Экосистема | Data/ML: pandas, PyTorch | Web: npm, Playwright, Puppeteer |
| Типизация | Pydantic → автогенерация JSON Schema | Zod → валидация + JSON Schema |
| Boilerplate | Минимальный (10–15 строк) | Немного больше |
| Deployment | Data pipelines, ML-сервисы | Serverless (Vercel, Cloudflare Workers) |

**Основной критерий** — существующий стек команды и характер подключаемой системы.

---

## Проектирование контрактов данных

### Resources vs Tools

**Resource** — read-only snapshot состояния системы. Модель читает, но не меняет.

Типичные примеры:
- Последние N строк лог-файла
- Конфигурационный YAML проекта
- Схема базы данных в виде DDL
- Снимок метрик из мониторинга

Правила проектирования:
- URI-схема предсказуемая: `file://logs/system`, `config://project/settings`
- Данные стабильные или медленно меняющиеся
- Размер ограничен контекстным окном модели
- Если данные большие — параметризация: количество строк, временной диапазон

**Tool** — функция с побочными эффектами. Может писать в БД, отправлять HTTP-запрос, запускать процесс.

Типичные примеры:
- Создание тикета в Jira / GitHub Issues
- Отправка сообщения в Slack
- Выполнение SQL-запроса
- Публикация события в очередь Kafka

### Description как промпт для модели

Модель выбирает инструмент по полю `description`. Это не документация для людей.

Хорошее description включает:
1. Что инструмент делает (одно предложение)
2. Когда использовать
3. Когда **не** использовать (частая причина ошибочных вызовов)
4. Формат ввода
5. Формат результата

```
# Плохо:
Gets user data

# Хорошо:
Получает профиль пользователя корпоративного LDAP по email.
Используй, когда пользователь просит посмотреть данные сотрудника: должность,
отдел, руководитель. НЕ используй для клиентов CRM — для них есть get_crm_contact.
Вход: email сотрудника. Выход: JSON с полями name, department, title, manager_email.
```

### Гранулярность инструментов

Один универсальный `query_database` с параметром SQL-запроса создаёт риски:
- Модель может выполнить деструктивный запрос (UPDATE, DELETE, DROP)
- JSON Schema не описывает допустимые запросы
- Ошибки синтаксиса SQL всплывают только в рантайме

Несколько узких инструментов (`get_user_by_id`, `list_orders_by_date_range`) — безопаснее и предсказуемее.

**Практическое правило 2026:** 3–7 узких инструментов на сервер.

---

## Python: FastMCP сервер

### Инициализация проекта

```bash
uv init mcp-server-demo
cd mcp-server-demo
uv add "mcp[cli]"
```

Структура:
```
mcp-server-demo/
├── pyproject.toml
├── src/
│   └── server.py
└── README.md
```

### Базовый сервер

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo-server")

if __name__ == "__main__":
    mcp.run()
```

По умолчанию — stdio-транспорт. Читает JSON-RPC со stdin, пишет ответы в stdout.

### Resource: чтение лога

```python
from pathlib import Path
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo-server")
LOG_PATH = Path("/var/log/system.log")

@mcp.resource("file://logs/system/{lines}")
def read_system_log(lines: int = 100) -> str:
    """
    Возвращает последние N строк системного журнала. По умолчанию 100 строк.
    """
    if not LOG_PATH.exists():
        return "Log file not found"

    try:
        with LOG_PATH.open("r", encoding="utf-8") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except PermissionError:
        return "Permission denied reading log"
```

Ключевые решения:
- URI с параметром `{lines}` позволяет модели запрашивать нужный объём
- Обработка FileNotFoundError и PermissionError возвращает понятные сообщения вместо стек-трейса
- Типизация `lines: int` автоматически генерирует валидацию Schema

### Tool: запрос статуса сервиса

```python
import asyncio
import os
import httpx
from pydantic import BaseModel, Field
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo-server")

class ServiceStatus(BaseModel):
    name: str
    up: bool
    response_time_ms: float
    checked_at: str

@mcp.tool()
async def check_service_status(
    service_name: str = Field(description="Имя сервиса из реестра"),
    timeout_seconds: float = Field(default=5.0, description="Таймаут HTTP-запроса")
) -> ServiceStatus:
    """
    Проверяет доступность внутреннего сервиса через health-check endpoint.
    Используй, когда пользователь спрашивает, работает ли сервис или хочет диагностику.
    """
    base_url = os.environ["HEALTH_BASE_URL"]
    url = f"{base_url}/{service_name}/health"

    async with httpx.AsyncClient() as client:
        start = asyncio.get_event_loop().time()
        try:
            resp = await client.get(url, timeout=timeout_seconds)
            elapsed = (asyncio.get_event_loop().time() - start) * 1000
            return ServiceStatus(
                name=service_name,
                up=resp.status_code == 200,
                response_time_ms=elapsed,
                checked_at=resp.headers.get("Date", ""),
            )
        except httpx.TimeoutException:
            return ServiceStatus(
                name=service_name,
                up=False,
                response_time_ms=timeout_seconds * 1000,
                checked_at="",
            )
```

### Запуск

```bash
# Режим разработки (открывает MCP Inspector)
uv run mcp dev src/server.py

# Production
uv run src/server.py
```

---

## TypeScript: SDK сервер

### Инициализация проекта

```bash
mkdir mcp-server-demo && cd mcp-server-demo
npm init -y
npm install @modelcontextprotocol/sdk zod
npm install --save-dev typescript @types/node tsx
npx tsc --init
```

`tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "esModuleInterop": true,
    "strict": true,
    "outDir": "./build",
    "rootDir": "./src",
    "skipLibCheck": true
  }
}
```

### Базовый сервер

```typescript
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new McpServer({
  name: "demo-server",
  version: "0.1.0",
});

const transport = new StdioServerTransport();
await server.connect(transport);
```

### Resource: чтение лога

```typescript
import { readFile } from "node:fs/promises";

const LOG_PATH = "/var/log/system.log";

server.resource(
  "system-log",
  "file://logs/system",
  {
    name: "System Log",
    description: "Последние строки системного журнала",
    mimeType: "text/plain",
  },
  async (uri) => {
    try {
      const content = await readFile(LOG_PATH, "utf-8");
      const lines = content.split("\n");
      const tail = lines.slice(-100).join("\n");
      return {
        contents: [{ uri: uri.href, mimeType: "text/plain", text: tail }],
      };
    } catch (err) {
      return {
        contents: [{ uri: uri.href, mimeType: "text/plain", text: `Error reading log: ${err}` }],
      };
    }
  }
);
```

### Tool с валидацией через Zod

Zod-схема одновременно валидирует аргументы и генерирует JSON Schema для модели:

```typescript
import { z } from "zod";

const checkServiceInput = z.object({
  service_name: z.string().describe("Имя сервиса из реестра"),
  timeout_seconds: z.number().default(5).describe("Таймаут HTTP-запроса в секундах"),
});

server.tool(
  "check_service_status",
  "Проверяет доступность внутреннего сервиса. " +
  "Используй при вопросах о работоспособности или для диагностики. " +
  "Не используй для внешних публичных API.",
  checkServiceInput.shape,
  async (args) => {
    const { service_name, timeout_seconds } = args;
    const baseUrl = process.env.HEALTH_BASE_URL!;
    const url = `${baseUrl}/${service_name}/health`;

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout_seconds * 1000);
    const start = Date.now();

    try {
      const resp = await fetch(url, { signal: controller.signal });
      clearTimeout(timer);
      return {
        content: [{
          type: "text",
          text: JSON.stringify({
            name: service_name,
            up: resp.ok,
            response_time_ms: Date.now() - start,
            checked_at: new Date().toISOString(),
          }),
        }],
      };
    } catch (err) {
      clearTimeout(timer);
      return {
        content: [{ type: "text", text: JSON.stringify({ name: service_name, up: false, error: String(err) }) }],
        isError: true,
      };
    }
  }
);
```

`isError: true` сигналит хосту о неудаче — модель увидит это и решит что делать дальше.

### Сборка и запуск

```json
{
  "scripts": {
    "build": "tsc",
    "start": "node build/index.js",
    "dev": "tsx src/index.ts"
  }
}
```

---

## Интеграция и отладка

### MCP Inspector

Официальный инструмент отладки — браузерный интерфейс, подключается к серверу без участия LLM.

```bash
# Python-сервер
npx @modelcontextprotocol/inspector uv run src/server.py

# TypeScript-сервер
npx @modelcontextprotocol/inspector node build/index.js
```

Что показывает:
- Список всех зарегистрированных Tools, Resources, Prompts
- JSON Schema для каждого инструмента
- Форма для ручного вызова с просмотром ответа
- Лог JSON-RPC сообщений в реальном времени

Inspector ускоряет итерации разработки: не нужно запускать Claude Desktop, писать промпт и ждать.

### Подключение к Claude Desktop

Конфигурация в `claude_desktop_config.json`:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "demo": {
      "command": "uv",
      "args": [
        "--directory", "/Users/you/projects/mcp-server-demo",
        "run", "src/server.py"
      ]
    }
  }
}
```

Для TypeScript:
```json
{
  "mcpServers": {
    "demo": {
      "command": "node",
      "args": ["/Users/you/projects/mcp-server-demo/build/index.js"]
    }
  }
}
```

После изменения конфигурации требуется перезапуск Claude Desktop.

### Подключение к Warp

Конфигурация в `~/.warp/.mcp.json` — тот же формат что и для Claude Desktop.

### Логирование

Для stdio-транспорта все логи пишутся в **stderr** (stdout занят протоколом):

```python
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp-demo")
```

```typescript
console.error(JSON.stringify({
  level: "info",
  tool: "check_service_status",
  args,
  ts: new Date().toISOString(),
}));
```

Что логировать:
- Каждый вызов инструмента с аргументами
- Время выполнения операции
- Ошибки с полным контекстом (type, message, stack)
- Внешние вызовы (HTTP, SQL) с временем и кодом ответа

---

## Переход в production

### Ограничения stdio

- Жизненный цикл сервера привязан к хосту — при закрытии IDE сервер останавливается
- Один процесс обслуживает одного клиента — масштабирование невозможно
- Безопасность зависит от прав локального пользователя

Когда stdio достаточно: персональные сценарии, локальные файлы, прототипирование.

### HTTP + SSE

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("demo-server")

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

По умолчанию — порт 8000, путь `/mcp`.

### OAuth 2.1 для production

Типовая последовательность:
1. Client запрашивает доступ с PKCE-challenge
2. Пользователь авторизуется через браузер
3. Сервер авторизации выдаёт access token и refresh token
4. MCP-клиент добавляет `Authorization: Bearer <token>` при каждом запросе

На практике интегрируется с существующими OAuth-провайдерами компании (Auth0, Okta, Azure AD, Keycloak). Переписывать OAuth-слой не нужно — SDK предоставляет middleware.

### Rate limiting и защита

Обязательные меры для production:
- Rate limiting по access token или IP (Redis-счётчики)
- Ограничение размера входящих запросов (защита от DoS)
- Валидация всех аргументов на стороне сервера — никогда не доверять клиенту
- Audit log всех вызовов: user_id, tool, timestamp

### Deployment stack 2026

```
Docker → private registry → Kubernetes/serverless
→ Ingress с TLS-терминацией
→ OAuth-валидация через sidecar (Envoy)
→ Метрики через OpenTelemetry → Prometheus + Grafana
→ Логи через Loki или ELK
```

Отдельный паттерн — Cloudflare Workers: edge-функция с географической близостью к пользователю.

---

## Ключевые выводы

- Написать работающий MCP-сервер можно за 10–15 минут на любом из двух официальных SDK. Минимум boilerplate-кода, авто-генерация JSON Schema из аннотаций.
- Качество description и гранулярность инструментов критически влияют на способность LLM правильно их использовать. Description — промпт для модели, не документация для людей.
- Разделение на Resources (read-only данные) и Tools (активные действия) даёт предсказуемую архитектуру. Путаница между ними — частая причина некорректного поведения.
- MCP Inspector кардинально ускоряет отладку — итерации в разы быстрее, чем через цикл с Claude Desktop.
- Транспорт stdio для локальной разработки. Production требует HTTP+SSE, OAuth 2.1 с PKCE, rate limiting и audit log.
