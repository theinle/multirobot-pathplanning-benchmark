import numpy as np
import random

from typing import (
    List,
    Dict,
    Tuple,
    Optional,
    Set,
    ClassVar,
    Any,
    Union,
    Generic,
    TypeVar,
    Type
)
from numpy.typing import NDArray
from itertools import chain
import heapq
import time
import math
from abc import ABC, abstractmethod
from multi_robot_multi_goal_planning.problems.planning_env import (
    State,
    BaseProblem,
    Mode,
)
from multi_robot_multi_goal_planning.problems.configuration import (
    Configuration,
    batch_config_dist
)
from multi_robot_multi_goal_planning.problems.util import path_cost, interpolate_path

from multi_robot_multi_goal_planning.planners import shortcutting

from multi_robot_multi_goal_planning.planners.termination_conditions import (
    PlannerTerminationCondition,
)
from multi_robot_multi_goal_planning.planners.rrtstar_base import find_nearest_indices
from multi_robot_multi_goal_planning.planners.rrtstar_base import save_data
# from multi_robot_multi_goal_planning.planners.sampling_phs import (
#     sample_phs_with_given_matrices, compute_PHS_matrices
# )
from multi_robot_multi_goal_planning.planners.sampling_informed import (Informed as BaseInformed)
T = TypeVar("T")
class BaseOperation(ABC):
    """Represents an operation instance responsible for managing variables related to path planning and cost optimization. """
    def __init__(self):

        self.costs = np.empty(10000000, dtype=np.float64)
        self.lb_costs_to_come = np.empty(10000000, dtype=np.float64)

    def get_cost(self, idx:int) -> float:
        """
        Returns cost of node with the specified index.

        Args: 
            idx (int): Index of node whose cost is to be retrieved.

        Returns: 
            float: Cost associated with the specified node."""
        return self.costs[idx]
    
    def get_lb_cost_to_come(self, idx:int) -> float:
        """
        Returns cost of node with the specified index.

        Args: 
            idx (int): Index of node whose cost is to be retrieved.

        Returns: 
            float: Cost associated with the specified node."""
        return self.lb_costs_to_come[idx]
    
    @abstractmethod
    def update(self):
        pass

    def _resize_array(self, array: NDArray, current_capacity: int, new_capacity: int) -> NDArray:
        """
        Dynamically resizes a NumPy array to a new capacity.

        Args: 
            array (NDArray): Array to be resized. 
            current_capacity (int): Current capacity of array.
            new_capacity (int):Target capacity for the array.

        Returns: 
            NDArray: The resized array. 
        """
        new_array = np.empty((new_capacity, *array.shape[1:]), dtype=array.dtype)
        new_array[:current_capacity] = array  # Copy existing data
        del array  # Free old array (Python garbage collector will handle memory)
        return new_array

    def ensure_capacity(self, array: NDArray, required_capacity: int) -> NDArray:
        """ 
        Ensures that a NumPy array has sufficient capacity to accommodate new elements and resizes it if necessary.

        Args: 
            array (NDArray): The array to be checked and potentially resized. 
            required_capacity (int): The minimum required capacity for the array.

        Returns: 
            NDArray: The array with ensured capacity. """
        current_size = array.shape[0]

        if required_capacity == current_size:
            return self._resize_array(array, current_size, required_capacity * 2)  # Double the size

        return array

class BaseNode(ABC):
    __slots__ = [
        "state",
        "forward",
        "rev",
        "is_transition",
        "is_reverse_transition",
        "transition",
        "whitelist",
        "blacklist",
        "id",
        "operation",
        "lb_cost_to_go"
    ]
    
    id_counter: ClassVar[int] = 0
    
    # Instance attributes
    forward: "Relatives"
    rev: "Relatives"
    state: State
    is_transition: bool
    is_reverse_transition:bool
    transition: Optional["BaseNode"]
    whitelist: Set[int]
    blacklist: Set[int]
    id: int
    operation:BaseOperation
    lb_cost_to_go: float

    def __init__(self, operation: BaseOperation, state: State, is_transition: bool = False) -> None:
        self.state = state
        self.forward = Relatives()
        self.rev = Relatives()
        self.is_transition = is_transition
        self.is_reverse_transition = False
        self.transition = None
        self.whitelist = set()
        self.blacklist = set()
        self.id = BaseNode.id_counter
        BaseNode.id_counter += 1
        self.operation = operation
        self.lb_cost_to_go = np.inf
    
    @abstractmethod
    def close(self):
        pass
    @abstractmethod
    def set_to_goal_node(self):
        pass

    def __lt__(self, other: "BaseNode") -> bool:
        return self.id < other.id

    def __hash__(self) -> int:
        return self.id

    @property
    def lb_cost_to_come(self):
        return self.operation.get_lb_cost_to_come(self.id)
    
    @lb_cost_to_come.setter
    def lb_cost_to_come(self, value) -> None:
        """Set the cost in the shared operation costs array.

        Args:
            value (float): Cost value to assign to the current node.

        Returns: 
            None: This method does not return any value."""
        self.operation.lb_costs_to_come[self.id] = value

    @property
    def cost(self):
        return self.operation.get_cost(self.id)
    
    @cost.setter
    def cost(self, value) -> None:
        """Set the cost in the shared operation costs array.

        Args:
            value (float): Cost value to assign to the current node.

        Returns: 
            None: This method does not return any value."""
        self.operation.costs[self.id] = value
        # if not np.isinf(value):
        #     self.lb_cost_to_come = value

class Relatives:
    __slots__ = [
        "parent",
        "children",
        "cost_to_parent",
        "fam"        
    ]
    parent: Optional["BaseNode"]
    children: List[int]
    cost_to_parent: Optional[float]
    fam: Set

    def __init__(self):
        self.parent = None
        self.children = []
        self.cost_to_parent = None
        self.fam = set()

    def reset(self):
        self.parent = None
        self.children = []
        self.cost_to_parent = None
        self.fam.clear()  
class DictIndexHeap(ABC, Generic[T]):
    __slots__ = ["queue", "items", "current_entries", "nodes"]

    queue: List[Tuple[float, int]]  # (priority, index)
    items: Dict[int, Any]  # Dictionary for storing active items
    current_entries: Dict[T, Tuple[float, int]]
    nodes: set
    idx = 0
    def __init__(self, collision_resolution: Optional[float] = None) -> None:
        self.queue = []
        self.items = {}
        self.current_entries = {}  
        heapq.heapify(self.queue)
        self.collision_resolution = collision_resolution

    def __len__(self):
        return len(self.current_entries)
    
    def __contains__(self, item: T) -> bool:
        return item in self.current_entries
    
    @abstractmethod
    def key(self, node: BaseNode) -> float:
        pass

    def heappush(self, item: T) -> None:
        """Push a single item into the heap."""
        # idx = len(self.items)
        priority = self.key(item)
        if item in self.current_entries:
            latest_priority, idx = self.current_entries[item]
            if latest_priority == priority:
                return
            if latest_priority < priority:
        #         # _, _ = heapq.heappop(self.queue)
                del self.items[idx]

        self.push_and_sync(item, priority)
        # self.nodes_in_queue[item[1]] = (priority, DictIndexHeap.idx)
        heapq.heappush(self.queue, (priority, DictIndexHeap.idx))
        DictIndexHeap.idx += 1
  
    def add_and_sync(self, item: T) -> None:
        pass

    def push_and_sync(self, item, priority) -> float:
        self.items[DictIndexHeap.idx] = item  # Store only valid items
        self.current_entries[item] = (priority, DictIndexHeap.idx) # always up to date with the newest one!
        self.add_and_sync(item)

    def peek_first_element(self) -> Any:
        while self.current_entries:
            priority, idx = self.queue[0]
            if idx not in self.items:
                _, _ = heapq.heappop(self.queue)
                continue
            item = self.items[idx]
            if item in self.current_entries:
                current_priority, current_idx = self.current_entries[item]
                # new_priority = self.key(item)
                if current_idx == idx:
                    assert(current_priority == priority), (
                        "queue wrong"
                    )
                    # if new_priority != priority: #needed if reverse search changed priorities
                    #     _, idx = heapq.heappop(self.queue)
                    #     item = self.pop_and_sync(idx)
                    #     self.heappush(item) 
                    #     continue
                    return priority, item
            _, idx = heapq.heappop(self.queue)
            _ = self.items.pop(idx)
            continue

    def remove(self, item, in_current_entries:bool = False):
        if not in_current_entries and item not in self.current_entries:
           return
        del self.current_entries[item]
    
    def heappop(self) -> BaseNode:
        """Pop the item with the smallest priority from the heap."""
        if not self.queue:
            raise IndexError("pop from an empty heap")

         # Remove from dictionary (Lazy approach)
        while self.current_entries:
            priority, idx = heapq.heappop(self.queue)
            if idx not in self.items:
                continue
            item = self.items.pop(idx)
            if item in self.current_entries:
                current_priority, current_idx = self.current_entries[item]
                # new_priority = self.key(item)
                if current_idx == idx:
                    assert(current_priority == priority), (
                        "queue wrong"
                    )
                    # if new_priority != priority: #needed if reverse search changed priorities
                    #     if type(item) is BaseNode:
                    #         pass
                    #     self.heappush(item) 
                    #     continue
                    self.remove(item, True)
                    return item
            
                
        raise IndexError("pop from an empty queue")
