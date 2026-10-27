# VPS Hardware & Environment Analysis for Manara

> **Generated on**: 2026-10-27  
> **Target Machine**: Production VPS (`159.195.192.148`)  
> **Target Domain**: `manara.saudiosm.org` / `saudiosm.org`  
> **Primary Purpose**: Inform pipeline memory caps, container CPU limits, and deployment architecture for Phase 1 & Phase 2.

---

## 1. Quick Summary of Limits (For Claude & Pipelines)

| Resource | Total | Currently Used | Available for Manara | Safe Pipeline Cap |
| :--- | :--- | :--- | :--- | :--- |
| **vCPU** | 2 cores | ~0.1 - 0.7 load | 2 cores | **1.5 cores** (`cpus: 1.5`) |
| **Physical RAM** | **3.8 GiB** (4.01 GB) | ~1.5 GiB (incl. cache) | **~2.3 GiB** | **1.25 GiB – 1.5 GiB** (`mem_limit: 1536m`) |
| **Swap** | **2.0 GiB** | 493 MiB | 1.59 GiB | In emergency reserve |
| **Disk Space** | **125 GiB** (ext4) | 15 GiB (13%) | **106 GiB** | 20+ GiB (ample for `.pbf` & GeoJSON) |
| **Architecture** | `x86_64` | AMD EPYC-Genoa | AVX-512 available | Fast single-thread & vector perf |

---

## 2. Standard Baseline Command Outputs (`nproc; free -h; df -h`)

### `nproc`
```text
2
```

### `free -h`
```text
               total        used        free      shared  buff/cache   available
Mem:           3.8Gi       1.5Gi       548Mi       137Mi       2.2Gi       2.3Gi
Swap:          2.0Gi       492Mi       1.5Gi
```

### `df -h`
```text
Filesystem      Size  Used Avail Use% Mounted on
udev            1.9G     0  1.9G   0% /dev
tmpfs           392M  1.3M  391M   1% /run
/dev/vda4       125G   15G  106G  13% /
tmpfs           2.0G     0  2.0G   0% /dev/shm
tmpfs           5.0M     0  5.0M   0% /run/lock
tmpfs           2.0G  4.0K  2.0G   1% /tmp
/dev/vda3       944M  196M  683M  23% /boot
/dev/vda2       241M   512  241M   1% /boot/efi
```

---

## 3. CPU Specifications (`lscpu`)

* **Model**: AMD EPYC-Genoa Processor (Zen 4 architecture)
* **Sockets / Cores / Threads**: 2 sockets, 1 core/socket, 1 thread/core (2 vCPUs)
* **BogoMIPS**: 4493.24
* **Instruction Sets**: AVX, AVX2, AVX-512 (F, DQ, CD, BW, VL, BF16, VBMI, VBMI2, VNNI, VPOPCNTDQ)
* **Implication for Phase 2 Python Pipeline**:
  - AMD Genoa provides high single-core IPC and modern vector extensions.
  - GeoJSON spatial calculations (`shapely`, `pyproj`, `scipy`, `numpy`) and JSON serialization run efficiently.
  - Parallel multiprocessing should be capped at `workers = 2` (or `workers = 1` for background batch jobs to prevent starving web traffic).

---

## 4. Memory Breakdown (`/proc/meminfo`)

```text
MemTotal:        4013928 kB (~3.82 GiB)
MemFree:          543740 kB (~530 MiB)
MemAvailable:    2433564 kB (~2.32 GiB)
Buffers:          324376 kB (~316 MiB)
Cached:          1743792 kB (~1.66 GiB)
Active(anon):     944580 kB (~922 MiB - actual running app processes)
SwapTotal:       2097148 kB (2.0 GiB)
SwapFree:        1592644 kB (1.52 GiB)
```

* **Observation**: Linux is using ~1.66 GiB for disk buffer cache (`buff/cache`), which is instantly reclaimable. The actual active anonymous memory used by all running programs is under **1.0 GiB**.
* **Safety Margin**: Keeping a minimum of **800 MiB – 1.0 GiB** untouched for OS, Traefik edge proxy, and Rahma Health leaves **1.25 GiB – 1.5 GiB** comfortable headroom for the Manara stack.

