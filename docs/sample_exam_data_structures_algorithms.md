# Data Structures and Algorithms: Sample  Exam


## Part 1: True or False

In what follows, you will be asked to select all **TRUE** statements. 
Points will only be awarded for choosing **all** correct statements.

### Question 1 

```
Algorithm: SelectionSort(array)
Input: An unsorted array of n comparable elements
Output: The array sorted in ascending order

n = length of array

for i = 0 to n-2
   minIndex = i

   for j = i+1 to n-1
      if array[j] < array[minIndex]
         minIndex = j

   swap array[i] with array[minIndex]
```

- [ ] The pseudocode provided for selection sort is an iterative algorithm.
- [ ] To sort an array of length 5 in ascending order, which is given as input in the opposite order (that is, descending), Selection sort will perform 10 comparisons.
- [ ] All statements except for this one are FALSE.
- [ ] To sort an array of length 5 in ascending order, which is given as input in the opposite order (that is, descending), Selection sort will perform only 2 swaps between elements that are different.

### Question 2 

- [ ] In an array-based Heap, you can calculate the parent of any node, without needing pointers.
- [ ] Finding the lowest valued element in a Max-Heap with n elements takes O(n) time.
- [ ] All other statements are FALSE.
- [ ] Building a heap of n elements takes O(n log n) time since each of the n insertions takes O(log n) time.

### Question 3 

- [ ] In a worst-case scenario, a Hash Table may degrade into a Linked List.
- [ ] The k-th element in a linked list can be accessed directly in O(1) time.
- [ ] All other statements are FALSE.
- [ ] Linked list nodes are stored contiguously in memory.

### Question 4 

- [ ] Memory use for the same number of elements is greater with arrays than with linked lists.
- [ ] All statements except for this one are FALSE.
- [ ] Element random access is possible in arrays.
- [ ] Memory allocation is less flexible with linked lists than with arrays.
- [ ] Element insertion in a sorted fashion is more efficient with linked lists than with arrays.

### Question 5 

Consider the undirected weighted graph given below. It has vertices a, b, c, d, e and the following edges:

| Edge | Weight |
|------|--------|
| a – b | 15 |
| a – c | 14 |
| b – c | 23 |
| b – d | 11 |
| c – d | 22 |
| d – e | 21 |

Which of the following edges form the minimum spanning tree of the given graph using Prim's algorithm, starting from vertex "e"?

- [ ] (e,d), (d,c), (c,a), (a,b)
- [ ] None of them.
- [ ] (e,d), (d,c), (c,b), (a,c)
- [ ] (e,d), (d,b), (b,a), (a,c)

### Question 6 

- [ ] All other statements are FALSE.
- [ ] If elements from a sorted array are inserted (in order) into an initially empty BST, the resulting tree will be balanced.
- [ ] Search running times in a Binary Search Tree depend on the tree's height, as opposed to the total number of elements.
- [ ] The deletion procedure in a BST is more complex and requires more lines of code than the insertion procedure.

### Question 7

- [ ] Both Heaps and Binary Search Trees maintain sorted order among sibling nodes.
- [ ] Hash Tables preserve the insertion order of keys.
- [ ] A Queue can be implemented using one Stack.
- [ ] All other statements are FALSE.

### Question 8

Consider the undirected weighted graph given below. It has vertices a, b, c, d, e and the following edges:

| Edge | Weight |
|------|--------|
| a – b | 15 |
| a – c | 14 |
| b – c | 23 |
| b – d | 11 |
| c – d | 22 |
| d – e | 15 |

By running Kruskal's algorithm to find a minimum spanning tree, in what order(s) can edges be selected?

- [ ] (b,d), (a,c), (e,d), (a,b)
- [ ] (b,d), (b,a), (a,c), (d,e)
- [ ] (e,d), (d,b), (b,a), (a,c)
- [ ] None of them.
- [ ] (b,d), (a,c), (a,b), (d,e)

---

## Part 2: Correct Option

In the following questions you must select the **CORRECT** option.

### Question 9 

Given the function `x` below, what is the complexity expressed with n, in terms of Big-O notation? As usual, the complexity is given as the lowest (in terms of function growth) upper bound. 

