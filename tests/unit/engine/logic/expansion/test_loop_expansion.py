import pytest
from uuid import uuid4
from typing import List

from odl_kernel.types import IrComponent, OpCode, NodeType, WiringObject, ProcessNode, LifecycleStatus, BusinessResult

# Target Strategy
from odl_kernel.engine.logic.expansion.base import ExpansionStrategy
from odl_kernel.engine.logic.expansion.loop import LoopExpansionStrategy

class TestLoopExpansionStrategy:
    
    @pytest.fixture
    def strategy(self) -> ExpansionStrategy:
        return LoopExpansionStrategy()

    @pytest.fixture
    def mock_parent(self):
        """Loop親ノード生成ヘルパー"""
        def _create(blueprint: IrComponent, params: dict, path: str = "root/loop_0") -> ProcessNode:
            return ProcessNode(
                node_id=uuid4().hex,
                node_type=NodeType.CONTROL,
                opcode=OpCode.LOOP,
                stack_path=path,
                wiring=WiringObject(inputs=[], output=None),
                children_blueprint=[blueprint],
                params=params
            )
        return _create

    @pytest.fixture
    def mock_child(self):
        """子ノード(イテレーション)生成ヘルパー"""
        def _create(index: int, status: LifecycleStatus, result: BusinessResult = BusinessResult.NONE) -> ProcessNode:
            return ProcessNode(
                node_id=uuid4().hex,
                node_type=NodeType.ACTION,
                opcode=OpCode.WORKER,
                stack_path=f"root/loop_0/v{index}/worker",
                wiring=WiringObject(inputs=[], output=None),
                lifecycle_status=status,
                business_result=result
            )
        return _create

    # =========================================================================
    # Case 1: First Iteration (v1の生成)
    # =========================================================================
    def test_first_iteration(self, strategy: ExpansionStrategy, mock_parent):
        """[Happy Path] 子供がいない時、v1を生成すること"""
        bp = IrComponent(stack_path="root/loop_0/v{$LOOP}/worker", opcode=OpCode.WORKER)
        parent = mock_parent(blueprint=bp, params={"count": 3})
        
        plans = strategy.plan_next_nodes(parent, [])

        assert len(plans) == 1
        assert plans[0].context_vars == {"$LOOP": 1}
        assert plans[0].resolved_path == "root/loop_0/v1/worker"
        assert plans[0].original_index == 0

    # =========================================================================
    # Case 2: Wait for Completion (待機)
    # =========================================================================
    def test_wait_for_running_iteration(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """[Flow Control] v1が実行中(RUNNING)の場合、v2を生成せず待機すること"""
        bp = IrComponent(stack_path="root/loop_0/v{$LOOP}/worker", opcode=OpCode.WORKER)
        parent = mock_parent(blueprint=bp, params={"count": 3})
        
        child_v1 = mock_child(index=1, status=LifecycleStatus.RUNNING)
        plans = strategy.plan_next_nodes(parent, [child_v1])
        assert len(plans) == 0

    # =========================================================================
    # Case 3: System Failure Check (LifecycleStatus) - 【追加・重要】
    # =========================================================================
    def test_stop_on_lifecycle_failed(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """
        [System Failure] v1がLifecycleStatus.FAILEDの場合、
        BusinessResultに関わらず即座にループを停止すること。
        """
        bp = IrComponent(stack_path="root/loop_0/v{$LOOP}/worker", opcode=OpCode.WORKER)
        parent = mock_parent(blueprint=bp, params={"count": 5})
        
        # v1 is FAILED (例: Worker Crash, Timeout)
        child_v1 = mock_child(index=1, status=LifecycleStatus.FAILED, result=BusinessResult.NONE)
        
        plans = strategy.plan_next_nodes(parent, [child_v1])
        
        # 停止 (v2は作らない)
        assert len(plans) == 0

    # =========================================================================
    # Case 4: Business Failure Check (BusinessResult)
    # =========================================================================
    def test_stop_on_business_error(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """[Business Failure] v1がBusinessResult.ERRORの場合、即座にループを停止すること"""
        bp = IrComponent(stack_path="root/loop_0/v{$LOOP}/worker", opcode=OpCode.WORKER)
        parent = mock_parent(blueprint=bp, params={"count": 5})
        
        # v1 is COMPLETED but ERROR
        child_v1 = mock_child(index=1, status=LifecycleStatus.COMPLETED, result=BusinessResult.ERROR)
        
        plans = strategy.plan_next_nodes(parent, [child_v1])
        assert len(plans) == 0

    # =========================================================================
    # Case 5: Break Logic (中断条件)
    # =========================================================================
    def test_break_on_success(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """[Logic] break_on='success' で v1 が SUCCESS なら終了すること"""
        bp = IrComponent(stack_path="root/loop_0/v{$LOOP}/worker", opcode=OpCode.WORKER)
        parent = mock_parent(blueprint=bp, params={"count": 5, "break_on": "success"})
        
        child_v1 = mock_child(index=1, status=LifecycleStatus.COMPLETED, result=BusinessResult.SUCCESS)
        plans = strategy.plan_next_nodes(parent, [child_v1])
        assert len(plans) == 0

    def test_continue_on_reject(self, strategy: ExpansionStrategy, mock_parent, mock_child):
        """[Logic] break_on='success' で v1 が REJECT なら継続すること"""
        bp = IrComponent(stack_path="root/loop_0/v{$LOOP}/worker", opcode=OpCode.WORKER)
        parent = mock_parent(blueprint=bp, params={"count": 5, "break_on": "success"})
        
        child_v1 = mock_child(index=1, status=LifecycleStatus.COMPLETED, result=BusinessResult.REJECT)
        plans = strategy.plan_next_nodes(parent, [child_v1])
        
        assert len(plans) == 1
        assert plans[0].context_vars == {"$LOOP": 2}

    # =========================================================================
    # Case 6: Nested Path Resolution
    # =========================================================================
    def test_nested_path_resolution(self, strategy: ExpansionStrategy, mock_parent):
        """[CRITICAL] ネストされた動的パスが正しく解決されること"""
        parent_resolved_path = "root/loop_outer/v2/loop_inner"
        tokenized_path = "root/loop_outer/v{$LOOP}/loop_inner/v{$LOOP}/worker"
        bp = IrComponent(stack_path=tokenized_path, opcode=OpCode.WORKER)
        
        parent = mock_parent(blueprint=bp, params={"count": 1}, path=parent_resolved_path)
        
        plans = strategy.plan_next_nodes(parent, [])

        assert len(plans) == 1
        expected_path = "root/loop_outer/v2/loop_inner/v1/worker"
        assert plans[0].resolved_path == expected_path
        assert "{$LOOP}" not in plans[0].resolved_path