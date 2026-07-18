import type { ProductGroup } from '../types'

interface Props {
  groups: ProductGroup[]
  onSelect: (groupId: number) => void
}

interface TreeNode extends ProductGroup {
  children: TreeNode[]
}

function buildTree(groups: ProductGroup[]): TreeNode[] {
  const byId = new Map<number, TreeNode>(groups.map((g) => [g.id, { ...g, children: [] }]))
  const roots: TreeNode[] = []
  for (const node of byId.values()) {
    if (node.parent_id != null && byId.has(node.parent_id)) {
      byId.get(node.parent_id)!.children.push(node)
    } else {
      roots.push(node)
    }
  }
  const bySortOrder = (a: TreeNode, b: TreeNode) => a.sort_order - b.sort_order
  const sortRecursive = (nodes: TreeNode[]) => {
    nodes.sort(bySortOrder)
    nodes.forEach((n) => sortRecursive(n.children))
  }
  sortRecursive(roots)
  return roots
}

function Node({ node, onSelect }: { node: TreeNode; onSelect: (id: number) => void }) {
  return (
    <li>
      <button type="button" className="category-item" onClick={() => onSelect(node.id)}>
        {node.name}
        <span className="category-count">{node.product_count}</span>
      </button>
      {node.children.length > 0 && (
        <ul className="category-children">
          {node.children.map((child) => (
            <Node key={child.id} node={child} onSelect={onSelect} />
          ))}
        </ul>
      )}
    </li>
  )
}

export function CategoryTree({ groups, onSelect }: Props) {
  const tree = buildTree(groups)
  return (
    <ul className="category-tree">
      {tree.map((node) => (
        <Node key={node.id} node={node} onSelect={onSelect} />
      ))}
    </ul>
  )
}