---

## 5. Storage & Disk I/O

* **Disk Device**: Virtual block device `/dev/vda` (128 GB total).
* **Root Partition**: `/dev/vda4` formatted as `ext4`, sized at **125 GB**.
* **Used Space**: 15 GB (13%).
* **Free Space**: **106 GB available**.
* **Implication for Phase 2**:
  - The Saudi Arabia `.osm.pbf` extract is ~100–300 MB.
  - The generated GeoJSON files (`places_of_worship_sa.geojson`, `suggested_mosques_sa.geojson`, etc.) total ~25–30 MB.
  - PostgreSQL / PostGIS database will require < 500 MB for the points of worship dataset.
  - Disk storage is not a constraint.

---

## 6. Operating System & Host Environment

* **Distribution**: Debian GNU/Linux 13 (trixie) - Debian 13.7
* **Kernel**: `Linux 6.12.113+deb13-amd64 #1 SMP PREEMPT_DYNAMIC`
* **Docker Engine**: Installed and healthy
* **Control Plane**: **Coolify 4.5.0**

---

## 7. Existing Services & Co-Hosting Footprint

The VPS is co-hosted with **Coolify** and **Rahma Health** (`rahmahealth.net`). Here is the current container footprint:

```text
CONTAINER                                  MEM USAGE    MEM %    CPU %   FUNCTION
coolify                                    336 MiB      8.58%    ~5%     Coolify management web UI & daemon
coolify-proxy (Traefik v3.7)               133 MiB      3.40%    <1%     Edge reverse proxy (ports 80 & 443)
coolify-db (PostgreSQL 15)                  49 MiB      1.25%    <1%     Coolify internal state DB
coolify-redis                               14 MiB      0.36%    <1%     Coolify queue / cache
coolify-sentinel                            11 MiB      0.29%    <1%     Host monitoring agent
nn0yw94zrb6w7lbgpmzt3jko (Rahma Health)     43 MiB      1.09%    0%      Rahma Health Astro web app
umami-gmhfnb1lw5fbu517czoboqg9             159 MiB      4.05%    0%      Shared Umami analytics (v3.0.3)
postgresql-gmhfnb1lw5fbu517czoboqg9         14 MiB      0.36%    0%      PostgreSQL 16 for Umami
qri8jmjjfbuaiwyfwbunrjvn (Manara live)       3 MiB      0.09%    0%      Current static Nginx container
---------------------------------------------------------------------------------------------
TOTAL WORKLOAD FOOTPRINT                   ~762 MiB     ~19%
```

---

## 8. Critical Architectural Constraints (Must Read Before Deployment)

### ⚠️ Constraint 1: Ports 80 & 443 are Owned by Traefik (`coolify-proxy`)
* There is **no host Caddy service** on the server.
* Do not attempt to bind a host web server to port `80` or `443` directly—it will fail or cause downtime for `rahmahealth.net`.
* All incoming web traffic on domains (`manara.saudiosm.org`, `analytics.saudiosm.org`) must be routed through Traefik (via Coolify container labels or an internal reverse proxy port).

### ⚠️ Constraint 2: Memory Capping for Phase 2 Pipeline
When configuring the Python pipeline (or Docker Compose service for Phase 2):
```yaml
deploy:
  resources:
    limits:
      cpus: '1.5'
      memory: 1536M
    reservations:
      cpus: '0.2'
      memory: 512M
```
* Under no circumstances should the Python pipeline exceed **2.0 GiB**, as an OOM condition could trigger the Linux kernel OOM killer against PostgreSQL or Coolify.

### ⚠️ Constraint 3: Umami Instance Sharing vs. Separate Container
* An Umami 3.0.3 instance backed by PostgreSQL 16 is already active on the VPS (`analytics.rahmahealth.net`), using ~173 MiB total RAM.
* Umami natively supports multiple independent websites with distinct Tracking IDs.
* Option A can either:
  1. Add `manara.saudiosm.org` as a website on the existing Umami service and route `analytics.saudiosm.org` to it via Coolify (saving ~200 MiB RAM).
  2. Deploy a lightweight dedicated Umami container capped at `mem_limit: 256m`.