class BaseTree():
    all_vertices = set()
    def __init__(self, 
                 operation:BaseOperation, 
                 robot_dims, 
                 batch_dist_fun, 
                 batch_cost_fun, 
                 update_connectivity, 
                 remove_forward_queue,
                 is_edge_collision_free
                 ):

        self.operation = operation
        self.cnt = 0
        self.vertices = {}
        self.vertices_node_ids = np.empty(100000, dtype=np.int64)
        self.vertices_batch_array = np.empty((100000, robot_dims), dtype=np.float64)
        self.vertices_position = {}
        self.batch_dist_fun = batch_dist_fun
        self.batch_cost_fun = batch_cost_fun
        self.update_connectivity = update_connectivity
        self.remove_forward_queue = remove_forward_queue
        self.is_edge_collision_free = is_edge_collision_free

    def ensure_capacity(self,array: NDArray, required_capacity: int) -> NDArray:
        return self.operation.ensure_capacity(array, required_capacity)
       
    def add_vertex(self, node: BaseNode) -> None:  
        if node.id in BaseTree.all_vertices:
            return
        BaseTree.all_vertices.add(node.id)         
        position = self.cnt
        self.vertices_position[node.id] = position
        self.vertices_batch_array = self.ensure_capacity(self.vertices_batch_array, position)
        self.vertices_batch_array[position,:] = node.state.q.state()
        self.vertices_node_ids = self.ensure_capacity(self.vertices_node_ids, position)
        self.vertices_node_ids[position] = node.id
        self.vertices[node.id] = node
        self.cnt +=1
    
    def get_vertices_batch_array(self)-> NDArray:
        return self.vertices_batch_array[:self.cnt]

    def get_vertices_node_ids(self)-> NDArray:
        return self.vertices_node_ids[:self.cnt]
    
    def get_position_of_node(self, node:BaseNode) -> int:
        return self.vertices_position[node.id]
 
    def neighbors(self, 
             node: BaseNode, 
             potential_parent:BaseNode, 
             r:float,
             ) -> Tuple[NDArray, NDArray, NDArray]:      
        """
        Retrieves neighbors of a node within a calculated radius for the given mode.

        Args:
            node (Node): New node for which neighbors are being identified.
            n_nearest_idx (int): Index of the nearest node to node.
            set_dists (Optional[NDArray]): Precomputed distances from n_new to all nodes in the specified subtree.
            tree (str): Identifier of subtree in which the nearest node is searched for

        Returns:
            Tuple:   
                - NDArray: Batch of neighbors near n_new.
                - NDArray: Corresponding cost values of these nodes.
                - NDArray: Corresponding IDs of these nodes.
        """
        #node is not yet in the tree
        batch_array= self.get_vertices_batch_array()
        set_dists = self.batch_dist_fun(node.state.q, batch_array)
        indices = find_nearest_indices(set_dists, r) # indices of batch_subtree
        if potential_parent is not None:
            potential_parent_idx = self.get_position_of_node(potential_parent)
            if potential_parent_idx not in indices:
                indices = np.insert(indices, 0, potential_parent_idx)
        node_indices = self.get_vertices_node_ids()[indices]
        n_near_costs = self.operation.costs[node_indices]
        N_near_batch = batch_array[indices]
        batch_cost = self.batch_cost_fun(node.state.q, N_near_batch)
        return batch_cost, n_near_costs, node_indices
    
    def find_parent(self, 
                    node: BaseNode, 
                    potential_parent:BaseNode,  
                    batch_cost: NDArray, 
                    n_near_costs: NDArray,
                    node_indices: NDArray,
                    goal_node_ids: NDArray,
                    ) -> None:
        """
        Sets the optimal parent for a new node by evaluating connection costs among candidate nodes.

        Args:
            mode (Mode): Current operational mode.
            node_indices (NDArray): Array of IDs representing candidate neighboring nodes.
            n_new (Node): New node that needs a parent connection.
            n_nearest (Node): Nearest candidate node to n_new.
            batch_cost (NDArray): Costs associated from n_new to all candidate neighboring nodes.
            n_near_costs (NDArray): Cost values for all candidate neighboring nodes.

        Returns:
            None: This method does not return any value.
        """

        idx =  np.where(node_indices == potential_parent.id)[0][0]
        c_new_tensor = n_near_costs + batch_cost
        c_min = c_new_tensor[idx]
        c_min_to_parent = batch_cost[idx]
        n_min = potential_parent
        if node.is_transition and node.is_reverse_transition:
            return n_min, c_min_to_parent 
        valid_mask = c_new_tensor < c_min
        if np.any(valid_mask):
            sorted_indices = np.where(valid_mask)[0][np.argsort(c_new_tensor[valid_mask])]
            for idx in sorted_indices:
                n = self.vertices[node_indices[idx].item()]
                if n.id  in goal_node_ids:
                    continue
                if self.is_edge_collision_free(n.state.q, node.state.q, node.state.mode):
                    c_min = c_new_tensor[idx]
                    c_min_to_parent = batch_cost[idx]      
                    n_min = n                            
                    break
                # else:
                #     #TODO remove from forward queue
                #     node.blacklist.add(n.id)
                #     n.blacklist.add(node.id)
        return n_min, c_min_to_parent

    def rewire(self, 
                node: BaseNode, 
                batch_cost: NDArray, 
                n_near_costs: NDArray,
                node_indices: NDArray,
               ) -> bool:
        """
        Rewires neighboring nodes by updating their parent connection to n_new if a lower-cost path is established.

        Args:
            mode (Mode): Current operational mode.
            node_indices (NDArray): Array of IDs representing candidate neighboring nodes.
            n_new (Node): New node as potential parent for neighboring nodes.
            batch_cost (NDArray): Costs associated from n_new to all candidate neighboring nodes.
            n_near_costs (NDArray): Cost values for all candidate neighboring nodes.

        Returns:
            bool: True if any neighbor's parent connection is updated to n_new; otherwise, False.
        """

        c_potential_tensor = node.cost + batch_cost

        improvement_mask = c_potential_tensor < n_near_costs
        
        if np.any(improvement_mask):
            improved_indices = np.nonzero(improvement_mask)[0]

            for idx in improved_indices:
                n_near = self.vertices[node_indices[idx].item()]
                if n_near.is_transition and n_near.is_reverse_transition:
                    continue
                if n_near == node.forward.parent or n_near.cost == np.inf or n_near.id == node.id:
                    continue
                if node.state.mode == n_near.state.mode or node.state.mode == n_near.state.mode.prev_mode:
                    if self.is_edge_collision_free(node.state.q, n_near.state.q, node.state.mode):
                        edge_cost = float(batch_cost[idx])
                        self.update_connectivity(node, n_near, edge_cost, node.cost + edge_cost)
                    # else:
                    #     #TODO need to remove form forward queue
                    #     node.blacklist.add(n_near.id)
                    #     n_near.blacklist.add(node.id)

