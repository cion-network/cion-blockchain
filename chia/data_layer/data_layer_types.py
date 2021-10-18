from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Optional, Tuple, Type, Union

import aiosqlite as aiosqlite

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes


class NodeType(IntEnum):
    # EMPTY = 0
    INTERNAL = 1
    TERMINAL = 2


class Side(IntEnum):
    LEFT = 0
    RIGHT = 1


class OperationType(IntEnum):
    INSERT = 0
    DELETE = 1


class CommitState(IntEnum):
    OPEN = 0
    FINALIZED = 1
    ROLLED_BACK = 2


Node = Union["TerminalNode", "InternalNode"]


@dataclass(frozen=True)
class TerminalNode:
    hash: bytes32
    # generation: int
    key: bytes32
    value: bytes32

    atom: None = field(init=False, default=None)

    @property
    def pair(self) -> Tuple[bytes32, bytes32]:
        return Program.to(self.key), Program.to(self.value)

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "TerminalNode":
        return cls(
            hash=bytes32(hexstr_to_bytes(row["hash"])),
            # generation=row["generation"],
            key=hexstr_to_bytes(row["key"]),
            value=hexstr_to_bytes(row["value"]),
        )


@dataclass(frozen=True)
class InternalNode:
    hash: bytes32
    # generation: int
    left_hash: bytes32
    right_hash: bytes32

    pair: Optional[Tuple[Node, Node]] = None
    atom: None = None

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "InternalNode":
        return cls(
            hash=bytes32(hexstr_to_bytes(row["hash"])),
            # generation=row["generation"],
            left_hash=bytes32(hexstr_to_bytes(row["left"])),
            right_hash=bytes32(hexstr_to_bytes(row["right"])),
        )

    def other_child_hash(self, hash: bytes32) -> bytes32:
        if self.left_hash == hash:
            return self.right_hash
        elif self.right_hash == hash:
            return self.left_hash

        # TODO: real exception considerations
        raise Exception("provided hash not present")


@dataclass(frozen=True)
class Root:
    tree_id: bytes32
    node_hash: Optional[bytes32]
    generation: int

    @classmethod
    def from_row(cls, row: aiosqlite.Row) -> "Root":
        raw_node_hash = row["node_hash"]
        if raw_node_hash is None:
            node_hash = None
        else:
            node_hash = bytes32(hexstr_to_bytes(raw_node_hash))

        return cls(
            tree_id=bytes32(hexstr_to_bytes(row["tree_id"])),
            node_hash=node_hash,
            generation=row["generation"],
        )


node_type_to_class: Dict[NodeType, Union[Type[InternalNode], Type[TerminalNode]]] = {
    NodeType.INTERNAL: InternalNode,
    NodeType.TERMINAL: TerminalNode,
}
