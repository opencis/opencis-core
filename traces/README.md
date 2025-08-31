# QEMU packet traces for testing

### 1. Save initial QEMU packet trace

``` bash
./cxl-util start -c fm -c switch -c sld-group --config-file configs/1vcs_4sld.yaml --pcap-file new.pcap
```

 * Memo down the dynamic port number when QEMU launches:

`[ServerComponent:SwitchConnectionManager] Found a new socket connection: ('127.0.0.1', *18682*)`

### 2. Filter out the port number from the packet trace

 * 8000 is fixed, replace 18682 with the dynamic port number when QEMU launches

``` bash
tcpdump -r new.pcap -w filtered.pcap 'tcp port 8000 or tcp port 18682'
```

### 3. Rewrite dynamic port number to 8080

``` bash
# apt install tcpreplay
tcprewrite --portmap=18682:8080 -i filtered.pcap -o traces/qemu.pcap
```

### 4. Clean-up

``` bash
rm new.pcap filtered.pcap
```
