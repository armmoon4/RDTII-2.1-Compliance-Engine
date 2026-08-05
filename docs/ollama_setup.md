# Ollama Setup Guide — RDTII 2.1 Compliance Engine

## Table of Contents

1. [Overview](#overview)
2. [Installation](#installation)
3. [Pulling a Model](#pulling-a-model)
4. [Windows + Docker: The Complete Guide](#windows--docker-the-complete-guide)
5. [Verification Checklist](#verification-checklist)
6. [Troubleshooting Matrix](#troubleshooting-matrix)
7. [Configuration Reference](#configuration-reference)
8. [Performance Tuning](#performance-tuning)

---

## Overview

Ollama is a local inference server for open-weight large language models. The RDTII engine uses it as a zero-cost, offline-capable LLM backend for its multi-agent adversarial analysis pipeline (Prosecution → Defense → Arbiter).

**System requirements:**

- **RAM:** 8 GB minimum (4 GB for the OS, 4 GB for the model)
- **Disk:** 5 GB free for the recommended model (`llama3.1`)
- **OS:** Windows 10/11, macOS 12+, or Linux (x86_64)

---

## Installation

### Windows

1. Download the installer from [ollama.com/download/OllamaSetup.exe](https://ollama.com/download/OllamaSetup.exe)
2. Run the installer — administrative privileges are required
3. Ollama registers itself as a **Windows Service** named `ollama` and starts automatically
4. Open a new PowerShell terminal and verify:

```powershell
ollama --version
Get-Service ollama
```

The service status should show `Running`. If it shows `Stopped`, run:

```powershell
Start-Service ollama
```

### macOS

```bash
brew install ollama
ollama serve
```

### Linux

```bash
curl -fsSL https://ollama.com/install.sh | sh
sudo systemctl start ollama
```

---

## Pulling a Model

```bash
ollama pull llama3.1
```

Verify:

```bash
ollama run llama3.1 "What is digital trade regulation? Reply in one sentence."
```

If you see a coherent response, Ollama is working.

**Model recommendations by available RAM:**

| RAM | Model | Size | Quality |
|---|---|---|---|
| 4 GB | `llama3.2:3b` | 2.0 GB | Adequate for structured output |
| 8 GB | `llama3.1` | 4.7 GB | Recommended — best balance |
| 12 GB | `gemma2:9b` | 5.5 GB | Strong JSON compliance |

---

## Windows + Docker: The Complete Guide

This section covers every possible issue that can prevent the RDTII worker container from reaching Ollama on your Windows host. Follow these steps **in order**.

---

### Step 1 — Verify Ollama is Running and Reachable

Before involving Docker, confirm Ollama is working on the host itself.

```powershell
# 1. Check the service
Get-Service ollama

# 2. Test the API directly
curl.exe http://localhost:11434/api/tags

# Expected output should be JSON like: {"models": [...]}
# If curl hangs or returns "Connection refused", Ollama is not listening.
```

**If this fails:**

- Open **Services** (`services.msc`), find `ollama`, ensure it is `Running`
- If it is `Stopped`, right-click → **Start**
- If it fails to start, check the Windows Event Viewer (`eventvwr.msc`) → Windows Logs → Application for Ollama crash details

---

### Step 2 — Configure Ollama to Listen on All Interfaces

Ollama's default binding is `127.0.0.1:11434` (localhost only). Docker containers connect from a different IP (`172.x.y.z`), so the connection is refused unless Ollama listens on `0.0.0.0:11434` (all interfaces).

#### Method A: System Environment Variable (Persistent)

```powershell
# Open an elevated PowerShell (Run as Administrator)

# Set the environment variable at the Machine level
[System.Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0", "Machine")

# Restart the Ollama service to pick up the new variable
Restart-Service ollama
```

#### Method B: Manual Service Configuration (Alternative)

```powershell
# Open Services
services.msc

# Find "Ollama" → Right-click → Properties
# The "Path to executable" field shows the command line.
# Ollama by default reads OLLAMA_HOST from environment variables.
# After setting via Method A and restarting, verify:

Get-Service ollama
```

#### Verify the Binding

```powershell
netstat -an | Select-String "11434"
```

You should see **two** lines:

```
TCP    0.0.0.0:11434          0.0.0.0:0              LISTENING
TCP    [::]:11434              [::]:0                 LISTENING
```

If you see only `127.0.0.1:11434`, the `OLLAMA_HOST` variable was not picked up. Restart the service again or reboot.

```powershell
# Alternative check — test from an external IP perspective
Test-NetConnection -ComputerName 127.0.0.1 -Port 11434
# Should show "TcpTestSucceeded: True"
```

---

### Step 3 — Understand the Windows + Docker Networking Model

Docker Desktop on Windows runs containers inside a lightweight Hyper-V or WSL2 VM. This means:

- `localhost` inside a container **does not** reach your Windows host
- `host.docker.internal` is a special DNS name that Docker Desktop injects to resolve to the host
- The `worker` container connects to your host via `http://host.docker.internal:11434`

#### Test host.docker.internal Resolution

```powershell
# From PowerShell (host side), check what host.docker.internal resolves to:
# It should resolve to an IP in the 172.x.x.x range.
# You don't need to do anything with this — Docker Desktop manages it automatically.
```

#### From inside the container:

```bash
docker compose exec worker curl -s http://host.docker.internal:11434/api/tags
```

**Expected output:**

```json
{"models":[{"name":"llama3.1:latest","modified_at":"...","size":...}]}
```

**If this fails with `Could not resolve host`:**

Add an explicit mapping in your `docker-compose.yml`:

```yaml
services:
  worker:
    # ... existing config ...
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

Then restart:

```bash
docker compose down
docker compose up -d
```

**If this fails with `Connection refused`:**

Ollama is not listening on `0.0.0.0`. Return to [Step 2](#step-2--configure-ollama-to-listen-on-all-interfaces).

---

### Step 4 — Set the Correct URL in `.env`

Edit your `.env` file:

```ini
# Correct for Windows + Docker Desktop:
OLLAMA_BASE_URL=http://host.docker.internal:11434

# Wrong (will fail):
# OLLAMA_BASE_URL=http://localhost:11434
# OLLAMA_BASE_URL=http://127.0.0.1:11434
```

Then restart the stack:

```bash
docker compose down
docker compose up -d
```

---

### Step 5 — Verify End-to-End

```bash
# 1. Check the health endpoint
curl http://localhost:8000/health

# Look for the "ollama" field:
# {
#   "ollama": "connected",
#   "ai_provider": "ollama",
#   ...
# }

# If it shows "ollama": "unavailable", the worker cannot reach Ollama.
```

---

### Complete Step-by-Step Quick Reference

```powershell
# ===== HOST SIDE (PowerShell as Administrator) =====

# 1. Verify Ollama is installed
ollama --version

# 2. Pull a model
ollama pull llama3.1

# 3. Set Ollama to listen on all interfaces
[System.Environment]::SetEnvironmentVariable("OLLAMA_HOST", "0.0.0.0", "Machine")

# 4. Restart the service
Restart-Service ollama

# 5. Confirm binding
netstat -an | Select-String "11434"
# Expected: 0.0.0.0:11434 LISTENING (NOT 127.0.0.1)

# 6. Test API from host
curl.exe http://localhost:11434/api/tags
# Expected: JSON with model list
```

```bash
# ===== DOCKER SIDE (Git Bash or WSL) =====

# 7. Ensure .env has the right URL
# OLLAMA_BASE_URL=http://host.docker.internal:11434

# 8. Restart Docker stack
docker compose down
docker compose up -d

# 9. Test connectivity from inside the container
docker compose exec worker curl -s http://host.docker.internal:11434/api/tags

# 10. Verify via health endpoint
curl http://localhost:8000/health
```

---

### Windows Firewall Notes

If connectivity fails after following all steps, the Windows Firewall may be blocking the Docker VM from reaching port 11434 on the host.

```powershell
# Check if there are any blocking rules
netsh advfirewall firewall show rule name=all | Select-String "11434"

# Add an inbound rule to allow traffic (if needed):
New-NetFirewallRule -DisplayName "Ollama Docker" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 11434 `
  -Action Allow
```

---

### WSL2 Considerations

Docker Desktop on current Windows versions uses WSL2 as the backend. Ollama itself runs as a **Windows native process** (not inside WSL2), which means:

- `host.docker.internal` resolves to the Windows host from the WSL2 VM
- The WSL2 VM is the one running Docker containers
- Communication path: **Container → WSL2 VM → host.docker.internal → Windows Host → Ollama**

This adds one extra network hop compared to Linux native Docker. In practice, latency is negligible (~1ms).

**If you prefer to run Ollama inside WSL2 instead of Windows:**

```bash
# Inside WSL2 terminal:
curl -fsSL https://ollama.com/install.sh | sh
ollama serve

# The URL becomes (WSL2's IP changes on reboot — use hostname):
OLLAMA_BASE_URL=http://$(hostname).local:11434

# Or simpler — add to .env:
# Since the worker container and WSL2 are on the same Docker network:
OLLAMA_BASE_URL=http://host.docker.internal:11434
# (Docker Desktop routes host.docker.internal to the Windows host,
#  which then routes to WSL2 where Ollama is running)
```

---

## Verification Checklist

Use this checklist after every configuration change:

| # | Check | Command | Expected |
|---|---|---|---|
| 1 | Ollama service is running | `Get-Service ollama` | `Running` |
| 2 | Ollama binds to `0.0.0.0` | `netstat -an \| findstr 11434` | `0.0.0.0:11434 LISTENING` |
| 3 | Model is pulled | `ollama list` | `llama3.1` (or your model) |
| 4 | Host can reach Ollama | `curl.exe http://localhost:11434/api/tags` | JSON with model list |
| 5 | `.env` has Docker URL | `Select-String "OLLAMA_BASE_URL" .env` | `http://host.docker.internal:11434` |
| 6 | Container can resolve host | `docker compose exec worker ping host.docker.internal` | Replies received |
| 7 | Container can reach Ollama | `docker compose exec worker curl -s http://host.docker.internal:11434/api/tags` | JSON with model list |
| 8 | Health endpoint reports OK | `curl http://localhost:8000/health` | `"ollama": "connected"` |

---

## Troubleshooting Matrix

### Symptoms and Root Causes

| Symptom | Likely Cause | Fix |
|---|---|---|
| `curl.exe http://localhost:11434/...` returns `Connection refused` | Ollama service not running | `Start-Service ollama` |
| `netstat` shows `127.0.0.1:11434` not `0.0.0.0:11434` | `OLLAMA_HOST` not set or not picked up | Set env var + `Restart-Service ollama` |
| `docker compose exec worker curl ...` returns `Could not resolve host` | Docker Desktop not injecting `host.docker.internal` | Add `extra_hosts` in docker-compose.yml |
| `docker compose exec worker curl ...` returns `Connection refused` | Ollama still bound to `127.0.0.1` after setting `OLLAMA_HOST` | Restart Windows or verify env var propagation |
| `curl http://localhost:8000/health` shows `ollama: "unavailable"` | Container cannot reach Ollama | Run verification checklist from #4 |
| Worker logs: `Ollama call failed: timeout` | Model too large for RAM or first-cold inference | Use smaller model or run warm-up |
| Worker logs: `Ollama call failed: empty response` | Model returned empty string | Try `qwen2.5:7b` or `gemma2:9b` (better JSON) |
| The health endpoint is not reachable at all | Docker containers are down | `docker compose ps` — if empty, run `docker compose up -d` |

### Diagnostic Commands

```powershell
# === Windows Host Diagnostics ===

# Is Ollama installed?
ollama --version

# Is the service running?
Get-Service ollama

# What port is Ollama listening on?
netstat -an | Select-String "11434"

# Test API directly
curl.exe -s http://localhost:11434/api/tags

# List pulled models
ollama list

# Test model inference
ollama run llama3.1 "Hello in one word"
```

```bash
# === Docker Container Diagnostics ===

# Are containers running?
docker compose ps

# Check worker logs in real time
docker compose logs -f worker

# Test DNS resolution from container
docker compose exec worker ping host.docker.internal

# Test HTTP connectivity from container
docker compose exec worker curl -s http://host.docker.internal:11434/api/tags

# Check if curl is installed in the container
docker compose exec worker which curl

# If curl is missing, install it:
docker compose exec worker apt-get update && docker compose exec worker apt-get install -y curl
```

---

## Configuration Reference

### `.env` Settings

| Variable | Value for Windows + Docker | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `ollama` or `auto` | Forces Ollama or auto-selects |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Must be the Docker hostname |
| `OLLAMA_MODEL` | `llama3.1` | Must match a pulled model name |

### How Provider Resolution Works

```
LLM_PROVIDER=ollama
  └── call_llm() → _call_ollama() → ChatOllama(base_url=OLLAMA_BASE_URL)

LLM_PROVIDER=auto
  ├── Grok (if XAI_API_KEY is set and returns non-empty)
  ├── DeepSeek (if DEEPSEEK_API_KEY is set and returns non-empty)
  ├── OpenAI (if OPENAI_API_KEY is set and returns non-empty)
  ├── Gemini (if GOOGLE_API_KEY is set and returns non-empty)
  └── Ollama (last resort — always tried if all cloud providers fail)
```

---

## Performance Tuning

### Keep the Model Warm

The first inference after Ollama starts is slow (model loads into memory). Run a warm-up before running the pipeline:

```powershell
ollama run llama3.1 "warm up"
```

### Reduce Timeout Risk

In the `.env` file, ensure the download timeout is generous enough:

```ini
DOWNLOAD_TIMEOUT_SECONDS=60
```

### Use a Smaller Model for Testing

```powershell
ollama pull llama3.2:3b
```

Then set `OLLAMA_MODEL=llama3.2:3b` in `.env` for faster iterations during development.

---

## Reference Links

- [Ollama Official Site](https://ollama.com)
- [Ollama GitHub](https://github.com/ollama/ollama)
- [Ollama Model Library](https://ollama.com/library)
- [Docker Desktop Windows Networking](https://docs.docker.com/desktop/networking/)
- [Ollama FAQ](https://github.com/ollama/ollama/blob/main/docs/faq.md)
