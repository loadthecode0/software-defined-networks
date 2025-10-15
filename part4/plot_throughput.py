import time
import re
import os
import matplotlib.pyplot as plt
from mininet.log import setLogLevel, info
from mininet.cli import CLI
from mininet.node import RemoteController

# Assumes p4_topo_sdn.py is in the same directory and contains
# the build() function and H1_IP, H2_IP constants.
from p4_topo_sdn import build, H1_IP, H2_IP

# --- Experiment Parameters ---
FLAP_DELAY = 2
DOWN_DURATION = 5
IPERF_DURATION = 15
IPERF_LOG = "/tmp/iperf_client_sdn.log"
PLOT_FILENAME = "sdn_throughput_vs_time.png"

# --- Link to Fail ---
EDGE_TO_FLAP = {"s_i": "s2", "s_j": "s3", "i_if": "s2-eth2", "j_if": "s3-eth1"}

def toggle_link(net, edge, action="down"):
    """Bring both sides of a switch link down or up."""
    s_i = net.get(edge["s_i"])
    s_j = net.get(edge["s_j"])
    info(f"*** Toggling link {s_i.name}-{s_j.name} {action.upper()}\n")
    s_i.cmd(f"ip link set {edge['i_if']} {action}")
    s_j.cmd(f"ip link set {edge['j_if']} {action}")

def run_experiment(net):
    """Starts iperf, flaps the link, and returns the parsed results."""
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
    time.sleep(IPERF_DURATION - FLAP_DELAY - DOWN_DURATION + 2)
    h2.cmd("kill %iperf")

    # Parse and return results for plotting
    return parse_iperf_log()

def parse_iperf_log():
    """Parses the iperf log and returns a list of (time, throughput) tuples."""
    if not os.path.exists(IPERF_LOG):
        print(f"Log file not found: {IPERF_LOG}")
        return []

    entries = []
    with open(IPERF_LOG, "r") as f:
        for line in f:
            match = re.search(r"(\d+\.\d+)-\s*(\d+\.\d+)\s+sec.*?([\d\.]+)\s+Mbits/sec", line)
            if match:
                end_time = float(match.group(2))
                bw = float(match.group(3))
                entries.append((int(round(end_time)), bw))
    return entries

def plot_throughput(iperf_data):
    """Generates and saves a throughput vs. time plot."""
    if not iperf_data:
        info("No data to plot.\n")
        return

    seconds = [entry[0] for entry in iperf_data]
    throughput = [entry[1] for entry in iperf_data]

    plt.figure(figsize=(12, 6))
    plt.plot(seconds, throughput, marker='o', linestyle='-', label='Throughput')

    # Add vertical lines for link failure and recovery
    plt.axvline(x=FLAP_DELAY, color='r', linestyle='--', label=f'Link Down (t={FLAP_DELAY}s)')
    plt.axvline(x=FLAP_DELAY + DOWN_DURATION, color='g', linestyle='--', label=f'Link Up (t={FLAP_DELAY + DOWN_DURATION}s)')

    plt.title('SDN Controller Performance During Link Failure')
    plt.xlabel('Time (seconds)')
    plt.ylabel('Throughput (Mbps)')
    plt.grid(True)
    plt.legend()
    plt.xticks(range(0, IPERF_DURATION + 1))
    plt.tight_layout()

    plt.savefig(PLOT_FILENAME)
    info(f"*** Plot saved to {PLOT_FILENAME}\n")

if __name__ == '__main__':
    setLogLevel('info')
    net = build()
    net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6633)
    net.start()

    info("*** Waiting for controller to connect and stabilize...\n")
    time.sleep(5)

    info("*** Pinging to establish initial path...\n")
    net.pingAll(timeout=1)

    # Run experiment and get data
    results = run_experiment(net)

    # Plot the results
    plot_throughput(results)

    CLI(net)
    net.stop()