class BaseGraph(ABC):
    root: BaseNode
    nodes: Dict
    node_ids: Dict
    tree: BaseTree

    def __init__(self, 
                 root_state, 
                 operation:BaseOperation,
                 distance_metric: str, 
                 batch_dist_fun, 
                 batch_cost_fun, 
                 is_edge_collision_free, 
                 collision_resolution,
                 node_cls: Type["BaseNode"] = BaseNode,
                 including_effort: bool = False):
        self.operation = operation
        self.distance_metric = distance_metric
        self.node_cls = node_cls
        self.root = self.node_cls(operation, root_state)
        self.dim = len(self.root.state.q.state())
        self.operation.update(self.root, lb_cost_to_go=np.inf, cost = 0, lb_cost_to_come = 0.0)
        self.batch_dist_fun = batch_dist_fun
        self.batch_cost_fun = batch_cost_fun
        self.is_edge_collision_free = is_edge_collision_free
        self.collision_resolution = collision_resolution
        self.including_effort = including_effort

        self.nodes = {}  # contains all the nodes ever created
        self.nodes[self.root.id] = self.root
        
        self.node_ids = {}
        self.node_ids[self.root.state.mode] = [self.root.id]
        self.tree = {}
        self.transition_node_ids = {}  # contains the transitions at the end of the mode
        self.reverse_transition_node_ids = {}
        self.reverse_transition_node_ids[self.root.state.mode] = [self.root.id]
        self.goal_nodes = []
        self.goal_node_ids = []
        self.initialize_cache()
        self.unit_n_ball_measure = ((np.pi**0.5) ** self.dim) / math.gamma(self.dim / 2 + 1) 
        self.new_path = None
        self.weight = 1
        
    def get_num_samples(self) -> int:
        num_samples = 0
        for k, v in self.node_ids.items():
            num_samples += len(v)

        num_transition_samples = 0
        for k, v in self.transition_node_ids.items():
            num_transition_samples += len(v)

        return num_samples + num_transition_samples
    
    def add_node(self, new_node, cost:float = np.inf, lb_cost_to_go:float = np.inf) -> None:
        self.nodes[new_node.id] = new_node
        key = new_node.state.mode
        if key not in self.node_ids:
            self.node_ids[key] = []
        self.node_ids[key].append(new_node.id)
        self.operation.update(new_node, lb_cost_to_go, cost)
        
    def add_vertex_to_tree(self, node: BaseNode) -> None:  
        mode = node.state.mode
        if mode not in self.tree: 
            self.tree[mode] = BaseTree(self.operation, 
                                       self.dim, 
                                       batch_dist_fun = self.batch_dist_fun,
                                       batch_cost_fun = self.batch_cost_fun,
                                       update_connectivity = self.update_connectivity,
                                       remove_forward_queue = self.remove_forward_queue,
                                       is_edge_collision_free = self.is_edge_collision_free)
        self.tree[mode].add_vertex(node)

    def add_states(self, states: List[State]):
        for s in states:
            self.add_node(self.node_cls(self.operation, s))

    def add_nodes(self, nodes: List[BaseNode]):
        for n in nodes:
            self.add_node(n)

    def add_transition_nodes(self, transitions: Tuple[Configuration, Mode, Mode]):
        
        for q, this_mode, next_mode in transitions:
            node_this_mode = self.node_cls(self.operation, State( q, this_mode), True)
            node_next_mode = self.node_cls(self.operation, State( q, next_mode), True)

            if this_mode in self.transition_node_ids:
                if self.transition_or_goal_is_already_present(node_this_mode) is not None:
                    continue
            is_goal = True
            if next_mode is not None:
                is_goal = False
                node_next_mode.transition = node_this_mode
                node_this_mode.transition = node_next_mode
                assert this_mode.task_ids != next_mode.task_ids
                self.update_edge_collision_cache(node_this_mode,node_next_mode, True)

            self.add_transition_node(node_this_mode, is_goal=is_goal)
            self.add_transition_node(node_next_mode, reverse=True)

    def add_transition_node(self, node, is_goal:bool = False, reverse:bool = False, cost:float = np.inf, lb_cost_to_go:float = np.inf):
        mode = node.state.mode
        if mode is None:
            return 
        
        if is_goal:
            self.goal_nodes.append(node)
            self.goal_node_ids.append(node.id)

        if not reverse:
            if mode in self.transition_node_ids:
                self.transition_node_ids[mode].append(node.id)
            else:
                self.transition_node_ids[mode] = [node.id]

        if reverse:
            node.is_reverse_transition = True 
            if mode in self.reverse_transition_node_ids:
                self.reverse_transition_node_ids[mode].append(node.id) 
            else:
                self.reverse_transition_node_ids[mode] = [node.id]

        self.nodes[node.id] = node
        self.operation.update(node, lb_cost_to_go, cost)
    
    def add_path_states(self, path:List[State], space_extent):
        self.new_path = []
        parent = self.root
        for i in range(len(path)):
            if i == 0:
                continue
            is_transition = False
            next_mode = None
            if (
                i < len(path) - 1
                and path[i].mode
                != path[i + 1].mode
            ):
                is_transition = True
                next_mode = path[i+1].mode
            if i == len(path)-1:
                is_transition = True
            node = self.node_cls(self.operation, path[i], is_transition)
            if node.id == 1810:
                pass
            if is_transition:
                if parent.is_transition and parent.is_reverse_transition and self.reverse_transition_is_already_present(node):
                    continue
                n = self.transition_or_goal_is_already_present(node)
                if n is not None:
                    edge_cost = float(self.batch_cost_fun([parent.state], [n.state]))
                    self.update_connectivity(parent, n, edge_cost, parent.cost + edge_cost)
                    self.new_path.append(n)
                    if n.transition is not None:
                        self.new_path.append(n.transition)
                        self.update_connectivity(n, n.transition, 0.0, n.cost)
                        r = self.get_r_star(self.tree[n.transition.state.mode].cnt, space_extent, self.unit_n_ball_measure)
                        batch_cost, n_near_costs, node_indices = self.tree[n.transition.state.mode].neighbors(n.transition, None, r)
                        self.tree[n.transition.state.mode].rewire(n.transition, batch_cost, n_near_costs, node_indices)
                    parent = self.new_path[-1]
                    continue

            self.add_path_node(node, parent, is_transition, next_mode, space_extent)
            parent = self.new_path[-1]     
        return 

    def add_path_node(self, node, parent, is_transition:bool, next_mode:Mode, space_extent): 
        self.new_path.append(node)
        if is_transition:
            edge_cost = float(self.batch_cost_fun([parent.state], [node.state]))
            self.update_connectivity(parent, node, edge_cost, parent.cost + edge_cost)
            is_goal = True
            node_next_mode = self.node_cls(self.operation, State(node.state.q, next_mode), is_transition)   
            self.add_vertex_to_tree(node)         
            if next_mode is not None:
                self.new_path.append(node_next_mode)
                is_goal = False
                self.update_connectivity(node, node_next_mode, 0.0, node.cost)

                node.transition = node_next_mode
                node_next_mode.transition = node
                
                r = self.get_r_star(self.tree[node_next_mode.state.mode].cnt, space_extent, self.unit_n_ball_measure)
                batch_cost, n_near_costs, node_indices = self.tree[node_next_mode.state.mode].neighbors(node_next_mode, None, r) 
                self.tree[node_next_mode.state.mode].rewire(node_next_mode, batch_cost, n_near_costs, node_indices)
                self.add_vertex_to_tree(node_next_mode)
            else:
                node.set_to_goal_node()

            self.add_transition_node(node, is_goal=is_goal, cost=node.cost)
            self.add_transition_node(node_next_mode, reverse=True, cost=node.cost)
            
            
        else:
            r = self.get_r_star(self.tree[node.state.mode].cnt, space_extent, self.unit_n_ball_measure)
            batch_cost, n_near_costs, node_indices = self.tree[node.state.mode].neighbors(node, parent, r) 
            true_parent, true_edge_cost = self.tree[node.state.mode].find_parent(node, parent, batch_cost, n_near_costs, node_indices, self.goal_node_ids) 
            self.update_connectivity(true_parent, node, float(true_edge_cost), true_parent.cost + float(true_edge_cost))
            self.tree[node.state.mode].rewire(node, batch_cost, n_near_costs, node_indices)
            self.add_node(node, cost=node.cost)
            self.add_vertex_to_tree(node)

    def transition_or_goal_is_already_present(self, node:BaseNode):  
        if len(self.transition_node_ids[node.state.mode]) > 0:
            configs_list = [
                            self.nodes[id].state.q
                            for id in self.transition_node_ids[node.state.mode]
                            ]
        
            dists = self.batch_dist_fun(node.state.q, configs_list)
            min_index = np.argmin(dists)
            min_dist = dists[min_index]

            if min_dist < 1e-6:
                id = self.transition_node_ids[node.state.mode][min_index]
                return self.nodes[id]
        return None
    
    def reverse_transition_is_already_present(self, node:BaseNode):  
        if len(self.transition_node_ids[node.state.mode]) > 0:
            configs_list = [
                            self.nodes[id].state.q
                            for id in self.reverse_transition_node_ids[node.state.mode]
                            ]
        
            dists = self.batch_dist_fun(node.state.q, configs_list)

            if np.min(dists) < 1e-6:
                return True
        return False

    def update_cache(self, key: Mode):
        if key in self.node_ids and key not in self.node_array_cache:
            ids = self.node_ids[key]
            self.node_array_cache[key] = np.empty((len(ids), self.dim ), dtype=np.float64)
            for i, id in enumerate(ids):
                self.node_array_cache[key][i] = self.nodes[id].state.q.q
        if key in self.transition_node_ids and key not in self.transition_node_array_cache:
            ids = self.transition_node_ids[key]
            self.transition_node_array_cache[key] = np.empty((len(ids), self.dim ), dtype=np.float64)
            for i, id in enumerate(ids):
                self.transition_node_array_cache[key][i] = self.nodes[id].state.q.q
        if key in self.reverse_transition_node_ids and key not in self.reverse_transition_node_array_cache:
            ids = self.reverse_transition_node_ids[key]
            self.reverse_transition_node_array_cache[key] = np.empty((len(ids), self.dim ), dtype=np.float64)
            for i, id in enumerate(ids):
                self.reverse_transition_node_array_cache[key][i] = self.nodes[id].state.q.q
        if key.prev_mode is None and key not in self.reverse_transition_node_array_cache:
            self.reverse_transition_node_array_cache[key] = np.array([self.root.state.q.q], dtype=np.float6)

    def initialize_cache(self):
        # modes as keys
        self.node_array_cache = {} 
        self.transition_node_array_cache = {}

        # node ids as keys
        self.neighbors_node_ids_cache = {} #neighbors received by radius
        self.neighbors_batch_cost_cache = {}
        self.neighbors_fam_ids_cache = {}
        self.tot_neighbors_batch_cost_cache = {}
        self.tot_neighbors_batch_effort_cache = {} #only needed for EIT*
        self.neighbors_batch_effort_cache = {}
        self.tot_neighbors_id_cache = {} #neighbors including family
        self.transition_node_lb_cache = {}
        self.reverse_transition_node_lb_cache = {}
        self.reverse_transition_node_array_cache = {}

        self.blacklist_cache = {}

    def get_r_star(
        self, number_of_nodes, informed_measure, unit_n_ball_measure, wheight=1):
        # r_star = (
        #     1.001
        #     * wheight
        #     * (
        #         (2 * (1 + 1 / self.dim))
        #         * (informed_measure / unit_n_ball_measure)
        #         * (np.log(number_of_nodes) / number_of_nodes)
        #     )
        #     ** (1 / self.dim)
        # )

        r_star = (
            1.001
            * 2* wheight
            * (
                ((1 + 1 / self.dim))
                * (informed_measure / unit_n_ball_measure)
                * (np.log(number_of_nodes) / number_of_nodes)
            )
            ** (1 / self.dim)
        )
        return r_star

    def get_neighbors(
        self, node: BaseNode, space_extent: float = 1, first_search:bool = False
    ) -> set:
         
        if node.id in self.neighbors_node_ids_cache:
            return self.update_neighbors(node)            
        key = node.state.mode
        self.update_cache(key)

        #initialize
        all_node_ids, all_node_arrays = [], []
        node_ids = np.empty(0, dtype=np.int64)
        if key in self.node_ids:
            dists = self.batch_dist_fun(node.state.q, self.node_array_cache[key])
            r_star = self.get_r_star(
                len(self.node_ids[key]), 
                space_extent, 
                self.unit_n_ball_measure, 
                self.weight
                )
            indices = find_nearest_indices(dists, r_star)
            if indices.size > 0:
                node_ids = np.array(self.node_ids[key])[indices]
                best_nodes_arr = self.node_array_cache[key][indices]
                all_node_ids.append(node_ids)
                all_node_arrays.append(best_nodes_arr)


        if key in self.transition_node_ids:
            transition_dists = self.batch_dist_fun(
                node.state.q, self.transition_node_array_cache[key]
            )

            r_star = self.get_r_star(
                len(self.transition_node_ids[key]),
                space_extent,
                self.unit_n_ball_measure,
                self.weight
                )
            if len(self.transition_node_ids[key]) == 1:
                r_star = 1e6

            indices_transitions = find_nearest_indices(transition_dists, r_star)
            if indices_transitions.size > 0:
                transition_node_ids = np.array(self.transition_node_ids[key])[indices_transitions]
                best_transitions_arr = self.transition_node_array_cache[key][indices_transitions]
                all_node_ids.append(transition_node_ids)
                all_node_arrays.append(best_transitions_arr)


        if key in self.reverse_transition_node_array_cache:
            reverse_transition_dists = self.batch_dist_fun(
                node.state.q, self.reverse_transition_node_array_cache[key]
            )
            r_star = self.get_r_star(
                len(self.reverse_transition_node_ids[key]),
                space_extent,
                self.unit_n_ball_measure,
                self.weight
                )

            if len(self.reverse_transition_node_array_cache[key]) == 1 and self.reverse_transition_node_ids[key][0] not in node_ids:
                r_star = 1e6

            indices_reverse_transitions = find_nearest_indices(reverse_transition_dists, r_star)
            if indices_reverse_transitions.size > 0:
                reverse_transition_node_ids = np.array(self.reverse_transition_node_ids[key])[indices_reverse_transitions]
                best_reverse_transitions_arr = self.reverse_transition_node_array_cache[key][indices_reverse_transitions]
                all_node_ids.append(reverse_transition_node_ids)
                all_node_arrays.append(best_reverse_transitions_arr)
    
        #set them all together
        if all_node_ids and all_node_arrays:
            all_ids = np.concatenate(all_node_ids)
            arr = np.vstack(all_node_arrays, dtype=np.float64)
        else:
            all_ids = np.array([], dtype=np.int64)
            arr = np.empty((0, node.state.q.shape[0]), dtype=np.float64)

        if node.is_transition and node.transition is not None:
            all_ids = np.concatenate((all_ids, np.array([node.transition.id])))
            arr = np.vstack([arr, node.transition.state.q.state()])


        assert node.id in all_ids, (
        " ohhh nooooooooooooooo"        
        )
        #remove node itself
        mask = all_ids != node.id
        all_ids = all_ids[mask]
        arr = arr[mask]

        assert node.id not in self.neighbors_node_ids_cache,("2 already calculated")
        self.neighbors_node_ids_cache[node.id] = all_ids 
        self.neighbors_batch_cost_cache[node.id] = self.batch_cost_fun(node.state.q, arr)
        self.blacklist_cache[node.id] = set()
        if self.including_effort:
                self.neighbors_batch_effort_cache[node.id] = self.batch_dist_fun(node.state.q, arr, c = 'max')/self.collision_resolution
        if first_search:
            self.tot_neighbors_batch_cost_cache[node.id] = self.neighbors_batch_cost_cache[node.id]
            self.tot_neighbors_id_cache[node.id] = all_ids
            if self.including_effort:
                self.tot_neighbors_batch_effort_cache[node.id] = self.neighbors_batch_effort_cache[node.id]
            return all_ids
        return self.update_neighbors(node, True)

    def update_neighbors_with_family_of_node(self, node: BaseNode, update: bool = False):
        node_id = node.id
        blacklist = node.blacklist

        # Compute current family (forward + reverse)
        current_fam = node.forward.fam | node.rev.fam
        assert not (current_fam & blacklist), (
           "items from the set are in the array" 
        )

        latest_fam = self.neighbors_fam_ids_cache.get(node_id, set())

        # Check if there's any change in the family or forced update
        fam_changed = current_fam != latest_fam
        if not update and not fam_changed:
            return self.tot_neighbors_id_cache.get(node_id, self.neighbors_node_ids_cache[node_id])

        # Save new family state
        self.neighbors_fam_ids_cache[node_id] = current_fam

        # Base neighbor list (already filtered by blacklist in update_neighbors)
        base_ids = self.neighbors_node_ids_cache[node_id]
        base_cost = self.neighbors_batch_cost_cache[node_id]
        base_set = set(base_ids)


        # New family members not already in base
        new_ids = np.array(list(current_fam - base_set), dtype=np.int64)
        if new_ids.size > 0:
            new_arr = np.array([self.nodes[id_].state.q.q for id_ in new_ids], dtype=np.float64)
            new_costs = self.batch_cost_fun(node.state.q, new_arr)
            self.tot_neighbors_id_cache[node_id] = np.concatenate((new_ids, base_ids))
            self.tot_neighbors_batch_cost_cache[node_id] = np.concatenate((new_costs, base_cost))
            if self.including_effort:
                new_effort = self.batch_dist_fun(node.state.q, new_arr, c = 'max')/self.collision_resolution
                self.tot_neighbors_batch_effort_cache[node_id] = np.concatenate((new_effort, self.neighbors_batch_effort_cache[node_id]))
        else:
            self.tot_neighbors_id_cache[node_id] = base_ids
            self.tot_neighbors_batch_cost_cache[node_id] = base_cost
            if self.including_effort:
                self.tot_neighbors_batch_effort_cache[node_id] = self.neighbors_batch_effort_cache[node_id]

        assert len(self.tot_neighbors_id_cache[node_id]) == len(self.tot_neighbors_batch_cost_cache[node_id]), "forward not right"
        assert len(self.tot_neighbors_id_cache[node_id]) >= len(self.neighbors_batch_cost_cache[node_id]), "sth not right"
        assert not (set(self.tot_neighbors_id_cache[node_id]) & blacklist), (
           "items from the set are in the array" 
        )
        assert (set(self.tot_neighbors_id_cache[node_id]) & current_fam) == current_fam, (
          "items from the set are not in the array"  
        )
        return self.tot_neighbors_id_cache[node_id]

    def update_neighbors(self, node:BaseNode, update:bool =False): # only needed for forward
        blacklist = node.blacklist
        blacklist_diff = blacklist -  self.blacklist_cache[node.id]
        if blacklist_diff:
            update=True
            self.neighbors_fam_ids_cache[node.id] = set()
            self.blacklist_cache[node.id] = blacklist.copy()
            node_ids = self.neighbors_node_ids_cache[node.id]
            if node_ids.size == 0:
                return self.update_neighbors_with_family_of_node(node, update)
            blacklist_array = np.fromiter(blacklist, dtype=np.int64)
            mask = ~np.isin(node_ids, blacklist_array)
            if np.any(~mask):
                self.neighbors_node_ids_cache[node.id] = node_ids[mask]
                self.neighbors_batch_cost_cache[node.id] = self.neighbors_batch_cost_cache[node.id][mask]
                if self.including_effort:
                    self.neighbors_batch_effort_cache[node.id] = self.neighbors_batch_effort_cache[node.id][mask]
            assert not (set(self.neighbors_node_ids_cache[node.id]) & node.blacklist), (
                                "items from the set are in the array"
                            )
        return self.update_neighbors_with_family_of_node(node, update)
            
    def update_forward_cost_of_children(self, n: BaseNode, start_nodes_to_update:set[int]) -> set[int]:
        stack = [n.id]
        while stack:
            current_id = stack.pop()
            current_node = self.nodes[current_id]
            children = current_node.forward.children
            if children:
                for _, id in enumerate(children):
                    child = self.nodes[id]
                    new_cost = current_node.cost + child.forward.cost_to_parent
                    child.cost = new_cost
                    start_nodes_to_update.add(child.id)
                stack.extend(children)
        return start_nodes_to_update
    
    def update_forward_cost(self, node:BaseNode):
        start_nodes_to_update = set()
        start_nodes_to_update.add(node.id)
        if len(node.forward.children) > 0:
            start_nodes_to_update = self.update_forward_cost_of_children(node, start_nodes_to_update)
        self.update_forward_queue_keys('start', start_nodes_to_update)
        
    def update_connectivity(self, n0: BaseNode, n1: BaseNode, edge_cost, updated_cost, tree: str = "forward", is_transition:bool = False):
        if tree == "forward":
            if n1.forward.parent is None: 
                n0.forward.children.append(n1.id)
            elif n1.forward.parent.id != n0.id:
                n1.forward.parent.forward.children.remove(n1.id)
                n1.forward.parent.forward.fam.remove(n1.id)
                n1.forward.fam.remove(n1.forward.parent.id)
                n0.forward.children.append(n1.id)
            n1.forward.parent = n0
            # assert (n1.lb_cost_to_come - updated_cost)<=1e-15, (
            #         "ohhhhhhhhhhhhhh something is wrong with the lb cost to go"
            #     )
            n1.forward.cost_to_parent = edge_cost
            assert n1.id in n0.forward.children, (
                "not a child")
            
            
            if updated_cost != n1.cost:
                n1.cost = updated_cost
                self.update_forward_cost(n1)
                
                
            # else:
            #     print("uhhh")
            self.update_edge_collision_cache(n1, n0, True)
            self.add_vertex_to_tree(n1)
            self.add_vertex_to_tree(n0)
            n1.forward.fam.add(n0.id)
            n0.forward.fam.add(n1.id)
            if is_transition and n1.transition.forward.parent is None:
                self.update_connectivity(n1, n1.transition, 0.0, n1.cost ,"forward")

        else:
            n1.lb_cost_to_go = updated_cost
            if n1.rev.parent is not None:
                if n1.rev.parent.id == n0.id:
                    if is_transition:
                        self.update_connectivity(n1, n1.transition, 0.0, n1.lb_cost_to_go,"reverse", False)
                    return
                if n1.rev.parent.id != n0.id:
                    # assert [
                    #             (self.nodes[child].rev.parent, child)
                    #             for child in n1.rev.parent.rev.children
                    #             if self.nodes[child].rev.parent is None
                    #             or self.nodes[child].rev.parent.id != n1.rev.parent.id
                    #         ] == [], "parent and children not correct"

                    n1.rev.parent.rev.children.remove(n1.id)
                    n1.rev.parent.rev.fam.remove(n1.id)
                    n1.rev.fam.remove(n1.rev.parent.id)
                    n0.rev.children.append(n1.id)
            else:
                n0.rev.children.append(n1.id)

            # assert (n1.lb_cost_to_go != n0.lb_cost_to_go_expanded + edge_cost), (
            # "asdf")
            n1.rev.parent = n0
            assert n1.id in n0.rev.children, (
                "not a child")
            
            n1.rev.cost_to_parent = edge_cost
            # assert [
            #             (self.nodes[child].rev.parent, child)
            #             for child in n1.rev.parent.rev.children
            #             if self.nodes[child].rev.parent is None
            #             or self.nodes[child].rev.parent.id != n1.rev.parent.id
            #         ] == [], (
            #             "new parent and new children not correct")
            if n0.state.mode.next_modes == []:
                assert n1.lb_cost_to_go >= float(self.batch_cost_fun([n1.state], [n0.state])), (
                "something is wrong with the lb cost to go"
            )
            else:
                goal_nodes = np.array([n.state.q.state() for n in self.goal_nodes])
                assert min((self.batch_cost_fun(n1.state.q, goal_nodes))) - n1.lb_cost_to_go <=1e-15 , (
                    "something is wrong with the lb cost to go"
                )

            # if (n1.test - n1.lb_cost_to_go )>1e-15:
            #     return
            # if not np.isinf(n1.test):
            #     assert (n1.test - n1.lb_cost_to_go )<=1e-15, (
            #             "ohhhhhhhhhhhhhh something is wrong with the lb cost to go"
            #         )
            # if not n1.is_transition:
            #     assert not np.isinf(n1.lb_cost_to_go), (
            #         "wrongg update"
            #     )
            n1.rev.fam.add(n0.id)
            n0.rev.fam.add(n1.id)
            if is_transition:
                self.update_connectivity(n1, n1.transition, 0.0, n1.lb_cost_to_go, "reverse", False)

    def compute_transition_lb_to_come(self, compute_lb_effort_to_go:bool = False):
        # run a reverse search on the transition nodes without any collision checking
        costs = {}
        transition_nodes = {}
        processed = 0

        closed_set = set()

        queue = []
        heapq.heappush(queue, (0, self.root))
        costs[self.root.id] = 0
        if compute_lb_effort_to_go:
            self.root.lb_effort_to_come = 0

        while len(queue) > 0:
            _, node = heapq.heappop(queue)
            mode = node.state.mode
            if node.id in closed_set:
                continue
            closed_set.add(node.id)
            if mode not in self.transition_node_ids:
                continue
            if mode not in transition_nodes:
                if mode.task_ids == self.goal_nodes[0].state.mode.task_ids:
                    transition_nodes[mode] = self.goal_nodes
                else:
                    transition_nodes[mode] = [self.nodes[id].transition for id in self.transition_node_ids[mode]]

            if len(transition_nodes[mode]) == 0:
                continue
            self.update_cache(mode)
            
            if mode not in self.transition_node_array_cache:
                continue

            # add neighbors to open_queue
            edge_costs = self.batch_cost_fun(
                node.state.q,
                self.transition_node_array_cache[mode],
            )

            parent_cost = costs[node.id]
            for edge_cost, n in zip(edge_costs, transition_nodes[mode]):
                cost = parent_cost + edge_cost
                id = n.id
                if id not in costs or cost < costs[id]:
                    costs[id] = cost
                    n.lb_cost_to_come = cost
                    if compute_lb_effort_to_go:
                        n.lb_effort_to_come =  n.lb_cost_to_come/self.collision_resolution
                    if n.transition is not None:
                        n.transition.lb_cost_to_come = cost
                        if compute_lb_effort_to_go:
                            n.transition.lb_effort_to_come = n.lb_effort_to_come
                    processed += 1
                    heapq.heappush(queue, (cost, n))
        # print(processed)

    def compute_transition_lb_effort_to_come(self):
        # run a reverse search on the transition nodes without any collision checking
        efforts = {}
        transition_nodes = {}
        processed = 0

        closed_set = set()

        queue = []
        heapq.heappush(queue, (0, self.root))
        efforts[self.root.id] = 0

        while len(queue) > 0:
            _, node = heapq.heappop(queue)
            mode = node.state.mode
            if node.id in closed_set:
                continue
            closed_set.add(node.id)
            if mode not in self.transition_node_ids:
                continue
            if mode not in transition_nodes:
                if mode.task_ids == self.goal_nodes[0].state.mode.task_ids:
                    transition_nodes[mode] = self.goal_nodes
                else:
                    transition_nodes[mode] = [self.nodes[id].transition for id in self.transition_node_ids[mode]]

            if len(transition_nodes[mode]) == 0:
                continue
            self.update_cache(mode)
            
            if mode not in self.transition_node_array_cache:
                continue

            # add neighbors to open_queue
            edge_efforts = self.batch_dist_fun(
                node.state.q,
                self.transition_node_array_cache[mode],
                c = 'max'
            )/self.collision_resolution
            parent_effort = efforts[node.id]
            for edge_effort, n in zip(edge_efforts, transition_nodes[mode]):
                effort = parent_effort + edge_effort
                if n.id not in efforts or effort < efforts[n.id]:
                    efforts[n.id] = effort
                    n.lb_effort_to_come = effort
                    if n.transition is not None:
                        n.transition.lb_effort_to_come = effort
                    processed += 1
                    heapq.heappush(queue, (effort, n))
        # print(processed) 

    def compute_node_lb_to_come(self, compute_lb_effort_to_go:bool = False):
        processed = 0
        reverse_transition_node_lb_cache = {}
        for mode in self.node_ids:
            for id in self.node_ids[mode]:
                n = self.nodes[id]
                mode = n.state.mode
                if mode not in self.reverse_transition_node_array_cache:
                    continue

                if mode not in reverse_transition_node_lb_cache:
                    reverse_transition_node_lb_cache[mode] = np.array(
                        [
                            self.nodes[id].lb_cost_to_come
                            for id in self.reverse_transition_node_ids[mode]
                        ],
                        dtype=np.float64,
                    )

                costs_to_transitions = self.batch_cost_fun(
                    n.state.q,
                    self.reverse_transition_node_array_cache[mode],
                )
                if self.including_effort:
                    efforts_to_transitions = self.batch_dist_fun(
                        n.state.q,
                        self.reverse_transition_node_array_cache[mode],
                        c = 'max'
                    )/self.collision_resolution
                    potential_efforts = reverse_transition_node_lb_cache[mode] + efforts_to_transitions
                    n.lb_effort_to_come = np.min(potential_efforts)

                
                potential_costs = reverse_transition_node_lb_cache[mode] + costs_to_transitions
                n.lb_cost_to_come = np.min(potential_costs)
                # if compute_lb_effort_to_go:
                #     n.lb_effort_to_come = n.lb_cost_to_come /self.collision_resolution
                processed +=1
        # print(processed)

    def compute_node_lb_effort_to_come(self):
        processed = 0
        reverse_transition_node_lb_cache = {}
        for mode in self.node_ids:
            for id in self.node_ids[mode]:
                n = self.nodes[id]
                mode = n.state.mode
                if mode not in self.reverse_transition_node_array_cache:
                    continue

                if mode not in reverse_transition_node_lb_cache:
                    reverse_transition_node_lb_cache[mode] = np.array(
                        [
                            self.nodes[id].lb_cost_to_come
                            for id in self.reverse_transition_node_ids[mode]
                        ],
                        dtype=np.float64,
                    )
                #use same distance metric as in collision detection
                efforts_to_transitions = self.batch_dist_fun(
                    n.state.q,
                    self.reverse_transition_node_array_cache[mode],
                    c = 'max'
                )
                potential_efforts = reverse_transition_node_lb_cache[mode] + efforts_to_transitions
                n.lb_effort_to_come = np.min(potential_efforts)/self.collision_resolution
                processed +=1
        print(processed)

    def update_edge_collision_cache(
            self, n0: BaseNode, n1: BaseNode, is_edge_collision_free: bool
        ):
            if is_edge_collision_free:
                n1.whitelist.add(n0.id)
                n0.whitelist.add(n1.id)
            else:
                if n1.id == 385 or n0.id == 385:
                    if n1.id == 44 or n0.id == 44:
                        print("collision")
                n0.blacklist.add(n1.id)
                n1.blacklist.add(n0.id)

    @abstractmethod
    def update_forward_queue(self, edge_cost, edge, edge_effort:float=None):
        pass
    @abstractmethod
    def remove_forward_queue(self, edge_cost, n0, n1, edge_effort):
        pass
    @abstractmethod
    def update_forward_queue_keys(self, type:str, node_ids:Optional[Set[BaseNode]] = None):
        pass
    @abstractmethod
    def update_reverse_queue_keys(self, type:str, node_ids:Optional[Set[BaseNode]] = None):
        pass

