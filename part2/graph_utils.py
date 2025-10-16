import json
import networkx as nx
from typing import List


class NetworkGraph:
    def __init__(self, config_path: str = "config.json"):
        self.config = {}
        self.G = nx.Graph()
        self.ecmp = False
        self.load_config(config_path)
        self.build_graph_from_config()

    def load_config(self, path: str):
        """Load config.json (nodes, weight_matrix, ecmp flag)."""
        with open(path, "r") as f:
            self.config = json.load(f)
        self.ecmp = self.config.get("ecmp", False)

    def build_graph_from_config(self):
        """Convert weight_matrix into a NetworkX weighted graph."""
        nodes = self.config.get("nodes", [])
        weight_matrix = self.config.get("weight_matrix", [])
        self.G.add_nodes_from(nodes)
        n = len(nodes)
        for i in range(n):
            for j in range(n):
                w = weight_matrix[i][j]
                if w and w > 0: # 0 means no connection except the diagonal
                    self.G.add_edge(nodes[i], nodes[j], weight=w, utilization=0)
                    # self.G[nodes[i]][nodes[j]]["utilization"] = 0.0
                    # self.graph.update_utilization(f"s{nodes[i]}", f"s{nodes[j]}", delta=1.0)

    def dijkstra_shortest_path(self, src: str, dst: str) -> List[str]:
        """Return one shortest path from src to dst."""
        try:
            return nx.shortest_path(self.G, source=src, target=dst, weight="weight")
        except nx.NetworkXNoPath:
            return []

    def dijkstra_all_shortest_paths(self, src: str, dst: str) -> List[List[str]]:
        """Return all equal-cost shortest paths (ECMP)."""
        try:
            return list(nx.all_shortest_paths(self.G, source=src, target=dst, weight="weight"))
        except nx.NetworkXNoPath:
            return []

    def update_utilization(self, u: str, v: str, delta: float):
        """Increase utilization on edge (u,v) by delta (can be negative to decrease)."""
        # print("While updating path utilization this is u and v, {u}, {v}")
        # print("While updating path utilization this is u and v")
        # print(u)
        # print(v)
        # if self.G.has_edge("s"+str(u), "s"+str(v)):
        #     self.G["s"+str(u)]["s"+str(v)]["utilization"] += delta
        if self.G.has_edge(u, v):
            self.G[u][v]["utilization"] += delta
            if self.G[u][v]["utilization"] < 0:
                self.G[u][v]["utilization"] = 0.0

    def get_utilization(self, u: str, v: str) -> float:
        """Get current utilization of edge (u,v)."""
        # print("While getting path utilization this is u and v")
        # print(u)
        # print(v)
        return self.G[u][v].get("utilization", 0.0) if self.G.has_edge(u, v) else float("inf")

    def path_utilization(self, path: List[str]) -> float:
        """Return total utilization along a path."""
        util = 0.0
        for i in range(len(path) - 1):
            # u, v = int(path[i][1]), int(path[i + 1][1])
            # u, v = int(path[i][1:]), int(path[i + 1][1:])
            u, v = path[i], path[i + 1]

            # print("While calculating path utilization this is u and v")
            # print(u)
            # print(v)
            util += self.get_utilization(u, v)
        return util