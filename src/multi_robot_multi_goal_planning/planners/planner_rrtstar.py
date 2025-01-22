from multi_robot_multi_goal_planning.planners.rrtstar_base import *

"""This file contains the original RRT* based on the paper 'Sampling-based Algorithms for Optimal Motion Planning' by E. Frazolli et al."""

class RRTstar(BaseRRTstar):
    def __init__(self, env, config: ConfigManager):
        super().__init__(env, config)
     
    def UpdateCost(self, n:Node) -> None:
        stack = [n]
        while stack:
            current_node = stack.pop()
            children = current_node.children
            if children:
                for _, child in enumerate(children):
                    child.cost = current_node.cost + child.cost_to_parent
                    child.agent_dists = current_node.agent_dists + child.agent_dists_to_parent
                stack.extend(children)
   
    def ManageTransition(self, n_new: Node, iter: int) -> None:
        if self.env.get_active_task(self.operation.active_mode.label).goal.satisfies_constraints(n_new.state.q.state()[self.operation.active_mode.indices], self.env.tolerance):
            self.operation.active_mode.transition_nodes.append(n_new)
            n_new.transition = True
            # Check if initial transition node of current mode is found
            if self.operation.active_mode.label == self.operation.modes[-1].label and not self.operation.init_sol:
                print(time.time()-self.start)
                print(f"{iter} {self.operation.active_mode.constrained_robots} found T{self.env.get_current_seq_index(self.operation.active_mode.label)}")
                if self.env.terminal_mode != self.operation.modes[-1].label:
                    self.operation.modes.append(Mode(self.env.get_next_mode(n_new.state.q,self.operation.active_mode.label), self.env))
                    self.ModeInitialization(self.operation.modes[-1])
                elif self.operation.active_mode.label == self.env.terminal_mode:
                    self.operation.ptc_iter = iter
                    self.operation.ptc_cost = n_new.cost
                    self.operation.init_sol = True
                    print(time.time()-self.start)
                self.FindLBTransitionNode(iter, True)
                self.AddTransitionNode(n_new)
                return
            self.AddTransitionNode(n_new)
        self.FindLBTransitionNode(iter)
 
    def PlannerInitialization(self) -> None:
        active_mode = self.operation.modes[0]
        self.ModeInitialization(self.operation.modes[0])
        start_state = State(self.env.start_pos, active_mode.label)
        start_node = Node(start_state, self.operation)
        # active_mode.batch_subtree = torch.cat((active_mode.batch_subtree, start_node.q_tensor.unsqueeze(0)), dim=0)
        active_mode.subtree.append(start_node)
        # active_mode.node_idx_subtree = torch.cat((active_mode.node_idx_subtree, torch.tensor([start_node.idx], device=device)),dim=0)
        active_mode.batch_subtree[len(active_mode.subtree)-1, :] = start_node.q_tensor
        
        active_mode.node_idx_subtree[len(active_mode.subtree)-1] = start_node.idx
        start_node.cost = 0
        start_node.cost_to_parent = torch.tensor(0, device=device, dtype=torch.float32)
    
    def Plan(self) -> List[State]:
        i = 0
        self.PlannerInitialization()
        while True:
            i += 1
            # Mode selection
            self.operation.active_mode  = (np.random.choice(self.operation.modes, p= self.SetModePorbability()))
            # RRT* core
            q_rand = self.SampleNodeManifold(self.operation)
            n_nearest= self.Nearest(q_rand, self.operation.active_mode.subtree, self.operation.active_mode.batch_subtree[:len(self.operation.active_mode.subtree)])        
            state_new = self.Steer(n_nearest, q_rand, self.operation.active_mode.label)
            if not state_new: # meaning n_new is exact the same as one of the nodes in the tree
                continue
            # if i == 1538 :
            #     print("hal")
            if self.env.is_collision_free(state_new.q.state(), self.operation.active_mode.label) and self.env.is_edge_collision_free(n_nearest.state.q, state_new.q, self.operation.active_mode.label):
                n_new = Node(state_new, self.operation)
                N_near_indices, N_near_batch, n_near_costs, node_indices = self.Near(n_new, self.operation.active_mode.batch_subtree[:len(self.operation.active_mode.subtree)])
                if n_nearest.idx not in node_indices:
                    continue
                n_nearest_index = torch.where(node_indices == n_nearest.idx)[0].item() 
                # if i%200 == 0:
                #     print(N_near_batch.size())
                batch_cost, batch_dist =  batch_config_torch(n_new.q_tensor, n_new.state.q, N_near_batch, metric = self.config.cost_type)
                self.FindParent(N_near_indices, n_nearest_index, n_new, n_nearest, batch_cost, batch_dist, n_near_costs)
                # if self.operation.init_sol:
                if self.Rewire(N_near_indices, n_new, batch_cost, batch_dist, n_near_costs, n_rand = q_rand.state(), n_nearest = n_nearest.state.q.state() ):
                    self.UpdateCost(n_new)
                    # self.SaveData(time.time()-self.start, n_new = n_new.state.q.state(), N_near = N_near, 
                    #           r =self.r, n_rand = n_rand.state.q.state(), n_nearest = n_nearest.state.q.state()) 
                
                self.ManageTransition(n_new, i)
                # if i%200 == 0:
                #     print(n_new.idx, n_new.cost)
            if self.operation.init_sol and i != self.operation.ptc_iter and (i- self.operation.ptc_iter)%self.config.ptc_max_iter == 0:
                diff = self.operation.ptc_cost - self.operation.cost
                self.operation.ptc_cost = self.operation.cost
                if diff < self.config.ptc_threshold:
                    break
            
            
            # if i >= 50000:
            #     print('i', i)
            #     print('tree', self.operation.tree)
            #     print(torch.cuda.memory_summary())
            #     break
            if i% 1000 == 0:
                if check_gpu_memory_usage():
                    break
            if i% 100000 == 0:
                print(i)

            
         

        self.SaveData(time.time()-self.start)
        print(time.time()-self.start)
        # print('i', i)
        # print('tree', self.operation.tree)
        # print(torch.cuda.memory_summary())
        return self.operation.path    




