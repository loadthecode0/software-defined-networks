#!/usr/bin/env python3

"""
Script to start Mininet with the custom topology and test Ryu controllers.

Usage:
    sudo python3 p1_test.py hub
    sudo python3 p1_test.py learning
"""

import sys
import time
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from p2_topo import CustomTopo


def run_test(controller_type):
    """Start Mininet, attach to Ryu, run tests."""
    setLogLevel("info")

    # Choose controller name for logging
    if controller_type == "hub":
        info("*** Testing Hub Controller\n")
    elif controller_type == "learning":
        info("*** Testing Learning Switch Controller\n")
    else:
        sys.exit("Usage: sudo python3 p1_test.py [hub|learning]")

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

    # Add RemoteController (expects ryu-manager to be running separately)
    net.addController(
        "c0",
        controller=RemoteController,
        ip="127.0.0.1",
        port=6633
    )

    net.build()
    net.start()

    info("*** Running pingall test\n")
    net.pingAll()

    info("*** Running iperf test between h1 and h3\n")
    h1, h3 = net.get("h1"), net.get("h3")
    net.iperf((h1, h3))

    info("*** You can run more commands in the CLI\n")
    CLI(net)

    net.stop()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: sudo python3 p1_test.py [hub|learning]")

    run_test(sys.argv[1])
