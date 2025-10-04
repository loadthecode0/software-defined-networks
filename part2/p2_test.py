#!/usr/bin/env python3

"""
Script to start Mininet with the custom topology and test Part 2 controllers.

Usage:
    sudo python3 p2_test.py sp       # Shortest Path Controller
    sudo python3 p2_test.py lb       # Load Balanced Controller
"""

import sys
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from p2_topo import CustomTopo


def run_test(controller_type):
    """Start Mininet, attach to Ryu, run tests."""
    setLogLevel("info")

    if controller_type == "sp":
        info("*** Testing Shortest Path Controller\n")
        ryu_app = "p2_shortestpath.py"
    elif controller_type == "lb":
        info("*** Testing Load Balanced Controller\n")
        ryu_app = "p2_loadbalanced.py"
    else:
        sys.exit("Usage: sudo python3 p2_test.py [sp|lb]")

    # Expect ryu-manager already running with correct app:
    info(f"*** Please ensure Ryu is running: ryu-manager {ryu_app}\n")

    # Setup topology
    topo = CustomTopo()
    net = Mininet(
        topo=topo,
        switch=OVSSwitch,
        build=False,
        controller=None,
        autoSetMacs=True,
        autoStaticArp=True
    )

    # Attach to remote Ryu controller
    net.addController(
        "c0",
        controller=RemoteController,
        ip="127.0.0.1",
        port=6633
    )

    net.build()
    net.start()

    # info("*** Running pingall test\n")
    # net.pingAll()

    # info("*** Running iperf test between h1 and h2 with 2 TCP streams\n")
    # h1, h2 = net.get("h1"), net.get("h2")
    # net.iperf((h1, h2), l4Type="TCP", options="-P 2")

    info("*** You can run more commands in the CLI\n")
    CLI(net)

    net.stop()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: sudo python3 p2_test.py [sp|lb]")

    run_test(sys.argv[1])
