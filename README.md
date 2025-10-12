# software-defined-networks

Assignment 3 for COL334 (Networks), Semester 1 (2025-26) at IITD.

Implementing basic network policies using OpenFlow-like APIs.

## Commands

### PART 1

Start the controller in one terminal:

#### For Hub Controller
```
ryu-manager part1/p1_hub.py
```

#### For Learning Switch
```
ryu-manager part1/p1_learning.py
```

In another terminal, start the test script:

#### Test Hub
```
sudo python3 part1/p1_test.py hub
```

#### Test Learning Switch
```
sudo python3 part1/p1_test.py learning
```
#### Run `iperf` with h3 as server and h1 as client:
```
mininet> h3 iperf -s &
mininet> h1 iperf -c h3 -t 10 -P 2
```

### PART 2

#### For L2SPF Controller
```
ryu-manager part2/p2_l2spf.py
```

#### For Dynamic Path Selection
```
ryu-manager part2/p2bonus_l2spf.py
```

In another terminal, start the test script:

#### Test L2SPF Controller
```
sudo python3 part2/p2_test.py sp
```

#### Test Dynamic Path Selection
```
sudo python3 part2/p2_test.py lb
```

#### Run `iperf` with h2 as server and h1 as client:
```
mininet> h2 iperf -s &
mininet> h1 iperf -c h2 -t 10 -P 2
```

### Look at the installed rules at a node

In yet another terminal:

```
sudo ovs-ofctl dump-flows <nodename> -O OpenFlow13
```
Or, to watch the rules live:

```
watch -n 1 "sudo ovs-ofctl dump-flows s1 -O OpenFlow13"
```

# Some pointers regarding the libraries

## Datapath

In Ryu (and OpenFlow in general), a datapath is the logical representation of a switch that has connected to the controller.

It’s essentially a Python object (datapath) that encapsulates:
- The switch’s datapath ID (DPID) — unique identifier (like “s1” → DPID=1).
- The switch’s OpenFlow protocol version.
- A channel/socket between the controller and the switch.
- Methods to send OpenFlow messages (e.g., flow mods, packet outs).