# F1 Grid

Mini lab: a Formula 1 championship board packaged with **Docker** and deployed to **Kubernetes**.

The app is a small FastAPI service. It reads current driver standings and the next race from the [Jolpica F1 API](https://api.jolpi.ca/) (Ergast-compatible). If the API is down, it serves a snapshot baked into the image.

Built as a portfolio piece for a junior AI / Kubernetes role: containers, probes, ConfigMap, CI.

## Run with Docker

```bash
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080)

JSON: [http://localhost:8080/api/standings](http://localhost:8080/api/standings)

Health: `/health` · Ready: `/ready`

## Run on Kubernetes

Needs a local cluster (Docker Desktop Kubernetes, kind, or minikube). The image is local, so load it first.

```bash
docker build -t f1-grid:local .
# kind: kind load docker-image f1-grid:local
# minikube: minikube image load f1-grid:local

kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

kubectl -n f1-grid get pods,svc
```

Then open [http://localhost:30080](http://localhost:30080) (NodePort).

Change season without rebuilding:

```bash
kubectl -n f1-grid set env configmap/f1-grid-config F1_SEASON=2025
kubectl -n f1-grid rollout restart deployment/f1-grid
```

## What to look at in an interview

| Piece | Why it is there |
| --- | --- |
| `Dockerfile` | slim Python image, non-root user |
| `docker-compose.yml` | one-command local run + container healthcheck |
| `k8s/deployment.yaml` | 2 replicas, CPU/memory limits, liveness vs readiness |
| `k8s/configmap.yaml` | season and cache TTL without baking them into the image |
| `/health` vs `/ready` | process is up vs standings can actually be served |
| fallback JSON | platform still answers if the upstream F1 API fails |
| `.github/workflows/ci.yml` | image build + kubeconform on every push |

## Local Python (optional)

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Data source: [Jolpica Ergast](https://github.com/jolpica/jolpica-f1). Not affiliated with Formula 1.
