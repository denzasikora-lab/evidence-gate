# Evidence Gate — руководство по настройке

## Окружение

Проект настроен для **GitHub Codespaces** с Docker-in-Docker через `.devcontainer/devcontainer.json`. Полный стек DataHub (GMS, OpenSearch, MySQL, Kafka и фронтенд) требует заметного объёма памяти. При запуске вне Codespaces нужны Docker с минимум 8 ГБ свободной RAM и CLI DataHub.

## Быстрый запуск

### 1. Проверьте окружение

```bash
docker --version
python --version
```

### 2. Запустите локальный экземпляр DataHub

Выполните в терминале Codespace:

```bash
datahub docker quickstart
```

Команда запускает GMS, OpenSearch, MySQL, Kafka и интерфейс DataHub. При первом запуске скачиваются образы объёмом в несколько ГБ; последующие запуски быстрее.

### 3. Перенаправленные порты и доступ к интерфейсу

Codespaces автоматически перенаправляет следующие порты. URL уникален для вашего codespace: смотрите вкладку **Ports** в VS Code или используйте `gh codespace ports forward <port>:<port> -c <your-codespace-name>` локально.

- **Порт 9002** — интерфейс DataHub: `http://localhost:9002`; логин `datahub`, пароль `datahub`.
- **Порт 8080** — REST API GMS DataHub: `http://localhost:8080`.
- **Порт 8000** — сервис FastAPI Evidence Gate: `http://localhost:8000`.

### 4. Загрузите образцы данных (`showcase-ecommerce`)

```bash
python scripts/load_showcase_ecommerce.py
```

Скрипт безопасно запускать повторно: для тех же URN он идемпотентен.

### 5. Установите зависимости и настройте `.env`

```bash
pip install -r requirements.txt
cp .env.example .env
```

Затем задайте в `.env` `DATAHUB_GMS_URL`, `DATAHUB_MCP_URL` и `GEMINI_API_KEY`. Для DataHub Cloud также укажите `DATAHUB_GMS_TOKEN`; для локального `datahub docker quickstart` он не нужен и остаётся пустым. Ключ [Google AI Studio](https://aistudio.google.com/apikey) нужен только для превращения уже вычисленных фактов решения в читаемый текст; он никогда не определяет, разрешить или заблокировать изменение.

### 6. Проверьте подключение к DataHub

```bash
python scripts/verify_mcp_connection.py
```

### 7. Запустите полное демо

```bash
python scripts/submit_change.py --fixture fixtures/net_revenue_rename.json
```

Откройте интерфейс DataHub на порту 9002 и найдите `order_details`, чтобы увидеть записанное обоснование решения.

## Остановка и очистка

### Остановить стек DataHub, сохранив данные

```bash
docker compose -f /home/vscode/.datahub/quickstart/docker-compose.yml -p datahub stop
```

Или остановите конкретные контейнеры:

```bash
docker stop datahub-frontend-quickstart-1 datahub-datahub-gms-quickstart-1 datahub-datahub-actions-quickstart-1 datahub-kafka-broker-1 datahub-opensearch-1 datahub-mysql-1
```

Данные остаются в томах Docker; следующая команда `datahub docker quickstart` поднимет их без повторной загрузки.

### Полный сброс

```bash
datahub docker nuke
```

Команда удаляет все данные DataHub, в том числе записанные решения. Используйте её, только чтобы начать с чистого состояния; затем повторите шаги 4 и 7.

### Освободить место на диске

Если `datahub docker quickstart` сообщает о нехватке места:

```bash
docker system df                 # посмотреть, что занимает место
docker system prune -af --volumes # запускать, только если не нужно сохранять данные остановленных контейнеров
```

Перед `--volumes` проверьте `docker ps`, чтобы не потерять нужные данные контейнера MySQL или другого хранилища.

### Остановить сам codespace

На `github.com/codespaces` или командой `gh codespace stop -c <your-codespace-name>`. Это приостанавливает оплату вычислений, сохраняя файловую систему и тома Docker.

## Устранение неполадок

Типичные проблемы подключения DataHub/MCP описаны в `docs/troubleshooting.md`.
