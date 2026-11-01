# Evidence Gate — устранение неполадок

## Частые проблемы и решения

### 1. Не запущен Docker daemon

Если `docker --version` или `docker ps` завершается ошибкой в Codespaces:

- Убедитесь, что devcontainer собран с функцией `ghcr.io/devcontainers/features/docker-in-docker:2`.
- Пересоберите devcontainer: откройте палитру команд (`Ctrl+Shift+P` / `Cmd+Shift+P`) и выберите `Codespaces: Rebuild Container`.

### 2. DataHub Quickstart завершается ошибкой или истекает время ожидания

- Проверьте выделенную память: бесплатный тариф Codespaces предоставляет 8 ГБ RAM, чего достаточно для `datahub docker quickstart`.
- Выполните `docker ps` и убедитесь, что контейнеры `datahub-gms`, `datahub-frontend-react`, `opensearch` и `mysql` работоспособны.

### 3. Порт не перенаправлен или интерфейс недоступен

- Проверьте вкладку **Ports** в VS Code / Codespaces.
- Убедитесь, что порт 9002 есть в списке, перенаправлен и имеет подходящую видимость Public/Private.

### 4. Не загружается `datahub datapack load showcase-ecommerce`

- Проверьте, что `DATAHUB_GMS_URL` указывает на `http://localhost:8080`.
- Проверьте состояние GMS: `curl http://localhost:8080/health`.
