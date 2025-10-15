# p4_sdn_runner.py
import time
import re
import os
from mininet.log import setLogLevel, info
from mininet.cli import CLI
from mininet.node import RemoteController

# Import topology builder and constants
from p4_topo_sdn import build, H1_IP, H2_IP

# Experiment parameters
FLAP_DELAY = 2      # Seconds to wait before bringing link down
DOWN_DURATION = 5   # Seconds the link stays down
IPERF_DURATION = 15 # Total iperf test time in seconds
IPERF_LOG = "/tmp/iperf_client.log"

# Define the link to be failed (s2 <-> s3)
EDGE_TO_FLAP = {"s_i": "s2", "s_j": "s3", "i_if": "s2-eth2", "j_if": "s3-eth1"}

def toggle_link(net, edge, action="down"):
    """Bring both sides of a switch link down or up."""
    s_i = net.get(edge["s_i"])
    s_j = net.get(edge["s_j"])
    info(f"*** Toggling link {s_i.name}-{s_j.name} {action.upper()}\n")
    s_i.cmd(f"ip link set {edge['i_if']} {action}")
    s_j.cmd(f"ip link set {edge['j_if']} {action}")

def run_experiment(net):
    """Starts iperf, flaps the link, and collects results."""
    h1, h2 = net.get('h1', 'h2')
    server_ip = H2_IP.split('/')[0]

    info(f"*** Starting iperf server on {h2.name}\n")
    h2.cmd(f"iperf -s &")
    time.sleep(1)

    info(f"*** Starting iperf client: {h1.name} -> {h2.name} for {IPERF_DURATION}s\n")
    h1.cmd(f"iperf -c {server_ip} -t {IPERF_DURATION} -i 1 > {IPERF_LOG} 2>&1 &")
    
    time.sleep(FLAP_DELAY)
    toggle_link(net, EDGE_TO_FLAP, action="down")

    time.sleep(DOWN_DURATION)
    toggle_link(net, EDGE_TO_FLAP, action="up")

    info(f"*** Waiting for iperf to finish...\n")
    time.sleep(IPERF_DURATION - FLAP_DELAY - DOWN_DURATION + 20)
    
    # Stop server
    h2.cmd("kill %iperf")
    
    # Parse results
    parse_results()

def parse_results():
    """Parses the iperf log to estimate convergence."""
    if not os.path.exists(IPERF_LOG):
        print("iperf log not found!")
        return

    entries = []
    with open(IPERF_LOG, "r") as f:
        for line in f:
            match = re.search(r"(\d+\.\d+)-\s*(\d+\.\d+)\s+sec.*?([\d\.]+)\s+Mbits/sec", line)
            if match:
                end_time = float(match.group(2))
                bw = float(match.group(3))
                entries.append((int(round(end_time)), bw))
    
    print("\n--- IPERF Results (Per Second) ---")
    for sec, bw in entries:
        print(f"Second {sec}: {bw:.2f} Mbps")
    
    if not entries: return

    pre_flap_bws = [bw for s, bw in entries if s <= FLAP_DELAY]
    baseline = sum(pre_flap_bws) / len(pre_flap_bws) if pre_flap_bws else 0
    
    drop_sec, recover_sec = None, None
    for sec, bw in entries:
        if sec > FLAP_DELAY and bw < 1.0 and drop_sec is None:
            drop_sec = sec
        if drop_sec is not None and sec > drop_sec and bw > baseline * 0.5:
            recover_sec = sec
            break
            
    print("\n--- Convergence Analysis ---")
    print(f"Baseline Throughput: {baseline:.2f} Mbps")
    if drop_sec:
        print(f"Throughput dropped at second: {drop_sec}")
    if recover_sec:
        print(f"Throughput recovered at second: {recover_sec}")
        print(f"Estimated Convergence Time: {recover_sec - drop_sec} second(s)")
    else:
        print("Could not determine recovery time from logs.")


if __name__ == '__main__':
    setLogLevel('info')
    net = build()
    net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)
    net.start()
    
    info("*** Waiting for controller to connect and stabilize...\n")
    time.sleep(3)


    # ADD THIS LINE to force path creation
    info("*** Pinging to establish initial path...\n")
    net.pingAll(timeout=1) # Or just h1.cmd('ping -c 1 h2')
    run_experiment(net)
    
    CLI(net)
    net.stop()