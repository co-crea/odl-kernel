# ODL Kernel

<p align="center">
  <strong>The Physics Engine for AI Agents.</strong><br>
  Deterministic Foundation for Probabilistic Systems.
</p>

<p align="center">
  <a href="#license--commercial-terms"><img src="https://img.shields.io/badge/License-BSL_1.1-orange.svg" alt="License"></a>
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/Coverage-100%25-green.svg" alt="Coverage">
  <img src="https://img.shields.io/badge/Determinism-UUID_v5-blueviolet.svg" alt="Determinism">
</p>

---

**The Deterministic Execution Engine for Organizational Definition Language (ODL).**

`odl-kernel` is the reference implementation of the ODL "Physics." It is a stateless, pure-functional execution engine designed to manage the lifecycle of autonomous AI agents and human-AI collaboration.

Unlike traditional workflow engines, the Kernel acts as a rigorous state machine that derives the next organizational state and necessary side effects (Commands) based on a provided `JobSnapshot` and `KernelEvent`.

## ⚛️ Core Principles

* **Functional Core:** The Kernel is side-effect-free. It does not access databases or external APIs directly; it only calculates the transition.
* **Deterministic Identity:** Every node is assigned a mathematically derived UUID v5 based on its structural path. This ensures that process IDs remain consistent across restarts, replays, and forks.
* **Deep Analyze:** The engine performs fixed-point iteration to advance states until a stable equilibrium is reached, allowing the host to observe only meaningful state changes.



## Usage

The integration follows a strict **"Load -> Analyze -> Apply"** pattern.

```python
import odl_kernel
from odl_kernel.types import JobSnapshot, KernelEvent

# 1. Prepare Input (Stateless)
snapshot = JobSnapshot(job=job_data, nodes=node_map)
event = KernelEvent(type="TICK", occurred_at=datetime.now())

# 2. Analyze (Pure Physics)
# The Kernel calculates the next state and required commands.
result = odl_kernel.analyze(snapshot, event)

# 3. Apply Output (Side Effects)
# The Host runtime persists updated_nodes and executes result.commands.
my_db.save(result.updated_nodes)
```

> 📖 **Deep Dive: The Physics of Execution**
>
> The code above is just the entry point. The Kernel is a stateless, pure-functional "Physics Engine" designed to run inside your application.
>
> To understand the architecture (**Functional Core / Imperative Shell**) and how to implement the **Host Runtime** (Database persistence, LLM API connections, and the Event Loop), please read the full implementation guide:
>
> **[USAGE.md: The Host Implementation Guide](./USAGE.md)**

## 🏗 Relationship with `odl-lang`

This repository provides the execution environment. To define the organizational structures and compile them into an executable format, use the **[odl-lang](https://github.com/co-crea/odl-lang)** library.

## 🌹 Dedication

**Dedicated to the memory of Prof. Kazuhisa Seta, and to all researchers who continue to push the boundaries of Knowledge Engineering in his lineage.**

## ⚖️ License & Commercial Terms

Copyright (c) 2026 Centillion System, Inc. All rights reserved.

* **Licensor:** Centillion System, Inc. (https://centsys.jp/)
* **Contact:** odl@centsys.jp

This software is licensed under the **Business Source License 1.1 (BSL 1.1)**.

### Additional Use Grant
You are authorized to use this software in a production environment under the following conditions:
1. **Managed Service Restriction:** You may not use this software to provide a competing "Managed ODL Service" to third parties.
2. **Revenue Limit:** Use is free for individuals, academic institutions, and organizations with annual gross revenue less than **$10,000,000 USD**.
3. **Transition to OSS:** This software will convert to **Apache License 2.0** exactly two years after the release date of each version.

Organizations exceeding the revenue limit or wishing to provide managed services must obtain a commercial license from Centillion System, Inc.

---
*The deterministic ID generation logic in this Kernel uses a proprietary signature for provenance tracking and identity verification.*