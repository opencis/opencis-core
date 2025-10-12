#!/usr/bin/env python3

from sknetwork.data import karate_club, painters, movie_actor
from sknetwork.ranking import PageRank
graph = karate_club(metadata=True)
adjacency = graph.adjacency
position = graph.position
pagerank = PageRank()
scores = pagerank.fit_predict([[1,2,3],[4,5,6],[7,8,9]])