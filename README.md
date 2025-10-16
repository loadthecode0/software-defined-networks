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

README: UDP Testing Commands in Mininet

Overview:
---------
This guide explains how to test UDP performance between hosts in a Mininet network using iperf or iperf3. 
UDP tests are useful for measuring bandwidth, jitter, and packet loss, unlike TCP which focuses on reliability.

1. Start a UDP Server:
----------------------
Run this on the receiving host (e.g., h2):

# Using iperf
mininet> h2 iperf -s -u -i 1

# Using iperf3
mininet> h2 iperf3 -s -i 1

Options explained:
- -s        : Start in server mode
- -u        : Use UDP (default is TCP if omitted)
- -i 1      : Print statistics every 1 second

Server output will show:
- Received bandwidth
- Jitter
- Packet loss

2. Start a UDP Client:
----------------------
Run this on the sending host (e.g., h1):

# Using iperf
mininet> h1 iperf -c 10.0.0.2 -u -b 10M -t 10 -i 1

# Using iperf3
mininet> h1 iperf3 -c 10.0.0.2 -u -b 10M -t 10 -i 1

Options explained:
- -c <server_ip> : Specify server IP to connect
- -u             : Use UDP
- -b 10M         : Target bandwidth (e.g., 10 Mbps). UDP requires explicit bandwidth.
- -t 10          : Duration of test in seconds
- -i 1           : Print periodic reports every 1 second

Client output will show:
- Bandwidth being sent
- Jitter
- Packet loss (%)

3. Common Notes:
----------------
1. UDP vs TCP:
   - UDP is connectionless; sending too much data may overflow buffers, leading to packet loss.
   - TCP auto-adjusts to network capacity.

2. Measuring path performance:
   - Run UDP tests multiple times with different -b values to see path saturation.
   - Use -i 1 to observe how jitter and loss vary over time.

3. Background UDP server:
   - To run server in background:
     mininet> h2 iperf -s -u -i 1 &
   - & allows Mininet CLI to continue.

4. Verbose mode (iperf3):
   mininet> h1 iperf3 -c 10.0.0.2 -u -b 10M -t 10 -i 1 -V
   - -V prints more detailed information per packet.

4. Example Test:
----------------
1. Start Mininet:
   sudo mn --topo linear,2 --mac --switch ovsk --controller remote

2. Start UDP server:
   mininet> h2 iperf -s -u -i 1 &

3. Start UDP client:
   mininet> h1 iperf -c 10.0.0.2 -u -b 5M -t 10 -i 1

Expected output: Bandwidth, jitter, and packet loss per second.



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


