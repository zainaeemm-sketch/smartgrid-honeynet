"""
Honeynet proof of concept: IEC 60870-5-104 server backed by pandapower (CIGRE MV).

* Network: pandapower CIGRE MV benchmark (with_der="all") plus two feeder-head
  circuit breakers on the 20 kV side (switch indices 8 and 9).
* A client (the "attacker") sends a double command (C_DC_NA_1) to open the
  feeder-1 breaker; the server re-solves the AC power flow and reports the new
  breaker position (M_DP_TB_1) and measurements (M_ME_NC_1) spontaneously.

IOA scheme: 10000+switch status, 11000+switch command, 20000+bus voltage (kV),
30000+10*line+k line P/Q/I (k=0,1,2), 60000/60001/60002 grid P, Q, frequency.

Requirements:  pip install pandapower c104
Run:           python honeynet_poc_cigre_iec104.py
"""
import time, math, threading, warnings, logging, copy
warnings.filterwarnings("ignore"); logging.disable(logging.WARNING)
import c104, pandapower as pp, pandapower.networks as pn

net = pn.create_cigre_network_mv(with_der="all")
# feeder-head circuit breakers on the MV side (not in the original model)
for bus, line in ((1, 0), (12, 10)):
    pp.create_switch(net, bus, line, et="l", type="CB", closed=True, name=f"CB feeder bus{bus}")
lock = threading.Lock()
CA = 1
def ioa_sw(i): return 10000 + i
def ioa_cmd(i): return 11000 + i
def ioa_v(b): return 20000 + b
def ioa_line(l, k): return 30000 + 10 * l + k   # k: 0 P MW, 1 Q Mvar, 2 I A
IOA_PGRID, IOA_QGRID, IOA_F = 60000, 60001, 60002

server = c104.Server(ip="127.0.0.1", port=2404)
st = server.add_station(common_address=CA)
pts = {}
def solve_and_publish(cause):
    try:
        pp.runpp(net, numba=False, max_iteration=30); ok = True
    except Exception:
        ok = False
    for i, row in net.switch.iterrows():
        pts[ioa_sw(i)].value = c104.Double.ON if row.closed else c104.Double.OFF
    for b in net.bus.index:
        vm = net.res_bus.vm_pu[b] if ok else float("nan")
        pts[ioa_v(b)].value = 0.0 if (not ok or math.isnan(vm)) else float(vm * net.bus.vn_kv[b])
    for l in net.line.index:
        r = net.res_line.loc[l]
        for k, v in enumerate((r.p_from_mw, r.q_from_mvar, r.i_ka * 1000)):
            pts[ioa_line(l, k)].value = 0.0 if (not ok or math.isnan(v)) else float(v)
    pts[IOA_PGRID].value = float(net.res_ext_grid.p_mw.sum())
    pts[IOA_QGRID].value = float(net.res_ext_grid.q_mvar.sum())
    pts[IOA_F].value = 50.0
    if cause is not None:
        for p in pts.values():
            if p.type != c104.Type.C_DC_NA_1:
                p.transmit(cause=cause)
    return ok

def on_cmd(point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
    idx = point.io_address - 11000
    with lock:
        net.switch.at[idx, "closed"] = (point.value == c104.Double.ON)
        solve_and_publish(c104.Cot.SPONTANEOUS)
    return c104.ResponseState.SUCCESS

for i in net.switch.index:
    pts[ioa_sw(i)] = st.add_point(io_address=ioa_sw(i), type=c104.Type.M_DP_TB_1)
    c = st.add_point(io_address=ioa_cmd(i), type=c104.Type.C_DC_NA_1)
    c.on_receive(callable=on_cmd)
for b in net.bus.index:
    pts[ioa_v(b)] = st.add_point(io_address=ioa_v(b), type=c104.Type.M_ME_NC_1)
for l in net.line.index:
    for k in range(3):
        pts[ioa_line(l, k)] = st.add_point(io_address=ioa_line(l, k), type=c104.Type.M_ME_NC_1)
for a in (IOA_PGRID, IOA_QGRID, IOA_F):
    pts[a] = st.add_point(io_address=a, type=c104.Type.M_ME_NC_1)
t0 = time.perf_counter(); solve_and_publish(None); print(f"initial AC power flow {1e3*(time.perf_counter()-t0):.0f} ms")
server.start()

# ---------------- attacker-side client ----------------
client = c104.Client()
conn = client.add_connection(ip="127.0.0.1", port=2404, init=c104.Init.ALL)
cst = conn.add_station(common_address=CA)
seen = {}
def mon(point: c104.Point, previous_info: c104.Information, message: c104.IncomingMessage) -> c104.ResponseState:
    seen[point.io_address] = point.value
    return c104.ResponseState.SUCCESS
watch = [ioa_sw(8), ioa_v(1), ioa_v(5), ioa_v(13), ioa_line(0, 2), ioa_line(10, 2), IOA_PGRID, IOA_F]
for a in watch:
    t = c104.Type.M_DP_TB_1 if a < 11000 else c104.Type.M_ME_NC_1
    cst.add_point(io_address=a, type=t).on_receive(callable=mon)
cmd = cst.add_point(io_address=ioa_cmd(8), type=c104.Type.C_DC_NA_1)  # switch 8 = CB feeder bus1
client.start()
for _ in range(300):                      # wait up to 30 s for the connection
    if conn.is_connected: break
    time.sleep(0.1)
if not conn.is_connected:
    raise SystemExit("client could not connect to the IEC 104 server on 127.0.0.1:2404")
for _ in range(5):                        # general interrogation (C_IC_NA_1), retried if needed
    if len(seen) == len(watch): break
    conn.interrogation(common_address=CA)
    time.sleep(0.5)
time.sleep(0.5)
names = {ioa_sw(8):"CB feeder1 status", ioa_v(1):"V bus1 kV", ioa_v(5):"V bus5 kV", ioa_v(13):"V bus13 kV",
         ioa_line(0,2):"I feeder1 A", ioa_line(10,2):"I feeder2 A", IOA_PGRID:"P grid MW", IOA_F:"f Hz"}
def show(tag):
    print(tag, {names[a]: (round(v,2) if isinstance(v,float) else str(v)) for a, v in sorted(seen.items())})
show("before:")
# watch the right breaker: switch index 8
cmd.value = c104.Double.OFF
ok = cmd.transmit(cause=c104.Cot.ACTIVATION)
time.sleep(1.0)
print("command accepted:", ok)
print("server breaker 8 closed =", bool(net.switch.closed[8]))
show("after: ")
client.stop(); server.stop()
