# Whatte Observability

Минимальный observability stack для логов Whatte.

Статус:

- observability stack присутствует в репозитории
- compose лежит в `infra/monitoring/observability`
- стек operational / optional
- Grafana присутствует в конфиге, но не считается primary runtime requirement

Состав:

- Grafana
- Loki
- Promtail

Стек вынесен в отдельный `docker compose` и не меняет основной compose приложения.

## Что собирается

В первой версии собираются только docker json logs контейнеров:

- `human-engine-backend`
- `human-engine-postgres`

Promtail использует Docker service discovery для поиска нужных контейнеров, а сами логи читает из стандартных Docker json log files в `/var/lib/docker/containers/*/*-json.log`.

## Хранение на HDD

Данные хранятся на отдельном диске в:

- `/data/observability/loki`
- `/data/observability/grafana`
- `/data/observability/promtail`

## Подготовка каталогов

```bash
sudo mkdir -p /data/observability/loki
sudo mkdir -p /data/observability/grafana
sudo mkdir -p /data/observability/promtail
sudo chown -R 472:472 /data/observability/grafana
sudo chown -R 10001:10001 /data/observability/loki
```

Если Loki или Grafana пожалуется на права доступа, скорректируйте владельца каталогов после первого запуска по фактическому UID процесса внутри контейнера.

## Запуск

Compose-файл:

- [docker-compose.yml](/srv/human-engine/infra/monitoring/observability/docker-compose.yml)

Из директории observability:

```bash
cd /srv/human-engine/infra/monitoring/observability
docker compose up -d
```

Или одной командой из любого места:

```bash
docker compose -f /srv/human-engine/infra/monitoring/observability/docker-compose.yml up -d
```

## Открыть Grafana

- URL: `http://localhost:3001`
- login: `admin`
- password: `admin`

Datasource `Loki` создается автоматически через provisioning.

## Проверка

Проверить, что стек поднялся:

```bash
docker compose -f /srv/human-engine/infra/monitoring/observability/docker-compose.yml ps
```

Проверить, что Loki доступен:

```bash
curl http://localhost:3100/ready
```

Проверить, что Promtail жив:

```bash
docker logs human-engine-promtail --tail 20
```

Проверить, что Grafana жив:

```bash
curl http://localhost:3001/api/health
```

Проверить, что backend пишет логи:

```bash
docker logs human-engine-backend --tail 20
```

В Grafana:

1. Откройте `Explore`
2. Выберите datasource `Loki`
3. Выполните запрос:

```logql
{container="human-engine-backend"}
```

Для Postgres:

```logql
{container="human-engine-postgres"}
```

## Retention

Loki настроен как одиночный локальный инстанс с filesystem storage и retention `7 days` (`168h`).
