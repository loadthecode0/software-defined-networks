# #!/usr/bin/env python3
# # p4_topo_sdn.py
# # Mininet topology for the SDN link failure experiment.
# # This version creates a network of OpenFlow switches but uses the same
# # single-ring wiring as the provided OSPF starter code for a fair comparison.

# from mininet.net import Mininet
# from mininet.node import Host, OVSSwitch, RemoteController
# from mininet.link import TCLink
# from mininet.log import setLogLevel, info

# # These IPs and default gateways must match what your SDN controller expects.
# H1_IP = '10.0.12.2/24'
# H1_GATEWAY = '10.0.12.1'

# H2_IP = '10.0.67.2/24'
# H2_GATEWAY = '10.0.67.1'

# def build():
#     """
#     Builds a Mininet topology with 6 OpenFlow switches and 2 hosts.
#     This topology is intended to be used with a remote SDN controller.
#     """
#     net = Mininet(
#         controller=RemoteController, # A remote controller will be used
#         switch=OVSSwitch,           # Use Open vSwitch for switches
#         link=TCLink,                # Use TCLink to set bandwidth
#         autoSetMacs=True,           # Let Mininet automatically set MACs
#         autoStaticArp=False,        # The controller will handle ARP
#         build=False                 # We will build the network manually
#     )

#     info('*** Adding switches\n')
#     # Add 6 Open vSwitch instances. stp=True helps prevent loops before the controller connects.
#     switches = [net.addSwitch(f's{i+1}', stp=True) for i in range(6)]
#     s1, s2, s3, s4, s5, s6 = switches

#     info('*** Adding hosts\n')
#     # Add hosts with their IP and default gateway configured.
#     h1 = net.addHost('h1', ip=H1_IP, defaultRoute=f'via {H1_GATEWAY}')
#     h2 = net.addHost('h2', ip=H2_IP, defaultRoute=f'via {H2_GATEWAY}')

#     info('*** Creating host <-> switch links\n')
#     # Use specific interface names to match the link flap script.
#     net.addLink(h1, s1, intfName1='h1-eth1', intfName2='s1-eth1', bw=10)
#     net.addLink(h2, s6, intfName1='h2-eth1', intfName2='s6-eth3', bw=10)

#     info('*** Creating inter-switch links (matching OSPF starter code wiring)\n')
#     # This single-ring wiring matches the provided OSPF topology.
#     net.addLink(s1, s2, intfName1='s1-eth2', intfName2='s2-eth1', bw=10)
#     net.addLink(s2, s3, intfName1='s2-eth2', intfName2='s3-eth1', bw=10)
#     net.addLink(s3, s6, intfName1='s3-eth2', intfName2='s6-eth1', bw=10)
#     net.addLink(s6, s5, intfName1='s6-eth2', intfName2='s5-eth2', bw=10)
#     net.addLink(s5, s4, intfName1='s5-eth1', intfName2='s4-eth2', bw=10)
#     net.addLink(s4, s1, intfName1='s4-eth1', intfName2='s1-eth3', bw=10)

#     return net

# if __name__ == '__main__':
#     # This part allows you to run the topology script directly to test it.
#     setLogLevel('info')
    
#     # Start the network and connect to a controller running on localhost
#     net = build()
#     net.addController('c0', controller=RemoteController, ip='127.0.0.1', port=6653)
    
#     info('*** Starting network\n')
#     net.start()
    
#     info('*** Testing connectivity\n')
#     net.pingAll()
    
#     info('*** Stopping network\n')
#     # net.stop()

# p4_topo_sdn.py
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.link import TCLink
from mininet.log import setLogLevel, info

# Constants for easy access by other scripts
H1_IP = "10.0.12.2/24"
H2_IP = "10.0.67.2/24"

def hex_dpid(n: int) -> str:
    """Helper to format DPID as a 16-character hex string."""
    return f"{int(n):016x}"

def set_if(node, ifname, ip_cidr=None, mac=None):
    """Helper to configure a network interface."""
    node.cmd(f'ip link set dev {ifname} down')
    node.cmd(f'ip addr flush dev {ifname}')
    if mac:
        node.cmd(f'ip link set dev {ifname} address {mac}')
    if ip_cidr:
        node.cmd(f'ip addr add {ip_cidr} dev {ifname}')
    node.cmd(f'ip link set dev {ifname} up')

def build():
    """Builds the custom Mininet network for the SDN experiment."""
    net = Mininet(
        controller=None, build=False, link=TCLink,
        autoSetMacs=False, autoStaticArp=False
    )

    info('*** Adding switches s1-s6\n')
    switches = {
        i: net.addSwitch(f's{i}', cls=OVSSwitch, dpid=hex_dpid(i))
        for i in range(1, 7)
    }

    info('*** Adding hosts h1 and h2\n')
    h1 = net.addHost('h1', ip=H1_IP, mac='00:00:00:00:01:02')
    h2 = net.addHost('h2', ip=H2_IP, mac='00:00:00:00:06:02')

    info('*** Creating links\n')
    # Host links
    net.addLink(h1, switches[1], intfName1='h1-eth1', intfName2='s1-eth1', port1=1, port2=1)
    net.addLink(h2, switches[6], intfName1='h2-eth1', intfName2='s6-eth3', port1=1, port2=3)
    # Switch links
    net.addLink(switches[1], switches[2], intfName1='s1-eth2', intfName2='s2-eth1', port1=2, port2=1)
    net.addLink(switches[2], switches[3], intfName1='s2-eth2', intfName2='s3-eth1', port1=2, port2=1)
    net.addLink(switches[3], switches[6], intfName1='s3-eth2', intfName2='s6-eth1', port1=2, port2=1)
    net.addLink(switches[6], switches[5], intfName1='s6-eth2', intfName2='s5-eth2', port1=2, port2=2)
    net.addLink(switches[5], switches[4], intfName1='s5-eth1', intfName2='s4-eth2', port1=1, port2=2)
    net.addLink(switches[4], switches[1], intfName1='s4-eth1', intfName2='s1-eth3', port1=1, port2=3)

    net.build()

    info('*** Configuring host IPs and default routes\n')
    h1.cmd(f'ip route add default via 10.0.12.1')
    h2.cmd(f'ip route add default via 10.0.67.1')

    return net