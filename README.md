# F1 Grid

Mini lab: a Formula 1 championship board on **Docker** and **Kubernetes**, with a **pit-wall brief** (LLM or template fallback) and a **Redis** cache.

The API reads standings, the season calendar and race results from the [Jolpica F1 API](https://api.jolpi.ca/). It then builds a championship model: remaining races, points still available, who is mathematically alive, recent form, a Monte Carlo **title forecast** for every driver and constructor, and an analyst you can ask. Drivers and constructors are separate pages.

## Run with Docker

```bash
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080) (drivers) or [http://localhost:8080/constructors](http://localhost:8080/constructors)

- JSON standings: `/api/standings`
- Championship model: `/api/analysis`
- Title forecast: `/api/forecast`
- Refresh: `/api/refresh` (checks Jolpica; `?force=true` rebuilds cache)
- Ask: `POST /api/ask` `{"question":"Antonelli title odds?"}`
- Health: `/health` (process up)
- Ready: `/ready` (Redis reachable + standings available)

The app polls Jolpica itself: every 30 minutes normally, every 10 minutes on race weekend (next GP ±1 day). If round or field points change, Redis keys for standings, forecast and brief are dropped and rebuilt. On Kubernetes a CronJob hits `/api/refresh` every 20 minutes as a backup.

Optional LLM (copy `.env.example` to `.env`):

```bash
OPENAI_API_KEY=sk-...
docker compose up --build
```

The badge on the model card shows `llm` or `model`.

## Run on Kubernetes

Needs a local cluster (Docker Desktop Kubernetes, kind, or minikube). Load the local app image first.

```bash
docker build -t f1-grid:local .
# kind: kind load docker-image f1-grid:local
# minikube: minikube image load f1-grid:local

kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
kubectl apply -f k8s/cronjob.yaml

kubectl -n f1-grid get pods,svc
```

Then open [http://localhost:30080](http://localhost:30080) (NodePort).

LLM key (optional):

```bash
kubectl -n f1-grid create secret generic f1-grid-secrets --from-literal=OPENAI_API_KEY=sk-...
kubectl -n f1-grid rollout restart deployment/f1-grid
```

Change season without rebuilding:

```bash
kubectl -n f1-grid set env configmap/f1-grid-config F1_SEASON=2025
kubectl -n f1-grid rollout restart deployment/f1-grid
```

## What to look at in an interview

| Piece | Why it is there |
| --- | --- |
| Championship model | remaining races, sprint weekends, who is out, pts needed to clinch |
| Title forecast | Monte Carlo remaining season for every driver and constructor |
| Constructors page | `/constructors` — same model for the teams' cup |
| Form sparklines | last 5 GPs from official results |
| Ask the analyst | `/api/ask` answers from the model; LLM only rewrites the same facts |
| Redis + `REDIS_URL` | cache shared across replicas |
| `/health` vs `/ready` | process up vs Redis + data can be served |
| `k8s/redis.yaml` | second Deployment/Service in the same namespace |
| optional Secret | API key is not baked into the image |
| fallback JSON | page still answers if the upstream F1 API fails |
| Auto-refresh | in-process poller + `/api/refresh` + k8s CronJob after each race |
| GitHub Actions | image build + kubeconform |

## Local Python (optional)

Needs Redis only if `REDIS_URL` is set. Without it, cache stays in memory.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Data source: [Jolpica Ergast](https://github.com/jolpica/jolpica-f1). Not affiliated with Formula 1.
