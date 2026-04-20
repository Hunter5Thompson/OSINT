# NVIDIA DGX Spark — Vollständiges Referenzdokument

## Hardware

- **Modell:** NVIDIA DGX Spark (`NVIDIA_DGX_Spark`), Hostname: `spark-5631`
- **GPU:** NVIDIA GB10 (Grace-Blackwell), Compute Capability **sm_121**, 48 SMs
- **CPU:** 20 Kerne ARM big.LITTLE (aarch64 v9.2) — 10× Cortex-X925 @3.9GHz + 10× Cortex-A725 @2.8GHz (MediaTek, NICHT Grace Neoverse-V2)
- **RAM:** 128 GB LPDDR5X Unified Memory (121 GiB nutzbar, 15 GiB Swap)
- **Storage:** 3,7 TB NVMe, einzelne Root-Partition
- **Netzwerk:** Ethernet 1 Gbit/s (IP: 192.168.178.39, fest in FritzBox gepinnt) + WiFi 7 (192.168.178.35, Fallback)

## Software

- **OS:** DGX OS 7.5.0 / Ubuntu 24.04.4 LTS
- **Kernel:** 6.17.0-1014-nvidia
- **GPU-Driver:** 580.142, CUDA 13.0 (host), Forward Compat für CUDA 13.2 Container
- **Container:** Docker 29.2.1, nvidia-container-toolkit 1.19.0
- **NGC PyTorch:** 26.03 Container lokal gecached (`nvcr.io/nvidia/pytorch:26.03-py3`)

## Zugang

- **SSH:** `ssh spark` (Alias in `~/.ssh/config` auf deadpool-ultra)
- **User:** `albert` (UID 1000), Key-Auth passwortlos
- **sudo:** Verlangt Passwort (kein NOPASSWD)
- **IP:** 192.168.178.39 (Ethernet, fest zugewiesen in FritzBox 6660 Cable)

## Performance-Baseline

| Dtype | TFLOPS | RTX 5090 (Vergleich) |
|---|---|---|
| FP32 | 18,7 | ~110 |
| TF32 | 40,1 | ~220 |
| FP16 TC | 91,2 | ~210 |
| BF16 TC | 92,6 | ~210 |

## vLLM Server (aktuell aktiv)

- **Container:** `vllm-gemma4` (Docker, `--restart unless-stopped`)
- **Image:** `vllm-gemma4:latest` (custom build: vllm/vllm-openai:latest + transformers 5.5.3)
- **Modell:** `google/gemma-4-26B-A4B-it`, BF16, ~48.5 GiB im Speicher
- **API:** `http://192.168.178.39:8000/v1/` (OpenAI-kompatibel)
- **Max Context:** 32768 Tokens
- **Start:** `docker start vllm-gemma4` (nach Reboot)

## Architektur-Besonderheiten

- **Kein dediziertes VRAM** — `nvidia-smi --query-gpu=memory.total` = `[N/A]`. Über System-RAM rechnen (`free -h`), nicht nvidia-smi
- `torch.cuda.get_device_properties(0).total_memory` meldet korrekt 121,7 GiB
- `.cpu()` / `.cuda()` sind effektiv No-Ops (Unified Memory, kein H2D/D2H Transfer-Cost)
- Idle-Power: ~3,5 W bei 33°C

## Rolle im Setup

Ergänzt die RTX 5090 auf deadpool-ultra. **Arbeitsteilung:**
- Große Modelle (>32 GB, Long-Context) → Spark
- Training, Feintuning, Roh-TFLOPS → RTX 5090

## CLI-Tool

`gemma` Befehl auf deadpool-ultra — CLI-Chat mit Streaming gegen den Spark vLLM-Server (`~/bin/gemma`).

## Offene Punkte

- Hostname noch auf Werks-Default `spark-5631`
- sudo NOPASSWD für power-ops nicht konfiguriert
- Wake-on-LAN nicht eingerichtet
- Tailscale bewusst nicht installiert
