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

#### Look at the installed rules at a node

In yet another terminal:

```
sudo ovs-ofctl dump-flows <nodename> -O OpenFlow13
```
Or, to watch the rules live:

```
watch -n 1 "sudo ovs-ofctl dump-flows s1 -O OpenFlow13"
```