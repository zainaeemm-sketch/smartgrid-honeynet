# Smart-grid honeynet – proof of concept

An IEC 60870-5-104 server whose values come from an AC power-flow simulation of the
**CIGRE medium-voltage benchmark** in **pandapower**. When a client (the "attacker")
sends a command to open a breaker, the network is re-simulated and the physical
consequences (breaker status, voltages, currents, power exchange) are reported back
over IEC 104.

## What the test does

1. Loads the CIGRE MV network (`with_der="all"`) and adds two feeder-head circuit
   breakers on the 20 kV side.
2. Starts an IEC 104 server (common address 1) exposing breaker positions, bus
   voltages, line P/Q/I, grid P/Q and frequency.
3. A client connects, reads all values (general interrogation), then sends a double
   command (C_DC_NA_1) to open the feeder-1 breaker.
4. The server re-solves the power flow and sends the new values spontaneously.

Expected result:

| Quantity | Before | After opening feeder-1 breaker |
|---|---|---|
| Feeder-1 breaker | ON (closed) | OFF (open) |
| Bus 5 voltage | 18.90 kV | 0 kV (de-energised) |
| Feeder-1 current | 94.7 A | 0 A |
| Feeder-2 current | 18.5 A | 18.5 A (unaffected) |
| Substation busbar voltage (bus 1) | 19.88 kV | 20.04 kV |
| Import from 110 kV grid | 43.44 MW | 40.48 MW |

## Run it

**Easiest (no installation):** click **Code → Codespaces → Create codespace on main**.
When the terminal appears, run:

```bash
python honeynet_poc_cigre_iec104.py
```

**On your own computer (Linux or Windows, Python 3.9–3.12):**

```bash
pip install -r requirements.txt
python honeynet_poc_cigre_iec104.py
```

The IEC 104 library `c104` does not provide macOS builds; on a Mac use Codespaces.

## IEC 104 address scheme (information object addresses)

| IOA range | Meaning | pandapower source |
|---|---|---|
| 10000 + switch index | switch position (M_DP_TB_1) | `net.switch.closed` |
| 11000 + switch index | switch command (C_DC_NA_1) | writes `net.switch.closed`, re-runs power flow |
| 20000 + bus index | bus voltage, kV (M_ME_NC_1) | `net.res_bus.vm_pu × vn_kv` |
| 30000 + 10·line + k | line P (k=0), Q (k=1), I (k=2) | `net.res_line` |
| 60000 / 60001 / 60002 | grid P, grid Q, frequency | `net.res_ext_grid` / 50 Hz |

## Status

Proof of concept only. Planned next: full point list, select-before-operate,
protection logic, recorded-frequency replay, load/PV profiles, and cost logging.

## Built with

- [pandapower](https://www.pandapower.org/) – power-flow simulation
- [c104](https://github.com/Fraunhofer-FIT-DIEN/iec104-python) (Fraunhofer FIT) – IEC 60870-5-104
- CIGRE TF C6.04.02, TB 575 – MV benchmark network

Author: Zain Naeem, University of Palermo
