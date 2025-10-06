#!/usr/bin/env python3
from mininet.topo import Topo

class LoadBalanceTopo(Topo):
    """Diamond topology to test load balancing."""

    def build(self):
        # Hosts
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')
        h4 = self.addHost('h4')

        # Switches
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')
        s4 = self.addSwitch('s4')
        s5 = self.addSwitch('s5')
        s6 = self.addSwitch('s6')

        # Upper diamond
        self.addLink(s1, s2)
        self.addLink(s2, s3)
        self.addLink(s3, s4)

        # Lower diamond
        self.addLink(s1, s5)
        self.addLink(s5, s6)
        self.addLink(s6, s4)

        # Interconnect for redundancy (optional)
        self.addLink(s2, s5)
        self.addLink(s3, s6)

        # Hosts ↔ Switches
        self.addLink(h1, s1)
        self.addLink(h2, s2)
        self.addLink(h3, s3)
        self.addLink(h4, s4)
