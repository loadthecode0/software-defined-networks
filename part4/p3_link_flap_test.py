    # import time
    # import re
    # import os
    # import subprocess
    # from mininet.log import setLogLevel, info
    # from mininet.cli import CLI
    # from mininet.node import RemoteController, OVSSwitch

    # # Import your topology builder and constants
    # from p4_topo import build, H1_IP, H2_IP

    # # chosen flap parameters (match your OSPF test)
    # FLAP_DELAY = 2          # seconds after iperf start before bringing link down
    # DOWN_DURATION = 5       # seconds link stays down
    # IPERF_DURATION = 15     # total iperf run time (seconds)
    # IPERF_CLIENT_LOG = "/tmp/h1_iperf3.log"
    # IPERF_SERVER_LOG = "/tmp/h2_iperf3.log"

    # # The inter-switch edge to flap (names must match topo interface names)
    # # In your topo, s2 <-> s3 uses s2-eth2 and s3-eth1
    # EDGE_TO_FLAP = {
    #     "s_i": "s2",
    #     "s_j": "s3",
    #     "i_if": "s2-eth2",
    #     "j_if": "s3-eth1"
    # }


    # def if_down_up(net, edge, down=True):
    #     """Bring both sides of a router-router link down/up."""
    #     ri = net.get(edge["s_i"])
    #     rj = net.get(edge["s_j"])
    #     i_if = edge["i_if"]
    #     j_if = edge["j_if"]
    #     action = "down" if down else "up"
    #     info(f"*** Setting {ri.name}:{i_if} {action}\n")
    #     ri.cmd(f"ip link set {i_if} {action}")
    #     info(f"*** Setting {rj.name}:{j_if} {action}\n")
    #     rj.cmd(f"ip link set {j_if} {action}")
    #     # Small pause to let kernel process
    #     time.sleep(0.2)


    # def start_iperf3(h1, h2, duration=IPERF_DURATION):
    #     """Start iperf3 server on h2 and client on h1 (single test)."""
    #     # Clean old logs
    #     try:
    #         os.remove(IPERF_CLIENT_LOG)
    #     except FileNotFoundError:
    #         pass
    #     try:
    #         os.remove(IPERF_SERVER_LOG)
    #     except FileNotFoundError:
    #         pass

    #     info("*** Starting iperf3 server on h2\n")
    #     # use -1 so server exits after a single test
    #     h2.cmd(f"iperf3 -s -1 > {IPERF_SERVER_LOG} 2>&1 &")
    #     time.sleep(0.5)

    #     # ip address for client to connect (strip CIDR if present)
    #     server_ip = H2_IP.split("/")[0]
    #     info(f"*** Starting iperf3 client on h1 -> {server_ip} for {duration}s\n")
    #     h1.cmd(f"iperf3 -c {server_ip} -t {int(duration)} -i 1 > {IPERF_CLIENT_LOG} 2>&1 &")
    #     return IPERF_CLIENT_LOG, IPERF_SERVER_LOG


    # def parse_iperf3_client_log(log_path):
    #     """
    #     Parse iperf3 client log for per-second throughput lines and return a list:
    #     [(second_offset, Mbps_value), ...]
    #     iperf3 per-second lines typically look like:
    #       [  5]   0.00-1.00   sec  1.00 MBytes  8.39 Mbits/sec
    #     We'll extract the Mbits/sec value and associate it with the cumulative second index found.
    #     """
    #     entries = []
    #     if not os.path.exists(log_path):
    #         return entries

    #     sec_idx = 0
    #     with open(log_path, "r") as f:
    #         for line in f:
    #             # Common pattern: "0.00-1.00   sec ...  8.39 Mbits/sec"
    #             m = re.search(r"(\d+\.\d+)-(\d+\.\d+)\s+sec.*?([\d\.]+)\s+Mbits/sec", line)
    #             if m:
    #                 # take the upper bound of the interval as the second index
    #                 end = float(m.group(2))
    #                 bw = float(m.group(3))
    #                 # round end to integer seconds for simple indexing
    #                 entries.append((int(round(end)), bw))
    #     return entries


    # def estimate_convergence(iperf_entries, flap_time, down_duration):
    #     """
    #     Given per-second iperf entries [(sec, Mbps), ...], estimate:
    #     - time_when_throughput_dropped (first sec >= flap_time with bw < threshold)
    #     - time_when_recovered (first sec after drop where bw >= threshold * baseline)
    #     We compute baseline as average of seconds before flap_time (if available).
    #     Returns dict with baseline, drop_sec, recover_sec, recovery_time (seconds).
    #     """
    #     if not iperf_entries:
    #         return None

    #     # baseline: avg of entries with sec < flap_time
    #     pre = [bw for (s, bw) in iperf_entries if s <= max(0, int(flap_time))]
    #     baseline = sum(pre)/len(pre) if pre else max(bw for (_, bw) in iperf_entries)

    #     # threshold to consider "recovered" (50% of baseline)
    #     recover_th = baseline * 0.5
    #     # threshold to consider "dropped" (10% of baseline or < 1 Mbps)
    #     drop_th = max(baseline * 0.1, 1.0)

    #     drop_sec = None
    #     recover_sec = None

    #     for (s, bw) in iperf_entries:
    #         if s >= flap_time and drop_sec is None and bw <= drop_th:
    #             drop_sec = s
    #         if drop_sec is not None and s >= drop_sec and bw >= recover_th:
    #             recover_sec = s
    #             break

    #     if drop_sec and recover_sec:
    #         recovery_time = recover_sec - drop_sec
    #     else:
    #         recovery_time = None

    #     return {
    #         "baseline_mbps": baseline,
    #         "drop_sec": drop_sec,
    #         "recover_sec": recover_sec,
    #         "recovery_time_s": recovery_time,
    #         "entries": iperf_entries
    #     }


    # def link_flap_experiment(net, edge):
    #     """Run the iperf test and flap the edge per the schedule, return logs and metrics."""
    #     h1 = net.get("h1")
    #     h2 = net.get("h2")

    #     # start iperf
    #     client_log, server_log = start_iperf3(h1, h2, duration=IPERF_DURATION)

    #     # wait until time to flap
    #     info(f"*** Waiting {FLAP_DELAY}s before flapping link\n")
    #     time.sleep(FLAP_DELAY)

    #     # bring link down
    #     info(f"*** Bringing link DOWN: {edge['s_i']}:{edge['i_if']} <-> {edge['s_j']}:{edge['j_if']}\n")
    #     if_down_up(net, edge, down=True)

    #     # keep it down
    #     time.sleep(DOWN_DURATION)

    #     # bring link up
    #     info(f"*** Bringing link UP: {edge['s_i']}:{edge['i_if']} <-> {edge['s_j']}:{edge['j_if']}\n")
    #     if_down_up(net, edge, down=False)

    #     # wait remainder of iperf duration
    #     rem = max(0, IPERF_DURATION - FLAP_DELAY - DOWN_DURATION)
    #     info(f"*** Waiting {rem}s for iperf to finish\n")
    #     time.sleep(rem + 0.5)

    #     # pull logs and parse
    #     client_out = ""
    #     server_out = ""
    #     if os.path.exists(client_log):
    #         with open(client_log, "r") as f:
    #             client_out = f.read()
    #     if os.path.exists(server_log):
    #         with open(server_log, "r") as f:
    #             server_out = f.read()

    #     entries = parse_iperf3_client_log(client_log)
    #     metrics = estimate_convergence(entries, flap_time=FLAP_DELAY, down_duration=DOWN_DURATION)

    #     return client_log, server_log, client_out, server_out, metrics


    # def main():
    #     setLogLevel("info")
    #     info("*** Building topology and starting SDN test\n")

    #     net = build()  # call your topo.py build() directly

    #     info("*** Adding RemoteController (127.0.0.1:6653)\n")
    #     net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
    #     net.start()
    #     time.sleep(1.5)

    #     try:
    #         info("*** Running link flap experiment (SDN)\n")
    #         client_log, server_log, c_out, s_out, metrics = link_flap_experiment(net, EDGE_TO_FLAP)

    #         print("\n==== IPERF3 CLIENT LOG (tail) ====\n")
    #         print(c_out[-4000:] if c_out else "(no client log)")

    #         print("\n==== IPERF3 SERVER LOG (tail) ====\n")
    #         print(s_out[-4000:] if s_out else "(no server log)")

    #         if metrics:
    #             print("\n==== RECOVERY METRICS ====")
    #             print(f"Baseline throughput (Mbps): {metrics['baseline_mbps']:.2f}")
    #             print(f"Observed drop at second: {metrics['drop_sec']}")
    #             print(f"Observed recover at second: {metrics['recover_sec']}")
    #             print(f"Estimated recovery time (s): {metrics['recovery_time_s']}")
    #         else:
    #             print("\nNo iperf3 throughput entries parsed; cannot estimate convergence.")

    #         CLI(net)

    #     finally:
    #         info("*** Stopping network\n")
    #         # net.stop()

    # if __name__ == "__main__":
    #     main()


    """
    p3_link_flap_test.py

    SDN link flap test that uses the topology defined in topo.py (build()).
    Emulates: 2s after iperf start -> bring a switch-switch link DOWN for 5s -> bring it UP.
    Parses iperf client log to estimate convergence time.
    """

    import time
    import re
    import os
    from mininet.log import setLogLevel, info
    from mininet.cli import CLI
    from mininet.node import RemoteController

    # Import your topology builder and constants
    from p4_topo_sdn import build, H1_IP, H2_IP

    # chosen flap parameters (match your OSPF test)
    FLAP_DELAY = 2          # seconds after iperf start before bringing link down
    DOWN_DURATION = 5       # seconds link stays down
    IPERF_DURATION = 15     # total iperf run time (seconds)
    IPERF_CLIENT_LOG = "/tmp/h1_iperf.log"
    IPERF_SERVER_LOG = "/tmp/h2_iperf.log"

    # The inter-switch edge to flap (names must match topo interface names)
    # In your topo, s2 <-> s3 uses s2-eth2 and s3-eth1
    EDGE_TO_FLAP = {
        "s_i": "s2",
        "s_j": "s3",
        "i_if": "s2-eth2",
        "j_if": "s3-eth1"
    }


    def if_down_up(net, edge, down=True):
        """Bring both sides of a switch-switch link down/up."""
        ri = net.get(edge["s_i"])
        rj = net.get(edge["s_j"])
        i_if = edge["i_if"]
        j_if = edge["j_if"]
        action = "down" if down else "up"
        info(f"*** Setting {ri.name}:{i_if} {action}\n")
        ri.cmd(f"ip link set {i_if} {action}")
        info(f"*** Setting {rj.name}:{j_if} {action}\n")
        rj.cmd(f"ip link set {j_if} {action}")
        time.sleep(0.2)


    def start_iperf(h1, h2, duration=IPERF_DURATION):
        """Start iperf v2 server on h2 and client on h1."""
        # Clean old logs
        for log in [IPERF_CLIENT_LOG, IPERF_SERVER_LOG]:
            try:
                os.remove(log)
            except FileNotFoundError:
                pass

        info("*** Starting iperf server on h2\n")
        # -s server, run in background
        h2.cmd(f"iperf -s > {IPERF_SERVER_LOG} 2>&1 &")
        time.sleep(0.5)

        server_ip = H2_IP.split("/")[0]
        info(f"*** Starting iperf client on h1 -> {server_ip} for {duration}s\n")
        h1.cmd(f"iperf -c {server_ip} -t {int(duration)} > {IPERF_CLIENT_LOG} 2>&1 &")
        return IPERF_CLIENT_LOG, IPERF_SERVER_LOG


    def parse_iperf_client_log(log_path):
        """Parse iperf v2 client log for per-second throughput."""
        entries = []
        if not os.path.exists(log_path):
            return entries

        with open(log_path, "r") as f:
            for line in f:
                # Match lines like: "0.0- 1.0 sec  1.25 MBytes  10.5 Mbits/sec"
                m = re.search(r"(\d+\.\d+)-\s*(\d+\.\d+)\s+sec.*?([\d\.]+)\s+Mbits/sec", line)
                if m:
                    end = float(m.group(2))
                    bw = float(m.group(3))
                    entries.append((int(round(end)), bw))
        return entries


    def estimate_convergence(iperf_entries, flap_time, down_duration):
        """Estimate throughput drop and recovery metrics."""
        if not iperf_entries:
            return None

        # baseline: avg of entries before flap_time
        pre = [bw for (s, bw) in iperf_entries if s <= max(0, int(flap_time))]
        baseline = sum(pre)/len(pre) if pre else max(bw for (_, bw) in iperf_entries)

        recover_th = baseline * 0.5
        drop_th = max(baseline * 0.1, 1.0)

        drop_sec = None
        recover_sec = None

        for (s, bw) in iperf_entries:
            if s >= flap_time and drop_sec is None and bw <= drop_th:
                drop_sec = s
            if drop_sec is not None and s >= drop_sec and bw >= recover_th:
                recover_sec = s
                break

        recovery_time = recover_sec - drop_sec if drop_sec and recover_sec else None

        return {
            "baseline_mbps": baseline,
            "drop_sec": drop_sec,
            "recover_sec": recover_sec,
            "recovery_time_s": recovery_time,
            "entries": iperf_entries
        }


    def link_flap_experiment(net, edge):
        """Run iperf test and flap the link per schedule."""
        h1 = net.get("h1")
        h2 = net.get("h2")

        client_log, server_log = start_iperf(h1, h2, duration=IPERF_DURATION)

        info(f"*** Waiting {FLAP_DELAY}s before flapping link\n")
        time.sleep(FLAP_DELAY)

        info(f"*** Bringing link DOWN: {edge['s_i']}:{edge['i_if']} <-> {edge['s_j']}:{edge['j_if']}\n")
        if_down_up(net, edge, down=True)

        time.sleep(DOWN_DURATION)

        info(f"*** Bringing link UP: {edge['s_i']}:{edge['i_if']} <-> {edge['s_j']}:{edge['j_if']}\n")
        if_down_up(net, edge, down=False)

        rem = max(0, IPERF_DURATION - FLAP_DELAY - DOWN_DURATION)
        info(f"*** Waiting {rem}s for iperf to finish\n")
        time.sleep(rem + 0.5)

        client_out = ""
        server_out = ""
        if os.path.exists(client_log):
            with open(client_log, "r") as f:
                client_out = f.read()
        if os.path.exists(server_log):
            with open(server_log, "r") as f:
                server_out = f.read()

        entries = parse_iperf_client_log(client_log)
        metrics = estimate_convergence(entries, flap_time=FLAP_DELAY, down_duration=DOWN_DURATION)

        return client_log, server_log, client_out, server_out, metrics


    def main():
        setLogLevel("info")
        info("*** Building topology and starting SDN test\n")

        net = build()  # call your topo.py build() directly

        info("*** Adding RemoteController (127.0.0.1:6653)\n")
        net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
        net.start()
        time.sleep(1.5)

        # try:
        #     info("*** Running link flap experiment (SDN)\n")
        #     client_log, server_log, c_out, s_out, metrics = link_flap_experiment(net, EDGE_TO_FLAP)

        #     print("\n==== IPERF CLIENT LOG (tail) ====\n")
        #     print(c_out[-4000:] if c_out else "(no client log)")

        #     print("\n==== IPERF SERVER LOG (tail) ====\n")
        #     print(s_out[-4000:] if s_out else "(no server log)")

        #     if metrics:
        #         print("\n==== RECOVERY METRICS ====")
        #         print(f"Baseline throughput (Mbps): {metrics['baseline_mbps']:.2f}")
        #         print(f"Observed drop at second: {metrics['drop_sec']}")
        #         print(f"Observed recover at second: {metrics['recover_sec']}")
        #         print(f"Estimated recovery time (s): {metrics['recovery_time_s']}")
        #     else:
        #         print("\nNo iperf throughput entries parsed; cannot estimate convergence.")

        CLI(net)

        # finally:
        #     info("*** Stopping network\n")
        #     net.stop()


    if __name__ == "__main__":
        main()
