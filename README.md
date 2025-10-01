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