class Informed(BaseInformed):
    def lb_cost_from_start(self, state:State, g, lb_attribute_name="lb_cost_to_come"):
        if state.mode not in g.reverse_transition_node_array_cache:
            ids = g.reverse_transition_node_ids[state.mode]
            g.reverse_transition_node_array_cache[state.mode] = np.empty((len(ids), g.dim), dtype=np.float64)
            for i, id in enumerate(ids):
                g.reverse_transition_node_array_cache[state.mode][i] = g.nodes[id].state.q.q

        if state.mode not in g.reverse_transition_node_lb_cache:
            ids = g.reverse_transition_node_ids[state.mode]
            g.reverse_transition_node_lb_cache[state.mode] = np.empty(len(ids), dtype=np.float64)
            for i, id in enumerate(ids):
                g.reverse_transition_node_lb_cache[state.mode][i] = g.nodes[id].lb_cost_to_come

        costs_to_transitions = self.env.batch_config_cost(
            state.q,
            g.reverse_transition_node_array_cache[state.mode],
        )

        min_cost = np.min(
            g.reverse_transition_node_lb_cache[state.mode] + costs_to_transitions
        )
        return min_cost

    def lb_cost_from_goal(self, state:State, g, lb_attribute_name="lb_cost_to_go"):
        if state.mode not in g.transition_node_ids:
            return np.inf

        if state.mode not in g.transition_node_array_cache:
            ids = g.transition_node_ids[state.mode]
            g.transition_node_array_cache[state.mode] = np.empty((len(ids), g.dim), dtype=np.float64)
            for i, id in enumerate(ids):
                g.transition_node_array_cache[state.mode][i] = g.nodes[id].state.q.q

        if state.mode not in g.transition_node_lb_cache:
            ids = g.transition_node_ids[state.mode]
            g.transition_node_lb_cache[state.mode] = np.empty(len(ids), dtype=np.float64)
            for i, id in enumerate(ids):
                g.transition_node_lb_cache[state.mode][i] = g.nodes[id].lb_cost_to_go


        costs_to_transitions = self.env.batch_config_cost(
            state.q,
            g.transition_node_array_cache[state.mode],
        )

        min_cost = np.min(
            g.transition_node_lb_cache[state.mode] + costs_to_transitions
        )
        return min_cost