```
function x(int n){
    for(int i=1 ; i<=n ; i++){
        for(int j=1 ; j<=n ; j++){
            for(int k=3 ; k<=n ; k++){
                for(int l=1 ; l<=n ; l=l*2){
                    int h=4;
                }
            }
        }
    }
}
```

- ( ) O(n^3 * log(n))
- ( ) O(n^4-3)
- ( ) O(n^3)
- ( ) O(n)

### Question 10

Given the function `search` below, what is the complexity expressed with *n*, where *n* is the number of elements in the array, in terms of Big-O notation? As usual, the complexity is given as the lowest (in terms of function growth) upper bound. 

```
def search(arr, x):
    low = 0
    high = len(arr) - 1
    mid = 0
    while low <= high:
        mid = (high + low) // 2
        if arr[mid] < x:
            low = mid + 1
        elif arr[mid] > x:
            high = mid - 1
        else:
            return mid
    return -1
```

- ( ) O(*n* log *n*)
- ( ) O(log *n*)
- ( ) O(*n*²)
- ( ) O(*n*)
- ( ) I don't know.

### Question 11

Look at the array:

`9 -1 5 -28 -7 -6 3 2`

Consider how the array changes at each step of going through a merge-sort program, where the values of the array are being sorted in an increasing order (i.e. 1 2 3). Below you will see the state of the array **before** and **after** the merges in the bottom of the recursion tree.

**Before the first merge step:**
`9 -1 5 -28 -7 -6 3 2`

**After the first merge step:**
`-1 9 -28 5 -7 -6 2 3`

Find the state of the array **after** the merges in the next level in the recursion tree. Then select the **CORRECT** statement below.

- ( ) After the merges in the next level in the recursion tree the state of the array is `-28 -1 5 9 -7 -6 2 3`.
- ( ) After the merges in the next level in the recursion tree the state of the array is `-28 -7 -6 -1 2 3 5 9`.
- ( ) After the merges in the next level in the recursion tree the state of the array is `-28 -7 -6 9 2 3 -1 9`.
- ( ) After the merges in the next level in the recursion tree the state of the array is `-28 -1 5 9 -7 -6 3 2`.

---

## Part 3: Open Ended Questions

In the following questions, partial credit will be awarded. Make sure to write down your idea even if you don't know how to finish the problem.

### Question 12 

Suppose you have a weighted directed graph where you want to find the shortest path from s to t, but with a twist: every time you traverse an edge, you must pay a fixed "toll" of c units in addition to the edge's weight. Modify Dijkstra's algorithm to handle this scenario. The pseudocode for Dijkstra's algorithm has been provided below:

```
Algorithm: Dijkstra(graph, source)
Input: graph with non-negative weights, source vertex s
Output: shortest distances from s to all vertices

dist[v] ← ∞ for all v
dist[s] ← 0
PQ ← priority queue with all vertices, prioritized by dist
visited ← empty set

while PQ is not empty do
   u ← PQ.extractMin()
   if u in visited then continue
   add u to visited

   for each neighbor v of u do
      if dist[u] + weight(u,v) < dist[v] then
         dist[v] ← dist[u] + weight(u,v)
         PQ.decreaseKey(v, dist[v])
      end if
   end for
end while

return dist
```

### Question 13

Describe a graph on five vertices on which Kruskal's algorithm would perform slower than Prim's. Describe your graph with an adjacency matrix (any other description will receive partial points only). Explain why Prim would be a better choice for this graph.

### Question 14 

Below is an iterative implementation of Breadth-First Search (BFS). Write pseudocode for an iterative implementation of **Depth-First Search** (DFS). You may draw inspiration from the algorithm for BFS. Recursive implementations will receive half credit.

```
Algorithm: BFS(graph, startNode)
Input: A graph and a starting vertex
Output: Prints all vertices reachable from startNode, visited in breadth-first order

   create empty queue Q
   create empty set visited

   enqueue startNode into Q
   add startNode to visited

   while Q is not empty
      currentNode = dequeue from Q
      print currentNode

      for each neighbor of currentNode
         if neighbor not in visited
            add neighbor to visited
            enqueue neighbor into Q
```

### Question 15

Prove or disprove the following statement: "In an unweighted, undirected graph, if BFS from source s visits node v before node w, then the shortest path distance from s to v is less than or equal to the distance from s to w."
