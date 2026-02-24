import pytest
from uuid import uuid4
from typing import List, Dict, Any

from odl_kernel.types import IrComponent, OpCode, NodeType, WiringObject, ProcessNode, LifecycleStatus, BusinessResult

# Target Strategy
from odl_kernel.engine.logic.expansion.base import ExpansionStrategy
from odl_kernel.engine.logic.expansion.iterate import IterateExpansionStrategy

class TestIterateExpansionStrategy:
    
    @pytest.fixture
    def strategy(self) -> ExpansionStrategy:
        return IterateExpansionStrategy()

    @pytest.fixture
    def mock_parent(self):
        """Iterate親ノード生成ヘルパー"""
        def _create(items: Dict[str, Any], strategy_mode: str = "serial", path: str = "root/iter") -> ProcessNode:
            bp = IrComponent(stack_path="root/iter/{$KEY}/worker", opcode=OpCode.WORKER)
            return ProcessNode(
                node_id=uuid4().hex,
                node_type=NodeType.CONTROL,
                opcode=OpCode.ITERATE,
                stack_path=path,
                wiring=WiringObject(inputs=[], output=None),
                children_blueprint=[bp],
                params={
                    "items": items,
                    "strategy": strategy_mode
                }
            )
        return _create

    @pytest.fixture
    def mock_child(self):
        """子ノード生成ヘルパー"""
        def _create(key: str, status: LifecycleStatus, result: BusinessResult = BusinessResult.NONE, parent_path: str = "root/iter") -> ProcessNode:
            return ProcessNode(
                node_id=uuid4().hex,
                node_type=NodeType.ACTION,
                opcode=OpCode.WORKER,
                # Path: Parent + Key + NodeName
                stack_path=f"{parent_path}/{key}/worker",
                wiring=WiringObject(inputs=[], output=None),
                lifecycle_status=status,
                business_result=result
            )
        return _create

    # =========================================================================
    # Serial Mode Tests
    # =========================================================================
    
    def test_serial_first_step(self, strategy: ExpansionStrategy, mock_parent):
        """[Serial] 最初の要素(Key1)を展開すること"""
        items = {"key1": "val1", "key2": "val2"}
        parent = mock_parent(items, strategy_mode="serial")
        
        plans = strategy.plan_next_nodes(parent, [])

        assert len(plans) == 1
        plan = plans[0]
        assert plan.context_vars["$KEY"] == "key1"
        assert plan.context_vars["$ITEM"] == "val1"
        assert plan.context_vars["$LOOP"] == 1
        assert plan.resolved_path == "root/iter/key1/worker"

    def test_serial_wait(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """[Serial] key1が実行中ならkey2に進まないこと"""
        items = {"key1": "val1", "key2": "val2"}
        parent = mock_parent(items, strategy_mode="serial")
        
        child1 = mock_child("key1", LifecycleStatus.RUNNING)
        plans = strategy.plan_next_nodes(parent, [child1])
        
        assert len(plans) == 0

    def test_serial_next_step(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """[Serial] key1完了後にkey2を展開すること"""
        items = {"key1": "val1", "key2": "val2"}
        parent = mock_parent(items, strategy_mode="serial")
        
        child1 = mock_child("key1", LifecycleStatus.COMPLETED)
        plans = strategy.plan_next_nodes(parent, [child1])
        
        assert len(plans) == 1
        plan = plans[0]
        assert plan.context_vars["$KEY"] == "key2"
        assert plan.resolved_path == "root/iter/key2/worker"

    def test_serial_stop_on_error(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """[Serial] key1がERRORなら停止すること (Fail Fast)"""
        items = {"key1": "val1", "key2": "val2"}
        parent = mock_parent(items, strategy_mode="serial")
        
        child1 = mock_child("key1", LifecycleStatus.COMPLETED, BusinessResult.ERROR)
        plans = strategy.plan_next_nodes(parent, [child1])
        
        assert len(plans) == 0

    # =========================================================================
    # Parallel Mode Tests
    # =========================================================================

    def test_parallel_batch(self, strategy: ExpansionStrategy, mock_parent):
        """[Parallel] 全ての要素を一括展開すること"""
        items = {"keyA": "valA", "keyB": "valB"}
        parent = mock_parent(items, strategy_mode="parallel")
        
        plans = strategy.plan_next_nodes(parent, [])
        
        assert len(plans) == 2
        keys = sorted([p.context_vars["$KEY"] for p in plans])
        assert keys == ["keyA", "keyB"]

    def test_parallel_convergence(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """[Parallel] 欠落している要素(keyB)のみを展開すること (Convergence)"""
        items = {"keyA": "valA", "keyB": "valB", "keyC": "valC"}
        parent = mock_parent(items, strategy_mode="parallel")
        
        # keyA, keyC は存在
        child_a = mock_child("keyA", LifecycleStatus.COMPLETED)
        child_c = mock_child("keyC", LifecycleStatus.RUNNING)
        
        plans = strategy.plan_next_nodes(parent, [child_a, child_c])
        
        assert len(plans) == 1
        assert plans[0].context_vars["$KEY"] == "keyB"
        assert plans[0].resolved_path == "root/iter/keyB/worker"

    # =========================================================================
    # Path Resolution Test
    # =========================================================================
    
    def test_path_resolution_with_nest(self, strategy: ExpansionStrategy, mock_parent):
        """
        [Strict Path] 親パスを継承し、Keyをセグメントとして挿入すること。
        親: root/loop/v1
        子: root/loop/v1/{KEY}/worker
        """
        items = {"k1": "v1"}
        # 親パスにループ変数などが含まれている状況
        parent = mock_parent(items, strategy_mode="serial", path="root/loop/v1")
        
        plans = strategy.plan_next_nodes(parent, [])
        
        assert len(plans) == 1
        expected = "root/loop/v1/k1/worker"
        assert plans[0].resolved_path == expected