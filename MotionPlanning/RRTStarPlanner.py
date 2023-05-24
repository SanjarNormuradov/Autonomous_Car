from __future__ import absolute_import, print_function
import numpy as np
from RRTTree import RRTTree
import sys
import time
import math
# from tqdm import tqdm

class RRTStarPlanner(object):

    def __init__(self, planning_env, output_directory:str, stat_filename:str, rand_seed:int, bias = 0.05, eta = 1.0, max_iter = 10000):
        self.env = planning_env         # Map Environment
        self.tree = RRTTree(planning_env=self.env, 
                            eta=eta, 
                            bias=bias, 
                            output_directory=output_directory, 
                            rand_seed=rand_seed, 
                            stat_filename=stat_filename)
        self.bias = bias                # Goal Bias
        self.max_iter = max_iter        # Max Iterations
        self.eta = eta                  # Distance to extend

    def compute_cost(self, node_id):
        root_id = self.tree.GetRootID()

        cost = 0
        node = self.tree.vertices[node_id]
        while node_id != root_id:
            parent_id = self.tree.edges[node_id]
            parent = self.tree.vertices[parent_id]
            cost += self.env.compute_distance(node, parent)

            node_id = parent_id
            node = parent

        return cost

    def Plan(self, start_config, goal_config, rad=10):
        start_time = time.time()
        path = None
        vertex_id, vertex = None, None
        is_edge_valid = False
        # Generate RRT
        #   Seed the tree
        self.tree.AddVertex(start_config)
        #   Expand the tree
        for branch_id in range(1, self.max_iter+1):
            # print(f"branch_id: {branch_id}")
            # Randomly sample free state from the map, as long as an 
            # x_rand.shape = (self.c_space_dim, 1)
            # c_space is space of joint angles: 
            # i.e. for 2dof_robot_arm (x, y) = (joint1_angle, joint2_angle)
            while not is_edge_valid:
                x_rand = self.sample(goal_config)
                # print(f"x_rand:\n{x_rand}")
                # Get the tree vertex nearest to x_rand
                x_nearest_id, x_nearest_dist = self.tree.GetNearestVertex(x_rand)
                x_nearest = self.tree.vertices[x_nearest_id]
                # print(f"x_nearest:\n{x_nearest}")
                # Check an edge between x_nearest and x_rand for collision/out of map
                if self.env.edge_validity_checker(x_rand, x_nearest):
                    is_edge_valid = True
            is_edge_valid = False

            # Extend from x_nearest towards x_rand
            x_new = self.extend(x_nearest, x_rand)
            # print(f"x_new:\n{x_new}")

            # Search near neighbors of x_new within radius
            near_neigh_ids, near_neighs = self.tree.GetNNInRad(x_new, rad)
            # Connect new vertex to a parent with less cost
            x_min_id = x_nearest_id
            x_min = x_nearest
            cost_min = self.compute_cost(x_nearest_id) + self.env.compute_distance(x_nearest, x_new)
            for x_near_id, x_near in zip(near_neigh_ids, near_neighs):
                if self.env.edge_validity_checker(x_new, x_near) and (self.compute_cost(x_near_id) + self.env.compute_distance(x_near, x_new) < cost_min):
                    x_min_id = x_near_id
                    x_min = x_near
                    cost_min = self.compute_cost(x_near_id) + self.env.compute_distance(x_near, x_new)

            # Add x_new to tree vertices
            dist = self.env.compute_distance(x_min, x_new)
            self.tree.AddVertex(x_new, cost=dist)
            # Add edge between x_near and x_new
            self.tree.AddEdge(x_min_id, branch_id)

            # Rewire nearby vertices through new vertex
            for x_near_id, x_near in zip(near_neigh_ids, near_neighs):
                if self.env.edge_validity_checker(x_new, x_near) and (self.compute_cost(branch_id) + self.env.compute_distance(x_near, x_new) < self.compute_cost(x_near_id)):
                    self.tree.AddEdge(branch_id, x_near_id)

            # If x_new satisfy the goal criterion (close to the goal within some range), 
            # start looking for vertices to build the path 
            if branch_id % 600 == 0:
                vertex_id, vertex_dist = self.tree.GetNearestVertex(goal_config)
                vertex = self.tree.vertices[vertex_id]
                # print(f"vertex:\n{vertex}")
                if self.env.goal_criterion(vertex):
                    path = []
                    break

        # Double make sure that in case of different max_iter, we won't miss the path after all iterations
        vertex_id, vertex_dist = self.tree.GetNearestVertex(goal_config)
        vertex = self.tree.vertices[vertex_id]
        if self.env.goal_criterion(vertex):
            path = []

        # Search the path
        if path is not None:
            print(f"\n#Iterations: {len(self.tree.vertices)-1}")
            while not np.array_equal(vertex, start_config):
                path.append(tuple(vertex.flatten()))
                # Find the parent of the current vertex
                vertex_id = self.tree.edges[vertex_id]
                vertex = self.tree.vertices[vertex_id]
            path.append(tuple(vertex.flatten()))
            # Reverse the order of vertices
            path.reverse()
            path = np.array(path)

        cost = [self.env.compute_distance(path[i], path[i+1]) for i in range(len(path)-1)]
        end_time = time.time()
        self.tree.time_cost = end_time - start_time
        self.tree.path_cost = round(sum(cost), 4)

        return path

    def extend(self, x_nearest, x_rand):
        # Find action that would take from x_nearest=(x1,y1,z1) ---> x_rand=(x2,y2,z2)
        # Compute distance between x_nearest and x_rand
        dist = self.env.compute_distance(x_nearest, x_rand)
        # Scale the distance according to self.eta
        dist *= self.eta
        # Compute x_new=(x3,y3,z3) using trigonometry
        if self.env.c_space_dim == 2:
            # Compute inclination angle
            alpha = math.atan2(x_rand[1] - x_nearest[1], x_rand[0] - x_nearest[0])
            # Compute (x3,z3)
            x_new = [x_nearest[0] + dist * math.cos(alpha), 
                     x_nearest[1] + dist * math.sin(alpha)]
        elif self.env.c_space_dim == 3:
            # Compute inclination angle
            alpha = math.atan2(x_rand[2] - x_nearest[2], self.env.compute_distance(x_rand[:2], x_nearest[:2]))
            beta = math.atan2(x_rand[1] - x_nearest[1], x_rand[0] - x_nearest[0])
            # Compute (x3,y3,z3)
            x_new = [x_nearest[0] + dist * math.cos(alpha) * math.cos(beta), 
                     x_nearest[1] + dist * math.cos(alpha) * math.sin(beta), 
                     x_nearest[2] + dist * math.sin(alpha)]
        # Align approximate x_new with one of grid cells 
        x_new = np.round(np.array(x_new)).astype(int)

        return x_new

    def sample(self, goal):
        # Sample random point from map
        if np.random.uniform() < self.bias:
            return goal

        return self.env.sample()