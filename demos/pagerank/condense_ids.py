#!/usr/bin/env python3
with open("./links-anon-sampled.txt") as f:
    with open("./links-anon-sampled-condensed.txt", "w") as sf:
        mapping = {}
        nextId = 0
        for l in f:
            l = l.strip()
            ls = l.split(' ')
            idFrom = int(ls[0])
            idTo = int(ls[1])
            if idFrom in mapping:
                idFrom = mapping[idFrom]
            else:
                mapping[idFrom] = nextId
                idFrom = nextId
                nextId += 1
            
            if idTo in mapping:
                idTo = mapping[idTo]
            else:
                mapping[idTo] = nextId
                idTo = nextId
                nextId += 1

            sf.write(f"{idFrom} {idTo}\n")
        
        print(f"Finished condensing IDs. Total IDs: {nextId}")
