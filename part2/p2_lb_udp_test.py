#!/usr/bin/env python3
"""
UDP-based load balancing validation test
"""

import time
from mininet.net import Mininet
from mininet.node import RemoteController, OVSSwitch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from p2_topo_lb import LoadBalanceTopo


def run_udp_test():
    setLogLevel("info")

    topo = LoadBalanceTopo()
    net = Mininet(topo=topo, switch=OVSSwitch, controller=None,
                  autoSetMacs=True, autoStaticArp=True)

    # Attach Ryu controller (must be already running)
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6633)

    net.build()
    net.start()

    h1, h2, h3, h4 = net.get('h1', 'h2', 'h3', 'h4')

    info("\n*** Testing basic connectivity\n")
    net.pingAll()

    info("\n*** Starting UDP servers on h4\n")
    h4.cmd('iperf -s -u -p 5001 > /tmp/h4_udp_5001.log &')
    h4.cmd('iperf -s -u -p 5002 > /tmp/h4_udp_5002.log &')
    h4.cmd('iperf -s -u -p 5003 > /tmp/h4_udp_5003.log &')

    time.sleep(2)

    info("\n*** Running high UDP load from h1→h4 (path A likely)\n")
    h1.cmd('iperf -c %s -u -p 5001 -b 50M -t 10 &' % h4.IP())

    time.sleep(2)

    info("\n*** Running moderate UDP load from h2→h4 (should pick another path)\n")
    h2.cmd('iperf -c %s -u -p 5002 -b 10M -t 10 &' % h4.IP())

    time.sleep(2)

    info("\n*** Running low UDP load from h3→h4 (should pick least utilized)\n")
    h3.cmd('iperf -c %s -u -p 5003 -b 5M -t 10 &' % h4.IP())

    time.sleep(15)

    info("\n*** Dumping flow tables on switches\n")
    for sw in ['s1', 's2', 's5', 's6']:
        info(net.get(sw).cmd('ovs-ofctl dump-flows %s | grep udp' % sw))

    info("\n*** Use controller logs to check chosen paths based on utilization\n")

    CLI(net)
    net.stop()


if __name__ == "__main__":
    run_udp_test()
