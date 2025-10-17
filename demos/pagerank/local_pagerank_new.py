#!/usr/bin/env python3
from typing import Dict, List, Tuple
from tqdm import tqdm


def crawl():
    pages: Dict[int, List[int]] = dict()
    all_pages: Dict[int, int] = {}
    with open("links-anon-sampled-condensed-5000.txt") as f:
        for l in f.readlines():
            l = l.strip()
            follow = l.split(" ")
            follower = int(follow[0])
            followee = int(follow[1])
            all_pages[follower] = 0
            all_pages[followee] = 0
            if follower in pages:
                pages[follower].append(followee)
            else:
                pages[follower] = [followee]
    total_pages = len(all_pages)
    # print(pages)
    return pages, total_pages


class CustomMatrix:
    def __init__(self, rows, intWidth=4, offset=0x0):
        self._rows = rows
        self._intWidth = intWidth
        self._offset = offset

    def getAddr(self, row: int, col: int) -> int:
        assert (row < self._rows) and (col < self._rows)
        return ((row * self._rows + col) * self._intWidth) + self._offset

    def getRowCol(self, addr: int) -> Tuple[int, int]:
        addr -= self._offset
        col8 = addr % (self._rows * self._intWidth)
        row8 = (addr - col8) // self._rows
        return (row8 // self._intWidth, col8 // self._intWidth)


def iterate_pagerank(corpus: Dict[int, List[int]], damping_factor=0.85, total_pages=0):
    """
    Return PageRank values for each page by iteratively updating
    PageRank values until convergence.

    Return a dictionary where keys are page names, and values are
    their estimated PageRank value (a value between 0 and 1). All
    PageRank values should sum to 1.
    """
    if total_pages == 0:
        pages_number = len(corpus)
    else:
        pages_number = total_pages
    old_dict = {}
    new_dict = {}

    MAX_ITER = 6

    print(f"1 / pages_number = {1 / pages_number}")
    print(len(corpus))
    print(total_pages)

    # assigning each page a rank of 1/n, where n is total number of pages in the corpus
    for page in range(total_pages):
        old_dict[page] = 1 / pages_number

    iter = 0
    # repeatedly calculating new rank values basing on all of the current rank values
    with tqdm(
        total=MAX_ITER,
        desc=f"Iteration",
        position=2,
        leave=False,
    ) as pbar:
        while iter < MAX_ITER:
            with tqdm(
                total=total_pages,
                desc=f"Iteration Progress",
                position=1,
                leave=False,
            ) as pbar2:
                for page in range(total_pages):
                    temp = 0
                    for linking_page in range(total_pages):
                        # check if page links to our page
                        if linking_page in corpus and page in corpus[linking_page]:
                            temp += old_dict[linking_page] / len(corpus[linking_page])
                        # if page has no links, interpret it as having one link for every other page
                        if linking_page not in corpus or len(corpus[linking_page]) == 0:
                            temp += (old_dict[linking_page]) / pages_number
                    temp *= damping_factor
                    temp += (1 - damping_factor) / pages_number

                    new_dict[page] = temp
                    pbar2.update()

            # difference = max([abs(new_dict[x] - old_dict[x]) for x in old_dict])

            print(f"iter {iter}, sum={sum(new_dict.values())}")
            old_dict = new_dict.copy()
            iter += 1
            pbar.update()

    return old_dict


corpus = {0: [1], 1: [0, 2], 2: [1], 3: [0]}
real_len = len(corpus)
corpus, real_len = crawl()
# print(corpus)
ranks = iterate_pagerank(corpus, total_pages=real_len)
print("PageRank scores:", ranks)
print(f"Sum: {sum(ranks.values())}")
