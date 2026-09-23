# local-ai

Local models behind one API: Ollama runs the models, LiteLLM is an
OpenAI-compatible gateway with a single key and a response cache, and Vane
gives a search-grounded answer UI on top of SearXNG.

## What

- **Ollama** loads and serves open-weight models on the GPU machine.
- **LiteLLM** is what every client talks to. It speaks the OpenAI API, maps
  friendly model names (`default`, `floor`) to real backends, retries or falls
  back to another model on errors, and caches identical requests in Valkey.
- **Vane** (a slim Perplexica fork) is a chat UI that runs a web search
  through SearXNG and has the model answer from the results, with sources.

Automation tools, scripts and editors all point at LiteLLM with one key, and
I can move a model to another GPU box by editing one line in `config.yaml`.

## Why

- **One front door.** Ollama has no authentication. It stays LAN-bound and
  only LiteLLM, which checks the key, is used by clients.
- **Stable names.** Clients ask for `default`; what `default` means changes in
  `config.yaml`, not in every client.
- **Cache.** Automations often repeat the exact same prompt. In the test below
  the second identical request came back from the cache in 0.04 s instead of
  30 s. A side effect to remember: benchmarking through a caching gateway
  measures the cache. Turn `cache` off, or vary the prompt, when timing a
  model.
- **Search on your own box.** Vane uses the lab's SearXNG instead of a paid
  search API.

## Files

| File | Purpose |
|------|---------|
| `compose.yaml` | Ollama `0.34.3` (NVIDIA GPU block), LiteLLM `main-v1.83.14-stable`, Valkey cache, Vane pinned by digest |
| `config.yaml` | LiteLLM model list, cache settings, retries and fallback |
| `.env.example` | Bind address, LiteLLM key, SearXNG URL |

## Usage

```bash
cp .env.example .env && $EDITOR .env
docker compose up -d
docker exec ollama ollama pull qwen3.5:9b        # and any other model in config.yaml
docker exec ollama ollama pull llama3.2:1b

curl -s http://<BIND_IP>:4000/v1/chat/completions \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"default","messages":[{"role":"user","content":"hello"}]}'
```

Vane is on `http://<BIND_IP>:3300`. On first open it asks for a model
provider in its settings; give it LiteLLM as an OpenAI-compatible endpoint
(`http://<BIND_IP>:4000/v1` and the same key). I did not test that step in
the run below.

Tested on Docker on a machine without a GPU (GPU block and published ports
removed): all four containers started, Ollama, LiteLLM and the cache went
healthy, `llama3.2:1b` pulled, a chat request to model `floor` through LiteLLM
returned 200 in 30 s on CPU, the same request again returned in 0.04 s from
the cache, a request with a wrong key was refused (HTTP 400), and the Vane
UI answered 200. Not tested here: GPU inference, the 9B models, and a Vane
search end to end (it needs a provider configured in its UI).

## Integration

- **SearXNG**, Vane needs the JSON API. The `searxng` folder's `limiter.toml`
  must list the Vane host in `pass_ip`, or the limiter answers 429.
- **Traefik + Authelia**, if you publish Vane or LiteLLM on a hostname, put
  both behind SSO. LiteLLM's own key still applies.
- **Splitting hosts**, run only `ollama` on the GPU box (`docker compose up -d
  ollama`) and change every `api_base` in `config.yaml` to
  `http://<gpu-host>:11434`.