# taken from https://github.com/marleyshan21/Batch-informed-trees/blob/master/python/BIT_Star.py
# needed adaption to work.
class BaseITstar(ABC):
    """
    Represents the base class for IT*-based algorithms, providing core functionalities for motion planning.
    """
    def __init__(
        self,
        env: BaseProblem,
        ptc: PlannerTerminationCondition,
        mode_sampling_type: str = "greedy",
        distance_metric: str = "euclidean",
        try_sampling_around_path: bool = True,
        try_informed_sampling: bool = True,
        init_uniform_batch_size: int = 100,
        init_transition_batch_size:int = 100,
        uniform_batch_size: int = 200,
        uniform_transition_batch_size: int = 500,
        informed_batch_size: int = 500,
        informed_transition_batch_size: int = 500,
        path_batch_size: int = 500,
        locally_informed_sampling: bool = True,
        try_informed_transitions: bool = True,
        try_shortcutting: bool = True,
        try_direct_informed_sampling: bool = True,
        inlcude_lb_in_informed_sampling:bool = True,
        remove_based_on_modes:bool = False,
        with_tree_visualization:bool = False
    ):
        self.env = env
        self.ptc = ptc
        self.mode_sampling_type = mode_sampling_type
        self.distance_metric = distance_metric
        self.try_sampling_around_path = try_sampling_around_path
        self.try_informed_sampling = try_informed_sampling
        self.init_uniform_batch_size = init_uniform_batch_size
        self.init_transition_batch_size = init_transition_batch_size
        self.uniform_batch_size = uniform_batch_size
        self.uniform_transition_batch_size = uniform_transition_batch_size
        self.informed_batch_size = informed_batch_size
        self.informed_transition_batch_size = informed_transition_batch_size
        self.path_batch_size = path_batch_size
        self.locally_informed_sampling = locally_informed_sampling
        self.try_informed_transitions = try_informed_transitions
        self.try_shortcutting = try_shortcutting
        self.try_direct_informed_sampling = try_direct_informed_sampling
        self.inlcude_lb_in_informed_sampling = inlcude_lb_in_informed_sampling
        self.remove_based_on_modes = remove_based_on_modes
        self.with_tree_visualization = with_tree_visualization

        self.reached_modes = []
        self.start_time = time.time()
        self.costs = []
        self.times = []
        self.all_paths = []
        self.conf_type = type(env.get_start_pos())
        self.approximate_space_extent = np.prod(np.diff(env.limits, axis=0))
        self.current_best_cost = None
        self.current_best_path = None
        self.current_best_path_nodes = None
        self.cnt = 0
        self.operation = self._create_operation()

        self.start_transition_arrays = {}
        self.end_transition_arrays = {}
        self.remove_nodes = False
        self.dynamic_reverse_search_update = False
        self.g = None

        self.updated_target_nodes = set()
        self.reverse_closed_set = set()
        self.reverse_tree_set = set()
        self.reduce_neighbors = False
        self.first_search = True
        self.informed = Informed(env, 
                        'graph_based',   
                        locally_informed_sampling,
                        include_lb=inlcude_lb_in_informed_sampling
                        )
        
    def _create_operation(self) -> BaseOperation:
        return BaseOperation()
    
    def _create_graph(self, root_state:State) -> BaseGraph:
        return BaseGraph(
            root_state=root_state,
            operation=self.operation,
            batch_dist_fun=lambda a, b, c=None: batch_config_dist(a, b, c or self.distance_metric),
            batch_cost_fun= lambda a, b: self.env.batch_config_cost(a, b),
            is_edge_collision_free = self.env.is_edge_collision_free,
            collision_resolution = self.env.collision_resolution,
            node_cls=BaseNode
            )
    
    def sample_valid_uniform_batch(self, batch_size: int, cost: float) -> List[State]:
        new_samples = []
        num_attempts = 0
        num_valid = 0
        failed_attemps = 0

        if len(self.g.goal_nodes) > 0:
            focal_points = np.array(
                [self.g.root.state.q.state(), self.g.goal_nodes[0].state.q.state()],
                dtype=np.float64,
            )

        while len(new_samples) < batch_size:
            # if failed_attemps > 10000000:
            #     break
            num_attempts += 1
            # print(len(new_samples))
            # sample mode
            m = self.sample_mode(
                self.reached_modes, "uniform_reached", cost is not None
            )

            # print(m)

            # sample configuration
            q = []
            for i in range(len(self.env.robots)):
                r = self.env.robots[i]
                lims = self.env.limits[:, self.env.robot_idx[r]]
                if lims[0, 0] < lims[1, 0]:
                    qr = (
                        np.random.rand(self.env.robot_dims[r])
                        * (lims[1, :] - lims[0, :])
                        + lims[0, :]
                    )
                else:
                    qr = np.random.rand(self.env.robot_dims[r]) * 6 - 3

                q.append(qr)

            q = self.conf_type.from_list(q)

            if cost is not None:
                if sum(self.env.batch_config_cost(q, focal_points)) > cost:
                    failed_attemps += 1
                    continue

            if self.env.is_collision_free(q, m):
                new_samples.append(State(q, m))
                num_valid += 1
            else:
                 failed_attemps += 1

        print("Percentage of succ. attempts", num_valid / num_attempts)

        return new_samples, num_attempts

    def sample_valid_uniform_transitions(self, transistion_batch_size, cost):
        transitions = 0

        if len(self.g.goal_nodes) > 0:
            focal_points = np.array(
                [self.g.root.state.q.state(), self.g.goal_nodes[0].state.q.state()],
                dtype=np.float64,
            )
        # while len(transitions) < transistion_batch_size:
        failed_attemps = 0
        while transitions < transistion_batch_size:
            if failed_attemps > 2* transistion_batch_size:
                break 
            if len(self.g.goal_node_ids) == 0:
                mode_sampling_type = "greedy"
            else:
                mode_sampling_type = "uniform_reached"
            # sample mode
            mode = self.sample_mode(self.reached_modes, mode_sampling_type, None)

            # sample transition at the end of this mode
            possible_next_task_combinations = self.env.get_valid_next_task_combinations(
                mode
            )
            # print(mode, possible_next_task_combinations)

            if len(possible_next_task_combinations) > 0:
                ind = random.randint(0, len(possible_next_task_combinations) - 1)
                active_task = self.env.get_active_task(
                    mode, possible_next_task_combinations[ind]
                )
            else:
                active_task = self.env.get_active_task(mode, None)

            goals_to_sample = active_task.robots

            goal_sample = active_task.goal.sample(mode)

            # if mode.task_ids == [3, 8]:
            #     print(active_task.name)

            q = []
            for i in range(len(self.env.robots)):
                r = self.env.robots[i]
                if r in goals_to_sample:
                    offset = 0
                    for _, task_robot in enumerate(active_task.robots):
                        if task_robot == r:
                            q.append(
                                goal_sample[
                                    offset : offset + self.env.robot_dims[task_robot]
                                ]
                            )
                            break
                        offset += self.env.robot_dims[task_robot]
                else:  # uniform sample
                    lims = self.env.limits[:, self.env.robot_idx[r]]
                    if lims[0, 0] < lims[1, 0]:
                        qr = (
                            np.random.rand(self.env.robot_dims[r])
                            * (lims[1, :] - lims[0, :])
                            + lims[0, :]
                        )
                    else:
                        qr = np.random.rand(self.env.robot_dims[r]) * 6 - 3

                    q.append(qr)

            q = self.conf_type.from_list(q)

            if cost is not None:
                if sum(self.env.batch_config_cost(q, focal_points)) > cost:
                    continue

            if self.env.is_collision_free(q, mode):
                if self.env.is_terminal_mode(mode):
                    next_mode = None
                else:
                    next_mode = self.env.get_next_mode(q, mode)

                
                self.g.add_transition_nodes([(q, mode, next_mode)])
                if len(list(chain.from_iterable(self.g.transition_node_ids.values()))) > transitions:
                    transitions +=1
                else:
                    failed_attemps +=1
                # print(mode, mode.next_modes)

                if next_mode not in self.reached_modes and next_mode is not None:
                    self.reached_modes.append(next_mode)
            
        print(f"Adding {transitions} transitions")
        return

    def sample_around_path(self, path):
        # sample index
        interpolated_path = interpolate_path(path)
        # interpolated_path = current_best_path
        new_states_from_path_sampling = []
        new_transitions_from_path_sampling = []
        for _ in range(200):
            idx = random.randint(0, len(interpolated_path) - 2)
            state = interpolated_path[idx]

            # this is a transition. we would need to figure out which robots are active and not sample those
            q = []
            if (
                state.mode != interpolated_path[idx + 1].mode
                and np.linalg.norm(
                    state.q.state() - interpolated_path[idx + 1].q.state()
                )
                < 1e-5
            ):
                next_task_ids = interpolated_path[idx + 1].mode.task_ids

                # TODO: this seems to move transitions around
                task = self.env.get_active_task(state.mode, next_task_ids)
                involved_robots = task.robots
                for i in range(len(self.env.robots)):
                    r = self.env.robots[i]
                    if r in involved_robots:
                        qr = state.q[i] * 1.0
                    else:
                        qr_mean = state.q[i] * 1.0

                        qr = np.random.rand(len(qr_mean)) * 0.2 + qr_mean

                        lims = self.env.limits[:, self.env.robot_idx[r]]
                        if lims[0, 0] < lims[1, 0]:
                            qr = np.clip(qr, lims[0, :], lims[1, :])

                    q.append(qr)

                q = self.conf_type.from_list(q)

                if self.env.is_collision_free(q, state.mode):
                    new_transitions_from_path_sampling.append(
                        (q, state.mode, interpolated_path[idx + 1].mode)
                    )

            else:
                for i in range(len(self.env.robots)):
                    r = self.env.robots[i]
                    qr_mean = state.q[i]

                    qr = np.random.rand(len(qr_mean)) * 0.2 + qr_mean

                    lims = self.env.limits[:, self.env.robot_idx[r]]
                    if lims[0, 0] < lims[1, 0]:
                        qr = np.clip(qr, lims[0, :], lims[1, :])

                    q.append(qr)

                q = self.conf_type.from_list(q)

                if self.env.is_collision_free(q, state.mode):
                    rnd_state = State(q, state.mode)
                    new_states_from_path_sampling.append(rnd_state)

        # fig = plt.figure()
        # ax = fig.add_subplot(projection='3d')
        # ax.scatter([a.q[0][0] for a in new_states_from_path_sampling], [a.q[0][1] for a in new_states_from_path_sampling], [a.q[0][2] for a in new_states_from_path_sampling])
        # ax.scatter([a.q[1][0] for a in new_states_from_path_sampling], [a.q[1][1] for a in new_states_from_path_sampling], [a.q[1][2] for a in new_states_from_path_sampling])
        # ax.scatter([a.q[2][0] for a in new_states_from_path_sampling], [a.q[2][1] for a in new_states_from_path_sampling], [a.q[1][2] for a in new_states_from_path_sampling])
        # plt.show()

        return new_states_from_path_sampling, new_transitions_from_path_sampling

    def add_sample_batch(self):
        # add new batch of nodes
        while True:

                        
            
            effective_uniform_batch_size = (
                self.uniform_batch_size if self.current_best_cost is not None or not self.first_search
                else self.init_uniform_batch_size
            )
            effective_uniform_transition_batch_size = (
                self.uniform_transition_batch_size
                if self.current_best_cost is not None or not self.first_search
                else self.init_transition_batch_size
            )

            # nodes_per_state = []
            # for m in reached_modes:
            #     num_nodes = 0
            #     for n in new_states:
            #         if n.mode == m:
            #             num_nodes += 1

            #     nodes_per_state.append(num_nodes)

            # plt.figure("Uniform states")
            # plt.bar([str(mode) for mode in reached_modes], nodes_per_state)

            # if self.env.terminal_mode not in reached_modes:   
            print("--------------------")
            print("Sampling transitions")
            self.sample_valid_uniform_transitions(
                transistion_batch_size=effective_uniform_transition_batch_size,
                cost=self.current_best_cost,
            )
            # new_transitions = self.sample_valid_uniform_transitions(
            #     transistion_batch_size=effective_uniform_transition_batch_size,
            #     cost=self.current_best_cost,
            # )
            if len(self.g.goal_nodes) == 0:
                continue


            # self.g.add_transition_nodes(new_transitions)
            # print(f"Adding {len(new_transitions)} transitions")
            
            print("Sampling uniform")
            new_states, required_attempts_this_batch = self.sample_valid_uniform_batch(
                    batch_size=effective_uniform_batch_size, cost=self.current_best_cost
                )
            self.g.add_states(new_states)
            print(f"Adding {len(new_states)} new states")

            self.approximate_space_extent = (
                np.prod(np.diff(self.env.limits, axis=0))
                * len(new_states)
                / required_attempts_this_batch
            )

            # print(reached_modes)

            

        # g.compute_lb_cost_to_go(self.env.batch_config_cost)
        # g.compute_lower_bound_from_start(self.env.batch_config_cost)

            if self.current_best_cost is not None and (
                self.try_informed_sampling or self.try_informed_transitions
            ):
                interpolated_path = interpolate_path(self.current_best_path)
                # interpolated_path = current_best_path

                if self.try_informed_sampling:
                    print("Generating informed samples")
                    new_informed_states = self.informed.generate_samples(
                                            self.reached_modes,
                                            self.informed_batch_size,
                                            interpolated_path,
                                            try_direct_sampling=self.try_direct_informed_sampling,
                                            g=self.g
                                        )
                    
                    self.g.add_states(new_informed_states)

                    print(f"Adding {len(new_informed_states)} informed samples")

                if self.try_informed_transitions:
                    print("Generating informed transitions")
                    new_informed_transitions = self.informed.generate_transitions(
                                                self.reached_modes,
                                                self.informed_transition_batch_size,
                                                interpolated_path,
                                                g=self.g
                                            )

                    
                    self.g.add_transition_nodes(new_informed_transitions)
                    print(f"Adding {len(new_informed_transitions)} informed transitions")

                    # g.compute_lb_cost_to_go(self.env.batch_config_cost)
                    # g.compute_lower_bound_from_start(self.env.batch_config_cost)

            if self.try_sampling_around_path and self.current_best_path is not None:
                print("Sampling around path")
                path_samples, path_transitions = self.sample_around_path(
                    self.current_best_path
                )

                self.g.add_states(path_samples)
                print(f"Adding {len(path_samples)} path samples")

                self.g.add_transition_nodes(path_transitions)
                print(f"Adding {len(path_transitions)} path transitions")
            
            if len(self.g.goal_nodes) != 0:
                break
        # for mode in self.reached_modes:
        #     q_samples = [self.g.nodes[id].state.q.state() for id in self.g.node_ids[mode]]
        #     modes = [self.g.nodes[id].state.mode.task_ids for id in self.g.node_ids[mode]]
        #     data = {
        #         "q_samples": q_samples,
        #         "modes": modes,
        #         "path": self.current_best_path
        #     }
        #     save_data(data)
        #     print()
        

        # self.g.compute_lb_reverse_cost_to_come(self.env.batch_config_cost)
        # self.g.compute_lb_cost_to_come(self.env.batch_config_cost)

    def sample_mode(
        self,
        reached_modes,
        mode_sampling_type: str = "uniform_reached",
        found_solution: bool = False,
    ) -> Mode:
        if mode_sampling_type == "uniform_reached":
            m_rnd = random.choice(reached_modes)
        if mode_sampling_type == "greedy":
            m_rnd = reached_modes[-1]
        return m_rnd

    def sample_manifold(self) -> None:
        print("====================")
        while True:
            self.g.initialize_cache()
            if self.current_best_path is not None:
                # prune
                # for mode in self.reached_modes:
                #     q_samples = [self.g.nodes[id].state.q.state() for id in self.g.node_ids[mode]]
                #     modes = [self.g.nodes[id].state.mode.task_ids for id in self.g.node_ids[mode]]
                #     data = {
                #         "q_samples": q_samples,
                #         "modes": modes,
                #         "path": self.current_best_path
                #     }
                #     save_data(data)
                #     print()
                # for mode in self.reached_modes:
                #     q_samples = [self.g.nodes[id].state.q.state() for id in self.g.transition_node_ids[mode]]
                #     modes = [self.g.nodes[id].state.mode.task_ids for id in self.g.transition_node_ids[mode]]
                #     data = {
                #         "q_samples": q_samples,
                #         "modes": modes,
                #         "path": self.current_best_path
                #     }
                #     save_data(data)
                #     print()

                self.remove_nodes_in_graph()

                # for mode in self.reached_modes:
                #     q_samples = [self.g.nodes[id].state.q.state() for id in self.g.node_ids[mode]]
                #     modes = [self.g.nodes[id].state.mode.task_ids for id in self.g.node_ids[mode]]
                #     data = {
                #         "q_samples": q_samples,
                #         "modes": modes,
                #         "path": self.current_best_path
                #     }
                #     save_data(data)
                #     print()
                # for mode in self.reached_modes:
                #     q_samples = [self.g.nodes[id].state.q.state() for id in self.g.transition_node_ids[mode]]
                #     modes = [self.g.nodes[id].state.mode.task_ids for id in self.g.transition_node_ids[mode]]
                #     data = {
                #         "q_samples": q_samples,
                #         "modes": modes,
                #         "path": self.current_best_path
                #     }
                #     save_data(data)
                #     print()


            print(f"Samples: {self.cnt}; {self.ptc}")

            samples_in_graph_before = self.g.get_num_samples()
            self.add_sample_batch()
            self.g.initialize_cache()

            samples_in_graph_after = self.g.get_num_samples()
            self.cnt += samples_in_graph_after - samples_in_graph_before

            # search over nodes:
            # 1. search from goal state with sparse check
            reached_terminal_mode = False
            for m in self.reached_modes:
                if self.env.is_terminal_mode(m):
                    reached_terminal_mode = True
                    break

            if reached_terminal_mode:
                print("====================")
                break
    
    def prune_set_of_expanded_nodes(self):
        if not self.remove_nodes:
            return BaseTree.all_vertices, []

        vertices_node_ids = []
        stack = [self.g.root.id]
        children_to_be_removed = []
        focal_points = {}
        focal_points_transition = {}
        inter_costs = {}
        count = 0
        while len(stack) > 0:
            id = stack.pop()
            node = self.g.nodes[id]
            key = node.state.mode           
            if node.is_transition and node.is_reverse_transition:
                if node.transition.id in vertices_node_ids:
                    vertices_node_ids.append(id)
                    stack.extend(node.forward.children)
                    count +=1
                continue
            
            if not self.remove_based_on_modes or key not in self.start_transition_arrays:
                if key not in focal_points:
                    focal_points[key] = np.array(
                    [self.g.root.state.q.state(), self.current_best_path[-1].q.state()],
                    dtype=np.float64,
                    )
                    focal_points_transition[key] =  focal_points[key]

                    inter_costs[key] = self.current_best_cost
            else:
                if key not in focal_points:
                    focal_points[key] = np.array(
                        [self.start_transition_arrays[key], self.end_transition_arrays[key]],
                        dtype=np.float64,
                    )
                    focal_points_transition[key] = np.array(
                    [self.start_transition_arrays[key]],
                    dtype=np.float64,
                    )
                    inter_costs[key] =  self.intermediate_mode_costs[key]
            

            if node in self.current_best_path_nodes:
                flag = False
            elif not node.is_transition:
                flag = sum(self.env.batch_config_cost(node.state.q, focal_points[key])) > inter_costs[key]
                if not flag:
                    #not in the current expanded tree
                    if node.id not in BaseTree.all_vertices:
                        flag = True
            else:
                flag = sum(self.env.batch_config_cost(node.state.q, focal_points_transition[key])) > inter_costs[key]
                
            if flag:
                children = [node.id]
                if node.forward.parent is not None:
                    node.forward.parent.forward.children.remove(node.id)
                    node.forward.parent.forward.fam.remove(node.id)
                    node.forward.fam.remove(node.forward.parent.id)
                    node.forward.parent = None
                to_be_removed = []
                while len(children) > 0:
                    child_id = children.pop()
                    to_be_removed.append(child_id)
                    children.extend(self.g.nodes[child_id].forward.children)
                children_to_be_removed.extend(to_be_removed)
            else:
                vertices_node_ids.append(id)
                stack.extend(node.forward.children)

        goal_mask = np.array([item in children_to_be_removed for item in self.g.goal_node_ids])
        goal_nodes = np.array(self.g.goal_node_ids)[goal_mask]
        if goal_nodes.size > 0:
            for goal in goal_nodes:
                goal_node = self.g.nodes[goal]
                goal_node.cost = np.inf
                goal_node.forward.reset()
                children_to_be_removed.remove(goal)
                key = goal_node.state.mode
                vertices_node_ids.append(goal)
        return vertices_node_ids, children_to_be_removed

    def remove_nodes_in_graph(self):
        num_pts_for_removal = 0
        vertices_to_keep, vertices_to_be_removed = self.prune_set_of_expanded_nodes()
        # vertices_to_keep = list(chain.from_iterable(self.g.vertices_node_ids.values()))
        # Remove elements from g.nodes_ids
        for mode in list(self.g.node_ids.keys()):# Avoid modifying dict while iterating
            # start = random.choice(self.g.reverse_transition_node_ids[mode])
            # goal = random.choice(self.g.re)
            if not self.remove_based_on_modes or mode not in self.start_transition_arrays:
                focal_points = np.array(
                [self.g.root.state.q.state(), self.current_best_path[-1].q.state()],
                dtype=np.float64,
                )
                cost = self.current_best_cost
                
            else:
                focal_points = np.array(
                    [self.start_transition_arrays[mode], self.end_transition_arrays[mode]],
                    dtype=np.float64,
                )
                cost =  self.intermediate_mode_costs[mode]
            original_count = len(self.g.node_ids[mode])
            self.g.node_ids[mode] = [
                id
                for id in self.g.node_ids[mode]
                if id == self.g.root.id or id in vertices_to_keep or (id not in vertices_to_be_removed and sum(
                    self.env.batch_config_cost(self.g.nodes[id].state.q, focal_points))
                <= cost)
            ]
            assert[id for id in self.g.node_ids[mode] if id in vertices_to_be_removed]== [],(
                "hoh"
            )
            num_pts_for_removal += original_count - len(self.g.node_ids[mode])
        # Remove elements from g.transition_node_ids
        self.g.reverse_transition_node_ids = {}

        for mode in list(self.g.transition_node_ids.keys()):
            if self.env.is_terminal_mode(mode):
                continue
            
            if not self.remove_based_on_modes or mode not in self.start_transition_arrays:
                focal_points = np.array(
                [self.g.root.state.q.state(), self.current_best_path[-1].q.state()],
                dtype=np.float64,
                )
                cost = self.current_best_cost
            else:
                focal_points = np.array(
                    [self.start_transition_arrays[mode]],
                    dtype=np.float64,
                )
                cost =  self.intermediate_mode_costs[mode]
            original_count = len(self.g.transition_node_ids[mode])
            self.g.transition_node_ids[mode] = [
                id
                for id in self.g.transition_node_ids[mode]
                if id in vertices_to_keep or (id not in vertices_to_be_removed and sum(
                    self.env.batch_config_cost(self.g.nodes[id].state.q, focal_points))
                <= cost)
            ]
            num_pts_for_removal += original_count - len(
                self.g.transition_node_ids[mode]
            )
        # Update elements from g.reverse_transition_node_ids
        self.g.reverse_transition_node_ids[self.env.get_start_mode()] = [self.g.root.id]
        all_transitions = list(chain.from_iterable(self.g.transition_node_ids.values()))
        transition_nodes = np.array([self.g.nodes[id] for id in all_transitions])
        valid_mask = np.array([node.transition is not None for node in transition_nodes])
        valid_nodes = transition_nodes[valid_mask]
        reverse_transition_ids = [node.transition.id for node in valid_nodes]
        reverse_transition_modes =[node.transition.state.mode for node in valid_nodes]
        for mode, t_id in zip(reverse_transition_modes, reverse_transition_ids):
            if mode not in self.g.reverse_transition_node_ids:
                self.g.reverse_transition_node_ids[mode] = []
            self.g.reverse_transition_node_ids[mode].append(t_id)
        if self.remove_nodes:
            self.g.tree = {}
            BaseTree.all_vertices.clear()
            self.g.add_vertex_to_tree(self.g.root)
        print(f"Removed {num_pts_for_removal} nodes")

    def process_valid_path(self, 
                           valid_path, 
                           with_queue_update:bool = True, 
                           with_shortcutting:bool = False, 
                           force_update:bool = False):
        path = [node.state for node in valid_path]
        new_path_cost = path_cost(path, self.env.batch_config_cost)
        if force_update or self.current_best_cost is None or new_path_cost < self.current_best_cost:
            self.alpha = 1.0
            self.current_best_path = path
            self.current_best_cost = new_path_cost
            self.current_best_path_nodes = valid_path
            self.remove_nodes = True
            self.dynamic_reverse_search_update = True
            # if not with_shortcutting:
            #     self.add_reverse_connectivity_to_path(self.current_best_path_nodes, False)
            print()
            print(f"found cost: {new_path_cost} at time {time.time() - self.start_time}")
            print('found path:', [n.id for n in valid_path])
            self.update_results_tracking(new_path_cost, path)

            if self.try_shortcutting and with_shortcutting:
                print("--- shortcutting ---")
                shortcut_path, _ = shortcutting.robot_mode_shortcut(
                    self.env,
                    path,
                    250,
                    resolution=self.env.collision_resolution,
                    tolerance=self.env.collision_tolerance
                )
                # assert all([
                #         self.env.is_edge_collision_free(path[i].q, path[i+1].q, path[i].mode) 
                #         for i in range(len(path) - 1)
                #     ]), (
                #         "hjsfdgklöäsjdk$"
                #     )


                # if not all([
                #         self.env.is_edge_collision_free(shortcut_path[i].q, shortcut_path[i+1].q, shortcut_path[i].mode) 
                #         for i in range(len(shortcut_path) - 1)
                #     ]):
                #         for i in range(len(shortcut_path)-1):
                #             if not self.env.is_edge_collision_free(shortcut_path[i].q, shortcut_path[i+1].q, shortcut_path[i].mode):
                #                 self.env.is_edge_collision_free(shortcut_path[i].q, shortcut_path[i+1].q, shortcut_path[i].mode)
                #                 print()
                
                # if not self.env.is_path_collision_free(
                #     shortcut_path):
                #     pass
                

                shortcut_path = shortcutting.remove_interpolated_nodes(shortcut_path)
                shortcut_path_cost = path_cost(
                    shortcut_path, self.env.batch_config_cost
                )
                # if not self.env.is_path_collision_free(
                #     shortcut_path):
                #     pass
                # if not all([
                #         self.env.is_edge_collision_free(shortcut_path[i].q, shortcut_path[i+1].q, shortcut_path[i].mode) 
                #         for i in range(len(shortcut_path) - 1)
                #     ]):
                #         for i in range(len(shortcut_path)-1):
                #             if not self.env.is_edge_collision_free(shortcut_path[i].q, shortcut_path[i+1].q, shortcut_path[i].mode):
                #                 self.env.is_edge_collision_free(shortcut_path[i].q, shortcut_path[i+1].q, shortcut_path[i].mode)

                    
                    

                    

                if shortcut_path_cost < self.current_best_cost:
                    self.update_results_tracking(shortcut_path_cost, shortcut_path)

                    self.current_best_path = shortcut_path
                    self.current_best_cost = shortcut_path_cost

                    interpolated_path = shortcut_path
                    self.g.add_path_states(interpolated_path, self.approximate_space_extent)   
                    self.current_best_path_nodes = self.generate_path(force_generation=True)
                    self.current_best_path = [node.state for node in self.current_best_path_nodes]

                    self.g.initialize_cache()
                    if with_queue_update:
                    #     self.initialize
                        self.initialize_lb()
                        # self.initialze_forward_search()
                        # self.initialize_reverse_search()
                        self.g.update_reverse_queue_keys('target')
                        self.g.update_reverse_queue_keys('start')
                        self.add_reverse_connectivity_to_path(self.current_best_path_nodes, True)
                        
                    self.current_best_cost = path_cost(self.current_best_path, self.env.batch_config_cost) 
                    print("rewired cost: " ,self.current_best_cost)
                    print('new path: ', [n.id for n in self.current_best_path_nodes])
                    # if not all([
                    #     self.env.is_edge_collision_free(self.current_best_path[i].q, self.current_best_path[i+1].q, self.current_best_path[i].mode) 
                    #     for i in range(len(self.current_best_path) - 1)
                    # ]):
                    #     for i in range(len(self.current_best_path)-1):
                    #         if not self.env.is_edge_collision_free(self.current_best_path[i].q, self.current_best_path[i+1].q, self.current_best_path[i].mode):
                    #             self.env.is_edge_collision_free(self.current_best_path[i].q, self.current_best_path[i+1].q, self.current_best_path[i].mode)
            
            else:
                pass
            
            # extract modes for removal strategy
             
    def update_removal_conditions(self):
        self.start_transition_arrays, self.end_transition_arrays, self.intermediate_mode_costs = {}, {}, {}
        self.start_transition_arrays[self.current_best_path_nodes[0].state.mode] = self.g.root.state.q.state()
        modes = [self.current_best_path_nodes[0].state.mode]
        start_cost = 0
        for n in self.current_best_path_nodes:
            if n.state.mode != modes[-1]:
                self.end_transition_arrays[modes[-1]] = n.state.q.state()
                self.start_transition_arrays[n.state.mode] = n.state.q.state()
                self.intermediate_mode_costs[modes[-1]] = n.cost - start_cost
                start_cost = n.cost
                modes.append(n.state.mode)
        self.end_transition_arrays[modes[-1]] = self.current_best_path_nodes[-1].state.q.state()
        self.intermediate_mode_costs[modes[-1]] = self.current_best_path_nodes[-1].cost - start_cost
        print("Modes of new path")
        print([m.task_ids for m in modes])     
            
    def add_reverse_connectivity_to_path(self, path, with_update):
        parent = path[-1]
        for node in reversed(path[1:-1]):
            if node.id == 1810:
                pass
            if with_update:
                edge_cost = parent.forward.cost_to_parent
                # lb_cost_to_go_expanded = lb_cost_to_go for AIT*
                self.g.update_connectivity(parent, node, edge_cost , parent.lb_cost_to_go + edge_cost,'reverse')
                node.close(self.env.collision_resolution)
            if node.is_transition and not node.is_reverse_transition:
                self.update_reverse_sets(node.transition)
                self.expand_node_forward(node.transition, False, True)
            else:
                self.expand_node_forward(node, False, True)
            self.update_reverse_sets(node)
            parent = node
      
    def generate_path(self, force_generation:bool = False) -> List[BaseNode]:
        path = []
        goal, cost = self.get_lb_goal_node_and_cost()
        if self.current_best_cost is not None:
            diff = self.current_best_cost - cost
        else:
            diff = cost
        if not force_generation and (math.isinf(cost) or goal is None or diff < 1e-6):
            return path
        path.append(goal)

        n = goal

        while n.forward.parent is not None:
            path.append(n.forward.parent)
            n = n.forward.parent

        # path.append(n)
        path = path[::-1]
        return path

    def update_results_tracking(self, cost, path):
        self.costs.append(cost)
        self.times.append(time.time() - self.start_time)
        self.all_paths.append(path)

    def get_lb_goal_node_and_cost(self) -> BaseNode:
        min_id = np.argmin(self.operation.costs[self.g.goal_node_ids], axis=0)
        best_cost = self.operation.costs[self.g.goal_node_ids][min_id]
        best_node = self.g.goal_nodes[min_id]
        return best_node, best_cost
    
    def expand_node_forward(self, node: Optional[BaseNode] = None, regardless_forward_closed_set:bool= False, choose_random_set:bool=False, first_search:bool = False) -> None:
        if node in self.g.goal_nodes:
            return   
        neighbors = self.g.get_neighbors(node, space_extent=self.approximate_space_extent, first_search= first_search)
        if neighbors.size == 0:
            return
        
        edge_costs = self.g.tot_neighbors_batch_cost_cache[node.id]
        if self.g.including_effort:
            edge_efforts = self.g.tot_neighbors_batch_effort_cache[node.id]
        else: 
            edge_efforts = np.zeros_like(edge_costs)


        if choose_random_set:
            if neighbors.size > 20:
                indices = np.random.choice(len(neighbors), size=20, replace=False)
                neighbors = neighbors[indices]
                edge_costs = edge_costs[indices]
                edge_efforts = edge_efforts[indices]

        

        
        for id, edge_cost, edge_effort in zip(neighbors, edge_costs, edge_efforts):
            n = self.g.nodes[id]
            if n.id == self.g.root.id:
                continue
            if node.forward.parent is not None and node.forward.parent.id == n.id:
                continue
            if n.is_transition and n.is_reverse_transition:
                continue
            if n.id in BaseTree.all_vertices and not regardless_forward_closed_set:
                if self.current_best_cost is None:
                    continue
                if node.cost + edge_cost >= n.cost:
                    continue
            assert (n.forward.parent == node) == (n.id in node.forward.children), (
                    f"Parent and children don't coincide (reverse): parent: {node.id}, child: {n.id}"
                    )
            
            assert(n.id not in node.blacklist), (
            "neighbors are wrong")
            if self.current_best_cost is not None:
                if not np.isinf(n.lb_cost_to_go):
                    if node.cost + edge_cost + n.lb_cost_to_go > self.current_best_cost:
                        continue
            
            edge = (node, n)
            if self.g.including_effort:
                self.g.update_forward_queue(edge_cost, edge, edge_effort)
            else:
                 self.g.update_forward_queue(edge_cost, edge)

    def save_tree_data(self, nodes:Tuple[set]) -> None:
        data = {}
        data['all_nodes'] = [self.g.nodes[id].state.q.state() for id in list(chain.from_iterable(self.g.node_ids.values()))]
        data['all_transition_nodes'] = [self.g.nodes[id].state.q.state() for id in list(chain.from_iterable(self.g.transition_node_ids.values()))]
        # data['all_nodes_mode'] = [self.g.nodes[id].state.mode_task_ids for id in list(chain.from_iterable(self.g.node_ids.values()))]
        # data['all_transition_nodes_mode'] = [self.g.nodes[id].state.mode.task_ids for id in list(chain.from_iterable(self.g.transition_node_ids.values()))]
        for i, type in enumerate(['forward', 'reverse']):
            data[type] = {}
            data[type]['nodes'] = []
            data[type]['parents'] = []
            data[type]['modes'] = []
            for id in nodes[i]:
                node = self.g.nodes[id]
                data[type]["nodes"].append(node.state.q.state())
                data[type]['modes'].append(node.state.mode.task_ids)
                if type == 'forward':
                    parent = node.forward.parent
                else:
                    parent = node.rev.parent
                if parent is not None:
                    data[type]["parents"].append(parent.state.q.state())
                else:
                    data[type]["parents"].append(None)
        save_data(data, True)
    
    def initialize_search(self):
        # if self.g.get_num_samples() >200:
        #     q_samples = []
        #     modes = []
        #     for mode in self.reached_modes:
        #         q_samples.extend([self.g.nodes[id].state.q.state() for id in self.g.node_ids[mode]])
        #         modes.extend([self.g.nodes[id].state.mode.task_ids for id in self.g.node_ids[mode]])
        #     for mode in self.reached_modes:
        #         q_samples.extend([self.g.nodes[id].state.q.state() for id in self.g.transition_node_ids[mode]])
        #         modes.extend([self.g.nodes[id].state.mode.task_ids for id in self.g.transition_node_ids[mode]])
        #     data = {
        #         "q_samples": q_samples,
        #         "modes": modes,
        #         "path": self.current_best_path
        #     }
        #     save_data(data)
        #     print()
        #     q_samples = []
        #     modes = []
        #     vertices = list(self.g.vertices)
        #     q_samples.extend([self.g.nodes[id].state.q.state() for id in vertices])
        #     modes.extend([self.g.nodes[id].state.mode.task_ids for id in vertices])
        #     data = {
        #         "q_samples": q_samples,
        #         "modes": modes,
        #         "path": self.current_best_path
        #     }
        #     save_data(data)
        #     print()
        # self.sample_manifold()
        # q_samples = []
        # modes = []
        # for mode in self.reached_modes:
        #     q_samples.extend([self.g.nodes[id].state.q.state() for id in self.g.node_ids[mode]])
        #     modes.extend([self.g.nodes[id].state.mode.task_ids for id in self.g.node_ids[mode]])
        # for mode in self.reached_modes:
        #     q_samples.extend([self.g.nodes[id].state.q.state() for id in self.g.transition_node_ids[mode]])
        #     modes.extend([self.g.nodes[id].state.mode.task_ids for id in self.g.transition_node_ids[mode]])
        # data = {
        #     "q_samples": q_samples,
        #     "modes": modes,
        #     "path": self.current_best_path
        # }
        # save_data(data)
        # print()
        # if self.current_best_cost is not None:
        #     path = self.generate_path(True)
        #     if len(path) > 0:
        #         self.process_valid_path(path, force_update = True, update_queues=False )
        # print("edges sparsely checked several times", [self.sparesly_checked_edges[key] for key in self.sparesly_checked_edges.keys() if self.sparesly_checked_edges[key] > 1])
        if self.current_best_cost is not None:
            print()
            print("Shortcutting before new batch")
            self.current_best_path_nodes = self.generate_path(True)
            self.process_valid_path(self.current_best_path_nodes, False, True, True)
            self.update_removal_conditions() 
        self.sample_manifold()
        self.initialize_lb()
        self.initialze_forward_search()
        self.initialize_reverse_search()
        self.dynamic_reverse_search_update = False
        self.first_search = False

    def PlannerInitialization(self) -> None:
        q0 = self.env.get_start_pos()
        m0 = self.env.get_start_mode()
        self.reached_modes.append(m0)
        #initilaize graph
        self.g = self._create_graph(State(q0, m0))
        # initialize all queues (edge-queues)    
        self.g.add_vertex_to_tree(self.g.root)
        self.initialize_search()
    
    @abstractmethod
    def update_reverse_sets(node):
        pass
        
    @abstractmethod
    def initialize_lb(self):    
        pass

    @abstractmethod
    def initialize_reverse_search(self, reset:bool =True):
        pass

    @abstractmethod
    def initialze_forward_search(self):
        pass

    @abstractmethod
    def Plan(self) -> Tuple[List[State], Dict[str, List[Union[float, float, List[State]]]]]:
        """
        Executes planning process using an RRT* framework.

        Args:
            None

        Returns:
            Tuple:
                - List[State]: The planned path as a list of states.
                - Dict[str, List]: A dictionary containing:
                    - "costs" (List[float]): Recorded path costs.
                    - "times" (List[float]): Recorded execution times.
                    - "paths" (List[List[State]]): All explored paths.


        """
        pass
